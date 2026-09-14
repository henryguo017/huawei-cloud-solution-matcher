# -*- coding: utf-8 -*-
"""建档成功后的「下一步推进建议」（L4 商机推进闭环 · 领域语义层）。

设计（2026-09-14 定稿）：
- 宿主确定性追加，不靠 LLM 自觉——零幻觉、零额外 LLM 成本、纯函数可单测；
- 只在 client_add 真新建成功时触发（harness._make_result 统一收口检测，
  FC 与 legacy 拦截链两条建档路径都经过该收口）；
- 阶段→动作映射属售前领域语义，按双层边界纪律（架构文档 §3）放本模块，引擎不感知；
- 建议块不写入 _session_drafts（在缓存判断之后追加），避免污染后续 PPT/Word 导出正文。

stage 取值与 mcp_server_crm.client_add 的抽取约定一致：
初步接触 / 需求调研 / 方案报价 / 商机谈判口径 / 商务谈判 / 已成交 / 已流失。
"""

_STAGE_ACTIONS = {
    "初步接触": [
        "约定一次 30~60 分钟需求深聊，弄清决策链（谁使用、谁拍板、谁付钱）",
        "发一份该行业的标杆客户案例打前站，降低理解成本与戒备心理",
        "确认预算区间与立项时间窗，判断商机真伪与跟进优先级",
    ],
    "需求调研": [
        "输出正式解决方案初稿（可直接让我基于本轮沟通信息生成）",
        "推动一次技术交流或 POC 测试，用实测数据替代口头承诺",
        "确认预算与决策流程，明确下一步对接的关键决策人",
    ],
    "方案报价": [
        "推动报价审批与商务谈判，锁定折扣口径与付款节奏",
        "安排高层互访或公司级背书，对冲竞品既有关系",
        "明确合同签订时间表，防止商机长期悬置在比价阶段",
    ],
    "商务谈判": [
        "推进合同条款确认与签订，同步约定验收标准",
        "提前对接交付与实施团队备资源，签约即可启动",
    ],
    "已成交": [
        "跟进交付与验收，把本项目沉淀为标杆案例",
        "挖掘增购与续约线索，请客户转介绍同类商机",
    ],
    "已流失": [
        "记录流失真实原因，保持季度性轻触达，等待预算或人事窗口",
    ],
}

_DEFAULT_ACTIONS = _STAGE_ACTIONS["初步接触"]

# 常见口语别名词 → 标准阶段（normalize_stage 用）
_STAGE_ALIASES = {
    "调研": "需求调研", "需求": "需求调研",
    "报价": "方案报价", "方案": "方案报价", "投标": "方案报价", "比价": "方案报价",
    "谈判": "商务谈判", "合同": "商务谈判",
    "成交": "已成交", "交付": "已成交", "验收": "已成交",
    "流失": "已流失", "失败": "已流失",
}


def normalize_stage(stage: str) -> str:
    """stage 归一：先精确匹配标准六值，再按别名关键词容错（「调研中」「谈合同」等写法）。"""
    s = str(stage or "").strip()
    if not s:
        return ""
    for key in _STAGE_ACTIONS:
        if key in s:
            return key
    for frag, target in _STAGE_ALIASES.items():
        if frag in s:
            return target
    return ""


def build_next_actions(name: str = "", stage: str = "") -> str:
    """生成追加在终稿尾部的推进建议块（markdown）。name/stage 为空时用通用话术兜底。"""
    key = normalize_stage(stage)
    actions = _STAGE_ACTIONS.get(key) or _DEFAULT_ACTIONS
    head = f"客户「{name}」" if name else "该客户"
    stage_note = f"（当前阶段：{key}）" if key else ""
    lines = ["---", f"**【下一步推进建议】**{head}{stage_note}"]
    for i, action in enumerate(actions, 1):
        lines.append(f"{i}. {action}")
    return "\n".join(lines)
