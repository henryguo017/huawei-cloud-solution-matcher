"""
网络环境检测工具
用于检测各API端点的连通性并生成配置建议
"""

import requests
import time
from dataclasses import dataclass
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from app.config import DETECTION_TIMEOUT


@dataclass
class EndpointStatus:
    """端点状态"""
    name: str
    url: str
    accessible: bool
    response_time: float
    error_message: Optional[str] = None


@dataclass
class NetworkReport:
    """网络检测报告"""
    deepseek_api: EndpointStatus
    aliyun_api: EndpointStatus
    baidu_api: EndpointStatus
    openai_api: EndpointStatus
    huggingface_mirror: EndpointStatus
    suggestions: List[str]
    timestamp: float
    
    def is_usable(self) -> bool:
        """判断系统是否可用 (至少有一个LLM API可用)"""
        return any([
            self.deepseek_api.accessible,
            self.aliyun_api.accessible,
            self.baidu_api.accessible,
            self.openai_api.accessible
        ])
    
    def get_available_providers(self) -> List[str]:
        """获取可用的LLM提供商列表"""
        providers = []
        if self.deepseek_api.accessible:
            providers.append("deepseek")
        if self.aliyun_api.accessible:
            providers.append("aliyun")
        if self.baidu_api.accessible:
            providers.append("baidu")
        if self.openai_api.accessible:
            providers.append("openai")
        return providers


class NetworkChecker:
    """网络环境检测器"""
    
    def __init__(self):
        self.endpoints = {
            "deepseek_api": {
                "name": "DeepSeek API",
                "url": "https://api.deepseek.com/v1/models"
            },
            "aliyun_api": {
                "name": "阿里云百炼 API",
                "url": "https://dashscope.aliyuncs.com/api/v1/models"
            },
            "baidu_api": {
                "name": "百度文心 API",
                "url": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1"
            },
            "openai_api": {
                "name": "OpenAI API",
                "url": "https://api.openai.com/v1/models"
            },
            "huggingface_mirror": {
                "name": "HuggingFace 镜像",
                "url": "https://hf-mirror.com"
            }
        }
    
    def test_endpoint(self, name: str, url: str, timeout: int = None) -> EndpointStatus:
        """测试单个端点连通性"""
        timeout = timeout or DETECTION_TIMEOUT
        start_time = time.time()
        
        try:
            response = requests.head(url, timeout=timeout, allow_redirects=True)
            response_time = (time.time() - start_time) * 1000
            
            if response.status_code < 500:
                return EndpointStatus(
                    name=name,
                    url=url,
                    accessible=True,
                    response_time=response_time
                )
            else:
                return EndpointStatus(
                    name=name,
                    url=url,
                    accessible=False,
                    response_time=response_time,
                    error_message=f"HTTP {response.status_code}"
                )
        
        except requests.exceptions.Timeout:
            return EndpointStatus(
                name=name,
                url=url,
                accessible=False,
                response_time=timeout * 1000,
                error_message="Timeout"
            )
        
        except requests.exceptions.ConnectionError:
            return EndpointStatus(
                name=name,
                url=url,
                accessible=False,
                response_time=0,
                error_message="Connection Error"
            )
        
        except Exception as e:
            return EndpointStatus(
                name=name,
                url=url,
                accessible=False,
                response_time=0,
                error_message=str(e)[:50]
            )
    
    def detect_all(self) -> NetworkReport:
        """检测所有端点"""
        results = {}
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                key: executor.submit(
                    self.test_endpoint,
                    endpoint["name"],
                    endpoint["url"]
                )
                for key, endpoint in self.endpoints.items()
            }
            
            for key, future in futures.items():
                results[key] = future.result()
        
        suggestions = self.generate_suggestions(results)
        
        return NetworkReport(
            deepseek_api=results["deepseek_api"],
            aliyun_api=results["aliyun_api"],
            baidu_api=results["baidu_api"],
            openai_api=results["openai_api"],
            huggingface_mirror=results["huggingface_mirror"],
            suggestions=suggestions,
            timestamp=time.time()
        )
    
    def generate_suggestions(self, results: dict) -> List[str]:
        """生成配置建议"""
        suggestions = []
        
        available_providers = []
        if results["deepseek_api"].accessible:
            available_providers.append("deepseek")
        if results["aliyun_api"].accessible:
            available_providers.append("aliyun")
        if results["baidu_api"].accessible:
            available_providers.append("baidu")
        if results["openai_api"].accessible:
            available_providers.append("openai")
        
        if available_providers:
            suggestions.append(f"[OK] 可用的LLM提供商: {', '.join(available_providers)}")
            
            if "deepseek" in available_providers:
                suggestions.append("[TIP] 推荐: 设置 LLM_PROVIDER=deepseek (国内速度快)")
            elif "aliyun" in available_providers:
                suggestions.append("[TIP] 推荐: 设置 LLM_PROVIDER=aliyun")
            elif "baidu" in available_providers:
                suggestions.append("[TIP] 推荐: 设置 LLM_PROVIDER=baidu")
        else:
            suggestions.append("[WARN] 没有可用的LLM API，请检查网络连接")
            suggestions.append("[TIP] 如果在国内，请检查是否需要配置API密钥")
        
        if results["huggingface_mirror"].accessible:
            suggestions.append("[OK] HuggingFace国内镜像可用，向量模型可正常下载")
        else:
            suggestions.append("[WARN] HuggingFace镜像不可达，向量模型下载可能失败")
            suggestions.append("[TIP] 建议: 手动下载模型到 data/embedding_model/ 目录")
        
        if results["openai_api"].accessible and not any([
            results["deepseek_api"].accessible,
            results["aliyun_api"].accessible,
            results["baidu_api"].accessible
        ]):
            suggestions.append("[INFO] 检测到OpenAI可用但国内API不可达")
            suggestions.append("[TIP] 可能正在使用VPN，建议切换到国内LLM提供商")
        
        return suggestions


def detect_network_environment() -> NetworkReport:
    """检测网络环境 (便捷函数)"""
    checker = NetworkChecker()
    return checker.detect_all()


def print_network_report(report: NetworkReport = None):
    """打印网络检测报告"""
    if report is None:
        report = detect_network_environment()
    
    print("=" * 60)
    print("网络环境检测报告")
    print("=" * 60)
    
    endpoints = [
        ("DeepSeek API", report.deepseek_api),
        ("阿里云百炼 API", report.aliyun_api),
        ("百度文心 API", report.baidu_api),
        ("OpenAI API", report.openai_api),
        ("HuggingFace 镜像", report.huggingface_mirror),
    ]
    
    print("\n[端点状态]")
    for name, status in endpoints:
        if status.accessible:
            print(f"  [OK] {name}: {status.response_time:.0f}ms")
        else:
            print(f"  [FAIL] {name}: {status.error_message}")
    
    print("\n[配置建议]")
    for suggestion in report.suggestions:
        print(f"  {suggestion}")
    
    print("\n[可用提供商]")
    providers = report.get_available_providers()
    if providers:
        for p in providers:
            print(f"  - {p}")
    else:
        print("  (无)")
    
    print("=" * 60)
    
    return report


if __name__ == "__main__":
    print("正在检测网络环境...\n")
    report = print_network_report()
    
    if report.is_usable():
        print("\n[OK] 系统可以正常运行!")
    else:
        print("\n[FAIL] 系统无法运行，请根据上述建议进行配置")
