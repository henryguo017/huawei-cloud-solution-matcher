# -*- coding: utf-8 -*-
"""定向重跑指定 idx（覆盖 jsonl 中对应行），其余题目保持不动。"""
import asyncio
import os
import re
import sys
import json
import time

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import asyncio as _a
async def _sync_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)
_a.to_thread = _sync_to_thread

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.agent import get_agent

TARGETS = [3, 4, 10, 15, 16, 22, 33]

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_50q_results.jsonl")


def extract_intent(logs):
    for e in logs or []:
        msg = e.get("message", "")
        if "[INTENT]" in msg:
            m = re.search(r"intent['\"]:\s*['\"](\w+)['\"]", msg)
            if m:
                return m.group(1)
    return "unknown"


def behavior_of(intent, res):
    if res.get("paused"):
        return "澄清追问(Clarify)"
    if intent == "greeting":
        return "轻量问候回复"
    if intent == "account":
        return "账户指路回复"
    if intent == "general":
        return "通用问答(LLM直答)"
    if intent in ("solution", "competitor"):
        if res.get("success"):
            return "方案/对比终稿(增强管线)"
        return "兜底/不完全回答"
    return "其他"


async def main():
    agent = get_agent(max_steps=6, timeout=180.0)
    # 读现有
    by_idx = {}
    if os.path.exists(SRC):
        with open(SRC, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                by_idx[r["idx"]] = r

    # 题目表（与 agent_50q.QUESTIONS 一致）
    from tests.agent_50q import QUESTIONS

    for i, (cat, q, exp) in enumerate(QUESTIONS):
        idx = i + 1
        if idx not in TARGETS:
            continue
        sid = f"re{i}_{int(time.time()*1000)}"
        t0 = time.time()
        try:
            res = await asyncio.wait_for(agent.run(q, session_id=sid), timeout=480.0)
        except asyncio.TimeoutError:
            res = {"answer": "", "success": False, "steps": 0, "logs": [], "paused": False,
                   "questions": [], "tool_calls": [], "error": "TimeoutError(>480s)"}
        except BaseException as e:
            res = {"answer": "", "success": False, "steps": 0, "logs": [], "paused": False,
                   "questions": [], "tool_calls": [], "error": f"{type(e).__name__}: {e}"}
        wall = round(time.time() - t0, 1)
        intent = extract_intent(res.get("logs", []))
        behavior = behavior_of(intent, res)
        rec = {
            "idx": idx, "category": cat, "question": q, "expected": exp,
            "intent": intent, "behavior": behavior,
            "success": res.get("success", False), "paused": res.get("paused", False),
            "steps": res.get("steps", 0), "wall": wall,
            "answer": res.get("answer", ""),
            "clarify_questions": res.get("questions", []),
            "tool_calls": [tc.get("tool") for tc in res.get("tool_calls", [])],
            "error": res.get("error", ""),
        }
        by_idx[idx] = rec
        status = "OK" if intent == exp else "ROUTE_DIFF"
        print(f"[RE-RUN {idx}] {cat} | exp={exp} got={intent} | {behavior} | steps={rec['steps']} wall={wall}s | {status}", flush=True)
        await asyncio.sleep(1.0)

    # 写回（按 idx 排序）
    out = [by_idx[k] for k in sorted(by_idx.keys())]
    with open(SRC, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"REWRITTEN {len(out)} records", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
