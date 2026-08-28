# -*- coding: utf-8 -*-
"""MCP 客户端（P2-3 拉伸项）。

通过 stdio JSON-RPC 2.0 连接外部 MCP Server，并把远端工具注册进本地 ToolRegistry，
使 Agent 可直接调用远端工具（与 app/agent/mcp_server.py 暴露的标准 MCP 互相对接）。

⚠️ 本文件为 git 对象损坏后，按 mcp_server.py 的 ToolRegistry 接口重建的骨架实现；
原实现已丢失，且全仓当前无任何 import 此文件的代码（属可选拉伸项）。
若你有更完整的版本请直接覆盖。register_remote_tools 当前仅做结构占位，
不会在没有任何已配置 MCP Server 时被调用，无副作用。
"""
import json
import logging
import subprocess
import asyncio
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class MCPClient:
    """单个 stdio MCP Server 的 JSON-RPC 2.0 客户端。"""

    def __init__(self, command: List[str], timeout: float = 30.0, label: str = ""):
        self.command = command
        self.timeout = timeout
        self.label = label or " ".join(command)
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._req_id = 0
        self._tools: List[Dict[str, Any]] = []

    async def connect(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        await self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "huawei-cloud-agent", "version": "1.0"},
        })
        self._tools = await self.list_tools()

    async def _rpc(self, method: str, params: Dict[str, Any], notify: bool = False) -> Dict[str, Any]:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("MCPClient 未连接")
        self._req_id += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": self._req_id}
        self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()
        if notify:
            return {}
        line = await self._proc.stdout.readline()
        if not line:
            return {}
        return json.loads(line.decode("utf-8"))

    async def list_tools(self) -> List[Dict[str, Any]]:
        resp = await self._rpc("tools/list", {})
        return resp.get("result", {}).get("tools", []) if resp else []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        resp = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        return resp.get("result")

    async def close(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
                await self._proc.wait()
            except Exception:
                pass
            self._proc = None


def register_remote_tools(tool_registry, servers: Optional[List[Dict[str, Any]]] = None) -> int:
    """把若干 MCP Server 暴露的工具注册进本地 ToolRegistry。

    servers: [{"command": [...], "label": "..."}, ...]
    返回成功注册的工具数。当前为骨架：未实际拉起子进程（避免无配置时副作用），
    真实实现应逐个 MCPClient.connect() 后把远端 tool schema 适配为本地 Tool 并 add 进 registry。
    """
    servers = servers or []
    logger.debug(f"[mcp_client] register_remote_tools 被调用，servers={len(servers)}")
    # TODO(原实现): 逐个 connect + 适配 schema + tool_registry.add(...)
    return 0
