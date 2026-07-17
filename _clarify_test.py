import asyncio, sys
sys.path.insert(0, "E:/newai/huawei-cloud-solution-matcher")
from app.agent.harness import AgentHarness

class FakeRegistry:
    def get_tools_prompt(self): return "tools: none"
    def get(self, name): return None

class FakeMemory:
    def clear_short_term(self, sid): pass
    def add_user_message(self, sid, c): pass
    def get_conversation_history(self, sid): return "（第一次对话）"
    def add_thought(self, sid, c): pass
    def add_action(self, sid, t, i): pass
    def add_observation(self, sid, c): pass
    def add_agent_response(self, sid, c): pass

def scripted(*responses):
    i = {"n": 0}
    async def fake_call(prompt):
        n = i["n"]; i["n"] += 1
        return responses[min(n, len(responses) - 1)]
    return fake_call

async def test_basic():
    h = AgentHarness(tools=FakeRegistry(), memory=FakeMemory(), max_steps=6)
    h._call_llm = scripted(
        'Clarify: [{"question": "行业是？", "options": ["制造", "零售"]}]',
        "Final Answer: 这是方案正文。",
    )
    events = []
    async def cb(e): events.append(e)
    r1 = await h.run("我想做方案", session_id="t1", event_callback=cb)
    assert r1.get("paused") is True, f"expected paused, got {r1}"
    assert r1.get("clarify_id"), "expected clarify_id"
    clar = [e for e in events if e["type"] == "clarify"]
    assert clar, "expected a clarify event"
    assert clar[0]["questions"][0]["question"] == "行业是？", clar
    print("[OK] 首轮发出 clarify 事件并暂停, clarify_id=", r1["clarify_id"])

    cid = r1["clarify_id"]
    events2 = []
    r2 = await h.run("", session_id="t1", event_callback=lambda e: events2.append(e),
                     clarify_id=cid, answers=[{"question": "行业是？", "answer": "制造"}])
    assert r2.get("paused") is not True, f"resume should not pause, got {r2}"
    assert r2.get("success") is True, f"resume should succeed, got {r2}"
    assert "方案正文" in (r2.get("answer") or ""), r2
    assert not [e for e in events2 if e["type"] == "clarify"], "resume must not clarify again"
    print("[OK] 续跑得到 Final Answer, 未再次澄清")

async def test_forced_final():
    # 连续三次都返回 Clarify -> 第三次应被强制收尾（继续循环并最终出 Final）
    h = AgentHarness(tools=FakeRegistry(), memory=FakeMemory(), max_steps=10)
    h._call_llm = scripted(
        'Clarify: [{"question": "Q1？", "options": []}]',
        'Clarify: [{"question": "Q2？", "options": []}]',   # 第2轮，仍允许暂停（<3）
        'Clarify: [{"question": "Q3？", "options": []}]',   # 第3轮，应被强制收尾（>=3）
        "Final Answer: 强制收尾后的方案。",
    )
    events = []
    async def cb(e): events.append(e)
    r1 = await h.run("需求", session_id="t2", event_callback=cb)
    cid = r1["clarify_id"]
    assert r1.get("paused") is True

    # 续跑第2次：模型再次 Clarify，_clarify_round=2 < 3 → 仍允许暂停
    events2 = []
    r2 = await h.run("", session_id="t2", event_callback=lambda e: events2.append(e),
                     clarify_id=cid, answers=[{"question": "Q1？", "answer": "x"}])
    assert r2.get("paused") is True, f"第2轮应仍可暂停, got {r2}"
    cid2 = r2["clarify_id"]

    # 续跑第3次：模型还想 Clarify，但 _clarify_round >= 3 → 强制收尾
    events3 = []
    r3 = await h.run("", session_id="t2", event_callback=lambda e: events3.append(e),
                     clarify_id=cid2, answers=[{"question": "Q2？", "answer": "y"}])
    assert r3.get("success") is True, f"第3轮应强制收尾出方案, got {r3}"
    assert "强制收尾" in (r3.get("answer") or ""), r3
    print("[OK] 第3轮澄清被强制收尾并产出方案")

async def test_expired():
    h = AgentHarness(tools=FakeRegistry(), memory=FakeMemory())
    r = await h.run("", session_id="t3", clarify_id="nonexistent-id", answers=[])
    assert r.get("expired") is True, r
    print("[OK] 过期 clarify_id 返回 expired")

async def main():
    await test_basic()
    await test_forced_final()
    await test_expired()
    print("\nALL CLARIFY TESTS PASSED")

asyncio.run(main())
