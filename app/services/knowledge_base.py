from app.models.llm import get_embeddings
from app.models.vector_db import get_vector_db
from app.config import *
from langchain_core.documents import Document
import os
import time
import json
import hashlib
import logging
import shutil
import contextvars
import re
from pathlib import Path
from collections import OrderedDict
from urllib.parse import quote, unquote
from typing import Optional, Callable, Dict

logger = logging.getLogger(__name__)

_KB_CATEGORIES = {"huawei", "competitor"}

# ===== KB 检索结果 LRU 缓存（带 TTL）=====
# 相同查询（query/k/filter）在 TTL 内复用向量检索结果，省去重复的 query embedding 计算。
# TTL 保证 KB 重建/同步后最多 10 分钟内自动失效，无需手动清理；clear_kb_search_cache() 可立即清。
_KB_CACHE_MAX = 256
_KB_CACHE_TTL = 600  # 秒
_kb_search_cache: "OrderedDict[tuple, tuple]" = OrderedDict()

def _kb_cache_get(key):
    item = _kb_search_cache.get(key)
    if item is None:
        return None
    val, ts = item
    if time.time() - ts > _KB_CACHE_TTL:
        _kb_search_cache.pop(key, None)
        return None
    _kb_search_cache.move_to_end(key)
    return val

def _kb_cache_put(key, val):
    _kb_search_cache[key] = (val, time.time())
    _kb_search_cache.move_to_end(key)
    while len(_kb_search_cache) > _KB_CACHE_MAX:
        _kb_search_cache.popitem(last=False)

def clear_kb_search_cache():
    """KB 重建/同步后调用，立即清空检索缓存（TTL 之外的安全兜底）"""
    _kb_search_cache.clear()

# ===== 增量重建辅助（文件内容哈希 + 确定性向量 id）=====
def _kb_file_sha256(path):
    """计算文件内容 sha256（用于判定文档是否变化）"""
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            for blk in iter(lambda: f.read(65536), b''):
                h.update(blk)
    except Exception:
        return ""
    return h.hexdigest()

def _kb_stable_id(seed: str) -> str:
    """把任意字符串映射为定长、合法的向量库 id（sha1 40 字符）"""
    return hashlib.sha1(seed.encode('utf-8')).hexdigest()

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
        """从指定目录加载文档（每个 chunk 注入 _kb_src = 源文件绝对路径，供增量重建定位）"""
        from app.utils.document_loader import DocumentLoader
        from app.knowledge.splitters import get_splitter

        abs_dir = os.path.abspath(directory)
        if not os.path.exists(abs_dir):
            logger.info(f'[重建] [WARN] 目录不存在: {abs_dir}')
            return []

        label = f"[{dir_label}]" if dir_label else ""
        logger.info(f'[重建] {label} 加载文档目录: {abs_dir}')

        loader = DocumentLoader()
        raw_docs = []
        for root, dirs, files in os.walk(abs_dir):
            for fname in files:
                if os.path.splitext(fname)[1].lower() in (".pdf", ".txt", ".md"):
                    fpath = os.path.abspath(os.path.join(root, fname))
                    try:
                        loaded = loader.load_single_file(fpath)
                        for d in loaded:
                            d.metadata["_kb_src"] = fpath  # 真实源文件路径（含行业子目录，唯一）
                        raw_docs.extend(loaded)
                    except Exception as e:
                        logger.info(f'[重建] 加载失败 {fpath}: {e}')

        if raw_docs:
            logger.info(f'[重建] {label} 加载到 {len(raw_docs)} 个原始文档')
            subdirs = [d for d in os.listdir(abs_dir) if os.path.isdir(os.path.join(abs_dir, d))]
            if subdirs:
                logger.info(f"[重建] {label} 包含 {len(subdirs)} 个子目录: {', '.join(subdirs[:5])}{('...' if len(subdirs) > 5 else '')}")
        else:
            logger.info(f'[重建] {label} [WARN] 未加载到任何文档片段')

        # 切分为 chunk（与 load_documents_from_directory 行为一致）
        splitter = get_splitter("recursive", chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        docs = splitter.split(raw_docs) if raw_docs else []
        if docs:
            logger.info(f'[重建] {label} 分割为 {len(docs)} 个文档片段')

        return docs

    # ===== 增量重建：manifest 读写 + 确定性 id =====
    def _manifest_path(self):
        return os.path.join(self._vector_db_dir, "_kb_manifest.json")

    def _load_manifest(self):
        p = self._manifest_path()
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict) and 'files' in data:
                    return data
            except Exception as e:
                logger.info(f'[增量][WARN] manifest 解析失败，将走全量重建: {e}')
        return {"version": 1, "files": {}}

    def _save_manifest(self, data):
        p = self._manifest_path()
        tmp = p + ".tmp"
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)  # 原子替换，避免写一半损坏
        except Exception as e:
            logger.info(f'[增量][WARN] manifest 写入失败（不影响本次重建）: {e}')

    def _file_manifest_key(self, file_path, category):
        base = os.path.abspath(self._get_doc_base_dir(category))
        rel = os.path.relpath(os.path.abspath(file_path), base)
        prefix = "h:" if category == 'huawei' else "c:"
        return prefix + rel

    def _chunk_ids_for_file(self, file_path, category, n):
        base = _kb_stable_id(self._file_manifest_key(file_path, category))
        return [f"{base}#{i}" for i in range(n)]

    def _manifest_upsert_file(self, file_path, category, ids):
        m = self._load_manifest()
        m.setdefault('files', {})
        m['files'][self._file_manifest_key(file_path, category)] = {
            "hash": _kb_file_sha256(file_path),
            "chunk_ids": list(ids),
            "origin": "user",
        }
        self._save_manifest(m)

    def build_from_directory(self, use_default_dirs: bool = False,
                              on_progress: Optional[Callable[[int, int, str], None]] = None):
        """
        从目录【增量】重建知识库（含华为方案和竞品方案）。

        增量策略：基于文件内容哈希（manifest）比对，只对「新增 / 内容变化」的文件重新
        生成向量嵌入；未变化的文件向量原样保留（不重算、不删除）；已从磁盘移除的文件
        清理其旧向量。日常「系统新增几篇 + 用户文档不变」的场景，embedding 计算量可
        降低约两个数量级（分钟级 → 秒级）。

        兼容性：若检测到旧版向量库（无 manifest，且集合内已有向量，多为自动 uuid id），
        先做一次全量清理再按确定性 id 重建，避免新旧 id 共存产生重复向量。

        Args:
            use_default_dirs: 为 True 时强制使用全局默认目录（管理员重建全局KB）
            on_progress: 可选进度回调 (done, total, stage_text)
        """
        try:
            huawei_dir = os.path.abspath(KNOWLEDGE_BASE_DIRECTORY) if use_default_dirs else self._huawei_dir
            competitor_dir = os.path.abspath(COMPETITOR_DIRECTORY) if use_default_dirs else self._competitor_dir
            # 全局默认目录 = sync 的"源"；用户库里的系统文档都从这两个目录 copytree 而来
            source_huawei = os.path.abspath(KNOWLEDGE_BASE_DIRECTORY)
            source_competitor = os.path.abspath(COMPETITOR_DIRECTORY)

            # 1. 加载文档（仅文件读取 + 切分，不含 embedding，开销极小）
            huawei_docs = self._load_docs_from_dir(huawei_dir, "华为方案")
            competitor_docs = []
            if os.path.exists(competitor_dir):
                competitor_docs = self._load_docs_from_dir(competitor_dir, "竞品方案")
            else:
                logger.info(f'[重建] [WARN] 竞品目录不存在，跳过: {competitor_dir}')

            all_documents = huawei_docs + competitor_docs
            if not all_documents:
                logger.info('[重建] [ERR] 未加载到任何文档！请检查目录结构')
                return 0

            # 2. 按源文件分组，计算内容哈希
            current = {}  # manifest_key -> {rel_path, prefix, file_path, hash, chunks}
            def _group(docs, root, prefix):
                for d in docs:
                    src = d.metadata.get('_kb_src') or d.metadata.get('source')
                    if src:
                        ab = os.path.abspath(src)
                        rel = os.path.relpath(ab, root)
                    else:
                        # 无 source 元数据：以内容哈希作为稳定 key，避免重复累积
                        ab = None
                        rel = _kb_stable_id(d.page_content)
                    key = prefix + rel
                    entry = current.setdefault(key, {
                        'rel_path': rel, 'prefix': prefix,
                        'file_path': ab, 'hash': None, 'chunks': []
                    })
                    entry['chunks'].append(d)
            _group(huawei_docs, huawei_dir, "h:")
            _group(competitor_docs, competitor_dir, "c:")
            for info in current.values():
                info['hash'] = _kb_file_sha256(info['file_path']) if info['file_path'] \
                    else _kb_stable_id(info['chunks'][0].page_content)

            # 3. 比对 manifest，划分 保留 / 重建 / 删除
            old = self._load_manifest()
            old_files = old.get('files', {})

            # 3.0 修剪上游已删除的系统文档（仅用户库，user_id>0）
            # copytree 只覆盖不删多余文件，上游删除某篇官方文档后，用户库里它的磁盘文件
            # 与旧向量会残留。这里只在「系统是同步来源 且 当前源目录已不存在该相对路径」
            # 时动手删除磁盘+向量；用户自建文档(origin=user 或源目录本就无此相对路径)
            # 一律保留，绝误删。
            if self.user_id > 0:
                for key, info in list(current.items()):
                    src_root = source_huawei if key.startswith('h:') else source_competitor
                    rel_path = key[2:]
                    in_source = os.path.exists(os.path.join(src_root, rel_path))
                    was_system = old_files.get(key, {}).get('origin') == 'system'
                    if (was_system or in_source) and not in_source:
                        fp = info.get('file_path')
                        if fp and os.path.exists(fp):
                            try:
                                os.remove(fp)
                                # 清理空父目录（只到分类根目录为止，不越界）
                                parent = os.path.dirname(fp)
                                cat_base = self._huawei_dir if key.startswith('h:') else self._competitor_dir
                                while parent and os.path.abspath(parent) != os.path.abspath(cat_base) \
                                        and os.path.isdir(parent) and not os.listdir(parent):
                                    nxt = os.path.dirname(parent)
                                    os.rmdir(parent)
                                    parent = nxt
                            except Exception as e:
                                logger.info(f'[增量][WARN] 修剪删除磁盘文件失败 {fp}: {e}')
                        ids = old_files.get(key, {}).get('chunk_ids', [])
                        if ids:
                            try:
                                self.vector_db.delete(ids=ids)
                            except Exception:
                                pass
                        current.pop(key, None)
                        logger.info(f'[增量] 修剪上游已删除文件: {key}')

            # 切分参数指纹：CHUNK_SIZE/CHUNK_OVERLAP 改变会改变 chunk 边界，
            # 旧向量按旧边界切分，与新向量混排会 silently 拉低检索质量（不报错但劣化）。
            # 故参数变更时强制全量重建（清掉所有旧向量，全部按新参数重嵌）。
            cur_chunk_params = f"{CHUNK_SIZE}-{CHUNK_OVERLAP}"
            old_chunk_params = old.get('chunk_params')
            if old_chunk_params is not None and old_chunk_params != cur_chunk_params:
                logger.info(f'[增量][参数变更] 切分参数 {old_chunk_params} → {cur_chunk_params}，旧 chunk 边界失效，强制全量重建...')
                try:
                    existing = self.vector_db.get()
                    existing_ids = existing.get('ids', [])
                    if existing_ids:
                        self.vector_db.delete(ids=existing_ids)
                except Exception as e:
                    logger.info(f'[增量][WARN] 参数变更清理失败（忽略）: {e}')
                old_files = {}  # 全部进入 to_rebuild

            # 兼容旧版：无 manifest 但集合已有向量 → 先全量清理（一次性迁移）
            if not old_files:
                try:
                    existing = self.vector_db.get()
                    existing_ids = existing.get('ids', [])
                    if existing_ids:
                        logger.info(f'[增量][迁移] 检测到旧版向量库（{len(existing_ids)} 条），清理后按确定性 id 重建...')
                        self.vector_db.delete(ids=existing_ids)
                except Exception as e:
                    logger.info(f'[增量][WARN] 迁移清理失败（忽略）: {e}')

            to_keep, to_rebuild = set(), {}
            for key, info in current.items():
                if key in old_files and old_files[key].get('hash') == info['hash']:
                    to_keep.add(key)
                else:
                    to_rebuild[key] = info
            to_delete = set(old_files.keys()) - set(current.keys())

            # 4. 删除已从磁盘移除的文件的旧向量
            for key in to_delete:
                ids = old_files[key].get('chunk_ids', [])
                if ids:
                    try:
                        self.vector_db.delete(ids=ids)
                        logger.info(f'[增量] 清理已移除文件: {key} ({len(ids)} 片段)')
                    except Exception as e:
                        logger.info(f'[增量][WARN] 清理失败 {key}: {e}')

            # 5. 重建变更 / 新增文件（仅这部分需要 CPU embedding）
            new_files = {k: dict(old_files[k]) for k in to_keep}
            total_embed = sum(len(i['chunks']) for i in to_rebuild.values())
            done = 0
            if on_progress and total_embed:
                on_progress(0, total_embed, f"增量生成向量嵌入（{len(to_rebuild)} 个变更文件 / 共 {total_embed} 片段）...")
            for key, info in to_rebuild.items():
                if key in old_files:  # 变化文件：先删旧向量，避免孤儿 / 重复
                    old_ids = old_files[key].get('chunk_ids', [])
                    if old_ids:
                        try:
                            self.vector_db.delete(ids=old_ids)
                        except Exception:
                            pass
                base = _kb_stable_id(info['prefix'] + info['rel_path'])
                ids = [f"{base}#{i}" for i in range(len(info['chunks']))]
                n = len(info['chunks'])
                batch = 50
                try:
                    for s in range(0, n, batch):
                        seg = info['chunks'][s:s + batch]
                        self.vector_db.add_documents(seg, ids=ids[s:s + len(seg)])
                        done += len(seg)
                        if on_progress:
                            on_progress(done, total_embed, f"增量生成向量嵌入（{done}/{total_embed}）...")
                    in_source = os.path.exists(os.path.join(
                        source_huawei if key.startswith('h:') else source_competitor, key[2:]))
                    origin = 'system' if in_source else 'user'
                    new_files[key] = {"hash": info['hash'], "chunk_ids": ids, "origin": origin}
                    logger.info(f'[增量] 重建: {key} ({n} 片段, origin={origin})')
                except Exception as e:
                    # 单文件失败隔离：跳过并下次重试，不中断整个重建、不产生中间态崩溃
                    logger.info(f'[增量][WARN] 文件重建失败（跳过，下次同步重试）: {key}: {e}')
                    import traceback; traceback.print_exc()

            # 6. 持久化 manifest（含切分参数指纹，供下次检测参数变更）
            self._save_manifest({"version": 1, "chunk_params": cur_chunk_params, "files": new_files})

            # 7. 重建 retriever
            self.retriever = self.vector_db.as_retriever(
                search_kwargs={"k": VECTOR_SEARCH_TOP_K}
            )

            total_fragments = sum(len(v.get('chunk_ids', [])) for v in new_files.values())
            logger.info(f'[重建][OK] 增量完成：保留 {len(to_keep)} 个未变文件，重建 {len(to_rebuild)} 个变更文件，删除 {len(to_delete)} 个已移除文件，当前共 {total_fragments} 个片段')
            return total_fragments

        except ImportError as e:
            logger.info(f'[重建] [ERR] 导入失败: {e}')
            import traceback; traceback.print_exc()
            return 0
        except Exception as e:
            logger.info(f'[重建] [ERR] 构建知识库失败: {e}')
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
                logger.info(f'[用户{user_id}] 复制华为方案: {src_huawei} → {dst_huawei}')
                shutil.copytree(src_huawei, dst_huawei, dirs_exist_ok=True)

            # 2. 复制竞品文档
            if os.path.exists(src_competitor):
                logger.info(f'[用户{user_id}] 复制竞品方案: {src_competitor} → {dst_competitor}')
                shutil.copytree(src_competitor, dst_competitor, dirs_exist_ok=True)

            # 3. 复制向量数据库
            if os.path.exists(src_vectordb):
                logger.info(f'[用户{user_id}] 复制向量库: {src_vectordb} → {dst_vectordb}')
                shutil.copytree(src_vectordb, dst_vectordb, dirs_exist_ok=True)
                # 注意：ChromaDB 的 SQLite 文件中有绝对路径引用，但使用 persist_directory 参数可以正常加载

            # 4. 验证：创建 KnowledgeBaseService 实例，检查数据完整性
            try:
                kb = KnowledgeBaseService(user_id=user_id)
                stats = kb.get_stats()
                logger.info(f"[用户{user_id}] 复制完成，共 {stats.get('total_documents', 0)} 个向量片段")
            except Exception as verify_err:
                logger.info(f'[用户{user_id}] [WARN] 验证知识库失败（可忽略，后续使用时自动修正）: {verify_err}')

            return True

        except Exception as e:
            logger.info(f'[用户{user_id}] [ERR] 复制知识库失败: {e}')
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

    def _hybrid_pool(self, query, pool_size=15):
        """混合召回候选池：向量召回 + 关键词全文召回 → RRF 融合 → 阈值过滤。"""
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
        # 4) 阈值过滤
        if RAG_THRESHOLD > 0:
            fused = [d for d in fused if (d.metadata or {}).get("_score", 1.0) >= RAG_THRESHOLD]
        return fused[:pool_size]

    # 客户行业 → KB 行业映射（兼容旧数据自由填写的值；新数据已限定为 SUPPORTED_INDUSTRIES 下拉）
    CLIENT_INDUSTRY_ALIASES = {
        "安防": "智慧园区",
        "安防监控": "智慧园区",
        "智慧安防": "智慧园区",
        "视频监控": "智慧园区",
        "物联网": "智慧城市",
        "智慧物联": "智慧城市",
    }

    def _resolve_kb_industry(self, client_industry: str):
        """把客户档案的行业对齐到 KB 文档标签体系，用于收敛主检索。
        直接命中 SUPPORTED_INDUSTRIES 则原样返回；否则走别名映射；都不中返回 None（不过滤）。"""
        if not client_industry:
            return None
        if client_industry in SUPPORTED_INDUSTRIES:
            return client_industry
        return self.CLIENT_INDUSTRY_ALIASES.get(client_industry)

    def search_huawei(self, query, k=4, filter_industry=None):
        """只召回华为云方案文档（主方案落地用）——直接在华为子集上检索，避免被竞品挤出前排。
        filter_industry: 关联客户时传入的客户行业（已对齐 KB 标签），用于收敛主检索到该客户行业，
        彻底解决「需求未提行业时拉到无关行业文档」的错配问题。"""
        comp = self._competitor_companies
        results = []
        _cache_key = ("huawei", query, k, filter_industry)
        _cached = _kb_cache_get(_cache_key)
        if _cached is not None:
            return _cached
        kb_industry = self._resolve_kb_industry(filter_industry) if filter_industry else None
        try:
            if kb_industry:
                # 命中 KB 行业标签，直接按行业过滤（竞品文档 industry 为厂商名，天然被排除）
                results = self.vector_db.similarity_search(
                    query, k=k, filter={"industry": {"$in": [kb_industry]}}
                )
            else:
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
                d_ind = (d.metadata or {}).get("industry", "")
                if d_ind not in comp and d.page_content not in seen:
                    if kb_industry and d_ind != kb_industry:
                        continue
                    results.append(d)
                    seen.add(d.page_content)
                    if len(results) >= k:
                        break
        _kb_cache_put(_cache_key, results[:k])
        return results[:k]

    def search_user_uploaded(self, query, k=6):
        """只召回用户真实上传/新建的私有文档（doc_origin=user_uploaded），排除平台默认库副本"""
        _cache_key = ("user", query, k)
        _cached = _kb_cache_get(_cache_key)
        if _cached is not None:
            return _cached
        results = []
        try:
            results = self.vector_db.similarity_search(
                query, k=k, filter={"doc_origin": {"$eq": "user_uploaded"}}
            )
        except Exception as e:
            logger.warning(f"用户私有文档检索异常，回退混合池: {e}")
        if len(results) < k:
            seen = {d.page_content for d in results}
            try:
                pool = self._similarity_pool(query, pool_size=max(k * 4, 40))
                for d in pool:
                    if (d.metadata or {}).get("doc_origin") == "user_uploaded" and d.page_content not in seen:
                        results.append(d)
                        seen.add(d.page_content)
                        if len(results) >= k:
                            break
            except Exception as e:
                logger.warning(f"用户私有文档回退池异常: {e}")
        _kb_cache_put(_cache_key, results[:k])
        return results[:k]

    def search_competitor(self, query, k=2):
        """只召回竞品方案文档（竞品对比章节用）——直接在竞品子集上检索"""
        _cache_key = ("comp", query, k)
        _cached = _kb_cache_get(_cache_key)
        if _cached is not None:
            return _cached
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
        _kb_cache_put(_cache_key, results[:k])
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
                            logger.info(f'[OK] {industry}: {count} 个文档')
                    except Exception as e:
                        logger.info(f'[WARN] 读取 {industry} 目录失败: {e}')
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

            logger.info(f'\n[STATS] 知识库统计 (user_id={self.user_id}):')
            logger.info(f'  - 总文档片段数: {total_documents}')
            logger.info(f'  - 华为方案文件数: {total_files}')
            logger.info(f'  - 竞品文件数: {total_competitor_files} (覆盖{len(competitor_companies)}家竞品)')
            logger.info(f'  - 覆盖行业数: {len(supported_industries)}')
            logger.info(f"  - 覆盖行业: {(', '.join(supported_industries) if supported_industries else '无')}")
            logger.info(f'  - 方案覆盖度: {accuracy}%\n')

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
            logger.info(f'[ERR] 统计失败: {e}')
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

    def _safe_doc_path(self, category, rel_path):
        """把 doc_id 中的相对路径解析为绝对路径，并强制限制在分类根目录内。"""
        if category not in _KB_CATEGORIES:
            raise ValueError(f"无效的知识库分类: {category}")
        base = Path(self._get_doc_base_dir(category)).resolve()
        target = (base / rel_path).resolve()
        if target == base or not target.is_relative_to(base):
            raise ValueError("无效的文档路径")
        return str(target)

    @staticmethod
    def _safe_name_component(value, field):
        """把会拼进文件路径的字段清洗为安全成分，避免 `..`/分隔符改变目标目录。"""
        if not value or value in (".", ".."):
            raise ValueError(f"无效的{field}")
        if "\x00" in value:
            raise ValueError(f"{field}包含非法字符")
        return value.replace("/", "_").replace("\\", "_")

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
        file_path = self._safe_doc_path(category, rel_path)
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
        category = self._safe_name_component(category, "分类")
        if category not in _KB_CATEGORIES:
            raise ValueError(f"无效的知识库分类: {category}")
        industry = self._safe_name_component(industry, "行业")
        title = self._safe_name_component(title, "标题")
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
        file_path = self._safe_doc_path(category, rel_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        industry = os.path.basename(os.path.dirname(file_path))
        # _index_single_file 内部会先按确定性 id 清理旧向量，无需在此重复删除
        count = self._index_single_file(file_path, category, industry)
        self.retriever = self.vector_db.as_retriever(search_kwargs={"k": VECTOR_SEARCH_TOP_K})
        return {'id': doc_id, 'chunks': count}

    def delete_document(self, doc_id, delete_file=True):
        """删除文档及其向量"""
        category, rel_path = self._decode_doc_id(doc_id)
        file_path = self._safe_doc_path(category, rel_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        removed = self._remove_doc_vectors(file_path, category=category)
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
        file_path = self._safe_doc_path(category, rel_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        industry = os.path.basename(os.path.dirname(file_path))
        # _index_single_file 内部会先按确定性 id 清理旧向量，无需在此重复删除
        count = self._index_single_file(file_path, category, industry)
        self.retriever = self.vector_db.as_retriever(search_kwargs={"k": VECTOR_SEARCH_TOP_K})
        return {'chunks': count}

    def _index_single_file(self, file_path, category, industry):
        """将单个文件加载并索引到向量库（确定性 id + manifest 感知，避免重复向量）"""
        from app.utils.document_loader import load_documents_from_directory
        tmp_dir = os.path.join(os.path.dirname(file_path), '.tmp_index')
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_file = os.path.join(tmp_dir, os.path.basename(file_path))
        try:
            shutil.copy2(file_path, tmp_file)
            chunks = load_documents_from_directory(tmp_dir, CHUNK_SIZE, CHUNK_OVERLAP)
            if chunks:
                # 标记为「用户真实上传/新建」，与平台默认库副本区分（personal 路由据此只检索真私有资料）
                for c in chunks:
                    c.metadata["doc_origin"] = "user_uploaded"
                    c.metadata["_kb_src"] = os.path.abspath(file_path)
                # 先清理该文件旧向量（避免重复），再写入确定性 id
                self._remove_doc_vectors(file_path, category=category)
                ids = self._chunk_ids_for_file(file_path, category, len(chunks))
                self.vector_db.add_documents(chunks, ids=ids)
                self._manifest_upsert_file(file_path, category, ids)
                logger.info(f'[索引] {os.path.basename(file_path)} → {len(chunks)} 个向量片段')
            return len(chunks)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _remove_doc_vectors(self, file_path, category=None):
        """从向量库中移除指定文件的所有向量（manifest 优先，basename 兜底兼容旧数据）"""
        removed = 0
        if category is not None:
            key = self._file_manifest_key(file_path, category)
            m = self._load_manifest()
            if key in m.get('files', {}):
                ids = m['files'][key].get('chunk_ids', [])
                if ids:
                    try:
                        self.vector_db.delete(ids=ids)
                        removed += len(ids)
                    except Exception as e:
                        logger.info(f'[索引] 删除向量失败 {file_path}: {e}')
                m['files'].pop(key, None)
                self._save_manifest(m)
                logger.info(f'[索引] 已移除 {os.path.basename(file_path)}: {len(ids)} 个向量（manifest）')
                return removed
        # 兜底：按 source 文件名匹配（兼容旧版自动 uuid 向量 / 未传 category 的场景）
        try:
            all_data = self.vector_db.get()
            ids_to_remove = []
            filename = os.path.basename(file_path)
            for i, meta in enumerate(all_data.get('metadatas', [])):
                if meta and meta.get('source') == filename:
                    ids_to_remove.append(all_data['ids'][i])
            if ids_to_remove:
                self.vector_db.delete(ids=ids_to_remove)
                removed += len(ids_to_remove)
                logger.info(f'[索引] 已移除 {filename}: {len(ids_to_remove)} 个向量')
            return removed
        except Exception as e:
            logger.info(f'[索引] 移除向量失败 {file_path}: {e}')
            return removed


# ===== 知识库工厂缓存（模块级单例，避免重复实例化 ChromaDB 客户端） =====
# 缓存放在 app/services/knowledge_base.py 内，api 层通过 re-export 复用。
# 同一进程永远只存在一份缓存（无论从哪个路径 import），保证 KB 实例唯一。

_global_kb: Optional[KnowledgeBaseService] = None
_user_kb_cache: Dict[int, KnowledgeBaseService] = {}


def get_knowledge_base() -> KnowledgeBaseService:
    """获取全局/系统知识库实例（用于健康检查、重建等系统操作）"""
    global _global_kb
    if _global_kb is None:
        _global_kb = KnowledgeBaseService(user_id=0)
    return _global_kb


def get_user_knowledge_base(user_id: int) -> KnowledgeBaseService:
    """获取用户独立的知识库实例（按 user_id 缓存，每个用户一个独立 ChromaDB）

    首次访问时自动检测：如果用户 KB 目录不存在，先从默认 KB 复制。
    """
    if user_id <= 0:
        return get_knowledge_base()
    if user_id not in _user_kb_cache:
        # 检查用户 KB 是否已初始化（整个用户目录只在 copy_from_default 时创建）
        user_data_dir = os.path.join(USER_DOCS_BASE_DIR, str(user_id))
        if not os.path.exists(user_data_dir):
            logger.info(f"[KB] 用户 {user_id} 知识库不存在，从默认KB复制...")
            KnowledgeBaseService.copy_from_default(user_id)
            logger.info(f"[KB] 用户 {user_id} 知识库初始化完成")
        _user_kb_cache[user_id] = KnowledgeBaseService(user_id=user_id)
    return _user_kb_cache[user_id]


def reset_global_kb_cache() -> None:
    """清空全局 KB 单例（KB 重建后调用，使下次请求重新创建实例）"""
    global _global_kb
    _global_kb = None


def evict_user_kb_cache(user_id: int) -> None:
    """从用户 KB 缓存中移除指定 user_id（用户文档重建/上传后调用）"""
    _user_kb_cache.pop(user_id, None)
