# -*- coding: utf-8 -*-
"""调度器：把剩余未完成的题目（默认 30..50）逐题交给独立子进程 run_one_q.py 跑。

- 每题独立进程：单题段错误（139）只影响该题，调度器自动重试。
- 已完成的 idx 自动跳过（读取 agent_50q_results.jsonl）。
- 全部跑完后打印汇总。
"""
import os
import sys
import json
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PY = r"e:/newai/huawei-cloud-solution-matcher/venv/Scripts/python.exe"
OUT = os.environ.get("AGENT_OUT") or os.path.join(HERE, "agent_50q_results.jsonl")
RUN_ONE = os.path.join(HERE, "run_one_q.py")


def load_done():
    done = set()
    if os.path.exists(OUT):
        with open(OUT, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(int(json.loads(line)["idx"]))
                except Exception:
                    pass
    return done


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    total = end - start + 1
    print(f"[DRIVER] 范围 {start}..{end}（共 {total} 题）", flush=True)

    done = load_done()
    ok = 0
    failed = []
    for idx in range(start, end + 1):
        if idx in done:
            print(f"[{idx}] 已完成，跳过", flush=True)
            ok += 1
            continue
        # 每题最多重试 3 次（含首次）
        last_rc = None
        for attempt in range(1, 4):
            print(f"\n[{idx}] 第 {attempt} 次尝试 ...", flush=True)
            proc = subprocess.run(
                [PY, RUN_ONE, str(idx)],
                cwd=HERE,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            last_rc = proc.returncode
            if proc.returncode == 0:
                break
            print(f"  !! idx={idx} 进程异常退出 rc={proc.returncode}（段错误?），重试", flush=True)
        if last_rc == 0:
            ok += 1
        else:
            failed.append(idx)
            # 写错误占位，避免后续重复卡住
            rec = {
                "idx": idx, "category": "?", "question": f"idx={idx}",
                "expected": "?", "intent": "unknown", "behavior": "进程段错误未产出",
                "success": False, "paused": False, "steps": 0, "wall": 0,
                "answer": "", "clarify_questions": [], "tool_calls": [],
                "error": f"segfault after 3 retries (rc={last_rc})",
            }
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"  !! idx={idx} 三次均失败，写入错误占位", flush=True)

    print(f"\n[DRIVER DONE] 成功 {ok}/{total}，失败 {failed}", flush=True)


if __name__ == "__main__":
    main()
