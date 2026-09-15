"""P0 验证：自带 cost_calc MCP Server 真实 stdio 传输（子进程，纯 stdlib 可跑）。

启动 `python -m app.agent.mcp_server_cost_calc`，按 JSON-RPC 2.0 over stdio 走通：
  initialize → tools/list（应含 cost_calc / cost_reference_list）
  → tools/call cost_calc（真实计算月/年合计）
  → tools/call cost_reference_list
  → shutdown（子进程退出）
验证「项目能力 → MCP → 可被 client 消费」闭环的前半段（Server 侧）。
"""
import json
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 直接以脚本形式启动（纯 stdlib，绕过 app 包 __init__ 的重链 import，本地环境无 httpx/chromadb）。
SERVER_SCRIPT = os.path.join(PROJECT_ROOT, "app", "agent", "mcp_server_cost_calc.py")


def _rpc(req_id, method, params=None):
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}


def _send(proc, req):
    proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def _read(proc):
    line = proc.stdout.readline()
    if not line:
        return None
    return json.loads(line)


def main():
    proc = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        # 1) initialize
        _send(proc, _rpc(1, "initialize", {"protocolVersion": "2024-11-05"}))
        init_resp = _read(proc)
        assert init_resp and init_resp.get("id") == 1, f"initialize 无响应: {init_resp}"
        assert init_resp["result"]["serverInfo"]["name"] == "huawei-cloud-cost-calc"

        # 2) tools/list
        _send(proc, _rpc(2, "tools/list"))
        list_resp = _read(proc)
        tools = list_resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "cost_calc" in names, f"缺少 cost_calc: {names}"
        assert "cost_reference_list" in names, f"缺少 cost_reference_list: {names}"
        # 校验 cost_calc 的 inputSchema 含 items 必填
        cost_schema = next(t for t in tools if t["name"] == "cost_calc")["inputSchema"]
        assert "items" in cost_schema["properties"]
        assert "items" in cost_schema["required"]

        # 3) tools/call cost_calc（真实计算：2台ECS + 500GB OBS，1 月）
        _send(proc, _rpc(3, "tools/call", {
            "name": "cost_calc",
            "arguments": {
                "items": [
                    {"sku": "ecs.s6.large.2", "qty": 2, "months": 1},
                    {"sku": "obs.standard", "qty": 500, "months": 1},
                ]
            },
        }))
        call_resp = _read(proc)
        text = call_resp["result"]["content"][0]["text"]
        assert call_resp["result"]["isError"] is False, f"cost_calc 报错: {text}"
        # 月合计 = 160*2 + 0.099*500 = 320 + 49.5 = 369.50
        assert "¥369.50" in text, f"月合计计算错误: {text}"
        assert "年" in text and "4,434.00" in text, f"年合计计算错误: {text}"

        # 4) tools/call cost_calc（未知 SKU → 应 isError=true，不崩溃）
        _send(proc, _rpc(4, "tools/call", {
            "name": "cost_calc",
            "arguments": {"items": [{"sku": "not_a_sku", "qty": 1}]},
        }))
        bad_resp = _read(proc)
        assert bad_resp["result"]["isError"] is True, "未知 SKU 应标记错误但不崩溃"
        assert "未知 SKU" in bad_resp["result"]["content"][0]["text"]

        # 5) tools/call cost_reference_list
        _send(proc, _rpc(5, "tools/call", {"name": "cost_reference_list", "arguments": {}}))
        ref_resp = _read(proc)
        ref_text = ref_resp["result"]["content"][0]["text"]
        assert "ecs.s6.large.2" in ref_text and "SKU" in ref_text

        # 6) shutdown
        _send(proc, _rpc(6, "shutdown"))
        _read(proc)
    finally:
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        proc.wait(timeout=10)

    print("PASS: verify_p0_cost_calc_server — cost_calc MCP Server 端到端（stdio JSON-RPC）通过")


if __name__ == "__main__":
    main()
