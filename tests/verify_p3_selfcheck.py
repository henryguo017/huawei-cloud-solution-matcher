"""P3-3 自检 Gate 验证：直接驱动 harness._self_check_gate。

断言：
1. 缺陷草稿（缺竞品对比/产品组合/可执行步骤）→ gate 判 fail → 二次合成 → 最终 pass（或迭代后 quality_warn 可控）。
2. 正常方案 → 一次 pass，quality_warn=False。
3. self_check 事件含 gate/score 字段。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.harness import AgentHarness
from app.agent.tools import create_default_tools
from app.agent.memory import ConversationMemory


def make_harness():
    tools = create_default_tools()
    mem = ConversationMemory(max_history_turns=15)
    h = AgentHarness(tools=tools, memory=mem, max_steps=4, timeout=60)
    h._intent = "solution"
    h._quality_warn = False
    h._plan = ["需求分析", "检索资料", "撰写方案"]
    h._plan_status = ["done", "done", "done"]
    return h


async def run_gate(h, answer, user_input, expect_pass_first=True):
    events = []
    async def cb(ev):
        events.append(ev)
    out, qwarn = await h._self_check_gate(answer, user_input, cb)
    return out, qwarn, events


async def main():
    h = make_harness()
    # 先确认开关默认开
    from app.config import AGENT_SELF_CHECK
    assert (AGENT_SELF_CHECK or "1").strip() == "1", "AGENT_SELF_CHECK 应默认开启"

    # 用例 1：缺陷草稿（>200字但全是套话：用户提了阿里云，却无竞品对比/无产品/无步骤）
    bad = (
        "关于贵司的上云需求，我们认为上云是一个非常好的方向。上云能够带来很多好处，包括提升效率、"
        "降低成本、增强业务的灵活性和扩展性。当前云计算技术已经非常成熟，越来越多的企业选择迁移到云端。"
        "我们建议贵司尽早启动上云项目，安排专人跟进，与服务商保持密切沟通。总体而言，上云利大于弊，"
        "值得全面推进。我们相信上云会为贵司带来积极的业务变化与长远价值。请相关同事重视此事，"
        "积极推进落地。祝贵司数字化转型顺利，业务蒸蒸日上，取得更好的成绩，未来更加美好，再创辉煌。"
    )
    user_input = "我们是制造企业，想和阿里云对比，把ERP上云，给个方案"
    out1, qw1, ev1 = await run_gate(h, bad, user_input)
    gates1 = [e for e in ev1 if e.get("type") == "self_check"]
    assert gates1, "应发出 self_check 事件"
    first_gate = gates1[0].get("gate")
    print(f"[用例1] 缺陷草稿 → 首闸={first_gate} 末闸={gates1[-1].get('gate')} quality_warn={qw1}")
    print(f"        末稿长度={len(out1)} 评分={gates1[-1].get('score')}")
    # 缺陷草稿首闸应为 fail（缺竞品对比/产品/步骤）
    assert first_gate == "fail", f"缺陷草稿首闸应为 fail，实际 {first_gate}"
    # 经二次合成后应转为 pass 或 warn（不阻断）
    assert gates1[-1].get("gate") in ("pass", "warn"), f"末闸应为 pass/warn，实际 {gates1[-1].get('gate')}"
    assert len(out1) > len(bad), "二次合成后应更长/更完整"

    # 用例 2：正常方案（含痛点/架构/产品/价值/步骤/竞品对比，贴近真实 _synthesize_final 输出）
    good = (
        "## 一、需求与痛点\n贵司为约200人规模的制造企业，ERP（用友U8）与OA目前本地部署于机房，"
        "面临三类核心问题：①硬件三年到期、扩容需一次性投入约40万元；②运维依赖1名兼职IT、"
        "宕机恢复RTO>4小时；③业务旺季订单峰值本地服务器CPU常打满，影响排产。上云诉求明确：降本、提稳、弹性。\n"
        "## 二、方案架构\n采用「华为云通用计算增强型ECS c7.2xlarge（8C32G）×2（主备）+ 云数据库RDS for MySQL 8.0（主备高可用）"
        "+ 对象存储OBS（ERP附件/报表）+ 企业主机安全HSS + 云备份CBR」组合，VPC内网隔离、公网仅放OA门户。"
        "ERP分库保留、应用无改造上云。\n"
        "## 三、推荐产品组合\n华为云ECS c7.2xlarge×2、RDS for MySQL 8.0主备、OBS标准存储、HSS企业版、CBR云备份、"
        "Web应用防火墙WAF（护OA门户）。\n"
        "## 四、与阿里云对比\n华为云在等保2.0三级合规、本地服务响应（杭州有驻场）、制造行业ISV生态（用友/金蝶适配）"
        "上更贴合贵司；阿里云全球节点与AI PaaS更丰富，但本场景不需要。成本侧同规格RDS华为云约低8%。\n"
        "## 五、实施路径与价值\n第一阶段（2周）迁OA+WAF，验证网络与体验；第二阶段（4周）迁ERP+RDS，割接选周末、"
        "RTO降到<30分钟。预计三年TCO由本地约72万降至云端约50万，降幅约30%。\n"
        "## 六、下一步建议\n预约华为云架构师做现状评估与PoC（免费1周），确认RDS参数与割接窗口后即启动一阶段。"
    )
    out2, qw2, ev2 = await run_gate(h, good, user_input)
    gates2 = [e for e in ev2 if e.get("type") == "self_check"]
    print(f"[用例2] 正常方案 → 首闸={gates2[0].get('gate')} quality_warn={qw2} 评分={gates2[0].get('score')}")
    assert gates2[0].get("gate") == "pass", f"正常方案应一次 pass，实际 {gates2[0].get('gate')}"
    assert qw2 is False, "正常方案 quality_warn 应为 False"

    print("\n✅ P3-3 自检 Gate 验证全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
