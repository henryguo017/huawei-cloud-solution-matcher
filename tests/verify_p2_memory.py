"""P2-2 验证：长程记忆（episodic + procedural）

断言：
  1. save_episode ×2（制造业预测性维护 / 政务大数据）→ count_episodes=2
  2. retrieve_episodes("制造业 设备预测性维护") → 第 1 条命中且分数最高（语义相关）
  3. build_memory_context 注入文本含历史需求摘要
  4. clear_episodes → count_episodes=0
  5. 内存级验证，不依赖 HTTP/LLM
"""
import sys, os, json, asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("OMP_NUM_THREADS", "1")


async def main():
    print("=== P2-2 长程记忆验证 ===")
    from app.agent.memory_profiles import (
        save_episode, retrieve_episodes, build_memory_context,
        build_profile_context, clear_episodes, count_episodes,
    )

    UID = 3
    SID = "p2_memory_test"

    # 清理前置
    clear_episodes(UID)
    assert count_episodes(UID) == 0, "❌ 前置清理失败"
    print("  ✅ 前置清理后 episodes=0")

    # 1. 保存两条
    save_episode(UID, SID, "帮我在制造业客户做设备预测性维护方案", "华为云工业物联网+AI预测性维护方案：设备接入、故障预警、工单联动、实施分三阶段，预计降低非计划停机30%。")
    save_episode(UID, SID, "为政务客户做一网通办大数据平台方案", "华为云政务云+数据使能方案：数据共享交换、一网通办、安全等保三级，统一门户。")
    n = count_episodes(UID)
    print(f"  ✅ 保存 2 条情景记忆，episodes={n}")
    assert n == 2, f"❌ 应有 2 条，实际 {n}"

    # 2. 语义检索
    hits = retrieve_episodes(UID, "制造业 设备预测性维护 工业物联网")
    print(f"  ✅ 检索命中 {len(hits)} 条: " + " | ".join(f"({h['score']}) {h['demand'][:20]}" for h in hits))
    assert hits, "❌ 未检索到任何记忆"
    assert "制造" in hits[0]["demand"], f"❌ 首条应为制造业记忆，实际 {hits[0]['demand'][:30]}"
    assert hits[0]["score"] >= hits[-1]["score"], "❌ 相似度应降序"

    # 3. build_memory_context 注入文本
    ctx = build_memory_context(UID, "制造业 预测性维护")
    print(f"  ✅ 注入文本长度={len(ctx)}")
    assert "制造" in ctx, "❌ 注入文本应含历史制造业记忆"
    assert len(ctx) <= 600, f"❌ 注入文本超限（截断 600）：{len(ctx)}"

    # 4. procedural 画像（无画像时应返回空串，不报错）
    prof = build_profile_context(UID)
    print(f"  ✅ 画像块：{'有内容' if prof else '空（用户暂无画像，正常）'}")

    # 5. 清理
    removed = clear_episodes(UID)
    print(f"  ✅ 清理 {removed} 条")
    assert removed == 2, f"❌ 应清理 2 条，实际 {removed}"
    assert count_episodes(UID) == 0, "❌ 清理后应为 0"
    assert build_memory_context(UID, "制造业") == "", "❌ 清理后注入应为空"

    print("\nP2-2 长程记忆验证全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
