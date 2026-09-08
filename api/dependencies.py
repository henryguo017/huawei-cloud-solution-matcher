from typing import Dict
import time
from fastapi import Request, HTTPException
from app.services.solution_matcher import SolutionMatcherService
from app.services.competitor_analyzer import CompetitorAnalyzerService
from app.services.usage_logger import UsageLoggerService, get_usage_logger as _get_usage_logger
# re-export：供其它路由 `from api.dependencies import get_current_user[_optional]` 使用
# 注意：这两个名字在本文件内看似未使用，但被 achievement_routes 等模块引用，autoflake 勿删
from api.auth_dependencies import get_current_user, get_current_user_optional  # noqa: F401
# re-export：KB 工厂的真实定义在 app.services.knowledge_base（消除 app→api 反向依赖）；
# api 层保留别名以兼容 api/main.py 与 api/routes.py 的既有 import 路径。
from app.services.knowledge_base import (  # noqa: F401
    get_knowledge_base,
    get_user_knowledge_base,
)


_ratelimit_buckets: Dict[str, list] = {}


def _rate_limit_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(limit: int = 120, window: int = 60):
    """简单的单进程 IP/用户限流；多 worker 部署时应替换为 Redis 等共享存储。"""
    async def dependency(request: Request):
        now = time.time()
        # key = IP + 路由路径：同一 IP 下不同端点各自计数（此前共享同桶，
        # 多端点页签式操作会误触严格端点的限流，2026-09-09 情报订阅实测暴露）
        key = _rate_limit_key(request) + ":" + request.url.path
        bucket = _ratelimit_buckets.setdefault(key, [])
        bucket[:] = [t for t in bucket if t > now - window]
        if len(bucket) >= limit:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
        bucket.append(now)
        if len(_ratelimit_buckets) > 10000:
            for k in [k for k, v in _ratelimit_buckets.items() if not v]:
                _ratelimit_buckets.pop(k, None)
    return dependency


def anon_rate_limit(limit: int = 10, window: int = 60):
    """仅限未登录请求的限流（安全审计 M1，2026-09-08）。

    登录用户（带有效 Bearer token）直接放行，由端点原有的 rate_limit 管；
    未登录按 IP 计数。匿名匹配消耗 DeepSeek token，配额远严于登录用户。
    """
    from app.utils.auth_utils import decode_access_token

    async def dependency(request: Request):
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token and decode_access_token(token):
                return  # 登录用户：不占匿名配额
        now = time.time()
        key = "anon:" + _rate_limit_key(request)
        bucket = _ratelimit_buckets.setdefault(key, [])
        bucket[:] = [t for t in bucket if t > now - window]
        if len(bucket) >= limit:
            raise HTTPException(status_code=429, detail="未登录请求过于频繁，请登录后使用或稍后再试")
        bucket.append(now)
    return dependency


def anon_daily_cap(cap: int = 300, action: str = "match"):
    """匿名请求的全站每日总量闸门（安全审计 M1，2026-09-08）。

    基于 usage_logs 持久化计数（重启不清零，防换 IP 绕过）：当天匿名(action_type=action
    且 user_id 为空)请求数达到 cap 后，所有匿名请求一律 429。登录用户不受影响。
    """
    async def dependency(request: Request):
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token and decode_access_token(token):
                return
        from app.services.usage_logger import get_usage_logger
        try:
            used = get_usage_logger().count_today_anonymous(action)
        except Exception:
            used = 0  # 计数故障不阻断主链路（fail-open），另有每 IP 限流兜底
        if used >= cap:
            raise HTTPException(
                status_code=429,
                detail="今日免登录体验额度已用完，请注册/登录后使用"
            )
    return dependency


# ===== 解决方案匹配服务（无状态，每次创建新实例或共享） =====
def get_solution_matcher_for_user(user_id: int = 0) -> SolutionMatcherService:
    """获取解决方案匹配服务（传入 user_id 以便使用用户知识库）"""
    kb = get_user_knowledge_base(user_id) if user_id > 0 else get_knowledge_base()
    return SolutionMatcherService(kb_service=kb)

def get_solution_matcher() -> SolutionMatcherService:
    """获取解决方案匹配服务（全局知识库，兼容旧接口）"""
    return SolutionMatcherService(kb_service=get_knowledge_base())


# ===== 竞品分析服务 =====
def get_competitor_analyzer_for_user(user_id: int = 0) -> CompetitorAnalyzerService:
    """获取竞品分析服务（传入 user_id 以便使用用户知识库）"""
    kb = get_user_knowledge_base(user_id) if user_id > 0 else get_knowledge_base()
    return CompetitorAnalyzerService(kb_service=kb)

def get_competitor_analyzer() -> CompetitorAnalyzerService:
    """获取竞品分析服务（全局知识库，兼容旧接口）"""
    return CompetitorAnalyzerService(kb_service=get_knowledge_base())


def get_usage_logger() -> UsageLoggerService:
    return _get_usage_logger()


def get_achievement_service_dep():
    from app.services.achievement_service import get_achievement_service
    return get_achievement_service()


