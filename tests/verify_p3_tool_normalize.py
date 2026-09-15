"""
P3 工具参数归一化单元测试（无 LLM / 无 KB，秒级）。

验证 Tool.execute 在分发前能吸收 LLM 偶发的参数名漂移：
- search_competitor 收到 query（应为 competitor）
- list_dir 收到 path（应为 dir）
- search_kb 收到 top_k/limit（函数无此参数，应被丢弃）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.tools import ToolRegistry, Tool  # noqa: E402


def main():
    # 用工厂函数重建默认工具集，读取已注册工具的归一化结果
    from app.agent.tools import create_default_tools  # type: ignore
    reg2 = create_default_tools()

    cases = [
        # (工具名, 输入 kwargs, 期望归一后包含的键与映射)
        ("search_competitor", {"query": "阿里云", "industry": "制造"},
         {"competitor": "阿里云", "industry": "制造"}),
        ("search_competitor", {"competitor": "AWS", "query": "azure"},
         {"competitor": "AWS"}),  # 显式 competitor 优先，query 别名不覆盖
        ("list_dir", {"path": "/data/x"}, {"dir": "/data/x"}),
        ("search_kb", {"query": "云迁移", "industry": "制造", "top_k": 5, "limit": 3},
         {"query": "云迁移", "industry": "制造"}),
        ("web_search", {"query": "华为云最新动态"}, {"query": "华为云最新动态"}),
        ("read_customer_file", {"path": "a.docx"}, {"path": "a.docx"}),  # path 本就是合法参数
    ]

    failed = 0
    for name, inp, expect in cases:
        tool = reg2.get(name)
        assert tool is not None, f"工具未注册: {name}"
        norm = tool._normalize_args(inp)
        ok = all(norm.get(k) == v for k, v in expect.items()) and all(
            k in norm for k in expect.keys()
        )
        # 额外断言：归一后所有键都在函数签名内（不会触发 TypeError）
        import inspect
        sig = inspect.signature(tool.func)
        accepted = set(sig.parameters.keys())
        no_unknown = all(k in accepted for k in norm.keys())
        status = "OK" if (ok and no_unknown) else "FAIL"
        if status == "FAIL":
            failed += 1
        print(f"  [{status}] {name}: {inp} -> {norm}")
        assert no_unknown, f"{name} 归一后出现签名外参数: {norm}"

    if failed:
        print(f"\n❌ 工具参数归一化失败 {failed} 例")
        sys.exit(1)
    print("\n✅ 工具参数归一化全部通过（LLM 参数漂移不再导致检索崩溃）")


if __name__ == "__main__":
    main()
