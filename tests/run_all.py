# -*- coding: utf-8 -*-
"""统一测试入口（2026-09-16）：分层跑测试，一套命令跑全部。

用法（项目根目录）：
    python tests/run_all.py                # 默认 smoke（离线冒烟，CI 安全）
    python tests/run_all.py --layer e2e    # 端到端（需 localhost:8000 已启动 + DEEPSEEK_API_KEY）
    python tests/run_all.py --layer all    # 先冒烟后端到端
    python tests/run_all.py --list         # 只列出用例不执行
    python tests/run_all.py --only verify_p2_mcp_client --layer smoke   # 单跑一个

分层原则：
- smoke：无 LLM / 无服务器 / 无 KB 依赖（LLM in-proc 桩掉），任何机器秒级~分钟级跑完，
  GitHub Actions 每次 push 自动执行；
- e2e：走真实 /api/agent/chat 流式链路（需服务已启动），本地发布前 / ECS 部署后手动跑。

退出码：全部通过 = 0；任一失败 = 1（CI 据此卡门）。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SMOKE = [
    # (脚本名, 一句话说明)
    ("test_intent_coverage.py",        "意图路由 60 例（general/CRM/KB/导出/file_ops 边界）"),
    ("test_ppt_facts.py",              "PPT 客户数字提取（240台/OEE 进 PPT 回归锚点）"),
    ("verify_p3_tool_normalize.py",    "工具参数归一化（LLM 参数漂移防御）"),
    ("verify_vector_db_abstraction.py","vector_db 可插拔抽象（stub 级）"),
    ("verify_p2_mcp_client.py",        "MCP 客户端 stdio 握手/注册/调用（内置 mock server）"),
    ("verify_p3_parallel.py",          "只读工具并行执行（asyncio.gather）"),
    ("verify_p3_selfcheck.py",         "自检 Gate（5 维 rubric + 二次合成）"),
    ("verify_p3_replan.py",            "真反思-重规划（失败步重跑修复）"),
    ("verify_p1_reflexion.py",         "Reflexion 反思链"),
]

E2E = [
    ("verify_skill_packs.py",          "技能包挂载（需服务 + LLM）"),
    ("verify_p1_plan_step.py",         "两阶段 plan 驱动执行（需服务）"),
    ("verify_p2_plan_exec.py",         "两阶段执行断言（plan_index 单调/工具集）"),
    ("verify_p0_permission_gate.py",   "权限闸门（ask 弹窗链路）"),
    ("verify_export_formats.py",       "导出格式回归（Word/PPT/PDF）"),
    ("verify_fc_a8_error_injection.py","FC 门禁 A8 错误自愈率（≥6 例故障注入，需 key）"),
    ("verify_fc_a10_compaction.py",    "FC 门禁 A10 压缩保真（低窗口长任务，需 key）"),
]


def run_one(script: str) -> tuple:
    """跑单个测试脚本，返回 (通过?, 耗时秒)。"""
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    elapsed = time.time() - t0
    ok = proc.returncode == 0
    if not ok:
        tail = (proc.stdout or "")[-1500:]
        err = (proc.stderr or "")[-800:]
        print(f"  ── 失败输出（stdout 尾部）──\n{tail}")
        if err.strip():
            print(f"  ── stderr 尾部 ──\n{err}")
    return ok, elapsed


def run_layer(name: str, cases, fail_fast: bool, only: str = "") -> int:
    if only:
        cases = [c for c in cases if c[0] == only]
        if not cases:
            print(f"[{name}] 找不到用例: {only}")
            return 1
    print(f"\n{'=' * 62}\n[{name}] 共 {len(cases)} 项\n{'=' * 62}")
    failed = []
    for script, desc in cases:
        print(f"▶ {script}  — {desc}", flush=True)
        try:
            ok, elapsed = run_one(script)
        except subprocess.TimeoutExpired:
            ok, elapsed = False, 600.0
            print("  ── 超时（600s 上限）")
        mark = "PASS" if ok else "FAIL"
        print(f"  {mark}  ({elapsed:.1f}s)\n", flush=True)
        if not ok:
            failed.append(script)
            if fail_fast:
                print("fail-fast：停止后续用例")
                break
    total = len(cases) if not fail_fast else len(cases)
    print(f"[{name}] 完成：通过 {len(cases) - len(failed)}/{len(cases)}，失败 {len(failed)}")
    if failed:
        print("  失败清单：", ", ".join(failed))
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description="cloudsol 统一测试入口")
    ap.add_argument("--layer", choices=["smoke", "e2e", "all"], default="smoke")
    ap.add_argument("--fail-fast", action="store_true", help="首个失败即停止")
    ap.add_argument("--list", action="store_true", help="只列出用例")
    ap.add_argument("--only", default="", help="只跑指定脚本名")
    args = ap.parse_args()

    if args.list:
        for script, desc in SMOKE:
            print(f"[smoke] {script:<38} {desc}")
        for script, desc in E2E:
            print(f"[e2e]   {script:<38} {desc}")
        return 0

    rc = 0
    if args.layer in ("smoke", "all"):
        rc |= run_layer("smoke", SMOKE, args.fail_fast, args.only)
    if args.layer in ("e2e", "all"):
        rc |= run_layer("e2e", E2E, args.fail_fast, args.only)
    return rc


if __name__ == "__main__":
    sys.exit(main())
