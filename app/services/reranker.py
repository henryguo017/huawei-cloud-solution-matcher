"""本地 bge-reranker 重排后端（粗排+精排两段式检索的「精排」）。

设计要点：
- 仅在 ENABLE_RERANK=true 时，由 knowledge_base._rerank 延迟导入本模块（模块加载即注册到
  RERANKER_REGISTRY["default"]）。不依赖 knowledge_base 顶层 import，避免循环依赖。
- 模型懒加载（首次重排才 import transformers/torch），不影响服务启动、不强制装依赖。
- 任何加载/推理失败均回退透传（顺序不变、绝不降质），符合 _rerank 的失败安全契约。
"""
import logging
from typing import List

logger = logging.getLogger(__name__)

_RERANKER = None  # (model, tokenizer, device) 缓存，避免重复加载


def _load_model():
    """懒加载 bge-reranker 交叉编码器，返回 (model, tokenizer, device)。"""
    global _RERANKER
    if _RERANKER is not None:
        return _RERANKER
    from app.config import RERANK_MODEL_NAME
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification

    model_name = RERANK_MODEL_NAME
    logger.info(f"[rerank] 加载重排模型: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    _RERANKER = (model, tokenizer, device)
    logger.info(f"[rerank] 重排模型就绪 device={device}")
    return _RERANKER


def _bge_rerank(query: str, docs: List, batch_size: int = 16) -> List:
    """对候选文档按与 query 的相关性降序重排。失败一律回退透传。

    参数:
        query: 用户需求/检索问句
        docs:  候选 Document 列表（粗排召回的候选池）
    返回:
        按相关性降序的 Document 列表（失败时返回原 docs，顺序不变）
    """
    if not docs:
        return docs
    try:
        model, tokenizer, device = _load_model()
    except Exception as e:
        logger.warning(f"[rerank] 模型加载失败,回退透传: {e}")
        return docs
    try:
        pairs = [[query, getattr(d, "page_content", str(d))] for d in docs]
        scores = []
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i:i + batch_size]
            enc = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            enc = {k: v.to(device) for k, v in enc.items()}
            with torch.no_grad():
                logits = model(**enc).logits.view(-1).float()
            scores.extend(logits.tolist())
        ranked = [d for _, d in sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)]
        return ranked
    except Exception as e:
        logger.warning(f"[rerank] 推理失败,回退透传: {e}")
        return docs


# 注册到 knowledge_base 的可插拔重排注册表。
# 此处延迟导入 knowledge_base 仅取 RERANKER_REGISTRY（其已在模块第16行定义），
# 不会在 knowledge_base 加载期触发本模块（本模块仅由 _rerank 运行时延迟导入），无循环依赖。
from app.services.knowledge_base import RERANKER_REGISTRY
RERANKER_REGISTRY["default"] = _bge_rerank
