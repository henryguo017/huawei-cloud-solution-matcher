"""
P2：自带 MCP Server —— 客户管理与匹配历史（crm）

零新依赖（纯 Python stdlib：sqlite3/json/os/sys/asyncio/logging），
**不 import 任何 app 模块**（连 app.config 都不碰），数据库路径由 __file__ 推导，
可独立作为子进程运行，被 `mcp_client.py` 通过 stdio JSON-RPC 消费，
注册为 `mcp__crm__client_add` / `mcp__crm__client_list` /
`mcp__crm__client_update` / `mcp__crm__match_history`。

用途：
  让 Agent 能主动读写 CRM（此前客户档案只能在会话内提及、无法落库），
  并回溯历史匹配/竞品分析，做「这个客户上次聊到哪了」的连续性售前。

启动：python app/agent/mcp_server_crm.py   （⚠️ 务必脚本模式，禁止 python -m：后者会触发 app.agent 包 import 卡死）
协议：stdin 逐行 JSON-RPC（\\n 分隔），stdout 逐行响应。

⚠️ 多租户：clients / match_history 均按 user_id 隔离。
   user_id 解析顺序：① 工具显式入参 ② 环境变量 MCP_CRM_DEFAULT_USER_ID。
   两者都无 → 返回「错误：」开头的提示，要求向用户确认 user_id 或配置环境变量
   （绝不默认写进某个账号，避免串号）。
"""

import asyncio
import json
import logging
import os
import sqlite3
import sys

logger = logging.getLogger(__name__)

# ---- JSON-RPC 2.0 常量 ----
JSONRPC_VERSION = "2.0"
SERVER_NAME = "huawei-cloud-crm"
SERVER_VERSION = "0.1.0"

_INIT_RESULT = {
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {"listChanged": False}},
    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
}

# ---- 数据库路径（由本文件位置推导，不依赖 app.config / 工作目录）----
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
USERS_DB = os.path.join(_BASE_DIR, "data", "users.db")          # clients 表
USAGE_DB = os.path.join(_BASE_DIR, "data", "usage_logs.db")     # match_history 表

# clients 表允许通过 client_add / client_update 写入的字段白名单（防 SQL 注入 + 防幻觉列）
# 值 = (展示标签, 入参描述)：展示标签要短（会进工具返回文本），描述可长（只进 schema）
_CLIENT_WRITABLE = {
    "industry":       ("行业",   "所属行业，如 制造/政务/金融/能源/教育"),
    "company_size":   ("规模",   "企业规模，如 50-200人 / 2000人以上"),
    "region":         ("区域",   "所在区域，如 杭州/浙江省"),
    "contact_name":   ("联系人", "联系人姓名"),
    "contact_title":  ("职位",   "联系人职位，如 IT经理/信息化主任"),
    "contact_phone":  ("电话",   "联系电话"),
    "contact_email":  ("邮箱",   "联系邮箱"),
    "stage":          ("阶段",   "商机阶段：初步接触/需求调研/方案报价/商务谈判/已成交/已流失"),
    "budget":         ("预算",   "预算范围，如 50-80万"),
    "pain_points":    ("痛点",   "核心痛点，多个用分号分隔"),
    "decision_chain": ("决策链", "决策链/关键角色，如 信息中心主任→分管副总→总经理"),
    "tags":           ("标签",   "标签，逗号分隔"),
    "note":           ("备注",   "其他备注"),
}

_MAX_LIMIT = 50


def _resolve_user_id(arguments: dict):
    """解析 user_id：显式入参 → 环境变量 MCP_CRM_DEFAULT_USER_ID → None。"""
    raw = arguments.get("user_id")
    if raw not in (None, "", 0):
        try:
            return int(raw), None
        except (TypeError, ValueError):
            return None, f"错误：user_id 不是合法整数：{raw!r}"
    env_raw = (os.getenv("MCP_CRM_DEFAULT_USER_ID") or "").strip()
    if env_raw:
        try:
            return int(env_raw), None
        except ValueError:
            return None, f"错误：环境变量 MCP_CRM_DEFAULT_USER_ID 不是合法整数：{env_raw!r}"
    return None, (
        "错误：未提供 user_id，且未配置环境变量 MCP_CRM_DEFAULT_USER_ID。"
        "为避免写入错误账号，请向用户确认其 user_id 后重试，"
        "或由管理员在 .env 配置 MCP_CRM_DEFAULT_USER_ID=<该用户的 user_id>。"
    )


def _conn(path: str):
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _clean_limit(arguments: dict, default: int) -> int:
    try:
        n = int(arguments.get("limit", default) or default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, _MAX_LIMIT))


def _fmt_client(row: sqlite3.Row) -> str:
    """把客户档案格式化为多行可读文本（只输出有值的字段）。"""
    head = f"#{row['id']} {row['name']}"
    bits = []
    for key, (label, _desc) in _CLIENT_WRITABLE.items():
        try:
            val = row[key]
        except (IndexError, KeyError):
            val = None
        if val:
            bits.append(f"{label}：{val}")
    tail = " ｜ ".join(bits) if bits else "（无补充信息）"
    extra = f"｜更新于 {row['updated_at']}" if row["updated_at"] else ""
    return f"- {head} {extra}\n    {tail}"


# ---------------------------- 工具实现 ----------------------------

async def _h_client_list(**arguments) -> str:
    uid, err = _resolve_user_id(arguments)
    if err:
        return err
    if not os.path.exists(USERS_DB):
        return f"错误：客户库不存在：{USERS_DB}"
    keyword = (arguments.get("keyword") or "").strip()
    limit = _clean_limit(arguments, 20)
    sql = "SELECT * FROM clients WHERE user_id = ?"
    params = [uid]
    if keyword:
        sql += " AND (name LIKE ? OR industry LIKE ? OR tags LIKE ? OR note LIKE ?)"
        params += [f"%{keyword}%"] * 4
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    params.append(limit)
    try:
        conn = _conn(USERS_DB)
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM clients WHERE user_id = ?", [uid]
        ).fetchone()[0]
        conn.close()
    except sqlite3.Error as e:
        return f"错误：查询客户失败：{e}"
    if not rows:
        hint = f"（关键词「{keyword}」无匹配）" if keyword else ""
        return f"客户档案为空{hint}。可用 client_add 新增。"
    lines = [f"客户档案（user_id={uid}，共 {total} 个，本次返回 {len(rows)} 个）：", "─" * 48]
    lines += [_fmt_client(r) for r in rows]
    return "\n".join(lines)


async def _h_client_add(**arguments) -> str:
    uid, err = _resolve_user_id(arguments)
    if err:
        return err
    name = (arguments.get("name") or "").strip()
    if not name:
        return "错误：客户名称 name 不能为空。"
    if not os.path.exists(USERS_DB):
        return f"错误：客户库不存在：{USERS_DB}"
    fields, placeholders, params = [], [], []
    for key in ("name", *_CLIENT_WRITABLE.keys()):
        val = arguments.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        fields.append(key)
        placeholders.append("?")
        params.append(val.strip() if isinstance(val, str) else val)
    sql = (
        f"INSERT INTO clients (user_id, {', '.join(fields)}) "
        f"VALUES (?, {', '.join(placeholders)})"
    )
    try:
        conn = _conn(USERS_DB)
        # UNIQUE(user_id, name)：同名客户直接报错，引导走 client_update，避免产生重复档案
        existed = conn.execute(
            "SELECT id FROM clients WHERE user_id = ? AND name = ?", (uid, name)
        ).fetchone()
        if existed:
            conn.close()
            return (
                f"错误：客户「{name}」已存在（id={existed['id']}）。"
                f"如需更新信息请改用 client_update，不要重复建档。"
            )
        cur = conn.execute(sql, [uid, *params])
        conn.commit()
        new_id = cur.lastrowid
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (new_id,)).fetchone()
        conn.close()
    except sqlite3.Error as e:
        return f"错误：新增客户失败：{e}"
    return "已新增客户档案：\n" + _fmt_client(row)


async def _h_client_update(**arguments) -> str:
    uid, err = _resolve_user_id(arguments)
    if err:
        return err
    name = (arguments.get("name") or "").strip()
    if not name:
        return "错误：必须提供要更新的客户名称 name。"
    updates = {
        k: (v.strip() if isinstance(v, str) else v)
        for k, v in arguments.items()
        if k in _CLIENT_WRITABLE and v not in (None, "")
    }
    if not updates:
        return (
            "错误：未提供任何要更新的字段。可更新字段："
            + "、".join(_CLIENT_WRITABLE.keys())
        )
    if not os.path.exists(USERS_DB):
        return f"错误：客户库不存在：{USERS_DB}"
    set_sql = ", ".join(f"{k} = ?" for k in updates)
    try:
        conn = _conn(USERS_DB)
        row = conn.execute(
            "SELECT id FROM clients WHERE user_id = ? AND name = ?", (uid, name)
        ).fetchone()
        if not row:
            conn.close()
            return f"错误：未找到客户「{name}」（user_id={uid}）。请先用 client_add 建档。"
        conn.execute(
            f"UPDATE clients SET {set_sql}, updated_at = datetime('now','localtime') WHERE id = ?",
            [*updates.values(), row["id"]],
        )
        conn.commit()
        fresh = conn.execute("SELECT * FROM clients WHERE id = ?", (row["id"],)).fetchone()
        conn.close()
    except sqlite3.Error as e:
        return f"错误：更新客户失败：{e}"
    return f"已更新客户档案（{'、'.join(updates.keys())}）：\n" + _fmt_client(fresh)


async def _h_match_history(**arguments) -> str:
    uid, err = _resolve_user_id(arguments)
    if err:
        return err
    if not os.path.exists(USAGE_DB):
        return f"错误：匹配历史库不存在：{USAGE_DB}"
    keyword = (arguments.get("keyword") or "").strip()
    htype = (arguments.get("type") or "").strip()
    limit = _clean_limit(arguments, 10)
    sql = "SELECT id, demand_text, industry, competitor, type, created_at FROM match_history WHERE user_id = ?"
    params = [uid]
    if htype:
        sql += " AND type = ?"
        params.append(htype)
    if keyword:
        sql += " AND (demand_text LIKE ? OR industry LIKE ? OR competitor LIKE ?)"
        params += [f"%{keyword}%"] * 3
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    try:
        conn = _conn(USAGE_DB)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
    except sqlite3.Error as e:
        return f"错误：查询匹配历史失败：{e}"
    if not rows:
        return "暂无匹配历史。"
    lines = [f"匹配历史（user_id={uid}，最近 {len(rows)} 条）：", "─" * 48]
    for r in rows:
        kind = "竞品分析" if r["type"] == "analyze" else "方案匹配"
        who = f"｜竞品：{r['competitor']}" if r["competitor"] else ""
        ind = f"｜行业：{r['industry']}" if r["industry"] else ""
        demand = (r["demand_text"] or "")[:120]
        lines.append(f"- #{r['id']} [{kind}] {r['created_at']}{ind}{who}\n    需求：{demand}")
    lines.append("─" * 48)
    lines.append("提示：想看完整方案内容请说明是第几条，由上层接口按 id 取 solution 全文。")
    return "\n".join(lines)


# ---------------------------- 注册表 ----------------------------

_REGISTRY = [
    {
        "name": "client_list",
        "description": "查询客户档案列表（CRM）。按 user_id 隔离，可按关键词（名称/行业/标签/备注）过滤，"
                       "返回客户的结构化信息（行业、规模、区域、联系人、商机阶段、预算、痛点、决策链、标签）。"
                       "售前场景：开场前先查客户档案，避免重复提问用户已说过的信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "用户 ID；不传则取环境变量 MCP_CRM_DEFAULT_USER_ID"},
                "keyword": {"type": "string", "description": "关键词，模糊匹配客户名称/行业/标签/备注"},
                "limit": {"type": "integer", "description": f"返回条数，默认 20，上限 {_MAX_LIMIT}"},
            },
        },
        "handler": _h_client_list,
    },
    {
        "name": "client_add",
        "description": "新增客户档案（CRM 建档）。name 必填；其余字段按需填写即可（行业/规模/区域/联系人/商机阶段/预算/痛点/决策链/标签/备注）。"
                       "同一 user_id 下客户名唯一，重复建档会报错并提示改用 client_update。",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "用户 ID；不传则取环境变量 MCP_CRM_DEFAULT_USER_ID"},
                "name": {"type": "string", "description": "客户名称（必填）"},
                **{k: {"type": "string", "description": desc} for k, (_lbl, desc) in _CLIENT_WRITABLE.items()},
            },
            "required": ["name"],
        },
        "handler": _h_client_add,
    },
    {
        "name": "client_update",
        "description": "更新已有客户档案（按客户名定位）。最常用于推进商机阶段（stage）、补充联系人与预算。"
                       "只传需要改的字段，未传的保持原值。",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "用户 ID；不传则取环境变量 MCP_CRM_DEFAULT_USER_ID"},
                "name": {"type": "string", "description": "要更新的客户名称（必填，需已存在）"},
                **{k: {"type": "string", "description": desc} for k, (_lbl, desc) in _CLIENT_WRITABLE.items()},
            },
            "required": ["name"],
        },
        "handler": _h_client_update,
    },
    {
        "name": "match_history",
        "description": "查询历史匹配/竞品分析记录（需求原文、行业、竞品、时间）。"
                       "用于延续上次对话（『这个客户上次聊的什么方案』）或复用过往方案，"
                       "避免重复生成。可按 type(match/analyze) 与关键词过滤。",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "用户 ID；不传则取环境变量 MCP_CRM_DEFAULT_USER_ID"},
                "keyword": {"type": "string", "description": "关键词，模糊匹配需求原文/行业/竞品名"},
                "type": {"type": "string", "description": "match=方案匹配（默认全部） / analyze=竞品分析"},
                "limit": {"type": "integer", "description": f"返回条数，默认 10，上限 {_MAX_LIMIT}"},
            },
        },
        "handler": _h_match_history,
    },
]


def _make_result(result, req_id=None) -> dict:
    msg = {"jsonrpc": JSONRPC_VERSION, "result": result}
    if req_id is not None:
        msg["id"] = req_id
    return msg


def _make_error(code: int, message: str, data=None, req_id=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    msg = {"jsonrpc": JSONRPC_VERSION, "error": err}
    if req_id is not None:
        msg["id"] = req_id
    return msg


def _tool_schema(tool: dict) -> dict:
    return {
        "name": tool["name"],
        "description": tool["description"],
        "inputSchema": tool["parameters"] or {"type": "object", "properties": {}},
    }


def _get_tool(name: str):
    for t in _REGISTRY:
        if t["name"] == name:
            return t
    return None


async def _handle_request(req: dict, registry=None) -> dict:
    """处理单个 JSON-RPC 请求（与 mcp_server_cost_calc.py 同构，便于复用测试）。"""
    registry = registry or _REGISTRY
    method = req.get("method", "")
    req_id = req.get("id")
    if method == "initialize":
        return _make_result(_INIT_RESULT, req_id)
    if method == "tools/list":
        return _make_result({"tools": [_tool_schema(t) for t in registry]}, req_id)
    if method == "tools/call":
        params = req.get("params", {}) or {}
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        tool = _get_tool(name)
        if not tool:
            return _make_error(-32602, f"Tool not found: {name}", req_id=req_id)
        try:
            text = await tool["handler"](**arguments)
            is_error = isinstance(text, str) and text.startswith("错误：")
            return _make_result({
                "content": [{"type": "text", "text": text}],
                "isError": is_error,
            }, req_id)
        except Exception as e:  # noqa: BLE001
            return _make_error(-32603, f"Tool execution failed: {e}", req_id=req_id)
    if method == "ping":
        return _make_result({}, req_id)
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "shutdown":
        return _make_result({}, req_id)
    return _make_error(-32601, f"Method not found: {method}", req_id=req_id)


async def serve_stdio(registry=None) -> None:
    """stdin 逐行读取 JSON-RPC 请求 → stdout 逐行响应（MCP stdio 传输）。"""
    registry = registry or _REGISTRY
    logger.info("[MCP-crm] server 启动: %s v%s，工具数=%d", SERVER_NAME, SERVER_VERSION, len(registry))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            resp = _make_error(-32700, "Parse error")
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        if not isinstance(req, dict):
            continue
        resp = await _handle_request(req, registry)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            if req.get("method") == "shutdown":
                break


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve_stdio())


if __name__ == "__main__":
    main()
