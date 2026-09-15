"""
文档加载器策略族（ruoyi-ai 学习项 #2：可插拔 loader）

- BaseLoader：所有加载器基类，声明支持的后缀并实现 load()。
- 注册表：扩展名 → 加载器类，新增格式只需实现子类并注册，零侵入。
- 加载后统一补 metadata（source=文件名, industry=父目录名），与原 DocumentLoader 行为一致。
"""
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Type

from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader


class BaseLoader(ABC):
    """文档加载器基类。"""

    supported_extensions: tuple = ()

    @classmethod
    def supports(cls, ext: str) -> bool:
        return ext.lower() in cls.supported_extensions

    @abstractmethod
    def load(self, file_path: str) -> List[Document]:
        """加载单个文件为 Document 列表。"""
        ...

    def _attach_metadata(self, documents: List[Document], file_path: str) -> List[Document]:
        file_name = os.path.basename(file_path)
        industry = os.path.basename(os.path.dirname(file_path))
        for doc in documents:
            doc.metadata["source"] = file_name
            doc.metadata["industry"] = industry
        return documents


class PdfLoader(BaseLoader):
    supported_extensions = (".pdf",)

    def load(self, file_path: str) -> List[Document]:
        docs = PyPDFLoader(file_path).load()
        return self._attach_metadata(docs, file_path)


class TextLoader(BaseLoader):
    # .md 用 TextLoader 处理即可（纯文本）
    supported_extensions = (".txt", ".md")

    def load(self, file_path: str) -> List[Document]:
        # 直接读纯文本，跨 langchain 版本零依赖（输出与 TextLoader 一致：单 Document + 全文）
        with open(file_path, encoding="utf-8") as fh:
            text = fh.read()
        docs = [Document(page_content=text, metadata={})]
        return self._attach_metadata(docs, file_path)


# ===================== 加载器注册表 =====================
_LOADER_REGISTRY: Dict[str, Type[BaseLoader]] = {}


def register_loader(cls: Type[BaseLoader]) -> Type[BaseLoader]:
    for ext in cls.supported_extensions:
        _LOADER_REGISTRY[ext.lower()] = cls
    return cls


for _cls in (PdfLoader, TextLoader):
    register_loader(_cls)


def get_loader(file_path: str) -> BaseLoader:
    """按文件后缀返回对应加载器实例；不支持的格式抛 ValueError（与原行为一致）。"""
    ext = os.path.splitext(file_path)[1].lower()
    cls = _LOADER_REGISTRY.get(ext)
    if not cls:
        raise ValueError(f"不支持的文件格式: {ext}")
    return cls()
