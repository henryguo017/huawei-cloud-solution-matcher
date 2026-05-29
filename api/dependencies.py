from functools import lru_cache
from app.services.solution_matcher import SolutionMatcherService
from app.services.competitor_analyzer import CompetitorAnalyzerService
from app.services.knowledge_base import KnowledgeBaseService
from app.services.usage_logger import UsageLoggerService, get_usage_logger as _get_usage_logger

@lru_cache()
def get_solution_matcher() -> SolutionMatcherService:
    return SolutionMatcherService()

@lru_cache()
def get_competitor_analyzer() -> CompetitorAnalyzerService:
    return CompetitorAnalyzerService()

@lru_cache()
def get_knowledge_base() -> KnowledgeBaseService:
    return KnowledgeBaseService()


def get_usage_logger() -> UsageLoggerService:
    return _get_usage_logger()
