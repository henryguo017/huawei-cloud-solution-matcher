from app.models.llm import get_embeddings
from app.models.vector_db import get_vector_db
from app.config import *
from langchain_core.documents import Document
import os
import logging
import shutil
import contextvars
import re
from urllib.parse import quote, unquote
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# 可插拔重排器注册表（默认空 = no-op；接入 bge-reranker 等时在此注册 "default" 实现）
RERANKER_REGISTRY = {}

# ===== 用户上下文：在线程中传递当前 user_id，供 Agent 工具等无参接口使用 =====
_kb_current_user_id: contextvars.ContextVar[int] = contextvars.ContextVar('kb_user_id', default=0)

def set_kb_user_context(user_id: int):
    """设置当前请求的用户上下文（对 Agent 工具透明传递 user_id）"""
    _kb_current_user_id.set(user_id)

def get_kb_user_context() -> int:
    """获取当前请求的用户 ID，0 表示全局默认"""
    try:
        return _kb_current_user_id.get()
    except LookupError:
        return 0

class KnowledgeBaseService:
    """
    华为云解决方案知识库服务

    支持两种模式：
    - user_id=0（默认）：全局/系统知识库，路径即 config 中配置的默认目录
    - user_id>0：用户独立知识库，路径为 data/user_docs/{user_id}/...
    """

    def __init__(self, user_id: int = 0):
        self.user_id = user_id

        # 根据 user_id 确定物理目录
        if user_id > 0:
            user_base = os.path.join(USER_DOCS_BASE_DIR, str(user_id))
            self._huawei_dir = os.path.abspath(os.path.join(user_base, 'sample_solutions'))
            self._competitor_dir = os.path.abspath(os.path.join(user_base, 'competitors'))
            self._vector_db_dir = os.path.abspath(os.path.join(user_base, 'vector_db'))
        else:
            self._huawei_dir = os.path.abspath(KNOWLEDGE_BASE_DIRECTORY)
            self._competitor_dir = os.path.abspath(COMPETITOR_DIRECTORY)
            self._vector_db_dir = os.path.abspath(VECTOR_DB_PERSIST_DIRECTORY)

        # 确保用户目录存在
        for d in [self._huawei_dir, self._competitor_dir, self._vector_db_dir]:
            os.makedirs(d, exist_ok=True)

        self.embeddings = get_embeddings()
        self.vector_db = get_vector_db(self.embeddings, persist_directory=self._vector_db_dir)
        self.retriever = self.vector_db.as_retriever(search_kwargs={"k": VECTOR_SEARCH_TOP_K})
        # 预计算竞品公司集合，供检索时区分华为/竞品文档
        self._competitor_companies = self._compute_competitor_companies()

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
            subdirs = [d for d in os.listdir(abs_dir) if os.path.isdir(os.path.join(abs_dir, d))]
            if subdirs:
                print(f"[重建] {label} 包含 {len(subdirs)} 个子目录: {', '.join(subdirs[:5])}{'...' if len(subdirs) > 5 else ''}")
        else:
            print(f"[重建] {label} [WARN] 未加载到任何文档片段")

        return docs

    def build_from_directory(self, use_default_dirs: bool = False,
                              on_progress: Optional[Callable[[int, int, str], None]] = None):
        """
        从目录重建知识库（含华为方案和竞品方案）

        Args:
            use_default_dirs: 如果为 True，强制使用全局默认目录（管理员重建全局KB时）
            on_progress: 可选进度回调，签名 (done, total, stage_text)，用于后台任务实时上报进度
        """
        try:
            huawei_dir = os.path.abspath(KNOWLEDGE_BASE_DIRECTORY) if use_default_dirs else self._huawei_dir
            competitor_dir = os.path.abspath(COMPETITOR_DIRECTORY) if use_default_dirs else self._competitor_dir

            # 清除现有数据
            try:
                all_data = self.vector_db.get()
                existing_ids = all_data.get("ids", [])
                if existing_ids:
                    print(f"[重建] 清除旧数据 ({len(existing_ids)} 条)...")
                    self.vector_db.delete(ids=existing_ids)
                else:
                    print("[重建] 知识库为空，无需清除")
            except Exception as clear_err:
                print(f"[重建] [WARN] 清除旧数据时出现异常（可忽略）: {clear_err}")

            # 1. 加载华为云方案文档
            huawei_docs = self._load_docs_from_dir(huawei_dir, "华为方案")

            # 2. 加载竞品方案文档
            competitor_docs = []
            if os.path.exists(competitor_dir):
                competitor_docs = self._load_docs_from_dir(competitor_dir, "竞品方案")
            else:
                print(f"[重建] [WARN] 竞品目录不存在，跳过: {competitor_dir}")

            all_documents = huawei_docs + competitor_docs

            if not all_documents:
                print("[重建] [ERR] 未加载到任何文档！请检查目录结构")
                return 0

            print(f"[重建] 总计 {len(all_documents)} 个文档片段（华为 {len(huawei_docs)} + 竞品 {len(competitor_docs)}）")

            # 分批写入向量库并上报进度（CPU 嵌入耗时较长，分批让前端能看到进度）
            total = len(all_documents)
            batch_size = 50
            if on_progress:
                on_progress(0, total, f"正在生成向量嵌入（共 {total} 个片段）...")
            for i in range(0, total, batch_size):
                chunk = all_documents[i:i + batch_size]
                self.vector_db.add_documents(chunk)
                if on_progress:
                    done = min(i + batch_size, total)
                    on_progress(done, total, f"正在生成向量嵌入（{done}/{total}）...")

            print(f"[重建] [OK] 知识库重建完成！共 {total} 个文档片段")

            # 重建 retriever
            self.retriever = self.vector_db.as_retriever(
                search_kwargs={"k": VECTOR_SEARCH_TOP_K}
            )

            return total

        except ImportError as e:
            print(f"[重建] [ERR] 导入失败: {e}")
            import traceback; traceback.print_exc()
            return 0
        except Exception as e:
            print(f"[重建] [ERR] 构建知识库失败: {e}")
            import traceback; traceback.print_exc()
            return 0

    # ===== 用户知识库复制（注册时调用） =====

    @staticmethod
    def copy_from_default(user_id: int) -> bool:
        """
        为新用户复制默认知识库（文件 + 向量库）。

        复制内容：
        1. data/sample_solutions/ → data/user_docs/{user_id}/sample_solutions/
        2. data/competitors/      → data/user_docs/{user_id}/competitors/
        3. data/vector_db/        → data/user_docs/{user_id}/vector_db/
        """
        user_base = os.path.abspath(os.path.join(USER_DOCS_BASE_DIR, str(user_id)))

        # 源目录
        src_huawei = os.path.abspath(KNOWLEDGE_BASE_DIRECTORY)
        src_competitor = os.path.abspath(COMPETITOR_DIRECTORY)
        src_vectordb = os.path.abspath(VECTOR_DB_PERSIST_DIRECTORY)

        # 目标目录
        dst_huawei = os.path.join(user_base, 'sample_solutions')
        dst_competitor = os.path.join(user_base, 'competitors')
        dst_vectordb = os.path.join(user_base, 'vector_db')

        try:
            # 1. 复制华为方案文档
            if os.path.exists(src_huawei):
                print(f"[用户{user_id}] 复制华为方案: {src_huawei} → {dst_huawei}")
                shutil.copytree(src_huawei, dst_huawei, dirs_exist_ok=True)

            # 2. 复制竞品文档
            if os.path.exists(src_competitor):
                print(f"[用户{user_id}] 复制竞品方案: {src_competitor} → {dst_competitor}")
                shutil.copytree(src_competitor, dst_competitor, dirs_exist_ok=True)

            # 3. 复制向量数据库
            if os.path.exists(src_vectordb):
                print(f"[用户{user_id}] 复制向量库: {src_vectordb} → {dst_vectordb}")
                shutil.copytree(src_vectordb, dst_vectordb, dirs_exist_ok=True)
                # 注意：ChromaDB 的 SQLite 文件中有绝对路径引用，但使用 persist_directory 参数可以正常加载

            # 4. 验证：创建 KnowledgeBaseService 实例，检查数据完整性
            try:
                kb = KnowledgeBaseService(user_id=user_id)
                stats = kb.get_stats()
                print(f"[用户{user_id}] 复制完成，共 {stats.get('total_documents', 0)} 个向量片段")
            except Exception as verify_err:
                print(f"[用户{user_id}] [WARN] 验证知识库失败（可忽略，后续使用时自动修正）: {verify_err}")

            return True

        except Exception as e:
            print(f"[用户{user_id}] [ERR] 复制知识库失败: {e}")
            import traceback; traceback.print_exc()
            # 失败时清理部分复制的目录
            if os.path.exists(user_base):
                try:
                    shutil.rmtree(user_base)
                except:
                    pass
            return False

    def search(self, query):
        """检索相关文档"""
        return self.retriever.get_relevant_documents(query)

    # ===== 拆分检索：主方案用华为云方案文档，竞品对比用竞品文档 =====
    def _compute_competitor_companies(self):
        """从竞品目录子文件夹名推断竞品公司集合"""
        companies = set()
        if os.path.isdir(self._competitor_dir):
            try:
                for name in os.listdir(self._competitor_dir):
                    if os.path.isdir(os.path.join(self._competitor_dir, name)):
                        companies.add(name)
            except Exception:
                pass
        return companies

    def _similarity_pool(self, query, pool_size=15):
        """取一个较大的候选池，供后续按华为/竞品拆分"""
        try:
            if ENABLE_HYBRID_RETRIEVAL:
                return self._hybrid_pool(query, pool_size)
            return self.vector_db.similarity_search(query, k=pool_size)
        except Exception as e:
            logger.warning(f"向量检索异常: {e}")
            return []

    # ===================== RAG 三段式（ruoyi-ai 学习项 #1，默认关闭）====================
    def _keyword_recall(self, query, top_n=40):
        """关键词全文召回：扫描全库文档，按查询词重叠度打分排序（无新依赖）。

        返回 [(Document, score), ...] 按 score 降序。
        """
        try:
            data = self.vector_db.get()
        except Exception as e:
            logger.warning(f"关键词召回获取全库失败: {e}")
            return []
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        if not docs:
            return []

        # 查询词：按非汉字/字母/数字边界切分，并保留原句做子串匹配
        import re
        tokens = [t for t in re.split(r"[\s,，。、；;:：!！?？()（）\"'\"'<>《》/]+", query) if t]
        tokens = [t for t in tokens if len(t) >= 2]  # 过短词噪音大
        if not tokens:
            return []

        scored = []
        for text, meta in zip(docs, metas):
            if not text:
                continue
            hit = sum(1 for t in tokens if t in text)
            if hit == 0:
                continue
            score = hit / len(tokens)
            # 复用 metadatas（可能为 None）
            md = dict(meta) if isinstance(meta, dict) else {}
            from langchain_core.documents import Document
            scored.append((Document(page_content=text, metadata=md), score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]

    def _rrf_fuse(self, vector_ranked, keyword_ranked, alpha=RAG_RRF_ALPHA, k=RAG_RRF_K):
        """RRF 倒数排名融合：fused = alpha * RRF(vector) + (1-alpha) * RRF(keyword)。

        vector_ranked / keyword_ranked: [(Document, score), ...]（顺序即排名）。
        返回按融合分降序的 Document 列表，并在 metadata 写入 _score。
        """
        fused = {}
        for ranked, weight in ((vector_ranked, alpha), (keyword_ranked, 1 - alpha)):
            for rank, (doc, _s) in enumerate(ranked, start=1):
                key = (doc.page_content, doc.metadata.get("source"), doc.metadata.get("industry"))
                fused.setdefault(key, {"doc": doc, "score": 0.0})
                fused[key]["score"] += weight / (rank + k)
        items = sorted(fused.values(), key=lambda x: x["score"], reverse=True)
        result = []
        for it in items:
            doc = it["doc"]
            doc.metadata = dict(doc.metadata)
            doc.metadata["_score"] = round(it["score"], 6)
            result.append(doc)
        return result

    def _rerank(self, query, docs):
        """可插拔重排钩子（默认 no-op）。

        当前未接入重排后端（如 bge-reranker）。开启 ENABLE_RERANK 但无后端时安全透传，
        仅告警，不改变顺序/内容；接入时在 RERANKER_REGISTRY 注册实现即可。
        """
        if not ENABLE_RERANK:
            return docs
        reranker = RERANKER_REGISTRY.get("default")
        if reranker is None:
            logger.warning("ENABLE_RERANK=true 但未配置重排后端,安全透传(顺序不变)")
            return docs
        try:
            return reranker(query, docs)
        except Exception as e:
            logger.warning(f"重排失败,回退透传: {e}")
            return docs

    def _hybrid_pool(self, query, pool_size=15):
        """混合召回候选池：向量召回 + 关键词全文召回 → RRF 融合 → 重排 → 阈值过滤。"""
        # 1) 向量召回（带分数）
        try:
            vector_res = self.vector_db.similarity_search_with_score(query, k=pool_size)
        except Exception as e:
            logger.warning(f"向量召回失败,降级为纯关键词: {e}")
            vector_res = []
        # 2) 关键词全文召回
        keyword_res = self._keyword_recall(query, top_n=max(pool_size * 3, 40))
        # 3) RRF 融合
        fused = self._rrf_fuse(vector_res, keyword_res)
        # 4) 重排（可插拔，默认 no-op）
        fused = self._rerank(query, fused)
        # 5) 阈值过滤
        if RAG_THRESHOLD > 0:
            fused = [d for d in fused if (d.metadata or {}).get("_score", 1.0) >= RAG_THRESHOLD]
        return fused[:pool_size]

    def search_huawei(self, query, k=4):
        """只召回华为云方案文档（主方案落地用）——直接在华为子集上检索，避免被竞品挤出前排"""
        comp = self._competitor_companies
        results = []
        try:
            results = self.vector_db.similarity_search(
                query, k=k, filter={"industry": {"$nin": list(comp)}}
            )
        except Exception as e:
            logger.warning(f"华为子集检索异常，回退混合池: {e}")
        # 召回不足时在更大混合池中补充华为文档（竞品过多时仍保底）
        if len(results) < k:
            seen = {d.page_content for d in results}
            pool = self._similarity_pool(query, pool_size=max(k * 4, 40))
            for d in pool:
                if (d.metadata or {}).get("industry", "") not in comp and d.page_content not in seen:
                    results.append(d)
                    seen.add(d.page_content)
                    if len(results) >= k:
                        break
        return results[:k]

    def search_competitor(self, query, k=2):
        """只召回竞品方案文档（竞品对比章节用）——直接在竞品子集上检索"""
        comp = self._competitor_companies
        results = []
        try:
            results = self.vector_db.similarity_search(
                query, k=k, filter={"industry": {"$in": list(comp)}}
            )
        except Exception as e:
            logger.warning(f"竞品子集检索异常，回退混合池: {e}")
        if len(results) < k:
            seen = {d.page_content for d in results}
            pool = self._similarity_pool(query, pool_size=max(k * 4, 40))
            for d in pool:
                if (d.metadata or {}).get("industry", "") in comp and d.page_content not in seen:
                    results.append(d)
                    seen.add(d.page_content)
                    if len(results) >= k:
                        break
        return results[:k]

    def get_stats(self):
        """统计知识库数据 + 行业分布"""
        try:
            # 统计总文档数
            all_data = self.vector_db.get()
            total_documents = len(all_data.get("documents", []))

            # 统计文件夹下的行业文档数
            industry_counts = {}
            total_files = 0

            for industry in SUPPORTED_INDUSTRIES:
                industry_path = os.path.join(self._huawei_dir, industry)
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
            competitor_stats = {}
            total_competitor_files = 0
            competitor_companies = []

            if os.path.exists(self._competitor_dir):
                for company in os.listdir(self._competitor_dir):
                    company_path = os.path.join(self._competitor_dir, company)
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

            # 计算方案覆盖度（基于行业/文档/竞品覆盖的估算值，非真实匹配准确率）
            base_accuracy = 50
            industry_bonus = min(len(supported_industries) * 3, 30)
            doc_bonus = min(total_files // 10 * 1, 10)
            competitor_bonus = min(len(competitor_companies) // 2 * 1, 5)
            accuracy = base_accuracy + industry_bonus + doc_bonus + competitor_bonus
            accuracy = min(accuracy, 95)

            print(f"\n[STATS] 知识库统计 (user_id={self.user_id}):")
            print(f"  - 总文档片段数: {total_documents}")
            print(f"  - 华为方案文件数: {total_files}")
            print(f"  - 竞品文件数: {total_competitor_files} (覆盖{len(competitor_companies)}家竞品)")
            print(f"  - 覆盖行业数: {len(supported_industries)}")
            print(f"  - 覆盖行业: {', '.join(supported_industries) if supported_industries else '无'}")
            print(f"  - 方案覆盖度: {accuracy}%\n")

            return {
                "total_documents": total_documents,
                "supported_industries": supported_industries,
                "industry_counts": industry_counts,
                "competitor_companies": competitor_companies,
                "competitor_stats": competitor_stats,
                "total_competitor_files": total_competitor_files,
                "total_solution_files": total_files + total_competitor_files,
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
                "total_solution_files": 0,
                "accuracy": 50
            }

    # ===== 文档管理 CRUD =====

    def _get_doc_base_dir(self, category):
        """根据分类返回物理目录"""
        base = os.path.abspath(self._huawei_dir if category == 'huawei' else self._competitor_dir)
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
        return parts[0], parts[1]

    def list_documents(self):
        """列出所有文档的元数据"""
        docs = []
        for category, base_dir in [('huawei', self._huawei_dir), ('competitor', self._competitor_dir)]:
            abs_base = os.path.abspath(base_dir)
            if not os.path.exists(abs_base):
                continue
            for root, dirs, files in os.walk(abs_base):
                for f in files:
                    if not f.endswith(('.txt', '.pdf', '.md')):
                        continue
                    file_path = os.path.join(root, f)
                    rel_path = os.path.relpath(file_path, abs_base)
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
        target_dir = os.path.join(base_dir, industry)
        os.makedirs(target_dir, exist_ok=True)
        filename = f"{title}.txt"
        file_path = os.path.join(target_dir, filename)
        if os.path.exists(file_path):
            raise FileExistsError(f"文档已存在: {filename}")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
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
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        industry = os.path.basename(os.path.dirname(file_path))
        self._remove_doc_vectors(file_path)
        count = self._index_single_file(file_path, category, industry)
        self.retriever = self.vector_db.as_retriever(search_kwargs={"k": VECTOR_SEARCH_TOP_K})
        return {'id': doc_id, 'chunks': count}

    def delete_document(self, doc_id, delete_file=True):
        """删除文档及其向量"""
        category, rel_path = self._decode_doc_id(doc_id)
        base_dir = self._get_doc_base_dir(category)
        file_path = os.path.join(base_dir, rel_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        removed = self._remove_doc_vectors(file_path)
        if delete_file:
            os.remove(file_path)
            parent_dir = os.path.dirname(file_path)
            if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                os.rmdir(parent_dir)
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
        tmp_dir = os.path.join(os.path.dirname(file_path), '.tmp_index')
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_file = os.path.join(tmp_dir, os.path.basename(file_path))
        try:
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
