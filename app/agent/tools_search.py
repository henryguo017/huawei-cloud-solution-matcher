"""
P1-2 联网检索 provider（可插拔抽象）

- provider 由 config.WEB_SEARCH_PROVIDER 指定（tavily / serper / ...），默认关闭（空串）。
- 统一返回 [{"domain", "title", "url", "snippet"}]（top 5）。
- 调用方（tools._tool_web_search）会做 URL 脱敏（只留 domain）再喂给 LLM，防幻觉外链。
- 同步阻塞的 HTTP 请求由 tools 侧用 asyncio.to_thread 包裹，不阻塞事件循环。
- 铁律：API Key 只来自 config / .env，绝不写死在代码里。
"""
import logging
import re
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

    def extract(self, url: str, max_chars: int = 2000) -> List[Dict[str, str]]:
        """从指定 URL 抽取干净正文（Tavily /extract）。默认不支持时返回空列表。"""
        return []


class TavilyProvider(WebSearchProvider):
    """Tavily：面向 LLM 的搜索 API（默认推荐，免费额度充足，返回结构化结果）。"""

    name = "tavily"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, top_n: int = 5, topic: str = "general") -> List[Dict[str, str]]:
        import json
        import urllib.request

        # 查询调优（2026-09-08）：
        # - search_depth=advanced：Tavily 会做正文抽取，返回的内容摘要远比 basic 饱满
        # - topic=news（调用方按查询语义判定）+ days=30：新闻类查询走新闻索引并限定近 30 天，
        #   避免"华为云最新动态"命中年久失修的栏目页/落地页
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": top_n,
            "search_depth": "advanced",
        }
        if topic == "news":
            payload["topic"] = "news"
            payload["days"] = 30
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for r in (data.get("results") or [])[:top_n]:
            u = r.get("url", "")
            published = r.get("published_date") or ""
            out.append({
                "domain": _domain_of(u),
                "title": r.get("title", ""),
                "url": u,
                "snippet": (r.get("content") or "")[:400],
                "published": published[:10],
            })
        return out

    @staticmethod
    def _is_public_http_url(url: str) -> bool:
        """校验 URL 指向公网 http(s) 地址（安全审计 M3，2026-09-08）。

        抓取方是 Tavily 的服务器（本服务不出网抓取），但内网地址仍会被
        泄露给第三方并可能被解析到内网段——统一拒绝：非 http(s) scheme、
        localhost/裸域名伪造、私网/环回/链路本地/metadata IP 段。
        """
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
        except Exception:
            return False
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        host = parsed.hostname.lower().strip(".")
        if host in ("localhost",) or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
            return False
        if not host.replace(".", "").isdigit():
            return True  # 正常域名（含公网 IP 形式以外的）放行
        # 裸 IP：拒绝私网/环回/链路本地/CGNAT/云 metadata 段
        import ipaddress
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return True
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
        # CGNAT 100.64.0.0/10：新版 Python 的 is_private 不覆盖，但阿里云
        # metadata 服务（100.100.100.200）等云内部端点在此段，必须显式拦截
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return False
        return True

    def extract(self, url: str, max_chars: int = 2000) -> List[Dict[str, str]]:
        """Tavily /extract：抽取指定 URL 的干净正文（去广告/导航等噪音）。

        返回 [{"domain", "title", "url", "content"}]；抽取失败的 URL 在 failed 日志体现，不抛异常。
        max_chars 截断正文，控制注入 LLM 的 token 量。
        内网/非公网地址直接拒绝（安全审计 M3，2026-09-08），不外发给第三方。
        """
        import json
        import urllib.request

        if not self._is_public_http_url(url):
            logger.warning(f"[tavily-extract] 拒绝非公网/内网地址: {url}")
            return []

        payload = {"api_key": self.api_key, "urls": [url]}
        req = urllib.request.Request(
            "https://api.tavily.com/extract",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for r in (data.get("results") or []):
            u = r.get("url", url)
            out.append({
                "domain": _domain_of(u),
                "title": r.get("title", "") or "",
                "url": u,
                "content": (r.get("raw_content") or "")[:max_chars],
            })
        failed = data.get("failed_results") or []
        if failed:
            logger.warning(f"[tavily-extract] {len(failed)} 个 URL 抽取失败: {failed}")
        return out


class SerperProvider(WebSearchProvider):
    """Serper.dev：Google 结果聚合（备选）。"""

    name = "serper"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, top_n: int = 5, topic: str = "general") -> List[Dict[str, str]]:
        import json
        import urllib.request

        # serper 无 topic 概念，news 类查询追加时效词兜底
        if topic == "news" and not re.search(r"最新|近期|20\d\d", query):
            query = f"{query} 最新"
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
                "published": (r.get("date") or "")[:10],
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
