# -*- coding: utf-8 -*-
"""P2-3 真实 MCP 客户端端到端验证（零外部依赖，用内置 mock MCP Server 对端）。

用法（项目根目录，任意 python3）：
    python tests/verify_p2_mcp_client.py

验证项：
  1. MCPClient 能拉起 stdio 子进程、完成 initialize 握手、跳过通知、tools/list、tools/call；
  2. register_remote_tools 把远端工具以 mcp__<label>__<tool> 前缀注册进本地 ToolRegistry；
  3. 远端工具 execute 用「原始名」调用 Server 并把结果规整为非 Error 文本；
  4. 重名/本地冲突自动跳过；关闭回收子进程。

说明：mcp_client.py 的 stdio 传输层为纯标准库，且不依赖 app 包；register_remote_tools
仅在注册时懒加载本地 Tool 基类。本测试通过 sys.modules 注入 FakeTool/FakeRegistry，
在无 chromadb/langchain 的本地环境即可完整验证逻辑（与部署环境注册路径一致）。
"""
import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------- 1) 内置 mock MCP Server（纯标准库，stdio JSON-RPC） ----------
MOCK_SERVER = r'''
import sys, json
def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()
TOOLS = [
    {"name": "echo", "description": "回显参数", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
    {"name": "add", "description": "两数相加", "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}},
]
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception:
        send({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})
        continue
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "mock", "version": "0.0.1"}}})
    elif method == "notifications/initialized":
        continue  # 通知：无响应
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "echo":
            text = "echo:" + str(args.get("text", ""))
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}], "isError": False}})
        elif name == "add":
            s = args.get("a", 0) + args.get("b", 0)
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": str(s)}], "isError": False}})
        else:
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": "unknown"}], "isError": True}})
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": rid, "result": {}})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": rid, "result": {}})
        break
'''


# ---------- 2) 注入 FakeTool / FakeRegistry，绕开 app 包（避免 chromadb） ----------
def _install_fakes():
    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = []
    sys.modules.setdefault("app", app_pkg)
    agent_pkg = types.ModuleType("app.agent")
    agent_pkg.__path__ = []
    sys.modules["app.agent"] = agent_pkg

    tools_mod = types.ModuleType("app.agent.tools")

    class FakeTool:
        def __init__(self, name, description, parameters, func):
            self.name = name
            self.description = description
            self.parameters = parameters
            self.func = func
        def to_prompt_desc(self):
            return f"- {self.name}: {self.description}"
        async def execute(self, **kwargs):
            return "local"

    tools_mod.Tool = FakeTool
    sys.modules["app.agent.tools"] = tools_mod

    # 加载 mcp_client.py（此时 app.agent 已是 stub，不会触发 __init__ 链）
    spec = importlib.util.spec_from_file_location(
        "app.agent.mcp_client", os.path.join(ROOT, "app", "agent", "mcp_client.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, FakeTool


class FakeRegistry:
    def __init__(self):
        self._d = {}
    def register(self, t):
        self._d[t.name] = t
    def get(self, n):
        return self._d.get(n)
    def get_tool_names(self):
        return list(self._d.keys())


async def _test_transport(client_cls, server_py):
    py = sys.executable
    client = client_cls(command=[py, server_py], label="mock")
    await client.connect()
    tools = client._tools
    assert any(t["name"] == "echo" for t in tools), "tools/list 未返回 echo"
    # call_tool 用原始名
    res = await client.call_tool("echo", {"text": "hi"})
    txt = client_cls.__module__  # placeholder
    # 解析结果
    assert res and res.get("content", [{}])[0].get("text") == "echo:hi", f"echo 调用结果异常: {res}"
    add_res = await client.call_tool("add", {"a": 2, "b": 3})
    assert add_res["content"][0]["text"] == "5", f"add 调用结果异常: {add_res}"
    await client.close()
    return tools


async def main():
    mcp_mod, FakeTool = _install_fakes()
    MCPClient = mcp_mod.MCPClient

    # 写 mock server 临时文件
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(MOCK_SERVER)
        server_py = f.name

    try:
        # 1) 传输层端到端
        tools = await _test_transport(MCPClient, server_py)
        print(f"[1] 传输层 OK：连接/握手/tools/list/tools/call 全部通过，远端工具 {len(tools)} 个")

        # 2) register_remote_tools：前缀 + 注册
        registry = FakeRegistry()
        # 先放一个本地工具 add（与远端 add 重名，验证跳过不覆盖）
        registry.register(FakeTool("add", "local add", {}, lambda **k: "local"))
        names = await mcp_mod.register_remote_tools(registry, [{"command": [sys.executable, server_py], "label": "mock"}])
        print(f"[2] 注册名: {names}")
        assert "mcp__mock__echo" in names, "echo 未以 mcp__mock__ 前缀注册"
        assert "mcp__mock__add" not in names, "与本地重名的 add 应被跳过"
        assert registry.get("add") is not None and registry.get("add").func is not None  # 本地未被覆盖
        assert len(mcp_mod._CLIENTS) == 1

        # 3) RemoteTool.execute：用原始名调 Server + 规整文本
        echo_tool = registry.get("mcp__mock__echo")
        out = await echo_tool.execute(text="hello")
        assert out == "echo:hello", f"远端 execute 结果异常: {out!r}"
        print(f"[3] 远端工具 execute 真实生效: {out!r}")

        # 4) 关闭回收
        await mcp_mod.shutdown_all()
        assert len(mcp_mod._CLIENTS) == 0
        print("[4] 子进程已回收")

        print("\n✅ P2-3 MCP 客户端真实实现验证通过")
        return 0
    finally:
        try:
            os.unlink(server_py)
        except OSError:
            pass


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
        sys.exit(rc)
    except AssertionError as e:
        print(f"\n❌ 断言失败: {e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
