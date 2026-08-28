from app.models.llm import get_embeddings
from langchain_community.vectorstores import Chroma
from app.config import *

def get_vector_db(embeddings, persist_directory=VECTOR_DB_PERSIST_DIRECTORY):
    """
    获取向量数据库实例
    当前使用Chroma存储，预留华为云GaussDB扩展位置
    """
    if VECTOR_DB_PROVIDER == "chroma":
        return Chroma(
            persist_directory=persist_directory,
            embedding_function=embeddings,
            collection_name="huawei_solutions"
        )
    
    elif VECTOR_DB_PROVIDER == "gaussdb":
        raise NotImplementedError("华为云GaussDB向量数据库后续接入")
    
    else:
        raise ValueError(f"不支持的数据库类型: {VECTOR_DB_PROVIDER}")

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
        print("✅ 向量数据库适配DeepSeek测试成功")
        print("检索结果：", search_res[0].page_content)

        # 清空测试数据
        db.delete_collection()

    except Exception as e:
        print("❌ 向量库测试失败")
        print("报错：", str(e))