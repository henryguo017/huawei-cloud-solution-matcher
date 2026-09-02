# -*- coding: utf-8 -*-
"""P1-C 工具发现验证：MCP_SERVERS 环境变量与 data/mcp_servers.json manifest 合并。

- manifest 不存在/非法 → 忽略（降级）
- env 优先；manifest 中与 env 不重复的条目追加
- 同 key（url/command）去重

运行：python tests/verify_p1_discovery.py   （从项目根目录）
"""
import os
import sys
import json
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load_standalone(rel_path, name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, rel_path)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mcp_client = _load_standalone("app/agent/mcp_client.py", "mcp_client_standalone")
load_mcp_servers = mcp_client.load_mcp_servers
_project_root = mcp_client._project_root

MANIFEST = [
    {"url": "http://host/mcp", "label": "m"},
    {"command": ["python", "-m", "app.agent.mcp_server"], "label": "self"},
]
MANIFEST_PATH = os.path.join(_project_root(), "data", "mcp_servers.json")


def main():
    old = os.environ.get("MCP_SERVERS")
    try:
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(MANIFEST, f)

        # 1) env 为空 → 仅 manifest（2 项）
        os.environ.pop("MCP_SERVERS", None)
        merged = load_mcp_servers()
        assert len(merged) == 2, f"manifest 应返回 2 项，实际 {len(merged)}"
        print("[OK] manifest 独立生效（2 项）")

        # 2) env 含 manifest 没有的 → env(1) + manifest(2) = 3
        os.environ["MCP_SERVERS"] = '[{"url":"http://env/mcp","label":"env"}]'
        merged = load_mcp_servers()
        assert len(merged) == 3, f"env+manifest 应 3 项，实际 {len(merged)}"
        print("[OK] env 与 manifest 合并（3 项）")

        # 3) env 含与 manifest 同 key → 去重仍为 2
        os.environ["MCP_SERVERS"] = '[{"url":"http://host/mcp","label":"m"}]'
        merged = load_mcp_servers()
        assert len(merged) == 2, f"同 key 应去重为 2，实际 {len(merged)}"
        print("[OK] 同 key 去重（仍为 2 项）")
    finally:
        if os.path.exists(MANIFEST_PATH):
            os.remove(MANIFEST_PATH)
        if old is None:
            os.environ.pop("MCP_SERVERS", None)
        else:
            os.environ["MCP_SERVERS"] = old

    print("\n✅ P1-C 工具发现验证通过")


if __name__ == "__main__":
    main()
