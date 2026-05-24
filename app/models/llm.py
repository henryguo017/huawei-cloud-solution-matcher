import requests
import time
import os
import warnings
from abc import ABC, abstractmethod
from typing import Optional, Callable
warnings.filterwarnings('ignore')

from app.config import *

for key in list(os.environ.keys()):
    if "proxy" in key.lower():
        del os.environ[key]


class LLMProvider(ABC):
    """LLM提供商抽象基类"""
    
    @abstractmethod
    def chat(self, prompt: str, temperature: Optional[float] = None) -> str:
        """发送对话请求"""
        pass
    
    @abstractmethod
    def test_connection(self) -> bool:
        """测试连接是否正常"""
        pass
    
    def _retry_request(self, func: Callable, max_retries: int = None, interval: int = None) -> any:
        """重试机制包装器"""
        max_retries = max_retries or MAX_RETRIES
        interval = interval or RETRY_INTERVAL
        
        last_error = None
        for i in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_error = e
                if i < max_retries - 1:
                    time.sleep(interval)
        
        raise last_error


class DeepSeekProvider(LLMProvider):
    """DeepSeek提供商适配器 (国内推荐)"""
    
    def __init__(self):
        if not DEEPSEEK_API_KEY:
            raise ValueError("请设置 DEEPSEEK_API_KEY 环境变量")
    
    def chat(self, prompt: str, temperature: Optional[float] = None) -> str:
        temp = temperature if temperature is not None else DEEPSEEK_TEMPERATURE
        
        def _request():
            url = f"{DEEPSEEK_BASE_URL}/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "model": DEEPSEEK_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temp
            }
            response = requests.post(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        
        return self._retry_request(_request)
    
    def test_connection(self) -> bool:
        try:
            self.chat("你好", temperature=0.1)
            return True
        except:
            return False


class AliyunProvider(LLMProvider):
    """阿里云百炼提供商适配器 (国内推荐)"""
    
    def __init__(self):
        if not ALIYUN_API_KEY:
            raise ValueError("请设置 ALIYUN_API_KEY 环境变量")
    
    def chat(self, prompt: str, temperature: Optional[float] = None) -> str:
        temp = temperature if temperature is not None else ALIYUN_TEMPERATURE
        
        def _request():
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
            response = requests.post(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            result = response.json()
            return result["output"]["text"]
        
        return self._retry_request(_request)
    
    def test_connection(self) -> bool:
        try:
            self.chat("你好", temperature=0.1)
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
    
    def _get_access_token(self) -> str:
        """获取百度access_token"""
        if self._access_token and time.time() < self._token_expire_time:
            return self._access_token
        
        url = f"https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={BAIDU_API_KEY}&client_secret={BAIDU_SECRET_KEY}"
        response = requests.post(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        result = response.json()
        self._access_token = result["access_token"]
        self._token_expire_time = time.time() + result.get("expires_in", 86400) - 3600
        return self._access_token
    
    def chat(self, prompt: str, temperature: Optional[float] = None) -> str:
        temp = temperature if temperature is not None else BAIDU_TEMPERATURE
        
        def _request():
            token = self._get_access_token()
            url = f"{BAIDU_BASE_URL}/wenxin/chat?access_token={token}"
            data = {
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temp
            }
            response = requests.post(url, json=data, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()["result"]
        
        return self._retry_request(_request)
    
    def test_connection(self) -> bool:
        try:
            self.chat("你好", temperature=0.1)
            return True
        except:
            return False


class OpenAIProvider(LLMProvider):
    """OpenAI提供商适配器 (需VPN)"""
    
    def __init__(self):
        if not OPENAI_API_KEY:
            raise ValueError("请设置 OPENAI_API_KEY 环境变量")
    
    def chat(self, prompt: str, temperature: Optional[float] = None) -> str:
        temp = temperature if temperature is not None else OPENAI_TEMPERATURE
        
        def _request():
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
            response = requests.post(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        
        return self._retry_request(_request)
    
    def test_connection(self) -> bool:
        try:
            self.chat("Hello", temperature=0.1)
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


def get_llm(provider: str = None, temperature: float = 0.1) -> Callable:
    """获取LLM调用函数 (兼容原有接口)"""
    provider_instance = LLMFactory.create(provider)
    return lambda prompt: provider_instance.chat(prompt, temperature)


def get_llm_response(prompt: str = "你好", provider: str = None) -> str:
    """获取LLM响应 (兼容原有接口)"""
    provider_instance = LLMFactory.create(provider)
    return provider_instance.chat(prompt)


def test_llm_connection(provider: str = None) -> bool:
    """测试LLM连接"""
    try:
        provider_instance = LLMFactory.create(provider)
        return provider_instance.test_connection()
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
    """本地生成向量，无需API"""
    global _local_embedding_model
    
    if _local_embedding_model is None:
        _local_embedding_model = _load_embedding_model()
    
    if _local_embedding_model is None:
        return [0] * 384
    
    return _local_embedding_model.encode(text, convert_to_numpy=False).tolist()


class LocalEmbeddings:
    """兼容Chroma向量库接口"""
    
    def embed_documents(self, texts: list) -> list:
        return [get_embedding_vector(text) for text in texts]
    
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
    
    try:
        if test_llm_connection():
            print(f"[OK] {LLM_PROVIDER} 连接测试成功")
            res = get_llm_response("你好，请简短回复")
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
