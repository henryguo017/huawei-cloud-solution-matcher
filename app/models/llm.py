import json
import logging
import httpx
import asyncio
import time
from contextlib import asynccontextmanager
import os
import warnings
from abc import ABC, abstractmethod
from typing import Optional, Callable
warnings.filterwarnings('ignore')

from app.config import *

logger = logging.getLogger(__name__)

for key in list(os.environ.keys()):
    if "proxy" in key.lower():
        del os.environ[key]


# 进程级共享 httpx 异步客户端（懒初始化，复用 TCP 连接池）
# 避免每次请求都重建 AsyncClient + 连接池；limits 限制并发连接数，防高并发耗尽文件描述符
_llm_http_client = None

def _get_http_client():
    """返回进程级共享的 httpx.AsyncClient（带连接池上限），懒初始化保证在事件循环内创建"""
    global _llm_http_client
    if _llm_http_client is None:
        _llm_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=float(REQUEST_TIMEOUT), write=10.0, pool=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _llm_http_client


@asynccontextmanager
async def _http_client_cm():
    """共享客户端的透明上下文管理器：进入/退出不关闭底层连接池（连接池随进程复用）"""
    yield _get_http_client()


class LLMProvider(ABC):
    """LLM提供商抽象基类"""

    @abstractmethod
    async def chat(self, prompt: str, temperature: Optional[float] = None, model: Optional[str] = None) -> str:
        """发送对话请求"""

    async def chat_stream(self, prompt: str, temperature: Optional[float] = None, model: Optional[str] = None):
        """流式对话请求，yield 每个 token 字符串（默认实现：非流式降级）"""
        result = await self.chat(prompt, temperature, model)
        yield result

    @abstractmethod
    async def test_connection(self) -> bool:
        """测试连接是否正常"""

    async def _retry_request(self, func: Callable, max_retries: int = None, interval: int = None) -> any:
        """重试机制包装器（异步版）"""
        max_retries = max_retries or MAX_RETRIES
        interval = interval or RETRY_INTERVAL

        last_error = None
        for i in range(max_retries):
            try:
                return await func()
            except Exception as e:
                last_error = e
                if i < max_retries - 1:
                    await asyncio.sleep(interval)

        raise last_error


class DeepSeekProvider(LLMProvider):
    """DeepSeek提供商适配器 (国内推荐)"""

    def __init__(self):
        if not DEEPSEEK_API_KEY:
            raise ValueError("请设置 DEEPSEEK_API_KEY 环境变量")

    async def chat(self, prompt: str, temperature: Optional[float] = None, model: Optional[str] = None) -> str:
        temp = temperature if temperature is not None else DEEPSEEK_TEMPERATURE
        model_name = model or DEEPSEEK_MODEL_NAME

        async def _request():
            url = f"{DEEPSEEK_BASE_URL}/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temp,
                # V4-Flash-0731 正式版起 thinking 默认 enabled（无上限思考→匹配 140-170s）。
                # 本项目生成方案文本无需深度推理，默认 disabled；确需思考在 .env 设 DEEPSEEK_THINKING=enabled。
                "thinking": {"type": DEEPSEEK_THINKING},
                # 输出 token 上限，防无上限长文/思考拖慢响应
                "max_tokens": LLM_MAX_TOKENS,
            }
            async with _http_client_cm() as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]

        return await self._retry_request(_request)

    async def chat_stream(self, prompt: str, temperature: Optional[float] = None, model: Optional[str] = None):
        """DeepSeek 流式调用，yield 每个 delta content 字符串"""
        temp = temperature if temperature is not None else DEEPSEEK_TEMPERATURE
        model_name = model or DEEPSEEK_MODEL_NAME
        url = f"{DEEPSEEK_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temp,
            # 与 chat() 一致：默认关闭 V4 思考模式，控制匹配耗时（见 chat 内注释）
            "thinking": {"type": DEEPSEEK_THINKING},
            "max_tokens": LLM_MAX_TOKENS,
            "stream": True
        }
        async with _http_client_cm() as client:
            async with client.stream("POST", url, headers=headers, json=data) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except Exception:
                        continue

    async def test_connection(self) -> bool:
        try:
            await self.chat("你好", temperature=0.1)
            return True
        except:
            return False


class AliyunProvider(LLMProvider):
    """阿里云百炼提供商适配器 (国内推荐)"""

    def __init__(self):
        if not ALIYUN_API_KEY:
            raise ValueError("请设置 ALIYUN_API_KEY 环境变量")

    async def chat(self, prompt: str, temperature: Optional[float] = None, model: Optional[str] = None) -> str:
        temp = temperature if temperature is not None else ALIYUN_TEMPERATURE

        async def _request():
            url = f"{ALIYUN_BASE_URL}/services/aigc/text-generation/generation"
            headers = {
                "Authorization": f"Bearer {ALIYUN_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "model": ALIYUN_MODEL_NAME,
                "input": {"prompt": prompt},
                "parameters": {"temperature": temp}
            }
            async with _http_client_cm() as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                return result["output"]["text"]

        return await self._retry_request(_request)

    async def test_connection(self) -> bool:
        try:
            await self.chat("你好", temperature=0.1)
            return True
        except:
            return False


class BaiduProvider(LLMProvider):
    """百度文心提供商适配器 (国内推荐)"""

    def __init__(self):
        if not BAIDU_API_KEY or not BAIDU_SECRET_KEY:
            raise ValueError("请设置 BAIDU_API_KEY 和 BAIDU_SECRET_KEY 环境变量")
        self._access_token = None
        self._token_expire_time = 0

    async def _get_access_token(self) -> str:
        """获取百度access_token"""
        if self._access_token and time.time() < self._token_expire_time:
            return self._access_token

        url = f"https://aip.baidu.com/oauth/2.0/token?grant_type=client_credentials&client_id={BAIDU_API_KEY}&client_secret={BAIDU_SECRET_KEY}"
        async with _http_client_cm() as client:
            response = await client.post(url)
            response.raise_for_status()
            result = response.json()
            self._access_token = result["access_token"]
            self._token_expire_time = time.time() + result.get("expires_in", 86400) - 3600
            return self._access_token

    async def chat(self, prompt: str, temperature: Optional[float] = None, model: Optional[str] = None) -> str:
        temp = temperature if temperature is not None else BAIDU_TEMPERATURE

        async def _request():
            token = await self._get_access_token()
            url = f"{BAIDU_BASE_URL}/wenxin/chat?access_token={token}"
            data = {
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temp
            }
            async with _http_client_cm() as client:
                response = await client.post(url, json=data)
                response.raise_for_status()
                return response.json()["result"]

        return await self._retry_request(_request)

    async def test_connection(self) -> bool:
        try:
            await self.chat("你好", temperature=0.1)
            return True
        except:
            return False


class OpenAIProvider(LLMProvider):
    """OpenAI提供商适配器 (需VPN)"""

    def __init__(self):
        if not OPENAI_API_KEY:
            raise ValueError("请设置 OPENAI_API_KEY 环境变量")

    async def chat(self, prompt: str, temperature: Optional[float] = None, model: Optional[str] = None) -> str:
        temp = temperature if temperature is not None else OPENAI_TEMPERATURE

        async def _request():
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "model": OPENAI_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temp
            }
            async with _http_client_cm() as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]

        return await self._retry_request(_request)

    async def test_connection(self) -> bool:
        try:
            await self.chat("Hello", temperature=0.1)
            return True
        except:
            return False


class LLMFactory:
    """LLM工厂类"""

    _providers = {
        "deepseek": DeepSeekProvider,
        "aliyun": AliyunProvider,
        "baidu": BaiduProvider,
        "openai": OpenAIProvider
    }

    @classmethod
    def create(cls, provider_name: str = None) -> LLMProvider:
        """创建LLM提供商实例"""
        provider_name = provider_name or LLM_PROVIDER
        provider_name = provider_name.lower()

        if provider_name not in cls._providers:
            raise ValueError(f"不支持的LLM提供商: {provider_name}，支持的提供商: {list(cls._providers.keys())}")

        return cls._providers[provider_name]()

    @classmethod
    def get_supported_providers(cls) -> list:
        """获取支持的提供商列表"""
        return list(cls._providers.keys())


async def get_llm(provider: str = None, temperature: float = 0.1) -> Callable:
    """获取LLM调用函数 (兼容原有接口，返回async函数)"""
    provider_instance = LLMFactory.create(provider)
    return lambda prompt: provider_instance.chat(prompt, temperature)


async def get_llm_response(prompt: str = "你好", provider: str = None, model: Optional[str] = None) -> str:
    """获取LLM响应 (兼容原有接口，异步版)

    Args:
        model: 可选，指定具体模型名（如 MATCH_LLM_MODEL 分流）。None 时用 provider 默认模型。
    """
    provider_instance = LLMFactory.create(provider)
    return await provider_instance.chat(prompt, model=model)


async def get_llm_response_stream(prompt: str = "你好", provider: str = None, model: Optional[str] = None):
    """获取LLM流式响应，yield 每个 token"""
    provider_instance = LLMFactory.create(provider)
    async for token in provider_instance.chat_stream(prompt, model=model):
        yield token


async def test_llm_connection(provider: str = None) -> bool:
    """测试LLM连接"""
    try:
        provider_instance = LLMFactory.create(provider)
        return await provider_instance.test_connection()
    except Exception as e:
        print(f"连接测试失败: {e}")
        return False


os.environ['HF_ENDPOINT'] = HF_ENDPOINT

_local_embedding_model = None

def _load_embedding_model():
    """加载向量模型 (三级策略: 本地 > 镜像 > 官方)"""
    global _local_embedding_model

    if _local_embedding_model is not None:
        return _local_embedding_model

    try:
        from sentence_transformers import SentenceTransformer

        local_path = EMBEDDING_MODEL_LOCAL_PATH
        if os.path.exists(local_path) and os.path.exists(os.path.join(local_path, "config.json")):
            print(f"[OK] 使用本地向量模型: {local_path}")
            _local_embedding_model = SentenceTransformer(local_path)
            return _local_embedding_model

        if OFFLINE_MODE:
            raise RuntimeError(
                f"离线模式下本地模型不存在: {local_path}\n"
                "解决方案:\n"
                "1. 手动下载模型到该目录\n"
                "2. 或设置 OFFLINE_MODE=false 允许在线下载"
            )

        print(f"[...] 正在下载向量模型: {EMBEDDING_MODEL_NAME}")
        print(f"[TIP] 使用国内镜像: {HF_ENDPOINT}")
        _local_embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        print("[OK] 向量模型加载完成!")

        try:
            _local_embedding_model.save(local_path)
            print(f"[OK] 模型已缓存到: {local_path}")
        except:
            pass

        return _local_embedding_model

    except Exception as e:
        print(f"[WARN] 向量模型加载失败: {e}")
        return None


def get_embedding_vector(text: str) -> list:
    """本地生成单条向量，无需API"""
    global _local_embedding_model

    if _local_embedding_model is None:
        _local_embedding_model = _load_embedding_model()

    if _local_embedding_model is None:
        return [0] * 384

    return _local_embedding_model.encode(text, convert_to_numpy=False).tolist()


def get_embedding_vectors(texts: list, batch_size: int = EMBEDDING_BATCH_SIZE) -> list:
    """本地批量生成向量。

    相比逐条 encode，批量编码让底层矩阵运算跑满、省掉大量 Python/框架调用开销，
    在 CPU 上通常有 3-5 倍提速。用于知识库重建/同步等大批量嵌入场景。
    """
    global _local_embedding_model

    if not texts:
        return []

    if _local_embedding_model is None:
        _local_embedding_model = _load_embedding_model()

    if _local_embedding_model is None:
        return [[0] * 384 for _ in texts]

    # sentence-transformers 原生批量编码：一次传整批，内部按 batch_size 分批推理
    embeddings = _local_embedding_model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return embeddings.tolist()


class LocalEmbeddings:
    """兼容Chroma向量库接口"""

    def embed_documents(self, texts: list) -> list:
        # 批量编码（性能关键路径）：整批一次性算，替代逐条 encode
        return get_embedding_vectors(texts)

    def embed_query(self, text: str) -> list:
        return get_embedding_vector(text)


def get_embeddings() -> LocalEmbeddings:
    """获取嵌入函数 (兼容原有接口)"""
    return LocalEmbeddings()


if __name__ == "__main__":
    print("=" * 50)
    print("LLM服务测试")
    print("=" * 50)

    print(f"\n支持的LLM提供商: {LLMFactory.get_supported_providers()}")
    print(f"当前LLM提供商: {LLM_PROVIDER}")

    async def _test():
        try:
            if await test_llm_connection():
                print(f"[OK] {LLM_PROVIDER} 连接测试成功")
                res = await get_llm_response("你好，请简短回复")
                print(f"[OK] 对话测试成功: {res[:50]}...")
            else:
                print(f"[FAIL] {LLM_PROVIDER} 连接测试失败")
        except Exception as e:
            print(f"[FAIL] 测试失败: {e}")

        print("\n" + "=" * 50)
        print("向量模型测试")
        print("=" * 50)

        vec = get_embedding_vector("测试文本")
        print(f"[OK] 向量维度: {len(vec)}")
        print("\n[DONE] 全部测试完成!")

    asyncio.run(_test())
