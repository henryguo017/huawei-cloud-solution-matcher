"""P2-3 验证：最小 MCP Server（stdlib JSON-RPC over stdio）

断言：
  1. initialize → protocolVersion + serverInfo
  2. tools/list → ≥7 个工具，inputSchema 含 parameters（analyze_demand 必在）
  3. tools/call analyze_demand → content 非空文本
  4. tools/call 未知工具 → error -32602
  5. 子进程 stdio 通道：python -m app.agent.mcp_server 可启动并响应 initialize
"""
import sys, os, json, asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("OMP_NUM_THREADS", "1")


async def main():
    print("=== P2-3 MCP Server 验证 ===")

    # 0. 子进程 stdio 通道（真实 MCP 传输）— 必须放在任何 app.* import 之前：
    #    父进程加载 agent 模块树（含 embedding DLL）后再 spawn 子进程会触发 Windows
    #    0xC0000005 崩溃（DLL 加载器冲突）；干净环境完全正常。
    print("  [1/5] 子进程 stdio 握手验证...")
    import subprocess as sync_subprocess
    py = sys.executable
    req_line = json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize"}) + "\n"
    completed = sync_subprocess.run(
        [py, "-m", "app.agent.mcp_server"],
        cwd=ROOT, input=req_line.encode("utf-8"),
        stdout=sync_subprocess.PIPE, stderr=sync_subprocess.PIPE, timeout=30,
    )
    resp = None
    for raw in completed.stdout.decode("utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            resp = json.loads(raw)
            break
        except json.JSONDecodeError:
            continue
    assert resp and resp.get("result", {}).get("serverInfo", {}).get("name") == "huawei-cloud-solution-agent", \
        f"❌ 子进程握手失败 rc={completed.returncode} stderr={completed.stderr.decode('utf-8','replace')[:200]}"
    print("  ✅ 子进程 stdio 通道正常（initialize 握手成功）")

    from app.agent.tools import create_default_tools
    from app.agent.mcp_server import _handle_request

    registry = create_default_tools()

    # 1. initialize
    r1 = await _handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, registry)
    assert r1.get("result", {}).get("serverInfo", {}).get("name"), f"❌ initialize 异常: {r1}"
    print(f"  ✅ initialize -> {r1['result']['serverInfo']['name']} v{r1['result']['serverInfo']['version']}")

    # 2. tools/list
    r2 = await _handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, registry)
    tools = r2["result"]["tools"]
    names = [t["name"] for t in tools]
    print(f"  ✅ tools/list -> {len(tools)} 个工具: {names}")
    assert len(tools) >= 7, f"❌ 工具数应 ≥7，实际 {len(tools)}"
    assert "analyze_demand" in names and "search_kb" in names and "generate_doc" in names, "❌ 缺核心工具"
    ad = next(t for t in tools if t["name"] == "analyze_demand")
    assert "inputSchema" in ad and "properties" in ad["inputSchema"], "❌ inputSchema 应为 JSON Schema"
    assert "raw_input" in ad["inputSchema"]["properties"], "❌ analyze_demand 应含 raw_input 参数"

    # 3. tools/call
    r3 = await _handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                "params": {"name": "analyze_demand", "arguments": {"raw_input": "制造业预测性维护"}}}, registry)
    content = r3["result"]["content"]
    texts = "".join(c.get("text", "") for c in content)
    print(f"  ✅ tools/call analyze_demand -> {texts[:60]}...")
    assert texts.strip(), "❌ 工具返回为空"
    assert r3["result"]["isError"] is False, "❌ 不应为错误"

    # 4. 未知工具
    r4 = await _handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                "params": {"name": "no_such_tool", "arguments": {}}}, registry)
    assert "error" in r4 and r4["error"]["code"] == -32602, f"❌ 未知工具应报 -32602: {r4}"
    print("  ✅ 未知工具 → error -32602")

    print("\nP2-3 MCP Server 验证全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
