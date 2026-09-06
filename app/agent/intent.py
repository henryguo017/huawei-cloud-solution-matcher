# -*- coding: utf-8 -*-
"""意图分类（Agent 模式首轮路由）。

把用户输入分流为五类：
- greeting  纯礼节性问候/致谢/告别（不含任务词）
- account   账户/成就/收藏/历史方案等个人数据查询
- competitor 竞品对比（显式对比两个具体厂商）
- solution  方案匹配需求（含行业/场景/规模/明确的"做个方案"动作）
- general   其余（平台使用咨询、常识/算数、自我介绍、概念提问等）

返回 dict：{intent, competitors, industries, confidence}
competitors / industries 供 harness 在竞品对比与长程记忆注入时复用。

⚠️ 本文件为 git 对象损坏后，依据工作记忆片段 + tests/agent_50q.py 的 50 题预期路由重建。
若你有原始版本，请直接覆盖此处（变量名 _FILE_CONSULT_RE / _COMPARE_METHOD_RE /
_has_specific_competitor 为原实现残留片段，已尽量保留语义）。
"""
import re
from typing import Dict, List, Any

import logging

from app.config import SUPPORTED_COMPETITORS

logger = logging.getLogger(__name__)


# ─────────────────────────── 规则片段（与原实现语义对齐） ───────────────────────────

# 纯礼节问候/致谢/告别：以这些词开头、且不含任务词才判 greeting
_GREETING_RE = re.compile(
    r"^(你好|您好|在吗|有人吗|谢谢|感谢|辛苦了|晚安|早上好|下午好|晚上好|再见|拜拜|嗨|hi|hello)",
    re.I,
)
_THANKS_RE = re.compile(r"(谢谢|感谢|辛苦|麻烦你了)")

# 账户类：我的成就/收藏/历史方案/生成的方案等个人数据
_ACCOUNT_RE = re.compile(
    r"(我的成就|我的收藏|我的历史|我之前生成|我生成的方案|查看我|我的方案|我的导出|我的报告|我的账户|我的资料|我的画像|我的成就是)"
)

# 平台使用/功能咨询句式（原 _FILE_CONSULT_RE 片段）：这类归 general
# 注意：仅作语义保留，不用于强制路由（account 优先于它，避免误杀"查看我的方案"）
_FILE_CONSULT_RE = re.compile(
    r"(怎么|如何|能否|可以|怎样).{0,6}(上传|使用|查看|对比|知识库|覆盖|绑定|密码|邮箱|成就|区别|做什么|干嘛|功能)"
)

# 方法论咨询（原 _COMPARE_METHOD_RE 片段）：以"怎么对比/如何比较"开头且无具体成对竞品 → general
_COMPARE_METHOD_RE = re.compile(r"^(怎么|如何|怎样).{0,8}(对比|比较|选)")

# 对比动词信号（用于判定"是否真的在对比"）
_HAS_COMPARE_VERB = re.compile(r"(对比|比较|比一比|比怎么样|比怎么样|优劣势|差异|怎么选|谁更强|谁更|选型)")

# 明确的方案动作（含动词 + 方案/平台/系统/上云 等），避免把"这个方案让我有成就感"误判为方案意图
_SOLUTION_ACTION_RE = re.compile(
    r"(做个|做份|做一|生成方案|生成一份|写一份.*(方案|报告|文档)|规划.*方案|设计方案|建设.*平台|搭建.*平台|"
    r"部署.*(云|平台)|上云|帮我做.*方案|给我.*方案|出.*方案|一份方案)"
)

# 行业关键词（命中即视为方案意图，并提取为 industries）
_INDUSTRY_KEYWORDS = [
    "制造", "装备", "医疗", "影像", "医院", "政务", "一网通办", "城市大脑", "教育",
    "智慧校园", "金融", "农商行", "银行", "农业", "农场", "智慧农业", "园区", "工业园区",
    "交通", "交投", "零售", "门店", "能源", "光伏", "文旅", "景区", "汽车", "车联网",
    "矿山", "煤矿", "钢铁", "冶金", "化工", "物流", "仓储", "生物医药", "药企", "游戏",
    "出海", "工业", "政务云",
]

# 规模信号（含数字 + 单位）
_SCALE_RE = re.compile(
    r"(\d+)\s*(台|家|亩|例|万|亿|个|套|座|平方|平米|MW|GW|KW|师生|门店|企业|车辆|用户|人)"
)

# 概念提问（"什么是 AWS 的 S3" 之类 → general，不算竞品对比）
_CONCEPT_RE = re.compile(r"^(什么是|什么叫|怎么理解|解释一下|什么是|说说)")

# 导出文档意图（P1-2 harness export 分支依赖此分类）：明确的导出/下载动作 + 文档格式词
_EXPORT_RE = re.compile(
    r"(导出|下载|另存)[^。]{0,12}(word|pdf|pptx?|文档|方案书|报告)|(导出成|导出为)",
    re.I,
)

# 生成 PPT 意图（2026-09-06）：客户口语"给我生成PPT/做个PPT/输出一份PPT"——
# 生成类动词 + PPT 格式词组合（仅 PPT 系；"生成方案/报告"是内容生产不在此列）
_PPT_GEN_RE = re.compile(
    r"(生成|做一个?|做份?|做个|输出|来一份?|帮我做|帮我生成)[^。]{0,8}pptx?"
    r"|(生成|做|输出|来一份?)[^。]{0,8}(幻灯片|演示文稿)",
    re.I,
)
# 疑问句排除："PPT怎么做/如何生成PPT/什么是PPT" 是方法论咨询，不是导出
_PPT_QUESTION_RE = re.compile(r"(怎么做|如何做|怎么写|如何写|怎么用|怎么生成|如何生成|什么是|哪些|有什么区别)")

# 文件操作意图（harness file_ops 分支依赖此分类）：列出/读取/查看/解析 用户上传的资料文件
_FILE_OPS_RE = re.compile(
    r"(列出|读取|打开|解析|总结|归纳|看看|查看)[^。]{0,8}(我上传|上传的|客户资料|客户文件|资料文件|文件列表|文件)"
)

# 产品知识问答意图（harness knowledge_q 分支依赖此分类）：华为云产品/服务概念提问，走 search_kb 结构化作答
_PRODUCT_WORDS = (
    "OBS", "ECS", "EVS", "SFS", "RDS", "GaussDB", "DDS", "CDN", "WAF", "ELB", "VPC",
    "IAM", "DWS", "ModelArts", "盘古", "昇腾", "CCE", "SWR", "CES", "DMS", "Kafka",
    "云桌面", "HSS", "CBR", "SMS", "FunctionGraph", "DataArts", "MetaStudio",
)
_KNOWLEDGE_Q_RE = re.compile(
    r"(" + "|".join(_PRODUCT_WORDS) + r")|(华为云)[^。]{0,6}(产品|服务|能力|架构|优势)",
    re.I,
)

# 任务词（用于抑制 greeting 误判）
_TASK_WORDS = re.compile(
    r"(方案|对比|竞品|行业|平台|帮我|做|生成|查|看|怎么|如何|上传|邮箱|密码|成就|收藏|历史|写|规划|设计|建设|搭建)"
)


def _has_specific_competitor(text: str) -> List[str]:
    """从文本中提取出现的（具体）竞品名，返回列表。"""
    low = text.lower()
    found = [c for c in SUPPORTED_COMPETITORS if c.lower() in low]
    # 常见别称补全
    aliases = {
        "阿里": "阿里云", "腾讯": "腾讯云", "亚马逊": "AWS", "微软": "微软Azure",
        "谷歌": "Google Cloud", "甲骨文": "Oracle Cloud", "火山": "字节跳动火山引擎",
    }
    for k, v in aliases.items():
        if k in text and v not in found:
            found.append(v)
    return found


def _mk(intent: str, competitors: List[str], industries: List[str], confidence: float) -> Dict[str, Any]:
    return {
        "intent": intent,
        "competitors": competitors,
        "industries": industries,
        "confidence": confidence,
    }


def classify_intent(text: str) -> Dict[str, Any]:
    """意图分类主入口。

    规则优先级：greeting(纯礼节) → account → export → competitor → solution
    → knowledge_q → file_ops → general。
    export/file_ops/knowledge_q 三个分支的 harness 侧消费逻辑一直在
    （harness.py L962/L993/L995），本文件 git 损坏重建时曾丢失这三类规则，此处恢复。
    """
    t = (text or "").strip()
    if not t:
        return _mk("general", [], [], 0.0)

    industries = [k for k in _INDUSTRY_KEYWORDS if k in t]
    competitors = _has_specific_competitor(t)

    # 1) 纯礼节问候/致谢/告别（且无任务词）
    if _GREETING_RE.match(t) and not _TASK_WORDS.search(t):
        return _mk("greeting", competitors, industries, 0.95)
    # 仅致谢/寒暄且无任务词（短句）
    if _THANKS_RE.search(t) and not _TASK_WORDS.search(t) and len(t) <= 12:
        return _mk("greeting", competitors, industries, 0.9)

    # 2) 账户类（优先于平台使用咨询）
    if _ACCOUNT_RE.search(t):
        return _mk("account", competitors, industries, 0.9)

    # 2.5) 导出文档（明确导出/下载动作 + 格式词；账户类已先行，避免误吃"下载我的方案"）
    #      补：生成类动词+PPT 组合（"给我生成PPT"），疑问句（"PPT怎么做"）排除
    if _EXPORT_RE.search(t) or (_PPT_GEN_RE.search(t)
                                and not _PPT_QUESTION_RE.search(t)):
        return _mk("export", competitors, industries, 0.9)

    # 3) 竞品对比（必须出现具体外部竞品名，避免把"怎么对比华为云和其他竞品厂商"误判为对比）
    if competitors and _HAS_COMPARE_VERB.search(t):
        # 方法论咨询（怎么对比/如何比较）且无具体成对竞品 → general
        if _COMPARE_METHOD_RE.match(t) and len(competitors) < 2 and not re.search(
            r"(和|与|vs|对比.{0,4}(阿里|腾讯|aws|华为|西门子|移动|天翼|联通|字节|火山))", t, re.I
        ):
            return _mk("general", competitors, industries, 0.6)
        return _mk("competitor", competitors, industries, 0.9)

    # 4) 方案类：含行业 / 规模 / 明确方案动作
    if industries or _SCALE_RE.search(t) or _SOLUTION_ACTION_RE.search(t):
        # 概念提问（"什么是 AWS 的 S3"）且无方案动作 → general
        if _CONCEPT_RE.match(t) and not re.search(r"(方案|对比|竞品|做一个|帮我|生成|上云|建设|搭建)", t):
            return _mk("general", competitors, industries, 0.6)
        return _mk("solution", competitors, industries, 0.85)

    # 4.5) 产品知识问答（方案类已先行，带行业/规模/方案动作的不会走到这）
    if _KNOWLEDGE_Q_RE.search(t):
        return _mk("knowledge_q", competitors, industries, 0.85)

    # 4.6) 文件操作（咨询句式"怎么上传/如何查看"仍归 general，不抢）
    if _FILE_OPS_RE.search(t) and not _FILE_CONSULT_RE.search(t):
        return _mk("file_ops", competitors, industries, 0.85)

    # 5) 通用兜底
    return _mk("general", competitors, industries, 0.5)
