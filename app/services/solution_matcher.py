import asyncio
from app.models.llm import get_llm_response
from typing import Optional


class SolutionMatcherService:
    """DeepSeek版本 解决方案匹配服务"""

    def __init__(self, kb_service=None):
        """
        Args:
            kb_service: 外部传入的知识库服务实例。如果不传，使用全局默认KB。
        """
        if kb_service is not None:
            self.kb_service = kb_service
        else:
            from api.dependencies import get_knowledge_base
            self.kb_service = get_knowledge_base()

        # 固定提示词模板
        self.prompt_template = """
你是华为云解决方案专家。基于以下资料，为客户提供解决方案建议。

客户需求：{question}

相关资料：
{context}

请按以下格式回答：

## 1. 需求分析
分析客户核心需求和痛点

## 2. 推荐方案
推荐华为云解决方案并说明理由

## 3. 核心价值
列出3个价值点（含量化指标）

## 4. 产品组合
列出关键华为云产品及作用

## 5. 实施路径
分3个阶段说明实施计划

## 6. 投资回报
估算投资和预期收益

## 7. 成功案例
提供相关成功案例

## 8. 下一步建议
给出具体行动建议

内容要具体量化，避免泛泛而谈。
        """

    async def match(self, customer_demand):
        # 1. 知识库检索相关内容
        try:
            stats = self.kb_service.get_stats()
            kb_empty = (stats.get("total_documents", 0) == 0)
        except Exception:
            kb_empty = True

        if kb_empty:
            docs = []
            context_content = ""
        else:
            try:
                docs = await asyncio.to_thread(self.kb_service.search, customer_demand)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"向量检索异常，回退到 LLM 模式: {e}")
                docs = []
            context_content = "\n".join([doc.page_content for doc in docs])

        # 如果知识库为空，使用通用提示词
        if not docs or not context_content.strip():
            fallback_prompt = f"""
你是华为云资深解决方案专家，拥有15年以上行业解决方案设计经验。客户提出了以下需求：

{customer_demand}

虽然当前知识库中暂时没有相关的华为云解决方案文档，但请你基于华为云的产品体系、技术能力和行业最佳实践，给出专业、深入的建议：

## 1. 需求深度分析
- 客户背景理解：从需求描述推断客户行业、规模
- 核心需求识别：识别3-5个核心业务需求点
- 痛点根因分析：分析每个痛点的根本原因
- 业务场景还原：还原客户实际业务场景

## 2. 推荐解决方案方向
- 主推方向：推荐可能适用的华为云解决方案方向（如：工业互联网、智慧园区等）
- 选择理由：说明推荐该方向的依据
- 技术架构：描述大致的技术架构思路
- 适用性分析：分析该方向与客户需求的匹配度

## 3. 可能适用的华为云产品
每个产品需详细说明：
- 产品名称与定位
- 在本方案中的具体作用
- 关键能力与优势
- 与其他产品的协同关系

## 4. 实施路径建议
分阶段实施建议：
- 第一阶段：基础设施搭建
- 第二阶段：核心功能上线
- 第三阶段：深化应用推广

## 5. 预期价值分析
- 业务价值：列出2-3个核心业务价值
- 技术价值：列出2-3个技术层面价值
- 成功关键因素：识别成功的关键要素

## 6. 下一步行动建议
提供具体可执行的建议：
- 立即可执行事项
- 短期规划事项
- 中长期规划事项

注意：
1. 明确说明当前是基于华为云产品体系和通用知识给出的建议
2. 每个部分都要具体、量化，避免泛泛而谈
3. 建议客户联系华为云销售获取针对其行业的详细解决方案
4. 可通过上传更多行业解决方案文档来获得更精准的匹配
"""
            answer_result = await get_llm_response(fallback_prompt)
            return {
                "answer": answer_result,
                "source_documents": []
            }

        # 2. 拼接完整提问
        final_prompt = self.prompt_template.format(
            question=customer_demand,
            context=context_content
        )

        # 3. 调用DeepSeek接口获取结果
        answer_result = await get_llm_response(final_prompt)

        return {
            "answer": answer_result,
            "source_documents": docs
        }
