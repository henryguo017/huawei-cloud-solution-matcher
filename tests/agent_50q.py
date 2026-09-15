# -*- coding: utf-8 -*-
"""
Agent 模式 50 题全量回归测试驱动（本地 in-process，绕过登录鉴权）。

环境 workaround（仅测试用，不改生产代码）：
- 设置 OMP/MKL/OPENBLAS 单线程，规避 Windows+Python3.13 下 sentence-transformers
  在 worker 线程推理的段错误。
- monkeypatch asyncio.to_thread，让 embedding 在主线程执行（同上原因）。
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

# monkeypatch：让 to_thread 在当前（主）线程同步执行，规避多线程 embedding 段错误
import asyncio as _a

async def _sync_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)

_a.to_thread = _sync_to_thread

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent import get_agent

# ============================================================
# 50 题测试集（覆盖：日常对话 / 平台使用 / 账户个人 / 各行业方案 / 竞品对比 / 边缘异常）
# 每题: (分类, 问题, 期望路由)
# ============================================================
QUESTIONS = [
    # —— A. 日常对话 / 闲聊 ——
    ("日常对话", "你好", "greeting"),
    ("日常对话", "在吗？有人吗", "greeting"),
    ("日常对话", "谢谢你的帮助，辛苦了", "greeting"),
    ("日常对话", "晚安，明天见", "greeting"),
    ("日常对话", "你是谁，你能帮我做什么", "general"),
    ("日常对话", "今天天气真不错啊", "general"),
    ("日常对话", "哈哈你说话真有意思", "general"),
    ("日常对话", "帮我做个制造业方案，谢谢", "solution"),   # 带敬语不应误杀为问候

    # —— B. 平台使用 / 功能咨询 ——
    ("平台使用", "这个平台主要是做什么的", "general"),
    ("平台使用", "怎么上传客户的资料文件", "general"),
    ("平台使用", "怎么查看我之前生成过的方案", "account"),
    ("平台使用", "怎么对比华为云和其他竞品厂商", "general"),
    ("平台使用", "你们知识库里大概有多少方案资料", "general"),
    ("平台使用", "你们覆盖哪些行业", "general"),
    ("平台使用", "我忘记密码了怎么找回", "general"),
    ("平台使用", "怎么绑定我的邮箱", "general"),
    ("平台使用", "我的成就是怎么解锁的", "account"),
    ("平台使用", "agent 模式和经典模式有什么区别", "general"),

    # —— C. 账户 / 个人 ——
    ("账户个人", "我的成就是什么", "account"),
    ("账户个人", "我的收藏在哪里看", "account"),
    ("账户个人", "我的历史方案能导出吗", "account"),
    ("账户个人", "这个方案让我很有成就感", "general"),  # 不应误判为账户

    # —— D. 方案生成（各行业，详细到能出完整答案）——
    ("方案-制造", "某中型装备制造企业，200台数控设备，常因非计划停机损失大，想上预测性维护平台，减少停机并降本", "solution"),
    ("方案-医疗", "某三甲医院想建智慧医疗影像云平台，日均CT/MR检查2000例，希望AI辅助诊断并打通区域医联体", "solution"),
    ("方案-政务", "某市政务想做一网通办和城市大脑，提升市民办事效率，打通40个委办局数据", "solution"),
    ("方案-教育", "某高校想建智慧校园，统一身份认证加教学大数据分析，覆盖3万师生", "solution"),
    ("方案-金融", "某省级农商行想做智慧金融，零售客户风控加分布式核心系统，日交易峰值500万笔", "solution"),
    ("方案-农业", "某大型农场想做智慧农业，水肥一体化加无人机巡田加病虫害AI识别，1万亩基地", "solution"),
    ("方案-园区", "某工业园区想建智慧园区，安防加能耗管理加停车诱导，占地2000亩入驻企业300家", "solution"),
    ("方案-交通", "某交投集团想做智慧交通，信号优化加视频事件检测加公交调度，管理城区1200路口", "solution"),
    ("方案-零售", "某连锁零售企业想做智慧零售，会员精准营销加门店数字化加智能补货，800家门店", "solution"),
    ("方案-能源", "某能源集团想建智慧能源，光伏电站智能运维加碳资产管理，装机容量2GW", "solution"),
    ("方案-文旅", "某5A景区想做智慧文旅，游客画像加沉浸式体验加客流预警，年客流800万", "solution"),
    ("方案-汽车", "某汽车主机厂想建车联网平台，OTA升级加远程诊断加数据闭环，连接车辆50万台", "solution"),
    ("方案-矿山", "某煤矿想做矿山智能化，井下人员定位加设备预测性维护加视频智能分析，年产千万吨", "solution"),
    ("方案-钢铁", "某钢铁厂想做钢铁冶金智能制造，炉况预测加质量溯源加能效优化，年产钢2000万吨", "solution"),
    ("方案-化工", "某化工园区想做安全生产，危化品全流程监测加应急联动加风险预警，园区企业120家", "solution"),
    ("方案-物流", "某物流公司想做智慧物流，仓储机器人加路径优化加全程可视化，日均单量200万", "solution"),
    ("方案-生物医药", "某药企想做生物医药研发上云，高性能计算加基因测序分析，缩短新药研发周期", "solution"),
    ("方案-游戏", "某游戏公司想做出海，全球加速加弹性算力加反作弊，目标东南亚市场", "solution"),

    # —— E. 竞品对比 ——
    ("竞品对比", "对比阿里云和华为云在政务云上的优劣势", "competitor"),
    ("竞品对比", "对比腾讯云和华为云在音视频领域的差异", "competitor"),
    ("竞品对比", "对比AWS和华为云在出海业务上怎么选型", "competitor"),
    ("竞品对比", "华为云和天翼云在国资云场景怎么选", "competitor"),
    ("竞品对比", "西门子和国内的工业互联网平台比怎么样", "competitor"),
    ("竞品对比", "移动云和华为云在政务市场谁更强", "competitor"),

    # —— F. 边缘 / 异常 / 短需求 ——
    ("边缘异常", "帮我做个云方案", "solution"),          # 过短，应澄清追问
    ("边缘异常", "1+1等于几", "general"),
    ("边缘异常", "什么是 AWS 的 S3 存储服务", "general"),  # 概念提问，不应误判竞品
    ("边缘异常", "这个平台能不能帮我写周报", "general"),
]


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
    base = os.path.dirname(os.path.abspath(__file__))
    out_name = os.environ.get("AGENT_50Q_OUT", "agent_50q_results.jsonl")
    out_path = os.path.join(base, out_name)

    # —— 续跑支持：读取已完成的 idx，跳过 ——
    done_idx = set()
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        done_idx.add(int(json.loads(line)["idx"]))
                    except Exception:
                        pass
        except Exception:
            pass
    if done_idx:
        print(f"[RESUME] 已完成 {len(done_idx)} 题，将跳过: {sorted(done_idx)}", flush=True)

    total = len(QUESTIONS)
    # 统计已完成中与预期一致的数量（用于最终汇总）
    prev_ok = 0
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if r.get("intent") == r.get("expected"):
                        prev_ok += 1
                except Exception:
                    pass

    # 测试账户：guo（id=3），账户类问题据此从后端真实取数
    TEST_USER_ID = 3
    TEST_USER_INFO = {
        "id": 3, "username": "guo", "email": "3324507839@qq.com",
        "role": "user", "status": "active",
        "created_at": "2026-05-30 16:12:32", "last_login": "2026-08-23 07:39:53",
    }

    with open(out_path, "a", encoding="utf-8") as fout:
        for i, (cat, q, exp) in enumerate(QUESTIONS):
            idx = i + 1
            if idx in done_idx:
                continue
            sid = f"q{i}_{int(time.time()*1000)}"
            t0 = time.time()
            try:
                res = await asyncio.wait_for(
                    agent.run(q, session_id=sid, user_id=TEST_USER_ID, user_info=TEST_USER_INFO),
                    timeout=420.0,
                )
            except asyncio.TimeoutError:
                res = {"answer": "", "success": False, "steps": 0, "logs": [], "paused": False,
                       "questions": [], "tool_calls": [], "error": "TimeoutError(>200s)"}
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
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            status = "OK" if intent == exp else "ROUTE_DIFF"
            if intent == exp:
                prev_ok += 1
            print(f"[{idx}/{total}] {cat} | exp={exp} got={intent} | {behavior} | "
                  f"steps={rec['steps']} wall={wall}s | {status}", flush=True)
            await asyncio.sleep(1.0)
    print(f"\nDONE: {total} 题完成，路由与预期一致 {prev_ok}/{total}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
