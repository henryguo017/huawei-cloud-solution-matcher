"""Smoke test: 验证 ABCD 修复后 Agent 行为（串行 3 题）。"""
import asyncio, sys, os, json, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent import get_agent
from app.agent.intent import classify_intent


async def main():
    agent = get_agent(max_steps=8, timeout=120.0)
    questions = [
        "帮我做一个制造业预测性维护的方案，谢谢",   # 带敬语，不应误判为问候
        "1+1等于几",                                # 通用问答，应走 general 真实回答
        "什么是 AWS 的 S3 存储服务",               # 概念提问，不应误判为竞品对比
    ]
    for i, q in enumerate(questions):
        sid = f"smoke_{i}_{int(time.time()*1000)}"
        t0 = time.time()
        res = await agent.run(q, session_id=sid)
        dt = round(time.time() - t0, 1)
        ans = res.get("answer", "")
        print("=" * 60)
        print(f"Q{i+1}: {q}")
        print(f"[意图] {res.get('intent') if 'intent' in res else '?'} | steps={res.get('steps')} | elapsed={res.get('elapsed')}s | wall={dt}s | success={res.get('success')}")
        print(f"[回答前300字]\n{ans[:300]}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
