# -*- coding: utf-8 -*-
"""P1-1 验证：Plan 面板实时点亮（plan_index ↔ 工具调用 映射）

分两部分：
  A. 单元测试（不依赖 LLM）：PLAN_STEP_TOOL_MAP 步数对齐 + _tool_to_plan_index 映射正确。
  B. 流式验证（依赖运行中的后端 localhost:8000）：
     - plan 事件带 plan_status 且初始全 pending，步数 == 映射表长度；
     - tool_start/tool_end 携带 plan_index（0..n-1），且能观察到 running→done 进度；
     - final 事件 plan_index 指向最后一步（综合生成步），result 中 plan_status 末项 done。
"""
import os, sys, json, asyncio, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

BASE = "http://localhost:8000"


def unit_checks():
    print("=== A. 映射单元测试（无 LLM） ===")
    from app.agent.agent import get_agent
    h = get_agent().harness
    mp = h.PLAN_STEP_TOOL_MAP
    # 步数对齐
    assert len(mp["solution"]) == 3, f"solution 映射步数应为 3，实际 {len(mp['solution'])}"
    assert len(mp["competitor"]) == 2, f"competitor 映射步数应为 2，实际 {len(mp['competitor'])}"
    assert len(mp["knowledge_q"]) == 2, f"knowledge_q 映射步数应为 2，实际 {len(mp['knowledge_q'])}"
    assert len(mp["file_ops"]) == 3, f"file_ops 映射步数应为 3，实际 {len(mp['file_ops'])}"
    # 末步为空列表（综合生成步，不绑定具体工具）
    assert mp["solution"][-1] == [], "solution 末步应为综合生成步（空列表）"
    assert mp["competitor"][-1] == [], "competitor 末步应为综合生成步（空列表）"

    # _tool_to_plan_index 映射正确（置全 pending 以绕过 done 守卫）
    h._plan_status = ["pending"] * 3
    assert h._tool_to_plan_index("analyze_demand", "solution") == 0, "analyze_demand 应映射 step0"
    assert h._tool_to_plan_index("search_kb", "solution") == 1, "search_kb 应映射 step1"
    assert h._tool_to_plan_index("search_competitor", "solution") == 1, "search_competitor 应映射 step1"
    # 综合生成步（final_answer）无具体工具 → -1
    assert h._tool_to_plan_index("generate_doc", "solution") == -1, "generate_doc 不应归属具体 plan 步"
    # 无关工具 → -1
    assert h._tool_to_plan_index("web_search", "solution") == -1, "web_search 默认不应点亮 plan 步"
    # done 守卫：已 done 的步不再映射
    h._plan_status = ["done", "pending", "pending"]
    assert h._tool_to_plan_index("analyze_demand", "solution") == -1, "已 done 步不应再次映射"
    print("  ✅ PLAN_STEP_TOOL_MAP 步数对齐 + _tool_to_plan_index 映射全部正确")
    return True


async def stream_chat(session_id, message, token, timeout=300):
    H = {"Authorization": f"Bearer {token}"}
    async with __import__("httpx").AsyncClient(timeout=timeout) as c:
        async with c.stream("POST", f"{BASE}/api/agent/chat",
                            headers={**H, "Content-Type": "application/json"},
                            json={"message": message, "session_id": session_id}) as r:
            evt = ""
            out = {
                "plan": [], "plan_status_init": [], "tool_idx": [], "final_idx": None,
                "result_plan_status": None, "success": False, "answer": "", "events": [],
            }
            async for line in r.aiter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    evt = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    try:
                        d = json.loads(line[5:])
                    except Exception:
                        continue
                    out["events"].append((evt, d))
                    if evt == "plan":
                        out["plan"] = d.get("steps", [])
                        out["plan_status_init"] = d.get("plan_status", [])
                    elif evt in ("tool_start", "tool_end"):
                        if isinstance(d.get("plan_index"), int) and d["plan_index"] >= 0:
                            out["tool_idx"].append((evt, d["plan_index"]))
                    elif evt == "final":
                        out["final_idx"] = d.get("plan_index")
                    elif evt == "result":
                        out["success"] = d.get("success", False)
                        out["answer"] = d.get("answer") or ""
                        out["result_plan_status"] = d.get("plan_status")
    return out


async def stream_checks():
    print("\n=== B. 流式验证（localhost:8000） ===")
    from app.services.auth_service import AuthService
    from app.utils.auth_utils import create_access_token
    user = AuthService.get_user_by_id(3)
    TOKEN, _ = create_access_token(user["id"], user["username"], user.get("role", "user"), user.get("token_version", 1))

    # LLM 非确定性：偶尔会直接 Final Answer 不走工具，故最多重试 3 次直到观察到 tool plan_index 点亮
    res = None
    for attempt in range(1, 4):
        sid = f"p1_plan_{attempt}"
        print(f"  [尝试 {attempt}] Q: 帮我在制造业客户做设备预测性维护方案匹配")
        t0 = time.time()
        r = await stream_chat(sid, "帮我在制造业客户做设备预测性维护方案匹配", TOKEN)
        wall = round(time.time() - t0, 1)
        plan = r["plan"]
        print(f"    plan 步数={len(plan)} | plan_status_init={r['plan_status_init']} | tool_idx={r['tool_idx']} | wall={wall}s")
        if r["tool_idx"]:
            res = r
            break
        print(f"    ⚠️ 本次未走工具（LLM 直接收尾），重试…")
    assert res, "❌ 3 次尝试均未观察到工具调用，无法验证 plan_index 点亮"
    plan = res["plan"]

    # 判定
    assert plan, "❌ 无 plan 事件"
    assert len(plan) == 3, f"❌ solution plan 应为 3 步，实际 {len(plan)}"
    assert res["plan_status_init"] == ["pending"] * 3, f"❌ 初始 plan_status 应全 pending，实际 {res['plan_status_init']}"

    # tool_start/tool_end 携带 plan_index 且范围正确
    idxs = [i for _, i in res["tool_idx"]]
    assert idxs, "❌ 未观察到任何带 plan_index 的工具事件"
    assert all(0 <= i < len(plan) for i in idxs), f"❌ plan_index 越界: {idxs}"
    print(f"  ✅ 工具事件 plan_index 序列: {res['tool_idx']}")

    # running→done 进度：同一 plan 步先 tool_start(running) 后 tool_end(done)
    seen_running = set()
    done_steps = set()
    for evt, i in res["tool_idx"]:
        if evt == "tool_start":
            seen_running.add(i)
        else:
            done_steps.add(i)
    assert seen_running, "❌ 未观察到 running 点亮"
    # 被 done 的步必须曾 running（顺序正确）
    assert done_steps.issubset(seen_running | {len(plan) - 1}), \
        f"❌ 存在未先 running 就被 done 的步: done={done_steps} running={seen_running}"
    print(f"  ✅ running 步={sorted(seen_running)} | done 步={sorted(done_steps)}（进度正确）")

    # final 指向最后一步（综合生成步）
    assert isinstance(res["final_idx"], int) and res["final_idx"] == len(plan) - 1, \
        f"❌ final plan_index 应指向最后一步，实际 {res['final_idx']}"
    print(f"  ✅ final plan_index={res['final_idx']}（综合生成步）")

    # result 中 plan_status 末项为 done（全链路点亮收尾）
    rps = res["result_plan_status"]
    assert isinstance(rps, list) and len(rps) == len(plan), f"❌ result.plan_status 异常: {rps}"
    assert rps[-1] == "done", f"❌ result 末步应为 done，实际 {rps}"
    print(f"  ✅ result.plan_status={rps}（末步 done，全链路点亮）")
    print("\nP1-1 Plan 实时点亮验证全部通过 ✅")


async def main():
    unit_checks()
    await stream_checks()


if __name__ == "__main__":
    asyncio.run(main())
