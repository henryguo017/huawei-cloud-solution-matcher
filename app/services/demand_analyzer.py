"""
需求结构化分析共享服务（demand_analyzer）
=====================================================
职责：把模糊的用户需求 → 结构化分析（industry / scenarios / pain_points / keywords / confidence）。

背景（2026-08-26 解耦重构）：
- 原实现在 app/agent/tools.py 的 _tool_analyze_demand（Agent 工具），
  经典匹配链路（app/services/solution_matcher.py）也借用它，造成经典 → Agent 的反向依赖。
- 现抽为共享服务：Agent 工具与经典匹配都调用本模块，Agent 包内改动不再波及经典链路。
"""
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def analyze_demand(raw_input: str) -> str:
    """
    将模糊的用户输入 → 结构化的需求分析 JSON 字符串。
    返回：JSON 字符串（{"industry","scenarios","pain_points","keywords","confidence"}）；
    失败时返回包含 error 字段的 JSON（调用方需自行容错）。
    """
    from app.models.llm import get_llm_response

    prompt = f"""你是一位需求分析专家。用户表达了以下需求，但描述可能很模糊。请将这段模糊需求转化为结构化分析。

用户原始输入："{raw_input}"

请严格按以下 JSON 格式输出（不要输出其他内容）：

{{
  "industry": "最匹配的行业（如：制造业、智慧农业、智慧医疗、工业互联网等）",
  "scenarios": ["场景1", "场景2", "场景3"],
  "pain_points": ["痛点1", "痛点2", "痛点3"],
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
  "confidence": "高/中/低"
}}

注意：
1. keywords 要包含可用于向量检索的技术术语和产品名称
2. industry 从常见行业中选择：工业互联网、智慧交通、智慧农业、智慧医疗、智慧园区、智慧城市、智慧教育、智慧文旅、智慧能源、智慧金融、生物医药、零售、游戏、政务、汽车、互联网、制造
3. 如果用户提到了竞品名称（如阿里云、腾讯云、AWS等），在 keywords 中保留"""

    try:
        result = await get_llm_response(prompt)
        try:
            json_start = result.find("{")
            json_end = result.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(result[json_start:json_end])
                return json.dumps(parsed, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, ValueError):
            pass
        return result
    except Exception as e:
        logger.warning(f"[demand_analyzer] 分析失败: {e}")
        return json.dumps({"error": str(e), "raw_input": raw_input}, ensure_ascii=False)


async def analyze_demand_structured(customer_demand: str) -> Dict[str, Any]:
    """便捷封装：解析 analyze_demand 的 JSON 为 dict。失败/解析失败静默返回空 dict。"""
    if not customer_demand:
        return {}
    try:
        raw = await analyze_demand(customer_demand)
        j = raw.find("{")
        k = raw.rfind("}") + 1
        if j >= 0 and k > j:
            data = json.loads(raw[j:k])
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, ValueError):
        pass
    except Exception as e:
        logger.warning(f"[demand_analyzer] 结构化解析失败（跳过，降级为通用生成）: {e}")
    return {}
