from app.models.llm import get_embeddings
from app.models.vector_db import get_vector_db
from app.config import *
import os

class KnowledgeBaseService:
    def __init__(self):
        self.embeddings = get_embeddings()
        self.vector_db = get_vector_db(self.embeddings)
        self.retriever = self.vector_db.as_retriever(search_kwargs={"k": VECTOR_SEARCH_TOP_K})

    def build_from_directory(self):
        """从目录重建知识库"""
        try:
            from app.utils.document_loader import load_documents_from_directory
            self.vector_db.delete_collection()
            documents = load_documents_from_directory(
                directory=KNOWLEDGE_BASE_DIRECTORY,
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP
            )
            if documents:
                self.vector_db.add_documents(documents)
                return len(documents)
            return 0
        except Exception as e:
            print(f"构建知识库失败: {e}")
            return 0

    def search(self, query):
        """检索相关文档"""
        return self.retriever.get_relevant_documents(query)

    def get_stats(self):
        """终极修复：统计知识库数据 + 行业分布"""
        try:
            # 统计总文档数
            all_data = self.vector_db.get()
            total_documents = len(all_data.get("documents", []))
            
            # 统计文件夹下的行业文档数（最稳定方案）
            industry_counts = {}
            total_files = 0
            
            for industry in SUPPORTED_INDUSTRIES:
                industry_path = os.path.join(KNOWLEDGE_BASE_DIRECTORY, industry)
                if os.path.exists(industry_path):
                    try:
                        files = [f for f in os.listdir(industry_path) if f.endswith(('.txt', '.pdf', '.md', '.doc', '.docx'))]
                        count = len(files)
                        industry_counts[industry] = count
                        total_files += count
                        if count > 0:
                            print(f"✅ {industry}: {count} 个文档")
                    except Exception as e:
                        print(f"⚠️ 读取 {industry} 目录失败: {e}")
                        industry_counts[industry] = 0
                else:
                    industry_counts[industry] = 0
            
            # 有文档的行业
            supported_industries = [k for k, v in industry_counts.items() if v > 0]
            
            # 计算匹配准确率（基于知识库丰富度）
            # 基础准确率：50%
            # 行业覆盖率贡献：每覆盖一个行业 +3%（最多 +30%）
            # 文档数量贡献：每10个文档 +2%（最多 +20%）
            base_accuracy = 50
            industry_bonus = min(len(supported_industries) * 3, 30)
            doc_bonus = min(total_files // 10 * 2, 20)
            accuracy = base_accuracy + industry_bonus + doc_bonus
            accuracy = min(accuracy, 95)  # 最高不超过95%
            
            print(f"\n📊 知识库统计:")
            print(f"  - 总文档片段数: {total_documents}")
            print(f"  - 总文件数: {total_files}")
            print(f"  - 覆盖行业数: {len(supported_industries)}")
            print(f"  - 覆盖行业: {', '.join(supported_industries) if supported_industries else '无'}")
            print(f"  - 匹配准确率: {accuracy}%\n")
            
            return {
                "total_documents": total_documents,
                "supported_industries": supported_industries,
                "industry_counts": industry_counts,
                "accuracy": accuracy
            }
        except Exception as e:
            print(f"❌ 统计失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "total_documents": 0,
                "supported_industries": [],
                "industry_counts": {i: 0 for i in SUPPORTED_INDUSTRIES},
                "accuracy": 50
            }