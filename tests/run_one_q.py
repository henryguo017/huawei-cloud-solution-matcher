# -*- coding: utf-8 -*-
"""单题驱动：在独立子进程内运行指定 idx 的题目，结果追加写入 agent_50q_results.jsonl。

设计目的：规避 Windows+Python 下 sentence-transformers/OMP 多线程推理的偶发段错误
（EXIT=139 会杀死整个进程）。每题独立进程，单题崩溃不影响其他题，调度器会重试。
"""
import os
import sys
import json
import time
import asyncio

# —— 必须在导入任何重型依赖（torch/sentence_transformers）之前设好线程限制 ——
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# numpy 2.x 兼容 shim（chromadb 0.4.24 用到旧别名 np.float_ 等）
import numpy as np
for _n, _v in [("float_", np.float64), ("int_", np.int64), ("uint", np.uint64),
               ("bool8", np.bool_), ("object_", object), ("complex_", np.complex128)]:
    if not hasattr(np, _n):
        setattr(np, _n, _v)

try:
    import torch
    torch.set_num_threads(1)
except Exception:
    pass

# monkeypatch：to_thread 同步在主线程执行，规避多线程 embedding 段错误
import asyncio as _a
async def _sync_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)
_a.to_thread = _sync_to_thread

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from app.agent import get_agent
from agent_50q import QUESTIONS, extract_intent, behavior_of  # 复用题目集与判定


def main():
    if len(sys.argv) < 2:
        print("usage: run_one_q.py <idx>", flush=True)
        return 2
    idx = int(sys.argv[1])
    cat, q, exp = QUESTIONS[idx - 1]

    TEST_USER_ID = 3
    TEST_USER_INFO = {
        "id": 3, "username": "guo", "email": "3324507839@qq.com",
        "role": "user", "status": "active",
        "created_at": "2026-05-30 16:12:32", "last_login": "2026-08-23 07:39:53",
    }

    out_path = os.environ.get("AGENT_OUT") or os.path.join(HERE, "agent_50q_results.jsonl")
    agent = get_agent(max_steps=6, timeout=180.0)
    sid = f"q{idx}_{int(time.time()*1000)}"
    t0 = time.time()
    try:
        res = asyncio.run(asyncio.wait_for(
            agent.run(q, session_id=sid, user_id=TEST_USER_ID, user_info=TEST_USER_INFO),
            timeout=420.0,
        ))
    except asyncio.TimeoutError:
        res = {"answer": "", "success": False, "steps": 0, "logs": [], "paused": False,
               "questions": [], "tool_calls": [], "error": "TimeoutError(>420s)"}
    except BaseException as e:
        res = {"answer": "", "success": False, "steps": 0, "logs": [], "paused": False,
               "questions": [], "tool_calls": [], "error": f"{type(e).__name__}: {e}"}
    wall = round(time.time() - t0, 1)
    intent = extract_intent(res.get("logs", []))
    behavior = behavior_of(intent, res)
    rec = {
        "idx": idx,
        "category": cat,
        "question": q,
        "expected": exp,
        "intent": intent,
        "behavior": behavior,
        "success": res.get("success", False),
        "paused": res.get("paused", False),
        "steps": res.get("steps", 0),
        "wall": wall,
        "answer": res.get("answer", ""),
        "clarify_questions": res.get("questions", []),
        "tool_calls": [tc.get("tool") for tc in res.get("tool_calls", [])],
        "error": res.get("error", ""),
    }
    with open(out_path, "a", encoding="utf-8") as fout:
        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fout.flush()
    status = "OK" if intent == exp else "ROUTE_DIFF"
    print(f"[{idx}] {cat} | exp={exp} got={intent} | {behavior} | steps={rec['steps']} wall={wall}s | {status}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
