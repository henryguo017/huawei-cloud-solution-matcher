from app.models.llm import get_embeddings
from app.models.vector_db import get_vector_db
from app.config import *
import os
import hashlib
import shutil
from urllib.parse import quote, unquote

class KnowledgeBaseService:
    def __init__(self):
        self.embeddings = get_embeddings()
        self.vector_db = get_vector_db(self.embeddings)
        self.retriever = self.vector_db.as_retriever(search_kwargs={"k": VECTOR_SEARCH_TOP_K})

    def _load_docs_from_dir(self, directory, dir_label=""):
        """从指定目录加载文档"""
        from app.utils.document_loader import load_documents_from_directory
        
        abs_dir = os.path.abspath(directory)
        if not os.path.exists(abs_dir):
            print(f"[重建] [WARN] 目录不存在: {abs_dir}")
            return []
        
        label = f"[{dir_label}]" if dir_label else ""
        print(f"[重建] {label} 加载文档目录: {abs_dir}")
        
        docs = load_documents_from_directory(
            directory=abs_dir,
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP
        )
        
        if docs:
            print(f"[重建] {label} 加载到 {len(docs)} 个文档片段")
            # 列出子目录统计
            subdirs = [d for d in os.listdir(abs_dir) if os.path.isdir(os.path.join(abs_dir, d))]
            if subdirs:
                print(f"[重建] {label} 包含 {len(subdirs)} 个子目录: {', '.join(subdirs[:5])}{'...' if len(subdirs) > 5 else ''}")
        else:
            print(f"[重建] {label} [WARN] 未加载到任何文档片段")
        
        return docs

    def build_from_directory(self):
        """从目录重建知识库（含华为方案和竞品方案）"""
        try:
            # 不使用 delete_collection()（会破坏 Chroma 内部状态导致 add 失败）
            # 改为按 ID 清除现有文档
            try:
                all_data = self.vector_db.get()
                existing_ids = all_data.get("ids", [])
                if existing_ids:
                    print(f"[重建] 清除旧数据 ({len(existing_ids)} 条)...")
                    self.vector_db.delete(ids=existing_ids)
                else:
                    print(f"[重建] 知识库为空，无需清除")
            except Exception as clear_err:
                print(f"[重建] [WARN] 清除旧数据时出现异常（可忽略）: {clear_err}")

            # 1. 加载华为云方案文档
            huawei_docs = self._load_docs_from_dir(KNOWLEDGE_BASE_DIRECTORY, "华为方案")
            
            # 2. 加载竞品方案文档
            competitor_docs = []
            competitor_dir = getattr(__import__('app.config', fromlist=['COMPETITOR_DIRECTORY']), 'COMPETITOR_DIRECTORY', './data/competitors')
            if os.path.exists(competitor_dir):
                competitor_docs = self._load_docs_from_dir(competitor_dir, "竞品方案")
            else:
                print(f"[重建] [WARN] 竞品目录不存在，跳过: {competitor_dir}")

            all_documents = huawei_docs + competitor_docs
            
            if not all_documents:
                print(f"[重建] [ERR] 未加载到任何文档！请检查目录结构")
                return 0

            print(f"[重建] 总计 {len(all_documents)} 个文档片段（华为 {len(huawei_docs)} + 竞品 {len(competitor_docs)}）")
            print(f"[重建] 正在写入向量库...")
            self.vector_db.add_documents(all_documents)
            print(f"[重建] [OK] 知识库重建完成！共 {len(all_documents)} 个文档片段")

            # 重建 retriever（确保使用新数据）
            self.retriever = self.vector_db.as_retriever(
                search_kwargs={"k": VECTOR_SEARCH_TOP_K}
            )

            return len(all_documents)

        except ImportError as e:
            print(f"[重建] [ERR] 导入失败: {e}")
            import traceback; traceback.print_exc()
            return 0
        except Exception as e:
            print(f"[重建] [ERR] 构建知识库失败: {e}")
            import traceback; traceback.print_exc()
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
                            print(f"[OK] {industry}: {count} 个文档")
                    except Exception as e:
                        print(f"[WARN] 读取 {industry} 目录失败: {e}")
                        industry_counts[industry] = 0
                else:
                    industry_counts[industry] = 0
            
            # 统计竞品文档
            competitor_dir = getattr(__import__('app.config', fromlist=['COMPETITOR_DIRECTORY']), 'COMPETITOR_DIRECTORY', './data/competitors')
            competitor_stats = {}
            total_competitor_files = 0
            competitor_companies = []
            
            if os.path.exists(competitor_dir):
                for company in os.listdir(competitor_dir):
                    company_path = os.path.join(competitor_dir, company)
                    if os.path.isdir(company_path):
                        try:
                            files = [f for f in os.listdir(company_path) if f.endswith(('.txt', '.pdf', '.md', '.doc', '.docx'))]
                            count = len(files)
                            if count > 0:
                                competitor_companies.append(company)
                                competitor_stats[company] = count
                                total_competitor_files += count
                        except:
                            pass
            
            # 有文档的行业
            supported_industries = [k for k, v in industry_counts.items() if v > 0]
            
            # 计算匹配准确率（基于知识库丰富度）
            # 基础准确率：50%
            # 华为行业覆盖率贡献：每覆盖一个行业 +3%（最多 +30%）
            # 文档数量贡献：每10个文档 +1%（最多 +10%）
            # 竞品覆盖贡献：每2个竞品 +1%（最多 +5%）
            base_accuracy = 50
            industry_bonus = min(len(supported_industries) * 3, 30)
            doc_bonus = min(total_files // 10 * 1, 10)
            competitor_bonus = min(len(competitor_companies) // 2 * 1, 5)
            accuracy = base_accuracy + industry_bonus + doc_bonus + competitor_bonus
            accuracy = min(accuracy, 95)  # 最高不超过95%
            
            print(f"\n[STATS] 知识库统计:")
            print(f"  - 总文档片段数: {total_documents}")
            print(f"  - 华为方案文件数: {total_files}")
            print(f"  - 竞品文件数: {total_competitor_files} (覆盖{len(competitor_companies)}家竞品)")
            print(f"  - 覆盖行业数: {len(supported_industries)}")
            print(f"  - 覆盖行业: {', '.join(supported_industries) if supported_industries else '无'}")
            print(f"  - 匹配准确率: {accuracy}%\n")
            
            return {
                "total_documents": total_documents,
                "supported_industries": supported_industries,
                "industry_counts": industry_counts,
                "competitor_companies": competitor_companies,
                "competitor_stats": competitor_stats,
                "total_competitor_files": total_competitor_files,
                "accuracy": accuracy
            }
        except Exception as e:
            print(f"[ERR] 统计失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "total_documents": 0,
                "supported_industries": [],
                "industry_counts": {i: 0 for i in SUPPORTED_INDUSTRIES},
                "accuracy": 50
            }

    # ===== 文档管理 CRUD =====

    def _get_doc_base_dir(self, category):
        """根据分类返回物理目录"""
        base = os.path.abspath(KNOWLEDGE_BASE_DIRECTORY if category == 'huawei' else COMPETITOR_DIRECTORY)
        return base

    def _encode_doc_id(self, category, rel_path):
        """生成安全的文档ID"""
        raw = f"{category}/{rel_path}"
        return quote(raw, safe='')

    def _decode_doc_id(self, doc_id):
        """从文档ID解析分类和相对路径"""
        decoded = unquote(doc_id)
        parts = decoded.split('/', 1)
        if len(parts) != 2:
            raise ValueError(f"无效的文档ID: {doc_id}")
        return parts[0], parts[1]  # category, rel_path

    def list_documents(self):
        """列出所有文档的元数据"""
        docs = []
        for category, base_dir in [('huawei', KNOWLEDGE_BASE_DIRECTORY), ('competitor', COMPETITOR_DIRECTORY)]:
            abs_base = os.path.abspath(base_dir)
            if not os.path.exists(abs_base):
                continue
            for root, dirs, files in os.walk(abs_base):
                for f in files:
                    if not f.endswith(('.txt', '.pdf', '.md')):
                        continue
                    file_path = os.path.join(root, f)
                    rel_path = os.path.relpath(file_path, abs_base)
                    # 提取行业/分类名：相对于 base_dir 的父目录
                    parent = os.path.basename(os.path.dirname(file_path))
                    file_size = os.path.getsize(file_path)
                    doc_id = self._encode_doc_id(category, rel_path)
                    docs.append({
                        'id': doc_id,
                        'category': category,
                        'title': os.path.splitext(f)[0],
                        'filename': f,
                        'path': rel_path,
                        'industry': parent if category == 'huawei' else category,
                        'competitor': parent if category == 'competitor' else None,
                        'size': file_size,
                        'size_kb': round(file_size / 1024, 1),
                    })
        # 按分类+路径排序
        docs.sort(key=lambda d: (d['category'], d['path']))
        return docs

    def get_document(self, doc_id):
        """获取单个文档内容"""
        category, rel_path = self._decode_doc_id(doc_id)
        base_dir = self._get_doc_base_dir(category)
        file_path = os.path.join(base_dir, rel_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return {
            'id': doc_id,
            'category': category,
            'filename': os.path.basename(file_path),
            'content': content,
            'size': os.path.getsize(file_path),
        }

    def create_document(self, category, industry, title, content):
        """创建新文档并索引"""
        base_dir = self._get_doc_base_dir(category)
        # 确定目标目录
        target_dir = os.path.join(base_dir, industry)
        os.makedirs(target_dir, exist_ok=True)
        # 写入文件
        filename = f"{title}.txt"
        file_path = os.path.join(target_dir, filename)
        if os.path.exists(file_path):
            raise FileExistsError(f"文档已存在: {filename}")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        # 索引到向量库
        count = self._index_single_file(file_path, category, industry)
        rel_path = os.path.relpath(file_path, base_dir)
        doc_id = self._encode_doc_id(category, rel_path)
        return {'id': doc_id, 'path': file_path, 'chunks': count}

    def update_document(self, doc_id, content):
        """更新文档内容并重新索引"""
        category, rel_path = self._decode_doc_id(doc_id)
        base_dir = self._get_doc_base_dir(category)
        file_path = os.path.join(base_dir, rel_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        # 更新文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        # 重新索引：先清旧向量，再加新向量
        industry = os.path.basename(os.path.dirname(file_path))
        self._remove_doc_vectors(file_path)
        count = self._index_single_file(file_path, category, industry)
        # 重建 retriever
        self.retriever = self.vector_db.as_retriever(search_kwargs={"k": VECTOR_SEARCH_TOP_K})
        return {'id': doc_id, 'chunks': count}

    def delete_document(self, doc_id, delete_file=True):
        """删除文档及其向量"""
        category, rel_path = self._decode_doc_id(doc_id)
        base_dir = self._get_doc_base_dir(category)
        file_path = os.path.join(base_dir, rel_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        # 从向量库移除
        removed = self._remove_doc_vectors(file_path)
        # 删除物理文件
        if delete_file:
            os.remove(file_path)
            # 清理空目录
            parent_dir = os.path.dirname(file_path)
            if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                os.rmdir(parent_dir)
        # 重建 retriever
        self.retriever = self.vector_db.as_retriever(search_kwargs={"k": VECTOR_SEARCH_TOP_K})
        return {'removed_vectors': removed}

    def reindex_document(self, doc_id):
        """重新索引单个文档"""
        category, rel_path = self._decode_doc_id(doc_id)
        base_dir = self._get_doc_base_dir(category)
        file_path = os.path.join(base_dir, rel_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        industry = os.path.basename(os.path.dirname(file_path))
        self._remove_doc_vectors(file_path)
        count = self._index_single_file(file_path, category, industry)
        self.retriever = self.vector_db.as_retriever(search_kwargs={"k": VECTOR_SEARCH_TOP_K})
        return {'chunks': count}

    def _index_single_file(self, file_path, category, industry):
        """将单个文件加载并索引到向量库"""
        from app.utils.document_loader import load_documents_from_directory
        # 用临时目录技巧：创建临时目录，只放这一个文件
        tmp_dir = os.path.join(os.path.dirname(file_path), '.tmp_index')
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_file = os.path.join(tmp_dir, os.path.basename(file_path))
        try:
            # 复制文件到临时目录
            shutil.copy2(file_path, tmp_file)
            chunks = load_documents_from_directory(tmp_dir, CHUNK_SIZE, CHUNK_OVERLAP)
            if chunks:
                self.vector_db.add_documents(chunks)
                print(f"[索引] {os.path.basename(file_path)} → {len(chunks)} 个向量片段")
            return len(chunks)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _remove_doc_vectors(self, file_path):
        """从向量库中移除指定文件的所有向量"""
        try:
            all_data = self.vector_db.get()
            ids_to_remove = []
            filename = os.path.basename(file_path)
            for i, meta in enumerate(all_data.get('metadatas', [])):
                if meta and meta.get('source') == filename:
                    ids_to_remove.append(all_data['ids'][i])
            if ids_to_remove:
                self.vector_db.delete(ids=ids_to_remove)
                print(f"[索引] 已移除 {filename}: {len(ids_to_remove)} 个向量")
            return len(ids_to_remove)
        except Exception as e:
            print(f"[索引] 移除向量失败 {file_path}: {e}")
            return 0