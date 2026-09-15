"""P0 验证：MCP 权限网关覆盖 mcp__* 工具（纯函数单测，不依赖 chromadb 重链）。

直接验证 permission_gate.resolve_tool_policy 的策略解析：
  - 远端工具（mcp__<label>__<tool>）默认 "ask"（human-in-the-loop）
  - 用户覆盖优先于 mcp__ 默认
  - 内置默认策略（generate_doc/read_customer_file=ask, web_search=allow）保持
  - 未知工具返回 None（放行）
"""
import importlib.util
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 直接按文件路径加载（纯 stdlib 模块），绕过 app 包 __init__ 的重链 import（本地无 httpx/chromadb）。
_spec = importlib.util.spec_from_file_location(
    "permission_gate_standalone",
    os.path.join(PROJECT_ROOT, "app", "agent", "permission_gate.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
resolve_tool_policy = _mod.resolve_tool_policy
MCP_TOOL_PREFIX = _mod.MCP_TOOL_PREFIX

DEFAULT_POLICY = {
    "generate_doc": "ask",
    "read_customer_file": "ask",
    "web_search": "allow",
}


def test_mcp_remote_default_ask():
    assert resolve_tool_policy("mcp__cost__cost_calc", None, DEFAULT_POLICY) == "ask"
    assert resolve_tool_policy("mcp__self__search_kb", None, DEFAULT_POLICY) == "ask"
    assert resolve_tool_policy("mcp__anything__x", {}, DEFAULT_POLICY) == "ask"
    assert MCP_TOOL_PREFIX == "mcp__"


def test_user_override_beats_mcp():
    overrides = {"mcp__cost__cost_calc": "allow"}
    # 用户显式允许 → 不再强制 ask
    assert resolve_tool_policy("mcp__cost__cost_calc", overrides, DEFAULT_POLICY) == "allow"
    overrides_deny = {"mcp__cost__cost_calc": "deny"}
    assert resolve_tool_policy("mcp__cost__cost_calc", overrides_deny, DEFAULT_POLICY) == "deny"


def test_local_default_policy_kept():
    assert resolve_tool_policy("generate_doc", None, DEFAULT_POLICY) == "ask"
    assert resolve_tool_policy("read_customer_file", None, DEFAULT_POLICY) == "ask"
    assert resolve_tool_policy("web_search", None, DEFAULT_POLICY) == "allow"
    # 用户覆盖本地工具
    assert resolve_tool_policy("web_search", {"web_search": "deny"}, DEFAULT_POLICY) == "deny"


def test_unknown_tool_no_policy():
    assert resolve_tool_policy("some_new_local_tool", None, DEFAULT_POLICY) is None
    assert resolve_tool_policy("analyze_demand", {}, DEFAULT_POLICY) is None


if __name__ == "__main__":
    test_mcp_remote_default_ask()
    test_user_override_beats_mcp()
    test_local_default_policy_kept()
    test_unknown_tool_no_policy()
    print("PASS: verify_p0_permission_gate — mcp__ 工具默认走 human-in-the-loop 确认")
