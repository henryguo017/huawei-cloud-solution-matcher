# -*- coding: utf-8 -*-
"""P0 集成验证：真实 mcp_client ↔ 真实 cost_calc Server 的端到端 glue。

验证「项目能力 → MCP → Agent 可调用」闭环的真实链路：
  1. mcp_client 拉起真实的 app/agent/mcp_server_cost_calc.py（脚本形式，纯 stdlib）；
  2. register_remote_tools 把远端工具注册为 mcp__cost__cost_calc / mcp__cost__cost_reference_list；
  3. 远端工具 execute 真实返回成本测算文本（含月/年合计）。

用 sys.modules 注入 FakeTool/FakeRegistry 绕开 app 包重链（本地无 chromadb/langchain），
与部署环境注册路径一致。
"""
import asyncio
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_SCRIPT = os.path.join(ROOT, "app", "agent", "mcp_server_cost_calc.py")


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

    spec = importlib.util.spec_from_file_location(
        "app.agent.mcp_client", os.path.join(ROOT, "app", "agent", "mcp_client.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRegistry:
    def __init__(self):
        self._d = {}

    def register(self, t):
        self._d[t.name] = t

    def get(self, n):
        return self._d.get(n)

    def get_tool_names(self):
        return list(self._d.keys())


async def main():
    mcp_mod = _install_fakes()
    registry = FakeRegistry()
    servers = [{"command": [sys.executable, SERVER_SCRIPT], "label": "cost"}]
    names = await mcp_mod.register_remote_tools(registry, servers)
    print(f"[1] 注册名: {names}")
    assert "mcp__cost__cost_calc" in names, "cost_calc 未注册"
    assert "mcp__cost__cost_reference_list" in names, "cost_reference_list 未注册"

    # 执行远端工具（模拟 Agent 调用）：2台ECS + 500GB OBS，1 月
    tool = registry.get("mcp__cost__cost_calc")
    assert tool is not None
    out = await tool.execute(items=[
        {"sku": "ecs.s6.large.2", "qty": 2, "months": 1},
        {"sku": "obs.standard", "qty": 500, "months": 1},
    ])
    print(f"[2] cost_calc 返回（前 2 行）:\n" + "\n".join(out.splitlines()[:3]))
    assert "¥369.50" in out, f"月合计计算错误: {out}"
    assert "4,434.00" in out, f"年合计计算错误: {out}"

    # 未知 SKU 应返回 Error 文本
    err_out = await tool.execute(items=[{"sku": "no_such", "qty": 1}])
    assert err_out.startswith("Error:") or "未知 SKU" in err_out, f"未知 SKU 未报错: {err_out}"

    await mcp_mod.shutdown_all()
    assert len(mcp_mod._CLIENTS) == 0
    print("[3] 子进程已回收")
    print("\n✅ P0 集成验证通过：mcp_client 成功接入 cost_calc Server 并真实调用")
    return 0


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
