# -*- coding: utf-8 -*-
"""聚焦重测（E 修复后）：
1) 账户类 7 题（idx 11/17/19/20/21/51/52）：真实从后端取数，替换旧套话回答。
2) 回归观察题（watch）：重新跑若干可能受「账户正则放宽」影响的非账户题，
   确认未误判为 account，路由与预期一致。
全部使用测试账户 guo（id=3）。
"""
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

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "agent_50q_results.jsonl")

TEST_USER_ID = 3
TEST_USER_INFO = {
    "id": 3, "username": "guo", "email": "3324507839@qq.com",
    "role": "user", "status": "active",
    "created_at": "2026-05-30 16:12:32", "last_login": "2026-08-23 07:39:53",
}

# (idx, 分类, 问题, 期望路由)
ACCOUNT_Q = [
    (11, "平台使用", "怎么查看我之前生成过的方案", "account"),
    (17, "平台使用", "我的成就是怎么解锁的", "account"),
    (19, "账户个人", "我的成就是什么", "account"),
    (20, "账户个人", "我的收藏在哪里看", "account"),
    (21, "账户个人", "我的历史方案能导出吗", "account"),
    (51, "账户个人", "我的账户资料和登录信息是什么", "account"),
    (52, "账户个人", "给我看看我这个账号的整体概况", "account"),
]

# 回归观察：重新跑、确认未受账户正则放宽影响而误判为 account
WATCH_IDX = [10, 15, 22, 1, 7, 5, 13, 33]


def extract_intent(logs):
    for e in logs:
        m = e.get("message", "")
        if "[INTENT]" in m:
            return m.split("[INTENT]")[-1].strip()
    return "unknown"


def behavior_of(intent, res):
    if res.get("paused"):
        return "澄清追问"
    if intent == "greeting":
        return "轻量问候回复"
    if intent == "account":
        return "账户真实数据回复"
    if intent == "general":
        return "通用回答"
    if intent in ("solution", "competitor"):
        return "方案/对比生成"
    return "其他"


async def run_one(agent, idx, cat, q, exp):
    sid = f"re_{idx}_{int(time.time()*1000)}"
    t0 = time.time()
    try:
        res = await asyncio.wait_for(
            agent.run(q, session_id=sid, user_id=TEST_USER_ID, user_info=TEST_USER_INFO),
            timeout=240.0,
        )
    except BaseException as e:
        res = {"answer": "", "success": False, "steps": 0, "logs": [],
               "paused": False, "questions": [], "tool_calls": [],
               "error": f"{type(e).__name__}: {e}"}
    wall = round(time.time() - t0, 1)
    intent = extract_intent(res.get("logs", []))
    rec = {
        "idx": idx, "category": cat, "question": q, "expected": exp,
        "intent": intent, "behavior": behavior_of(intent, res),
        "success": res.get("success", False), "paused": res.get("paused", False),
        "steps": res.get("steps", 0), "wall": wall,
        "answer": res.get("answer", ""),
        "clarify_questions": res.get("questions", []),
        "tool_calls": [tc.get("tool") for tc in res.get("tool_calls", [])],
        "error": res.get("error", ""),
    }
    flag = "OK" if intent == exp else "DIFF"
    print(f"[{idx}] {cat} | exp={exp} got={intent} | {rec['behavior']} | "
          f"steps={rec['steps']} wall={wall}s | ans_len={len(rec['answer'])} | {flag}", flush=True)
    return rec


async def main():
    agent = get_agent(max_steps=6, timeout=180.0)

    # 载入已有记录（用于 watch 取原问题文本）
    old = {}
    if os.path.exists(SRC):
        with open(SRC, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    old[r["idx"]] = r
                except Exception:
                    pass

    new_records = []
    for (idx, cat, q, exp) in ACCOUNT_Q:
        new_records.append(await run_one(agent, idx, cat, q, exp))

    # watch：用原问题文本重跑
    for idx in WATCH_IDX:
        if idx not in old:
            print(f"[watch {idx}] 原记录缺失，跳过", flush=True)
            continue
        o = old[idx]
        new_records.append(await run_one(agent, idx, o["category"], o["question"], o["expected"]))

    for rec in new_records:
        old[rec["idx"]] = rec
    rows = [old[k] for k in sorted(old.keys())]
    with open(SRC, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"MERGED {len(rows)} records into {SRC}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
