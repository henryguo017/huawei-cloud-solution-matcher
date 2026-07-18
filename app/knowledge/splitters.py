"""
文档切分器策略族（ruoyi-ai 学习项 #2：可插拔 splitter）

- BaseSplitter：所有切分器基类。
- 注册表：名称 → 切分器类，新增切分策略（如按 token / 按代码语义）只需实现子类并注册。
- 默认 recursive 策略参数与原 DocumentLoader 完全一致（CHUNK_SIZE / CHUNK_OVERLAP）。
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Type

from langchain_core.documents import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from app.config import CHUNK_SIZE, CHUNK_OVERLAP


class BaseSplitter(ABC):
    @abstractmethod
    def split(self, documents: List[Document]) -> List[Document]:
        ...


class RecursiveCharacterSplitter(BaseSplitter):
    """递归字符切分（与原 DocumentLoader.text_splitter 参数一致）。"""

    def __init__(self, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP):
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )

    def split(self, documents: List[Document]) -> List[Document]:
        return self._splitter.split_documents(documents)


# ===================== 切分器注册表 =====================
_SPLITTER_REGISTRY: Dict[str, Type[BaseSplitter]] = {
    "recursive": RecursiveCharacterSplitter,
}


def get_splitter(name: str = "recursive", **kwargs) -> BaseSplitter:
    cls = _SPLITTER_REGISTRY.get(name)
    if not cls:
        raise ValueError(f"未知的分片器: {name}")
    return cls(**kwargs)
