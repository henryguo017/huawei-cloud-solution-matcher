# -*- coding: utf-8 -*-
"""vector_db 可插拔抽象验证（零外部依赖，stub 掉 chromadb/langchain 与 app 包）。

用法（任意 python3）：
    python tests/verify_vector_db_abstraction.py

验证项：
  1. get_vector_db("chroma") 返回 ChromaVectorDB，且方法委托到底层 Chroma 实例；
  2. get_vector_db("gaussdb") 凭据缺失时抛 VectorDBConfigError 且含可操作指引（非裸 NotImplementedError）；
  3. get_vector_db("未知") 抛 VectorDBConfigError；
  4. ChromaVectorDB.__getattr__ 兜底透传未知方法。
"""
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---- 注入 stub，避免 chromadb / app 包重依赖 ----
def _install_stubs():
    app = types.ModuleType("app"); app.__path__ = []; sys.modules["app"] = app
    models = types.ModuleType("app.models"); models.__path__ = []; sys.modules["app.models"] = models

    llm = types.ModuleType("app.models.llm")
    llm.get_embeddings = lambda *a, **k: object()
    sys.modules["app.models.llm"] = llm

    cfg = types.ModuleType("app.config")
    cfg.VECTOR_DB_PROVIDER = "chroma"
    cfg.VECTOR_DB_PERSIST_DIRECTORY = "/tmp/vector_db_test"
    sys.modules["app.config"] = cfg

    lc = types.ModuleType("langchain_community"); lc.__path__ = []; sys.modules["langchain_community"] = lc
    vs = types.ModuleType("langchain_community.vectorstores"); sys.modules["langchain_community.vectorstores"] = vs

    class FakeChroma:
        def __init__(self, persist_directory=None, embedding_function=None, collection_name=None):
            self.persist_directory = persist_directory
            self.embedding_function = embedding_function
            self.collection_name = collection_name
            self.calls = []
        def add_texts(self, texts, metadatas=None, **kw):
            self.calls.append(("add_texts", texts)); return ["id1"]
        def add_documents(self, documents, ids=None, **kw):
            self.calls.append(("add_documents", documents)); return ids or ["id1"]
        def similarity_search(self, query, k=4, **kw):
            self.calls.append(("similarity_search", query, k)); return ["doc"]
        def similarity_search_with_score(self, query, k=4, **kw):
            self.calls.append(("similarity_search_with_score", query, k)); return [("doc", 0.9)]
        def as_retriever(self, search_type="similarity", search_kwargs=None):
            self.calls.append(("as_retriever", search_kwargs)); return "retriever"
        def get(self, ids=None, **kw):
            self.calls.append(("get", ids)); return {"ids": [], "documents": [], "metadatas": []}
        def delete_collection(self):
            self.calls.append(("delete_collection",)); return None
        def persist(self):
            self.calls.append(("persist",)); return None
        def max_marginal_relevance_search(self, query, k=4, **kw):
            self.calls.append(("mmr", query)); return ["doc"]

    vs.Chroma = FakeChroma

    spec = importlib.util.spec_from_file_location(
        "app.models.vector_db", os.path.join(ROOT, "app", "models", "vector_db.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, FakeChroma


def main():
    mod, FakeChroma = _install_stubs()

    # 1) chroma 工厂 + 委托
    emb = object()
    db = mod.get_vector_db(emb)
    assert isinstance(db, mod.ChromaVectorDB), "chroma 应返回 ChromaVectorDB"
    assert isinstance(db._store, FakeChroma), "底层应为 FakeChroma"
    db.add_texts(["t1", "t2"])
    assert db._store.calls[-1][0] == "add_texts"
    r = db.as_retriever(search_kwargs={"k": 5})
    assert r == "retriever", "as_retriever 应委托"
    g = db.get()
    assert g["ids"] == [] and "documents" in g, "get 应委托并返回结构"
    db.similarity_search("q", k=3)
    assert db._store.calls[-1] == ("similarity_search", "q", 3)
    # __getattr__ 兜底透传未知方法
    db.max_marginal_relevance_search("q")
    assert db._store.calls[-1][0] == "mmr"
    print("[1] ChromaVectorDB 工厂 + 委托 + __getattr__ 兜底 通过")

    # 2) gaussdb 凭据缺失 → 可操作错误（非 NotImplementedError）
    mod.VECTOR_DB_PROVIDER = "gaussdb"
    try:
        mod.get_vector_db(emb)
        raise AssertionError("gaussdb 无凭据应抛错")
    except mod.VectorDBConfigError as e:
        assert "GAUSSDB_HOST" in str(e) and "psycopg2" not in str(e).split("\n")[0], "错误应给出配置指引"
        assert "未配置华为云 GaussDB" in str(e)
        print("[2] gaussdb 凭据缺失 → VectorDBConfigError（可操作指引）通过")

    # 3) 未知 provider → 可操作错误
    mod.VECTOR_DB_PROVIDER = "milvus"
    try:
        mod.get_vector_db(emb)
        raise AssertionError("未知 provider 应抛错")
    except mod.VectorDBConfigError as e:
        assert "milvus" in str(e)
        print("[3] 未知 provider → VectorDBConfigError 通过")

    # 4) gaussdb 有凭据但驱动未装 → 可操作错误（psycopg2 指引）
    os.environ["GAUSSDB_HOST"] = "h"; os.environ["GAUSSDB_PORT"] = "5432"
    os.environ["GAUSSDB_USER"] = "u"; os.environ["GAUSSDB_PASSWORD"] = "p"
    os.environ["GAUSSDB_DATABASE"] = "d"
    mod.VECTOR_DB_PROVIDER = "gaussdb"
    try:
        mod.get_vector_db(emb)
        raise AssertionError("驱动未装应抛错")
    except mod.VectorDBConfigError as e:
        assert "psycopg2" in str(e), "应提示安装 psycopg2-binary"
        print("[4] gaussdb 有凭据但驱动未装 → psycopg2 指引 通过")

    print("\n✅ vector_db 可插拔抽象验证通过")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
        sys.exit(rc)
    except AssertionError as e:
        print(f"\n❌ 断言失败: {e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
