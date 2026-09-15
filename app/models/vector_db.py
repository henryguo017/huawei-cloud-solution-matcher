# -*- coding: utf-8 -*-
"""向量数据库抽象层（可插拔）。

提供统一接口 VectorDB，当前两种实现：
  - ChromaVectorDB：默认可用实现（wraps langchain_community Chroma），行为与旧代码完全一致；
  - GaussDBVectorDB：华为云 GaussDB（pgvector）扩展点，凭据缺失/驱动未装时给出可操作错误，而非裸 NotImplementedError。

工厂 get_vector_db(embeddings, persist_directory) 按 VECTOR_DB_PROVIDER 选择实现：
  - "chroma"（默认）：ChromaVectorDB
  - "gaussdb"：GaussDBVectorDB（结构化扩展点，待接入 pgvector 客户端）
"""
import os
from app.models.llm import get_embeddings
from langchain_community.vectorstores import Chroma
from app.config import *

import logging
logger = logging.getLogger(__name__)


class VectorDBConfigError(Exception):
    """向量库配置缺失或不支持时抛出的可操作错误（替代裸 NotImplementedError）。"""


class VectorDB:
    """统一向量库接口（抽象基类）。

    仅声明项目实际用到的方法；具体实现见 ChromaVectorDB / GaussDBVectorDB。
    """

    def add_texts(self, texts, metadatas=None, **kwargs):
        raise NotImplementedError

    def add_documents(self, documents, ids=None, **kwargs):
        raise NotImplementedError

    def similarity_search(self, query, k=4, **kwargs):
        raise NotImplementedError

    def similarity_search_with_score(self, query, k=4, **kwargs):
        raise NotImplementedError

    def as_retriever(self, search_type="similarity", search_kwargs=None):
        raise NotImplementedError

    def get(self, ids=None, **kwargs):
        raise NotImplementedError

    def delete_collection(self):
        raise NotImplementedError

    def persist(self):
        raise NotImplementedError


class ChromaVectorDB(VectorDB):
    """默认实现：包装 langchain_community Chroma，对外暴露与旧代码完全一致的接口。

    所有方法直接委托底层 Chroma 实例；未知方法经 __getattr__ 透传，保证不破坏现有 chroma 用法。
    """

    def __init__(self, embeddings, persist_directory=VECTOR_DB_PERSIST_DIRECTORY):
        self._store = Chroma(
            persist_directory=persist_directory,
            embedding_function=embeddings,
            collection_name="huawei_solutions",
        )

    def __getattr__(self, name):
        # 兜底：任何未在子类中显式声明的方法，直接委托底层 Chroma 实例
        return getattr(self._store, name)

    # 显式委托（清晰可读；__getattr__ 已覆盖其余）
    def add_texts(self, texts, metadatas=None, **kwargs):
        return self._store.add_texts(texts, metadatas=metadatas, **kwargs)

    def add_documents(self, documents, ids=None, **kwargs):
        return self._store.add_documents(documents, ids=ids, **kwargs)

    def similarity_search(self, query, k=4, **kwargs):
        return self._store.similarity_search(query, k=k, **kwargs)

    def similarity_search_with_score(self, query, k=4, **kwargs):
        return self._store.similarity_search_with_score(query, k=k, **kwargs)

    def as_retriever(self, search_type="similarity", search_kwargs=None):
        return self._store.as_retriever(search_type=search_type, search_kwargs=search_kwargs)

    def get(self, ids=None, **kwargs):
        return self._store.get(ids=ids, **kwargs)

    def delete_collection(self):
        return self._store.delete_collection()

    def persist(self):
        return self._store.persist()


class GaussDBVectorDB(VectorDB):
    """华为云 GaussDB（pgvector）扩展点。

    结构化占位：凭据齐全且驱动可用时，应在此建立 pgvector 连接并实现向量检索；
    当前未实现，凭据缺失/驱动未装时统一抛出 VectorDBConfigError（可操作指引），不裸 NotImplementedError。
    """

    def __init__(self, embeddings, persist_directory=None):
        self._embeddings = embeddings
        # 读取华为云 GaussDB 向量库凭据（VECTOR_DB_TYPE 命名空间下的华为云配置）
        host = os.getenv("GAUSSDB_HOST")
        port = os.getenv("GAUSSDB_PORT")
        user = os.getenv("GAUSSDB_USER")
        password = os.getenv("GAUSSDB_PASSWORD")
        database = os.getenv("GAUSSDB_DATABASE")
        table = os.getenv("GAUSSDB_EMBEDDING_TABLE", "huawei_solutions")
        if not all([host, port, user, password, database]):
            raise VectorDBConfigError(
                "未配置华为云 GaussDB 向量库凭据，无法启用 gaussdb 模式。\n"
                "启用步骤：\n"
                "  1) 在 .env 设置 GAUSSDB_HOST / GAUSSDB_PORT / GAUSSDB_USER / GAUSSDB_PASSWORD "
                "/ GAUSSDB_DATABASE / GAUSSDB_EMBEDDING_TABLE；\n"
                "  2) 在 requirements.txt 增加 psycopg2-binary 并安装；\n"
                "  3) 在 GaussDBVectorDB 中接入 pgvector 客户端并实现 similarity_search / add_documents 等方法。\n"
                "当前默认 chroma 模式完全可用，无需切换。"
            )
        self._conn_info = {
            "host": host, "port": port, "user": user,
            "password": password, "database": database, "table": table,
        }
        # 驱动懒加载：不强制依赖，缺驱动时给出可操作错误
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            raise VectorDBConfigError(
                "gaussdb 模式需要 psycopg2 驱动。请执行：pip install psycopg2-binary"
            )
        # TODO(接入): 建立连接、确保 pgvector 扩展与向量表存在，并实现向量检索。
        raise VectorDBConfigError(
            "GaussDB 向量检索客户端尚未实现（扩展点已就位）。\n"
            "请在 GaussDBVectorDB 中接入 pgvector 客户端，并实现 similarity_search / "
            "similarity_search_with_score / add_documents / get / delete_collection 等方法。"
        )

    # 接口占位：真正接入 pgvector 后实现
    def add_texts(self, texts, metadatas=None, **kwargs):
        raise VectorDBConfigError("GaussDB 向量检索客户端尚未实现（扩展点）")

    def add_documents(self, documents, ids=None, **kwargs):
        raise VectorDBConfigError("GaussDB 向量检索客户端尚未实现（扩展点）")

    def similarity_search(self, query, k=4, **kwargs):
        raise VectorDBConfigError("GaussDB 向量检索客户端尚未实现（扩展点）")

    def similarity_search_with_score(self, query, k=4, **kwargs):
        raise VectorDBConfigError("GaussDB 向量检索客户端尚未实现（扩展点）")

    def as_retriever(self, search_type="similarity", search_kwargs=None):
        raise VectorDBConfigError("GaussDB 向量检索客户端尚未实现（扩展点）")

    def get(self, ids=None, **kwargs):
        raise VectorDBConfigError("GaussDB 向量检索客户端尚未实现（扩展点）")

    def delete_collection(self):
        raise VectorDBConfigError("GaussDB 向量检索客户端尚未实现（扩展点）")

    def persist(self):
        raise VectorDBConfigError("GaussDB 向量检索客户端尚未实现（扩展点）")


def get_vector_db(embeddings, persist_directory=VECTOR_DB_PERSIST_DIRECTORY):
    """工厂：按 VECTOR_DB_PROVIDER 选择向量库实现（默认 chroma）。"""
    provider = (VECTOR_DB_PROVIDER or "chroma").lower().strip()
    if provider == "chroma":
        return ChromaVectorDB(embeddings, persist_directory)
    if provider == "gaussdb":
        return GaussDBVectorDB(embeddings, persist_directory)
    raise VectorDBConfigError(
        f"不支持的向量库类型: {VECTOR_DB_PROVIDER}（当前仅支持 chroma / gaussdb 扩展点）"
    )


# 测试代码
if __name__ == "__main__":
    try:
        embeddings = get_embeddings()
        db = get_vector_db(embeddings)

        # 写入测试文本
        test_texts = [
            "华为云智慧农业解决方案提供环境精准控制和生长模型数字化功能",
            "华为云工业互联网解决方案提供设备预测性维护和数字孪生功能",
            "华为云智慧园区解决方案提供智能安防和能源管理功能"
        ]
        db.add_texts(test_texts)

        # 检索测试
        search_res = db.similarity_search("农业", k=1)
        logger.info('✅ 向量数据库适配DeepSeek测试成功')
        logger.info(" ".join(map(str, ['检索结果：', search_res[0].page_content])))

        # 清空测试数据
        db.delete_collection()

    except Exception as e:
        logger.info('❌ 向量库测试失败')
        logger.info(" ".join(map(str, ['报错：', str(e)])))
