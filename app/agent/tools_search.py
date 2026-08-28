"""
P1-2 联网检索 provider（可插拔抽象）

- provider 由 config.WEB_SEARCH_PROVIDER 指定（tavily / serper / ...），默认关闭（空串）。
- 统一返回 [{"domain", "title", "url", "snippet"}]（top 5）。
- 调用方（tools._tool_web_search）会做 URL 脱敏（只留 domain）再喂给 LLM，防幻觉外链。
- 同步阻塞的 HTTP 请求由 tools 侧用 asyncio.to_thread 包裹，不阻塞事件循环。
- 铁律：API Key 只来自 config / .env，绝不写死在代码里。
"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def _domain_of(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url or "").netloc or ""
    except Exception:
        return ""


class WebSearchProvider:
    """联网检索 provider 抽象基类。"""

    name = "base"

    def search(self, query: str, top_n: int = 5) -> List[Dict[str, str]]:
        raise NotImplementedError


class TavilyProvider(WebSearchProvider):
    """Tavily：面向 LLM 的搜索 API（默认推荐，免费额度充足，返回结构化结果）。"""

    name = "tavily"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, top_n: int = 5) -> List[Dict[str, str]]:
        import json
        import urllib.request

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": top_n,
            "search_depth": "basic",
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for r in (data.get("results") or [])[:top_n]:
            u = r.get("url", "")
            out.append({
                "domain": _domain_of(u),
                "title": r.get("title", ""),
                "url": u,
                "snippet": (r.get("content") or "")[:200],
            })
        return out


class SerperProvider(WebSearchProvider):
    """Serper.dev：Google 结果聚合（备选）。"""

    name = "serper"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, top_n: int = 5) -> List[Dict[str, str]]:
        import json
        import urllib.request

        url = "https://google.serper.dev/search"
        req = urllib.request.Request(
            url,
            data=json.dumps({"q": query, "num": top_n}).encode("utf-8"),
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for r in (data.get("organic") or [])[:top_n]:
            u = r.get("link", "")
            out.append({
                "domain": _domain_of(u),
                "title": r.get("title", ""),
                "url": u,
                "snippet": (r.get("snippet") or "")[:200],
            })
        return out


_PROVIDERS: Dict[str, WebSearchProvider] = {}


def get_web_search_provider(name: str) -> WebSearchProvider:
    """按名称返回 provider 实例（懒加载，读 config 取 key）。"""
    name = (name or "").strip().lower()
    if name in _PROVIDERS:
        return _PROVIDERS[name]
    from app.config import WEB_SEARCH_API_KEY
    key = WEB_SEARCH_API_KEY or ""
    if name == "tavily":
        inst: WebSearchProvider = TavilyProvider(key)
    elif name == "serper":
        inst = SerperProvider(key)
    else:
        raise ValueError(f"不支持的联网搜索 provider: {name}")
    _PROVIDERS[name] = inst
    return inst
