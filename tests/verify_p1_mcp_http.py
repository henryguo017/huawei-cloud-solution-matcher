# -*- coding: utf-8 -*-
"""P1-B MCP HTTP+SSE 传输验证（零外部网络 / 零重依赖）。

用真实的 mcp_server.serve_http（SSE 响应）作靶机，以真实的 MCPHttpClient 连过去：
  - initialize 握手 + tools/list 返回工具清单
  - tools/call 调通并返回 content
同时验证 _load_servers_from_config 能解析 url 形态的 MCP_SERVERS。

运行：python tests/verify_p1_mcp_http.py   （从项目根目录）
"""
import os
import sys
import json
import time
import socket
import asyncio
import threading
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load_standalone(rel_path, name):
    """按文件路径加载模块，绕过 app.agent 包 __init__（避免拉起 httpx 等重依赖）。

    mcp_server.py / mcp_client.py 仅在函数内懒加载 app.agent.tools，本测试不触发那些路径。
    """
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, rel_path)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mcp_server = _load_standalone("app/agent/mcp_server.py", "mcp_server_standalone")
_mcp_client = _load_standalone("app/agent/mcp_client.py", "mcp_client_standalone")
MCPHttpClient = _mcp_client.MCPHttpClient
_load_servers_from_config = _mcp_client._load_servers_from_config


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = f"fake {name}"
        self.parameters = {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, **kwargs):
        return f"echo:{kwargs.get('text', '')}"


class _FakeRegistry:
    def __init__(self):
        self._tools = [_FakeTool("echo"), _FakeTool("ping")]

    def list_tools(self):
        return self._tools

    def get(self, name):
        for t in self._tools:
            if t.name == name:
                return t
        return None

    def get_tool_names(self):
        return [t.name for t in self._tools]


def main():
    # 1) 配置解析：url 形态应被识别
    cfg = _load_servers_from_config(
        '[{"url":"http://localhost:9000/mcp","label":"remote"},'
        '{"command":["python","-m","app.agent.mcp_server"],"label":"self"}]'
    )
    assert any(c.get("url") for c in cfg), "MCP_SERVERS url 形态未被解析"
    assert any(c.get("command") for c in cfg), "MCP_SERVERS command 形态未被解析"
    print(f"[OK] _load_servers_from_config 解析 url+command 共 {len(cfg)} 项")

    # 2) 起真实 HTTP 靶机（SSE 响应）
    port = _free_port()
    t = threading.Thread(
        target=lambda: mcp_server.serve_http(registry=_FakeRegistry(), host="127.0.0.1", port=port),
        daemon=True,
    )
    t.start()
    time.sleep(0.6)

    async def run():
        c = MCPHttpClient(url=f"http://127.0.0.1:{port}/mcp", label="self")
        await c.connect()
        assert len(c._tools) == 2, f"期望 2 个工具，实际 {len(c._tools)}"
        res = await c.call_tool("echo", {"text": "hi"})
        assert res["content"][0]["text"] == "echo:hi", f"call_tool 返回异常: {res}"
        await c.close()
        return c._tools

    tools = asyncio.run(run())
    names = [x["name"] for x in tools]
    print(f"[OK] HTTP+SSE 传输：list_tools 返回 {names}")
    print(f"[OK] tools/call echo 返回 'echo:hi'（SSE 解析正确）")

    print("\n✅ P1-B MCP HTTP+SSE 验证通过")


if __name__ == "__main__":
    main()
