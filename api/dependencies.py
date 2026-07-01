from typing import Dict
from app.services.solution_matcher import SolutionMatcherService
from app.services.competitor_analyzer import CompetitorAnalyzerService
from app.services.knowledge_base import KnowledgeBaseService
from app.services.usage_logger import UsageLoggerService, get_usage_logger as _get_usage_logger

# ===== 全局知识库单例（仅用于健康检查、管理员全局重建等系统级操作） =====
_global_kb: KnowledgeBaseService = None

def get_knowledge_base() -> KnowledgeBaseService:
    """获取全局/系统知识库实例（用于健康检查、重建等系统操作）"""
    global _global_kb
    if _global_kb is None:
        _global_kb = KnowledgeBaseService(user_id=0)
    return _global_kb


# ===== 用户独立知识库缓存（按 user_id 键控） =====
_user_kb_cache: Dict[int, KnowledgeBaseService] = {}

import os as _os
from app.config import USER_DOCS_BASE_DIR

def get_user_knowledge_base(user_id: int) -> KnowledgeBaseService:
    """获取用户独立的知识库实例（按 user_id 缓存，每个用户一个独立 ChromaDB）
    
    首次访问时自动检测：如果用户 KB 目录不存在，先从默认 KB 复制。
    """
    if user_id <= 0:
        return get_knowledge_base()
    if user_id not in _user_kb_cache:
        # 检查用户 KB 是否存在（通过向量库目录判断）
        user_vdb = _os.path.join(USER_DOCS_BASE_DIR, str(user_id), 'vector_db')
        if not _os.path.exists(user_vdb) or not _os.listdir(user_vdb):
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[KB] 用户 {user_id} 知识库不存在，从默认KB复制...")
            KnowledgeBaseService.copy_from_default(user_id)
            logger.info(f"[KB] 用户 {user_id} 知识库初始化完成")
        _user_kb_cache[user_id] = KnowledgeBaseService(user_id=user_id)
    return _user_kb_cache[user_id]


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


from api.auth_dependencies import get_current_user, get_current_user_optional
