"""
工具定义 + 注册中心

每个 Tool 封装一个现有 Service，暴露给 Agent 的 ReAct 循环调用。
设计原则：
- 零改动现有代码，通过 import 对接
- 每个工具自描述（name + description + parameters），供 LLM 理解
- execute() 返回字符串 Observation，直接喂给下一轮 LLM
"""

import os
import json
import asyncio
import logging
import contextvars
from typing import Any, Callable, Dict, List, Optional

from app.services.knowledge_base import get_kb_user_context

logger = logging.getLogger(__name__)

# Agent 事件回调上下文（harness 在 _execute_tool 前注入，工具内部读取，避免改动所有工具的 execute 签名）
_AGENT_EVENT_CB: contextvars.ContextVar = contextvars.ContextVar("agent_event_cb", default=None)

# Agent 当前用户上下文（Agent 端点入口注入，平台工具按 uid 过滤/写入，数据隔离铁律）
_AGENT_USER_ID: contextvars.ContextVar = contextvars.ContextVar("agent_user_id", default=0)


def set_agent_user_context(user_id: int) -> None:
    """注入当前 Agent 调用的用户 id（0 表示匿名/未注入）"""
    _AGENT_USER_ID.set(user_id)


def get_agent_user_context() -> int:
    """读取当前 Agent 调用的用户 id（平台工具据此做数据隔离）"""
    return _AGENT_USER_ID.get()


def set_agent_event_callback(cb) -> None:
    if cb is not None:
        _AGENT_EVENT_CB.set(cb)


def get_agent_event_callback():
    return _AGENT_EVENT_CB.get()


def _get_kb():
    """根据当前上下文获取知识库实例（用户上下文或全局）"""
    user_id = get_kb_user_context()
    if user_id > 0:
        from api.dependencies import get_user_knowledge_base as _get_user_kb
        return _get_user_kb(user_id)
    from api.dependencies import get_knowledge_base as _get_global_kb
    return _get_global_kb()


class Tool:
    """单个工具定义"""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        func: Callable,
        domain: str = "general",
    ):
        self.name = name
        self.description = description
        self.parameters = parameters  # JSON Schema 格式的参数定义
        self.func = func
        self.domain = domain  # 工具域：solution/competitor/pricing/filegen/platform/general（用于 prompt 分组展示）

    def to_prompt_desc(self) -> str:
        """生成给 LLM 看的工具描述"""
        params_str = json.dumps(self.parameters, ensure_ascii=False, indent=2)
        return f"- {self.name}: {self.description}\n  Parameters: {params_str}"

    async def execute(self, **kwargs) -> str:
        """执行工具，返回 Observation 字符串"""
        try:
            # 参数名纠偏（F3 鲁棒性）：LLM 偶发传错参数名（如 run_code 传 query 而非 code）。
            # 仅对【单参数】工具做通用纠偏（无歧义）；多参数工具靠各自的参数别名兼容，
            # 避免把拼错的字段错误塞给错误参数（如 manage_client 的 name→action）。
            defined = set(self.parameters.get("properties", {}).keys())
            unknown = set(kwargs.keys()) - defined
            if unknown and len(defined) == 1:
                single = list(defined)[0]
                for k in list(unknown):
                    if single not in kwargs:
                        kwargs[single] = kwargs[k]
                        kwargs.pop(k, None)
                        logger.info(f"[Tool:{self.name}] 参数纠偏 {k} → {single}")
            result = self.func(**kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            # 统一转为字符串
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"Tool [{self.name}] execution error: {e}")
            return f"Error: {str(e)}"


# 工具域中文标签（prompt 分组展示用）
_DOMAIN_LABELS = {
    "solution": "方案类工具",
    "competitor": "竞品对比工具",
    "pricing": "价目查询工具",
    "filegen": "文件/计算工具",
    "platform": "平台操作工具（查我的数据/管理客户/导出）",
    "general": "通用工具",
}


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def get_tools_prompt(self) -> str:
        """生成所有工具的 Prompt 描述（按域分组展示，缓解工具选择困难）"""
        if not self._tools:
            return "（无可用工具）"
        groups: Dict[str, List[Tool]] = {}
        for tool in self._tools.values():
            groups.setdefault(tool.domain, []).append(tool)
        lines = []
        for domain, tools in groups.items():
            lines.append(f"【{_DOMAIN_LABELS.get(domain, domain)}】")
            for tool in tools:
                lines.append(tool.to_prompt_desc())
        return "\n".join(lines)

    def get_tool_names(self) -> List[str]:
        return list(self._tools.keys())


# ============================================================
# 四个核心工具的具体实现
# ============================================================

async def _tool_analyze_demand(raw_input: str) -> str:
    """
    工具: analyze_demand
    作用: 将模糊的用户输入 → 结构化的需求分析（行业、场景、痛点、关键词）
    实现: 调用 LLM 进行意图分析，不需要现有 Service
    """
    from app.models.llm import get_llm_response

    prompt = f"""你是一位需求分析专家。用户表达了以下需求，但描述可能很模糊。请将这段模糊需求转化为结构化分析。

用户原始输入："{raw_input}"

请严格按以下 JSON 格式输出（不要输出其他内容）：

{{
  "industry": "最匹配的行业（如：制造业、智慧农业、智慧医疗、工业互联网等）",
  "scenarios": ["场景1", "场景2", "场景3"],
  "pain_points": ["痛点1", "痛点2", "痛点3"],
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
  "confidence": "高/中/低"
}}

注意：
1. keywords 要包含可用于向量检索的技术术语和产品名称
2. industry 从常见行业中选择：工业互联网、智慧交通、智慧农业、智慧医疗、智慧园区、智慧城市、智慧教育、智慧文旅、智慧能源、智慧金融、生物医药、零售、游戏、政务、汽车、互联网、制造
3. 如果用户提到了竞品名称（如阿里云、腾讯云、AWS等），在 keywords 中保留"""

    try:
        result = await get_llm_response(prompt)
        # 尝试解析 JSON，失败则返回原始文本
        try:
            # 提取 JSON 部分（LLM 可能在前后加了说明文字）
            json_start = result.find("{")
            json_end = result.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(result[json_start:json_end])
                return json.dumps(parsed, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, ValueError):
            pass
        return result
    except Exception as e:
        return json.dumps({"error": str(e), "raw_input": raw_input}, ensure_ascii=False)


async def _tool_search_kb(query: str) -> str:
    """
    工具: search_kb
    作用: 用结构化关键词搜索华为云知识库
    实现: 对接 KnowledgeBaseService.search()
    """
    kb = _get_kb()
    try:
        logger.info(f"[search_kb] 开始查询, query={query[:50]}...")
        t0 = __import__('time').time()
        docs = await asyncio.to_thread(kb.search_huawei, query, 4)
        elapsed = round(__import__('time').time() - t0, 1)
        logger.info(f"[search_kb] 查询完成, 耗时={elapsed}s, 结果数={len(docs)}")
        if not docs:
            # 关键优化：空结果时给出明确的换关键词引导，避免 LLM 直接放弃
            return json.dumps({
                "status": "no_match",
                "query": query,
                "message": (
                    "用当前关键词「" + query + "」未检索到匹配的解决方案文档。"
                    "请务必换一组不同的关键词重试。建议：\n"
                    "1. 提取更核心的技术术语（如：工业物联网、预测性维护、数字孪生）\n"
                    "2. 使用更宽泛的行业词（如：制造业→工业互联网）\n"
                    "3. 尝试不同的产品角度（如：IoT平台、边缘计算、AI质检）\n"
                    "不要放弃，用新关键词再调用一次 search_kb！"
                ),
                "results": []
            }, ensure_ascii=False, indent=2)

        results = []
        for i, doc in enumerate(docs[:3]):  # 最多返回 3 条
            results.append({
                "index": i + 1,
                "content": doc.page_content[:300],  # 截断过长内容，避免 context 膨胀
                "source": doc.metadata.get("source", "unknown"),
                "industry": doc.metadata.get("industry", ""),
            })
        return json.dumps({
            "status": "ok",
            "query": query,
            "total_hits": len(docs),
            "results": results
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


async def _tool_search_competitor(competitor: str, industry: str = "") -> str:
    """
    工具: search_competitor
    作用: 搜索竞品在特定行业的方案信息
    实现: 对接 CompetitorAnalyzerService 的检索逻辑
    """
    kb = _get_kb()
    try:
        stats = kb.get_stats()
        if stats.get("total_documents", 0) == 0:
            return json.dumps({
                "status": "empty",
                "message": "知识库为空，无法检索竞品信息。",
                "results": []
            }, ensure_ascii=False)

        # 先检索华为方案
        hw_query = "华为云" + (f"在{industry}行业的解决方案 竞争优势" if industry else "解决方案")
        hw_docs = await asyncio.to_thread(kb.search_huawei, hw_query, 4)

        # 再检索竞品方案
        comp_query = f"{competitor}" + (f"在{industry}行业的解决方案 产品 优势" if industry else "解决方案")
        comp_docs = await asyncio.to_thread(kb.search_competitor, comp_query, 4)

        hw_results = []
        for i, doc in enumerate(hw_docs[:3]):
            hw_results.append({
                "type": "华为云",
                "content": doc.page_content[:300],
                "source": doc.metadata.get("source", ""),
            })

        comp_results = []
        for i, doc in enumerate(comp_docs[:3]):
            comp_results.append({
                "type": competitor,
                "content": doc.page_content[:300],
                "source": doc.metadata.get("source", ""),
            })

        if not hw_results and not comp_results:
            return json.dumps({
                "status": "no_match",
                "competitor": competitor,
                "industry": industry,
                "message": (
                    "未检索到「" + competitor + "」在「" + (industry or "全行业") + "」的相关资料。"
                    "请尝试：\n"
                    "1. 去掉行业限制，用更宽的搜索范围\n"
                    "2. 换一个竞品名称（如：阿里云 → AWS）\n"
                    "3. 用不同的技术角度搜索（如：云原生、大数据、AI平台）\n"
                    "不要放弃，调整参数后再试一次！"
                ),
                "results": []
            }, ensure_ascii=False, indent=2)

        # 发 competitor_table 事件（前端渲染竞品对比卡片，嵌入 Agent 对话流）
        cb = get_agent_event_callback()
        if cb:
            try:
                await cb({
                    "type": "competitor_table",
                    "competitor": competitor,
                    "industry": industry,
                    "huawei_count": len(hw_docs),
                    "competitor_count": len(comp_docs),
                    "huawei_snippet": (hw_docs[0].page_content[:200] if hw_docs else ""),
                    "competitor_snippet": (comp_docs[0].page_content[:200] if comp_docs else ""),
                })
            except Exception as e:
                logger.warning(f"[search_competitor] 事件回调失败: {e}")

        return json.dumps({
            "status": "ok",
            "competitor": competitor,
            "industry": industry,
            "huawei_docs_count": len(hw_docs),
            "competitor_docs_count": len(comp_docs),
            "results": hw_results + comp_results
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


async def _tool_query_pricing(query: str = "") -> str:
    """
    工具: query_pricing
    作用: 查询华为云产品参考价目（按产品名/规格/行业关键词模糊匹配）
    实现: 读取 data/pricing_reference.json 的 all_items 扁平列表；
          命中后通过 event_callback 发 pricing_info 事件供前端渲染价目卡片。
    """
    # 优先复用 routes 的带缓存加载器；失败则直接读 JSON 兜底
    try:
        from api.routes import _load_pricing_reference
        data = _load_pricing_reference()
    except Exception:
        import json as _json
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _path = os.path.join(_root, "data", "pricing_reference.json")
        try:
            with open(_path, "r", encoding="utf-8") as f:
                data = _json.load(f)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"价目表读取失败: {e}"}, ensure_ascii=False)

    all_items = data.get("all_items") or []
    if not all_items:
        # 旧版 JSON 兼容：遍历行业 profiles + 商务定价项
        for prof in data.get("profiles", {}).values():
            all_items.extend(prof.get("items", []))
        all_items.extend(data.get("business_only_products", []))

    if not all_items:
        return json.dumps({
            "status": "empty",
            "message": "价目表为空，无法查询价格。",
            "items": []
        }, ensure_ascii=False)

    q = (query or "").strip().lower()
    matched = []
    for it in all_items:
        if isinstance(it, dict):
            name = it.get("product", "")
            spec = it.get("spec", "")
        else:
            name = str(it)
            spec = ""
        if not q or q in name.lower() or q in spec.lower():
            matched.append({
                "product": name,
                "spec": spec,
                "billing": it.get("billing", "") if isinstance(it, dict) else "",
                "unit_label": it.get("unit_label", "") if isinstance(it, dict) else "",
                "ref_price": it.get("ref_price", 0) if isinstance(it, dict) else 0,
                "free": bool(it.get("free", False)) if isinstance(it, dict) else False,
                "business_only": bool(it.get("business_only", False)) if isinstance(it, dict) else False,
                "note": it.get("note", "") if isinstance(it, dict) else "",
            })

    # 无 query 时返回前 10 条作为概览；有 query 时最多 8 条
    matched = (matched[:10] if not q else matched[:8])

    if not matched:
        return json.dumps({
            "status": "no_match",
            "query": query,
            "message": (
                f"未找到与「{query}」匹配的价目产品。可尝试更宽泛的产品名"
                "（如：ECS、OBS、CDN、数据库、带宽）。"
            ),
            "items": []
        }, ensure_ascii=False)

    # 发 pricing_info 事件（前端渲染价目卡片，嵌入 Agent 对话流）
    cb = get_agent_event_callback()
    if cb:
        try:
            await cb({
                "type": "pricing_info",
                "query": query,
                "items": [{
                    "product": m["product"],
                    "spec": m["spec"],
                    "billing": m["billing"],
                    "unit_label": m["unit_label"],
                    "ref_price": m["ref_price"],
                    "free": m["free"],
                    "business_only": m["business_only"],
                    "note": m["note"],
                } for m in matched],
            })
        except Exception as e:
            logger.warning(f"[query_pricing] 事件回调失败: {e}")

    return json.dumps({
        "status": "ok",
        "query": query,
        "total": len(matched),
        "items": matched,
        "message": "已找到价目信息。请在 Final Answer 中列出具体产品、规格、计费方式与参考价格。"
    }, ensure_ascii=False, indent=2)


# ============================================================
# M2 新增：平台操作工具（查我的历史 / 客户档案 / 导出报告）
# 数据隔离铁律：一律用 get_agent_user_context() 拿 uid，按 uid 过滤/写入；
# uid<=0（匿名/未注入）时读操作返回空、写操作拒绝。
# ============================================================

async def _tool_get_my_history(history_id: int = 0, page: int = 1) -> str:
    """
    工具: get_my_history
    作用: 查询当前用户的历史方案记录（列表或单条详情）。
    """
    uid = get_agent_user_context()
    if uid <= 0:
        return json.dumps({"status": "error", "message": "需要登录后才能查看历史方案"}, ensure_ascii=False)
    from api.dependencies import get_usage_logger
    svc = get_usage_logger()
    try:
        if history_id and history_id > 0:
            item = svc.get_match_history_by_id(history_id, user_id=uid)
            if item is None:
                return json.dumps({"status": "not_found", "message": f"未找到历史记录 id={history_id}"}, ensure_ascii=False)
            return json.dumps({
                "status": "ok",
                "item": {
                    "id": item["id"],
                    "title": item.get("title") or item.get("demand_text", "")[:50],
                    "demand_text": item.get("demand_text", ""),
                    "industry": item.get("industry", ""),
                    "created_at": item.get("created_at", ""),
                    "version": item.get("version", 1),
                    "is_final": item.get("is_final", False),
                    "group_id": item.get("group_id"),
                },
            }, ensure_ascii=False, indent=2)
        rows = svc.get_match_history_list(limit=10, offset=(max(page, 1) - 1) * 10, user_id=uid)
        items = [{
            "id": r["id"],
            "title": r.get("title") or (r.get("demand_text") or "")[:50],
            "demand_text": (r.get("demand_text") or "")[:80],
            "industry": r.get("industry", ""),
            "created_at": r.get("created_at", ""),
            "version": r.get("version", 1),
            "is_final": r.get("is_final", False),
        } for r in rows]
        cb = get_agent_event_callback()
        if cb:
            try:
                await cb({"type": "history_list", "items": items, "total": len(items)})
            except Exception as e:
                logger.warning(f"[get_my_history] 事件回调失败: {e}")
        if not items:
            return json.dumps({"status": "empty", "message": "暂无历史方案记录"}, ensure_ascii=False)
        return json.dumps({
            "status": "ok",
            "total": len(items),
            "items": items,
            "message": "已查到历史方案列表。请在 Final Answer 中列出标题、行业、时间（简要即可）。",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[get_my_history] 查询失败: {e}")
        return f"Error: 查询历史失败 {str(e)}"


async def _tool_manage_client(
    action: str,
    name: str = "",
    industry: str = "",
    company_size: str = "",
    region: str = "",
    contact_name: str = "",
    contact_title: str = "",
    contact_phone: str = "",
    contact_email: str = "",
    stage: str = "",
    budget: str = "",
    pain_points: str = "",
    decision_chain: str = "",
    tags: str = "",
    note: str = "",
    client_id: int = 0,
) -> str:
    """
    工具: manage_client
    作用: 管理当前用户的客户档案（查询/新建/编辑/删除）。
    """
    uid = get_agent_user_context()
    if uid <= 0:
        return json.dumps({"status": "error", "message": "需要登录后才能管理客户档案"}, ensure_ascii=False)
    try:
        import sqlite3
        from app.utils import db_init
        conn = db_init.get_db_connection()
        action = (action or "").strip().lower()
        if action in ("list", "get"):
            if action == "get" and client_id > 0:
                row = conn.execute(
                    "SELECT * FROM clients WHERE id=? AND user_id=?", (client_id, uid)
                ).fetchone()
                conn.close()
                if not row:
                    return json.dumps({"status": "not_found", "message": f"未找到客户 id={client_id}"}, ensure_ascii=False)
                return json.dumps({"status": "ok", "client": {k: row[k] for k in row.keys()}}, ensure_ascii=False, indent=2)
            rows = conn.execute(
                "SELECT id, name, industry, region, stage, budget, contact_name, created_at, note"
                " FROM clients WHERE user_id=? ORDER BY id DESC LIMIT 20",
                (uid,),
            ).fetchall()
            conn.close()
            items = [{k: r[k] for k in r.keys()} for r in rows]
            if not items:
                return json.dumps({"status": "empty", "message": "暂无客户档案"}, ensure_ascii=False)
            return json.dumps({"status": "ok", "total": len(items), "clients": items}, ensure_ascii=False, indent=2)
        if action == "create":
            if not name or not name.strip():
                return json.dumps({"status": "error", "message": "创建客户必须提供名称(name)"}, ensure_ascii=False)
            cur = conn.execute(
                "INSERT INTO clients (user_id, name, industry, company_size, region, contact_name,"
                " contact_title, contact_phone, contact_email, stage, budget, pain_points,"
                " decision_chain, tags, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uid, name.strip(), industry, company_size, region, contact_name, contact_title,
                 contact_phone, contact_email, stage, budget, pain_points, decision_chain, tags, note),
            )
            conn.commit()
            new_id = cur.lastrowid
            conn.close()
            return json.dumps({"status": "ok", "action": "create", "client_id": new_id, "name": name,
                               "message": f"已创建客户「{name}」（id={new_id}）"}, ensure_ascii=False, indent=2)
        if action in ("update", "edit"):
            if client_id <= 0:
                return json.dumps({"status": "error", "message": "更新客户必须提供 client_id"}, ensure_ascii=False)
            row = conn.execute("SELECT id FROM clients WHERE id=? AND user_id=?", (client_id, uid)).fetchone()
            if not row:
                conn.close()
                return json.dumps({"status": "not_found", "message": f"未找到客户 id={client_id} 或无权限"}, ensure_ascii=False)
            updates = {}
            for f in ("name", "industry", "company_size", "region", "contact_name", "contact_title",
                      "contact_phone", "contact_email", "stage", "budget", "pain_points",
                      "decision_chain", "tags", "note"):
                v = locals().get(f)
                if v:
                    updates[f] = v
            if updates:
                sets = ", ".join(f"{k}=?" for k in updates)
                conn.execute(f"UPDATE clients SET {sets} WHERE id=? AND user_id=?", (*updates.values(), client_id, uid))
                conn.commit()
            conn.close()
            return json.dumps({"status": "ok", "action": "update", "client_id": client_id,
                               "updated": list(updates.keys())}, ensure_ascii=False, indent=2)
        if action == "delete":
            if client_id <= 0:
                return json.dumps({"status": "error", "message": "删除客户必须提供 client_id"}, ensure_ascii=False)
            row = conn.execute("SELECT name FROM clients WHERE id=? AND user_id=?", (client_id, uid)).fetchone()
            if not row:
                conn.close()
                return json.dumps({"status": "not_found", "message": f"未找到客户 id={client_id} 或无权限"}, ensure_ascii=False)
            conn.execute("DELETE FROM clients WHERE id=? AND user_id=?", (client_id, uid))
            conn.commit()
            conn.close()
            return json.dumps({"status": "ok", "action": "delete", "client_id": client_id,
                               "name": row["name"], "message": f"已删除客户「{row['name']}」"}, ensure_ascii=False, indent=2)
        conn.close()
        return json.dumps({"status": "error", "message": f"未知动作: {action}（支持 list/get/create/update/delete）"}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[manage_client] 操作失败: {e}")
        return f"Error: 客户档案操作失败 {str(e)}"


async def _tool_export_report(
    history_id: int,
    format: str = "word",
) -> str:
    """
    工具: export_report
    作用: 把指定历史方案导出为 Word/PDF 报告，返回下载链接。
    """
    uid = get_agent_user_context()
    if uid <= 0:
        return json.dumps({"status": "error", "message": "需要登录后才能导出报告"}, ensure_ascii=False)
    try:
        from app.services.usage_logger import UsageLoggerService
        from app.services.report_generator import ReportGeneratorService, ReportType, ExportFormat
        svc = UsageLoggerService()
        item = svc.get_match_history_by_id(history_id, user_id=uid)
        if item is None:
            return json.dumps({"status": "not_found", "message": f"未找到历史记录 id={history_id}"}, ensure_ascii=False)
        content = item.get("solution") or ""
        if not content.strip():
            return json.dumps({"status": "error", "message": "该记录无方案内容，无法导出"}, ensure_ascii=False)
        is_analyze = item.get("type") == "analyze"
        report_type = ReportType.COMPETITOR if is_analyze else ReportType.SOLUTION
        fmt = ExportFormat.PDF if (format or "word").lower() == "pdf" else ExportFormat.WORD
        title = (item.get("competitor") or item.get("demand_text") or "华为云方案")[:60]
        task = ReportGeneratorService().generate_report(
            report_type=report_type,
            content=content,
            format=fmt,
            metadata={"title": title, "customer": title},
        )
        if not task or task.status.value != "completed" or not task.file_path:
            return json.dumps({"status": "error", "message": f"文件生成失败: {getattr(task, 'error_message', '未知错误')}"},
                               ensure_ascii=False)
        dl_url = getattr(task, "download_url", "") or f"/api/export/download/{task.task_id}"
        cb = get_agent_event_callback()
        if cb:
            try:
                await cb({"type": "export_ready", "file_name": getattr(task, "file_name", ""),
                          "download_url": dl_url, "history_id": history_id})
            except Exception as e:
                logger.warning(f"[export_report] 事件回调失败: {e}")
        return json.dumps({
            "status": "ok",
            "file_name": getattr(task, "file_name", ""),
            "download_url": dl_url,
            "message": "报告已生成。请在 Final Answer 中给出下载链接。",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[export_report] 导出失败: {e}")
        return f"Error: 导出报告失败 {str(e)}"


# ============================================================
# 阶段1 新增：文件交互工具（读取/落盘/列举）
# ============================================================

async def _tool_read_customer_file(path: str) -> str:
    """
    工具: read_customer_file
    作用: 读取客户上传的任意格式文件（docx/xlsx/pdf/pptx/txt/csv/md/图片），
          提取纯文本供需求分析。图片经 OCR 转文字。
    实现: 复用 file_security 白名单校验 + parsers 多格式解析
    """
    from app.services.knowledge_base import get_kb_user_context
    from app.agent.file_security import safe_resolve
    from app.agent.parsers.read_file import extract_text, chunk_text

    user_id = get_kb_user_context()
    if user_id <= 0:
        return "Error: 未登录用户无法读取文件"

    try:
        abs_path = safe_resolve(user_id, path)
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.exists(abs_path):
        return f"Error: 文件不存在: {path}"

    text = extract_text(abs_path)
    if text.startswith("Error:"):
        return text

    # 不盲截断：返回全量；超长文本按重叠窗口分块，确保全部内容进入上下文、零丢弃
    chunks = chunk_text(text)
    if len(chunks) == 1:
        return f"【客户文件内容 {path}】\n{text}"
    return (
        f"【客户文件内容 {path}（共 {len(chunks)} 段，已全量保留）】\n"
        + "\n---\n".join(f"第{i + 1}段:\n{c}" for i, c in enumerate(chunks))
    )




async def _tool_list_dir(dir: str = "") -> str:
    """
    工具: list_dir
    作用: 列出用户白名单目录下的文件，供 Agent 选择/确认
    """
    from app.services.knowledge_base import get_kb_user_context
    from app.agent.file_security import safe_resolve, get_user_root

    user_id = get_kb_user_context()
    if user_id <= 0:
        return "Error: 未登录用户无法列举文件"

    try:
        target = safe_resolve(user_id, dir) if dir else str(get_user_root(user_id))
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.isdir(target):
        return f"Error: 目录不存在: {dir}"

    try:
        entries = []
        for name in sorted(os.listdir(target)):
            full = os.path.join(target, name)
            kind = "目录" if os.path.isdir(full) else "文件"
            entries.append(f"- [{kind}] {name}")
        if not entries:
            return f"（目录为空: {dir or '用户根目录'}）"
        return "用户目录文件列表：\n" + "\n".join(entries)
    except Exception as e:
        return f"Error: 列举失败: {e}"


def USER_DOCS_BASE_SAFE():
    from app.config import USER_DOCS_BASE_DIR
    return USER_DOCS_BASE_DIR


# ============================================================
# S0 新增：代码沙箱工具（让 Agent 在隔离环境跑 Python 生成真实产物）
# ============================================================

def _format_sandbox_observation(result: Dict[str, Any]) -> str:
    """把沙箱执行结果整理成给 LLM 看的 Observation 字符串。"""
    if not result.get("ok"):
        err = result.get("error", "未知错误")
        stderr = result.get("stderr", "")[:1500]
        return json.dumps({
            "status": "error",
            "error": err,
            "stderr_tail": stderr,
            "message": "代码执行失败。请检查报错、修改脚本后重新调用 run_code。",
        }, ensure_ascii=False, indent=2)

    files = result.get("files", [])
    summary = {
        "status": "ok",
        "stdout": result.get("stdout", "")[:1500],
        "files": [
            {"name": f["name"], "kind": f["kind"], "size": f["size"],
             "download_path": f["path"]}
            for f in files
        ],
    }
    if files:
        summary["message"] = (
            "已生成真实文件。请在 Final Answer 中告知用户可在界面下载，"
            "并列出文件名与用途；下载地址由前端根据 download_path 自动生成。"
        )
    else:
        summary["message"] = "代码执行成功但未生成文件（仅 print 了计算结果）。"
    return json.dumps(summary, ensure_ascii=False, indent=2)


async def _tool_run_code(code: str = "", query: str = "") -> str:
    """
    工具: run_code
    作用: 在隔离沙箱里运行 Python 代码，生成真实文件（Excel/PPT 等）或做精确计算。
    实现: 调用 sandbox.run_code，经 file_security jail 隔离；user_id 取自 kb 上下文，
          event_callback 取自 contextvar（由 harness 注入），实现 raw 流式透传。
    兼容: LLM 偶发把参数名传成 query（与 query_pricing 混淆），此处兼容取 code。
    """
    from app.agent.sandbox import run_code
    from app.services.knowledge_base import get_kb_user_context

    # 参数名别名兼容：LLM 偶发把 code 传成 query（工具变多后选择面扩大，混淆概率上升）
    if not code and query:
        code = query
    if not code or not code.strip():
        return json.dumps({"status": "error", "error": "缺少 code 参数（要执行的 Python 代码）"}, ensure_ascii=False)

    user_id = get_kb_user_context()
    if user_id <= 0:
        return json.dumps({"status": "error", "error": "未登录用户不可使用代码沙箱"}, ensure_ascii=False)

    event_cb = get_agent_event_callback()
    try:
        result = await run_code(code=code, user_id=user_id, event_callback=event_cb)
    except Exception as e:
        logger.error(f"[run_code] 沙箱调用异常: {e}")
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    return _format_sandbox_observation(result)


# ============================================================
# 工厂函数：创建默认工具集
# ============================================================

def create_default_tools() -> ToolRegistry:
    """创建包含 3 个核心工具的注册中心"""
    registry = ToolRegistry()

    # 1. analyze_demand — 需求分析
    registry.register(Tool(
        name="analyze_demand",
        description="分析模糊的用户需求，提取行业、场景、痛点和搜索关键词。当用户输入模糊、不明确时优先使用。",
        parameters={
            "type": "object",
            "properties": {
                "raw_input": {
                    "type": "string",
                    "description": "用户的原始输入文本"
                }
            },
            "required": ["raw_input"]
        },
        func=_tool_analyze_demand,
        domain="solution",
    ))

    # 2. search_kb — 知识库检索
    registry.register(Tool(
        name="search_kb",
        description="搜索华为云知识库，获取解决方案文档。使用从 analyze_demand 提取的关键词进行检索。",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询字符串，建议包含行业+场景+技术关键词，如 '制造业 工业物联网 预测性维护 华为云'"
                }
            },
            "required": ["query"]
        },
        func=_tool_search_kb,
        domain="solution",
    ))

    # 3. search_competitor — 竞品检索
    registry.register(Tool(
        name="search_competitor",
        description="搜索指定竞品在特定行业的方案资料。当用户提到竞品名称或需要对比时使用。",
        parameters={
            "type": "object",
            "properties": {
                "competitor": {
                    "type": "string",
                    "description": "竞品厂商名称，如：阿里云、腾讯云、AWS、微软Azure、西门子等"
                },
                "industry": {
                    "type": "string",
                    "description": "行业名称（可选），如：制造业、智慧医疗、工业互联网"
                }
            },
            "required": ["competitor"]
        },
        func=_tool_search_competitor,
        domain="competitor",
    ))

    # 4. read_customer_file — 读取客户上传的任意格式文件（含图片 OCR）
    registry.register(Tool(
        name="read_customer_file",
        description="读取客户上传的需求资料文件，提取纯文本供需求分析。支持 Word/Excel/PDF/PPT/TXT/CSV/MD，以及图片（自动 OCR 识别文字）。当用户提到客户资料、上传文件、招标书、需求文档时使用。输入为相对路径（如 customer_uploads/xxx.docx）。",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件的相对路径，如 customer_uploads/客户需求.docx"
                }
            },
            "required": ["path"]
        },
        func=_tool_read_customer_file,
        domain="filegen",
    ))

    # 5. list_dir — 列举用户目录文件
    registry.register(Tool(
        name="list_dir",
        description="列出用户文件目录下的文件，确认有哪些上传资料可用。",
        parameters={
            "type": "object",
            "properties": {
                "dir": {
                    "type": "string",
                    "description": "相对目录路径，留空表示用户根目录"
                }
            }
        },
        func=_tool_list_dir,
        domain="filegen",
    ))

    # 6. run_code — 代码沙箱（S0：让 Agent 动手生成真实产物）
    registry.register(Tool(
        name="run_code",
        description=(
            "在隔离沙箱里运行 Python 代码，用于精确计算（如 TCO/ROI 测算、成本对比）"
            "或生成真实文件（Excel 报表、数据表、PPT 等）。"
            "可用库：pandas、openpyxl、python-pptx（无需联网）。"
            "规则：脚本须独立可跑；结果用 openpyxl/pptx 写入当前工作目录的文件；"
            "关键结论用 print() 输出到 stdout 作为摘要；严禁联网（不要 urllib/requests 外部请求）。"
            "执行过程的 stdout/stderr 会实时回传，报错请自行修改脚本后重试。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "要执行的完整 Python 代码（字符串）。例如用 openpyxl 生成 cost.xlsx 并 print 总成本分项。"
                }
            },
            "required": ["code"]
        },
        func=_tool_run_code,
        domain="filegen",
    ))

    # 7. query_pricing — 价目查询（S0.5 统一 Agent 新增能力）
    registry.register(Tool(
        name="query_pricing",
        description=(
            "查询华为云产品的参考价格与计费方式。当用户询问价格、费用、成本、报价、"
            "包月/包年费用、预算时调用。输入为产品名或价格相关关键词"
            "（如 'ECS'、'OBS存储'、'CDN'、'云数据库'、'带宽'）。"
            "返回匹配产品的规格、计费方式、参考价格（免费产品标注免费，"
            "商务报价产品提示咨询华为云销售）。如需多产品总成本精确测算，"
            "可结合 run_code 调用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "产品名或价格相关关键词，如 'ECS'、'OBS'、'CDN流量'、'云数据库'"
                }
            },
            "required": ["query"]
        },
        func=_tool_query_pricing,
        domain="pricing",
    ))

    # 8. get_my_history — 我的历史方案（M2 平台工具）
    registry.register(Tool(
        name="get_my_history",
        description=(
            "查询当前登录用户的历史方案记录。当用户问\"我上次做的方案\"\"我的历史\""
            "\"找出之前XX的方案\"\"最近做过什么\"时调用。传 history_id 查单条详情，"
            "不传则返回最近列表（每页10条）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "history_id": {
                    "type": "integer",
                    "description": "历史记录 id（可选，传则查单条详情）",
                    "default": 0
                },
                "page": {
                    "type": "integer",
                    "description": "页码，从1开始（可选）",
                    "default": 1
                }
            }
        },
        func=_tool_get_my_history,
        domain="platform",
    ))

    # 9. manage_client — 客户档案（M2 平台工具）
    registry.register(Tool(
        name="manage_client",
        description=(
            "管理当前登录用户的客户档案。当用户说\"记个客户/建客户\"\"我的客户有哪些\""
            "\"把XX客户的信息改一下\"\"删掉XX客户\"时调用。"
            "action 必填：list(列表)/get(详情，需client_id)/create(新建，需name)/"
            "update(编辑，需client_id)/delete(删除，需client_id)。"
            "创建时 name 必填，其余字段可选（industry行业/company_size规模/region区域/"
            "contact_name联系人/stage阶段/budget预算/pain_points痛点/tags标签/note备注等）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "delete"],
                    "description": "操作类型（必填）"
                },
                "client_id": {"type": "integer", "description": "客户 id（get/update/delete 必填）", "default": 0},
                "name": {"type": "string", "description": "客户名称（create 必填）", "default": ""},
                "industry": {"type": "string", "description": "所属行业", "default": ""},
                "company_size": {"type": "string", "description": "企业规模", "default": ""},
                "region": {"type": "string", "description": "所在区域", "default": ""},
                "contact_name": {"type": "string", "description": "联系人", "default": ""},
                "contact_title": {"type": "string", "description": "联系人职位", "default": ""},
                "contact_phone": {"type": "string", "description": "联系电话", "default": ""},
                "contact_email": {"type": "string", "description": "联系邮箱", "default": ""},
                "stage": {"type": "string", "description": "项目阶段", "default": ""},
                "budget": {"type": "string", "description": "预算", "default": ""},
                "pain_points": {"type": "string", "description": "客户痛点", "default": ""},
                "decision_chain": {"type": "string", "description": "决策链", "default": ""},
                "tags": {"type": "string", "description": "标签", "default": ""},
                "note": {"type": "string", "description": "备注", "default": ""}
            },
            "required": ["action"]
        },
        func=_tool_manage_client,
        domain="platform",
    ))

    # 10. export_report — 导出报告（M2 平台工具）
    registry.register(Tool(
        name="export_report",
        description=(
            "把当前用户指定的历史方案导出为 Word/PDF 报告文件并给出下载链接。"
            "当用户说\"导成Word/PDF\"\"下载报告\"\"把方案导出\"时调用。"
            "需提供 history_id（历史记录 id，可先用 get_my_history 查到）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "history_id": {
                    "type": "integer",
                    "description": "要导出的历史记录 id（必填）"
                },
                "format": {
                    "type": "string",
                    "enum": ["word", "pdf"],
                    "description": "导出格式，默认 word",
                    "default": "word"
                }
            },
            "required": ["history_id"]
        },
        func=_tool_export_report,
        domain="platform",
    ))

    return registry
