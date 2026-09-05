"""
P0：自带 MCP Server —— 华为云方案成本测算（cost_calc）

零新依赖（纯 Python stdlib），不 import 任何 app 重链（chromadb/langchain 等），
可独立作为子进程运行，被 `mcp_client.py` 通过 stdio JSON-RPC 消费，
注册为 `mcp__cost__cost_calc` / `mcp__cost__cost_reference_list`。

用途：
  1. 验证「项目能力 → MCP → Agent 可调用」闭环（远端的成本测算能力被 Agent 当作工具调用）。
  2. 演示用：Agent 在做方案时，可随时调用成本测算给出 TCO 估算。

启动：python -m app.agent.mcp_server_cost_calc
协议：stdin 逐行 JSON-RPC（\\n 分隔），stdout 逐行响应。

注意：价格数据为华为云公开官网列表价区间的「估算值」，非实时报价，
仅用于方案层面的量级测算；实际以官网询价 / 商务折扣为准。
"""

import asyncio
import json
import logging
import sys

logger = logging.getLogger(__name__)

# ---- JSON-RPC 2.0 常量 ----
JSONRPC_VERSION = "2.0"
SERVER_NAME = "huawei-cloud-cost-calc"
SERVER_VERSION = "0.1.0"

_INIT_RESULT = {
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {"listChanged": False}},
    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
}

# ---- 内置 SKU 目录（公开官网列表价估算，单位：人民币 CNY / 单位·月）----
# unit_price 含义：每「unit」每个月的费用（存储/带宽按 GB·月 / Mbps·月 计）。
SKU_CATALOG = {
    "ecs.s6.medium.2":   {"name": "ECS 通用计算型 s6.medium.2（1vCPU/2GB）",            "unit": "台",   "unit_price": 80.0},
    "ecs.s6.large.2":    {"name": "ECS 通用计算型 s6.large.2（2vCPU/4GB）",            "unit": "台",   "unit_price": 160.0},
    "ecs.s6.xlarge.2":   {"name": "ECS 通用计算型 s6.xlarge.2（4vCPU/8GB）",           "unit": "台",   "unit_price": 320.0},
    "ecs.c6.2xlarge.2":  {"name": "ECS 计算型 c6.2xlarge.2（8vCPU/16GB）",             "unit": "台",   "unit_price": 640.0},
    "obs.standard":      {"name": "OBS 标准存储",                                       "unit": "GB",   "unit_price": 0.099},
    "rds.mysql.s6.large.2":  {"name": "RDS for MySQL s6.large.2（2vCPU/4GB）",         "unit": "实例", "unit_price": 400.0},
    "rds.mysql.s6.xlarge.2": {"name": "RDS for MySQL s6.xlarge.2（4vCPU/8GB）",        "unit": "实例", "unit_price": 800.0},
    "bandwidth.shared":  {"name": "共享带宽（固定规格）",                                "unit": "Mbps", "unit_price": 20.0},
    "cdn.traffic":       {"name": "CDN 流量（按量，按 GB·月估算）",                     "unit": "GB",   "unit_price": 0.20},
    "waf.enterprise":    {"name": "WAF 企业版",                                        "unit": "实例", "unit_price": 3880.0},
}


def _fmt_cny(v: float) -> str:
    return f"¥{v:,.2f}"


def _build_cost_calc_text(items: list) -> str:
    """根据资源清单计算成本，返回可读文本（含月/年合计）。

    非法输入（缺清单 / 未知 SKU / 数量非数字）直接返回以「错误：」开头的文本，
    由 MCP 客户端标记为 isError，让 Agent 自行纠正后重试。
    """
    if not items:
        return "错误：未提供资源清单 items。请参考 cost_reference_list 选择 SKU 后传入。"
    unknown, bad_qty = [], []
    for it in items:
        it = it or {}
        sku = it.get("sku", "")
        if sku not in SKU_CATALOG:
            unknown.append(sku)
        try:
            float(it.get("qty", 0) or 0)
            float(it.get("months", 1) or 1)
        except (TypeError, ValueError):
            bad_qty.append(sku or "?")
    if unknown:
        return "错误：未知 SKU：" + "、".join(unknown) + "。请用 cost_reference_list 查看可用 SKU。"
    if bad_qty:
        return "错误：以下条目的 qty/months 不是合法数字：" + "、".join(bad_qty)

    lines = [
        "成本测算结果（单位：人民币 CNY；价格来源：华为云公开官网列表价估算，非实时报价）",
        "─" * 48,
    ]
    total_month = 0.0
    for it in items:
        it = it or {}
        sku = it.get("sku", "")
        qty_f = float(it.get("qty", 0) or 0)
        months_f = float(it.get("months", 1) or 1)
        spec = SKU_CATALOG[sku]
        cost = spec["unit_price"] * qty_f * months_f
        total_month += cost
        lines.append(
            f"- {spec['name']} ×{qty_f:g} {spec['unit']} ×{months_f:g} 月 = {_fmt_cny(cost)}"
        )
    lines.append("─" * 48)
    lines.append(f"合计（月）：{_fmt_cny(total_month)}")
    lines.append(f"合计（年，×12）：{_fmt_cny(total_month * 12)}")
    lines.append("注：以上为列表价估算，未含折扣 / 代金券 / 预留实例优惠；实际以官网询价为准。")
    return "\n".join(lines)


def _build_reference_text() -> str:
    # 仅暴露 SKU 名称/规格/单位，不泄露单价 —— 单价只在 cost_calc 内部计算返回，
    # 强制 Agent 必须调用 cost_calc 才能得到报价，避免 LLM 用目录里的价格自行估算绕过工具。
    lines = ["可用 SKU 参考（cost_calc 的 items[].sku 取值；单价由 cost_calc 计算返回，此处不泄露）：", "─" * 48]
    for sku, spec in SKU_CATALOG.items():
        lines.append(f"- {sku}: {spec['name']}（{spec['unit']}）")
    lines.append("─" * 48)
    lines.append("调用示例：cost_calc(items=[{\"sku\":\"ecs.s6.large.2\",\"qty\":2,\"months\":1},{\"sku\":\"obs.standard\",\"qty\":500}])")
    return "\n".join(lines)


# ---- 内存注册表（自包含，不依赖 app.agent.tools）----
async def _h_cost_calc(**arguments) -> str:
    items = arguments.get("items") or []
    if not isinstance(items, list):
        return "错误：items 必须为数组。"
    return _build_cost_calc_text(items)


async def _h_cost_reference_list(**arguments) -> str:
    return _build_reference_text()


_REGISTRY = [
    {
        "name": "cost_calc",
        "description": "华为云方案成本测算（成本/TCO/报价/预算/月租的唯一权威价源）：传入资源清单 items"
                       "（每项含 sku/qty/months），返回按月/按年的 TCO 估算（CNY）。"
                       "价格为公开官网列表价估算，非实时报价；返回的合计金额必须直接写入方案预算，"
                       "禁止自行估算单价或用知识库检索替代本工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "资源清单，每项 {sku, qty(数量), months(月数,默认1)}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sku": {"type": "string", "description": "SKU 编码，见 cost_reference_list"},
                            "qty": {"type": "number", "description": "数量（台/GB/Mbps/实例）"},
                            "months": {"type": "number", "description": "计费月数，默认 1"},
                        },
                        "required": ["sku", "qty"],
                    },
                }
            },
            "required": ["items"],
        },
        "handler": _h_cost_calc,
    },
    {
        "name": "cost_reference_list",
        "description": "列出成本测算可用的 SKU 目录与示例调用，供 Agent/用户选择资源规格。"
                       "注意：本工具只暴露 SKU 名称/规格/单位，不含单价；"
                       "拿到目录后必须紧接着调用 cost_calc 才能完成报价，"
                       "切勿用知识库检索或自行估算替代 cost_calc。",
        "parameters": {"type": "object", "properties": {}},
        "handler": _h_cost_reference_list,
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
    """处理单个 JSON-RPC 请求（与 mcp_server.py 同构，便于复用测试）。"""
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
    logger.info("[MCP-cost] server 启动: %s v%s，工具数=%d", SERVER_NAME, SERVER_VERSION, len(registry))
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
    import asyncio as _asyncio
    logging.basicConfig(level=logging.INFO)
    _asyncio.run(serve_stdio())


if __name__ == "__main__":
    main()
