# -*- coding: utf-8 -*-
"""FC 灰度门禁 · A10 压缩保真验证（长任务真触发压缩，2026-09-15）

指标定义（docs/agent-architecture-fc-2026-09-11.md §6 / S4 缺口清单）：
    A10 压缩保真 = 触发压缩后仍成功完成任务的占比，达标线 ≥90%。
S4 现状：30 例对照中压缩次数全为 0（单请求 token 远低于 0.75×64000）→
压缩路径只有离线单测，无真实运行证据。

做法：把 AGENT_CONTEXT_WINDOW 调到 3600（压缩阈值 ≈2700 估算 token），
给一个多阶段任务（两次独立 KB 检索 + 整合成稿）。KB 检索结果体量足以在
数轮内冲破阈值 → 触发 ≥2 次真实压缩。判定「压缩后任务继续跑完」：
  ① trace.compactions ≥ 2；
  ② stopped_by == "model"（模型自主收敛，不是宿主熔断）；
  ③ 计划闭合（plan_open_at_final == 0）；
  ④ 终稿非缩水（≥300 字）。

运行条件：DEEPSEEK_API_KEY + KB 可用。预期耗时 2-5 分钟。
输出：逐项断言 + JSON 证据；全部满足退出码 0，否则 1。
"""
import asyncio
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

# 必须先于 app.config 导入设置（config 在 import 时读 env）；
# 先赋值再 load_dotenv(override=False)，本地 .env 不会覆盖本值。
os.environ["AGENT_CONTEXT_WINDOW"] = "3600"
os.environ.setdefault("AGENT_COMPACT_KEEP_TURNS", "3")

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(ROOT, '.env'))

if not os.getenv("DEEPSEEK_API_KEY"):
    print("缺少 DEEPSEEK_API_KEY（.env）——本脚本是真 API E2E。")
    sys.exit(2)

from app.config import AGENT_CONTEXT_WINDOW  # noqa: E402  # 确认生效值
from app.agent.harness import AgentHarness  # noqa: E402
from app.agent.memory import ConversationMemory  # noqa: E402
from app.agent.tools import create_default_tools  # noqa: E402

PERMS = {"generate_doc": "allow", "web_search": "allow",
         "web_extract": "allow", "run_python": "allow"}

TASK = (
    "请分三个阶段完成一份制造业上云对比材料："
    "第一阶段，检索知识库中制造业数字化转型方案的核心要点；"
    "第二阶段，检索知识库中政务云或工业互联网方案的核心要点；"
    "第三阶段，把两次检索结果整合成一份对比稿，包含"
    "「业务场景对比」「技术架构对比」「实施路径对比」三个章节，每章 120 字以上。"
)


async def main() -> int:
    print(f"AGENT_CONTEXT_WINDOW 生效值 = {AGENT_CONTEXT_WINDOW}"
          f"（压缩阈值 ≈{int(AGENT_CONTEXT_WINDOW * 0.75)} 估算 token）")
    h = AgentHarness(create_default_tools(), ConversationMemory(), verbose=False)
    t0 = asyncio.get_event_loop().time()
    result = await asyncio.wait_for(
        h.run(TASK, session_id="a10_compaction", runtime="fc", autonomy="high",
              tool_permissions=PERMS, user_id=0),
        timeout=900,
    )
    wall = asyncio.get_event_loop().time() - t0
    meta = getattr(h, "_fc_meta", None) or {}
    answer = result.get("answer") or ""

    checks = [
        ("compactions ≥ 2", int(meta.get("compactions", 0)) >= 2,
         f"实际 {meta.get('compactions')}"),
        ("stopped_by == model（自主收敛）", meta.get("stopped_by") == "model",
         f"实际 {meta.get('stopped_by')}"),
        ("计划闭合（plan_open_at_final == 0）",
         int(meta.get("plan_open_at_final", -1)) == 0,
         f"实际 {meta.get('plan_open_at_final')}"),
        ("终稿非缩水（≥300 字）", len(answer) >= 300, f"实际 {len(answer)} 字"),
        ("任务成功", bool(result.get("success")),
         f"success={result.get('success')}"),
    ]

    print(f"\n耗时 {wall:.0f}s，轮次 {meta.get('turns')}，"
          f"计划 {meta.get('plan_steps')} 步")
    print("=" * 64)
    fails = 0
    for name, ok, actual in checks:
        if not ok:
            fails += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name}（{actual}）")
    print("=" * 64)
    print("终稿开头:", answer[:150].replace("\n", " "))

    a10 = 1.0 if fails == 0 else 0.0
    print("\n证据 JSON:", json.dumps(
        dict(metric="A10", rate=a10, compactions=meta.get("compactions"),
             stopped_by=meta.get("stopped_by"),
             plan_open_at_final=meta.get("plan_open_at_final"),
             turns=meta.get("turns"), wall=round(wall),
             answer_len=len(answer), window=int(AGENT_CONTEXT_WINDOW),
             date="2026-09-15"), ensure_ascii=False))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
