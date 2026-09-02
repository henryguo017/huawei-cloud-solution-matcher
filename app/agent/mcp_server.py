"""
P2-3：最小 MCP（Model Context Protocol）Server — 零新依赖（Python stdlib）

把现有 ToolRegistry（analyze_demand / search_kb / ... / generate_doc / web_search 共 7 个）
暴露为标准 MCP 协议（JSON-RPC 2.0 over stdio），支持 initialize / tools/list / tools/call。

用途：
  1. 能力展示：本 Agent 的工具集是标准 MCP 可消费的（对接任意 MCP client）。
  2. 可插拔：工具生态符合行业标准，第三方 MCP client 可接入。

启动：python -m app.agent.mcp_server
协议：stdin 逐行 JSON-RPC（\n 分隔），stdout 逐行响应。
"""

import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)

# ---- JSON-RPC 2.0 常量 ----
JSONRPC_VERSION = "2.0"
SERVER_NAME = "huawei-cloud-solution-agent"
SERVER_VERSION = "0.1.0"

# MCP 初始化返回的 capabilities（最小子集）
_INIT_RESULT = {
    "protocolVersion": "2024-11-05",
    "capabilities": {
        "tools": {"listChanged": False},
    },
    "serverInfo": {
        "name": SERVER_NAME,
        "version": SERVER_VERSION,
    },
}


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


def _tool_schema(tool) -> dict:
    """Tool → MCP tools/list 项（inputSchema 直接复用 JSON Schema parameters）"""
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.parameters or {"type": "object", "properties": {}},
    }


async def _handle_request(req: dict, registry) -> dict:
    """处理单个 JSON-RPC 请求（同步包装为异步接口，供测试与 serve 复用）"""
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "initialize":
        return _make_result(_INIT_RESULT, req_id)
    if method == "tools/list":
        tools = [_tool_schema(t) for t in registry.list_tools()]
        return _make_result({"tools": tools}, req_id)
    if method == "tools/call":
        params = req.get("params", {}) or {}
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        tool = registry.get(name)
        if not tool:
            return _make_error(-32602, f"Tool not found: {name}", req_id=req_id)
        try:
            # Tool.execute 内部已捕获异常并返回 "Error: ..." 字符串
            text = await tool.execute(**arguments)
            is_error = isinstance(text, str) and text.startswith("Error:")
            return _make_result({
                "content": [{"type": "text", "text": text}],
                "isError": is_error,
            }, req_id)
        except Exception as e:
            return _make_error(-32603, f"Tool execution failed: {e}", req_id=req_id)
    if method == "ping":
        return _make_result({}, req_id)
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None  # 通知类：无响应
    if method == "shutdown":
        return _make_result({}, req_id)
    return _make_error(-32601, f"Method not found: {method}", req_id=req_id)


async def serve_stdio(registry=None) -> None:
    """stdin 逐行读取 JSON-RPC 请求 → stdout 逐行响应（MCP stdio 传输）"""
    from app.agent.tools import create_default_tools
    registry = registry or create_default_tools()
    logger.info(f"[MCP] server 启动: {SERVER_NAME} v{SERVER_VERSION}，工具数={len(registry.get_tool_names())}")
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


def serve_http(registry=None, host: str = "127.0.0.1", port: int = 8001) -> None:
    """MCP Streamable HTTP 传输（P1-B 测试靶机 + P3 双向暴露铺路）。

    纯标准库 http.server：POST /mcp 接收 JSON-RPC，_handle_request 处理后以
    text/event-stream（SSE）返回 data: {...}，客户端据此按 id 解析。零新依赖。
    启动：python -m app.agent.mcp_server --http --port 8001
    """
    import asyncio
    if registry is None:
        from app.agent.tools import create_default_tools
        registry = create_default_tools()

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                req = json.loads(raw.decode("utf-8", "replace")) if raw else {}
            except json.JSONDecodeError:
                req = {"jsonrpc": JSONRPC_VERSION, "id": None, "method": "invalid"}
            resp = None
            if isinstance(req, dict):
                # 每个请求独立事件循环（测试靶机足够；生产可换 uvloop/单循环）
                resp = asyncio.run(_handle_request(req, registry))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Mcp-Session-Id", "http-session-demo")
            self.end_headers()
            if resp is not None:
                self.wfile.write(f"data: {json.dumps(resp, ensure_ascii=False)}\n\n".encode("utf-8"))

        def log_message(self, *a):
            pass

    srv = HTTPServer((host, port), _Handler)
    logger.info(f"[MCP] HTTP server 启动: http://{host}:{port}/mcp ，工具数={len(registry.get_tool_names())}")
    srv.serve_forever()


def main():
    import asyncio
    import argparse
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description="Huawei Cloud MCP Server（stdio / HTTP+SSE）")
    p.add_argument("--http", action="store_true", help="以 HTTP+SSE 模式启动（默认 stdio）")
    p.add_argument("--host", default="127.0.0.1", help="HTTP 模式监听地址")
    p.add_argument("--port", type=int, default=8001, help="HTTP 模式监听端口")
    args = p.parse_args()
    if args.http:
        serve_http(host=args.host, port=args.port)
    else:
        asyncio.run(serve_stdio())


if __name__ == "__main__":
    main()
