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
        key = _rate_limit_key(request)
        bucket = _ratelimit_buckets.setdefault(key, [])
        bucket[:] = [t for t in bucket if t > now - window]
        if len(bucket) >= limit:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
        bucket.append(now)
        if len(_ratelimit_buckets) > 10000:
            for k in [k for k, v in _ratelimit_buckets.items() if not v]:
                _ratelimit_buckets.pop(k, None)
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


