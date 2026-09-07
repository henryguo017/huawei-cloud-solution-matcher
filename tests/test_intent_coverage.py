# -*- coding: utf-8 -*-
"""全类别意图覆盖离线测试：classify_intent + general 分支各拦截器。
不跑 LLM，只验证路由与标记是否落入预期分支。"""
import re
import sys
sys.path.insert(0, r'E:\newai\huawei-cloud-solution-matcher')

from app.agent.intent import classify_intent
from app.agent.harness import AgentHarness

DOC_RE = AgentHarness._DOC_INTENT_RE  # 直接引用类属性，杜绝测试副本漂移
WEB_TRIG = re.compile(r"搜索|联网|搜一下|查一下|查询|搜搜|新闻|最新|实时|今天|现在", re.I)

# (utterance, expected_intent, expected_flags)  flags: doc/web/crm_w/crm_q/kb 任一集合
# 预期说明：
# - 拦截链优先级 crm_w > crm_q > kb：命中任一即"吸收"web 标记（真实链路 CRM 拦截先于联网）
# - solution 意图带规格问价 → 两阶段成本强制步兜底，不要求 general+price
# - MPS/NVIDIA 不在本产品竞品清单（12 家云/工业巨头），归 general 由模型+联网作答
# - solution 意图 + CRM 命中且无方案动词 → harness CRM 短路（等价 crm_w）
CASES = [
    # ── 闲聊/问答（general/greeting，无执行标记）──
    ("你好", "greeting", set()),
    ("你能做什么", "general", set()),
    ("你是谁", "general", set()),
    ("1+1等于几", "general", set()),
    ("Python是什么", "general", set()),
    ("讲个笑话", "general", set()),
    ("你会玩王者荣耀吗", "general", set()),
    ("帮我写一封请假条", "general", set()),
    ("你认识孙绪鑫吗", "general", set()),
    ("帮我定个明天8点的闹钟", "general", set()),
    ("帮我发封邮件给张总", "general", set()),
    # ── 实时信息（general + web）──
    ("华为云最新动态", "general", {"web"}),
    ("今天天气怎么样", "general", {"web"}),
    ("搜一下昇腾Atlas 950的发布信息", "general", {"web"}),
    ("查一下阿里云现在的价格活动", "general", {"web"}),
    # ── 文档执行（doc/export）──
    ("能根据华为云最新消息给我整理一份文档吗", "general", {"doc", "web"}),
    ("那ppt可以吗", "general", {"doc"}),
    ("需要ppt文件", "general", {"doc"}),
    ("转成word", "general", {"doc"}),
    ("把刚才那份华为云动态整理成PPT并导出", "general", {"doc"}),
    ("把刚才的内容导出", "general", {"doc"}),
    ("给我生成PPT", "export", set()),
    ("导出成 PDF", "export", set()),
    # ── 方案/竞品 ──
    ("帮我做一份智慧园区数字化上云方案，3个园区380家企业", "solution", set()),
    ("华为云和阿里云哪个好", "competitor", set()),
    ("阿里云和腾讯云选哪个", "competitor", set()),
    # ── CRM ──
    ("把海康威视存成客户", "general", {"crm_w"}),
    ("查一下海康威视的档案", "general", {"crm_q"}),
    ("给海康威视加个行业，制造业", "general", {"crm_w", "via_solution"}),
    ("删除客户海康威视", "general", {"crm_w"}),
    ("我的客户有哪些", "general", {"crm_q"}),
    ("我们合作过哪些客户", "general", {"crm_q"}),
    ("客户海康威视现在处于什么商机阶段", "general", {"crm_q"}),
    ("海康威视的历史方案", "general", {"crm_q"}),
    # ── 账户 ──
    ("我的收藏有哪些", "account", set()),
    ("我的历史方案", "account", set()),
    # ── KB ──
    ("知识库有多少文档", "general", {"kb"}),
    ("OBS是什么", "knowledge_q", set()),
    ("华为云产品有哪些优势", "knowledge_q", set()),
    # ── 文件 ──
    ("列出我上传的文件", "file_ops", set()),
    ("总结一下客户资料文件", "file_ops", set()),
    # ── 成本（solution 意图走两阶段成本强制步）──
    ("50台4核8G的ECS用3个月多少钱", "solution", set()),
    ("100套云桌面一年要花多少钱", "solution", set()),
    # ── 平台咨询 ──
    ("怎么上传知识库", "general", set()),
    ("怎么修改密码", "general", set()),
    # ── 边界审计补（2026-09-07 对抗性探针）：口语动词 / 裸行业词 / 裸格式应答 / 中英混合 ──
    ("帮我弄个方案", "solution", set()),          # 口语动词"弄个"原漏判为 general
    ("做个PPT呗", "export", set()),               # PPT 口语应走导出链（PPT 引擎）
    ("制造业", "general", set()),                 # 裸行业词（澄清回答）不应触发方案生成
    ("教育", "general", set()),                   # 同上
    ("3个园区", "solution", set()),               # 带规模数字的澄清回答 → 方案
    ("word吧", "general", {"doc"}),               # 裸格式词应答 → 成文意图
    ("pdf", "general", {"doc"}),                  # 同上
    ("help me make a PPT", "general", {"doc"}),   # 英文成文请求
    ("What is OBS?", "knowledge_q", set()),       # 英文产品概念问 → 知识库
    ("在吗", "greeting", set()),                  # 问候变体
    ("把上次生成的方案导出", "general", {"doc"}),  # 指代历史的导出诉求 → 成文链
]

fails = []
for text, want_intent, want_flags in CASES:
    got = classify_intent(text)
    intent = got["intent"]
    flags = set()
    if intent == "general":
        if DOC_RE.search(text):
            flags.add("doc")
        if WEB_TRIG.search(text):
            flags.add("web")
        if AgentHarness._crm_intent_hit(text):
            flags.add("crm_w")
        if AgentHarness._crm_query_hit(text):
            flags.add("crm_q")
        if AgentHarness._kb_stats_hit(text):
            flags.add("kb")
        # 拦截优先级：crm/kb 命中时吸收 web（CRM 拦截先于联网执行）
        if flags & {"crm_w", "crm_q", "kb"}:
            flags.discard("web")
    ok = intent == want_intent and flags == want_flags
    # solution 意图 + CRM 命中且无方案动词 = harness CRM 短路，等价 crm_w
    via_short = want_flags == {"crm_w", "via_solution"}
    if via_short:
        ok = (intent == "solution" or intent == "general") and AgentHarness._crm_intent_hit(text)
    if not ok:
        fails.append((text, want_intent, want_flags, intent, flags))
    print(("PASS" if ok else "FAIL"), f"| {text[:28]:<30} want={want_intent}{sorted(want_flags - {'via_solution'})} got={intent}{sorted(flags)}")

print()
print(f"总计 {len(CASES)} 例，失败 {len(fails)}")
for f in fails:
    print("  FAIL:", f)
