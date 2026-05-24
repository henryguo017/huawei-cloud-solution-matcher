from app.models.llm import get_llm_response
from app.services.knowledge_base import KnowledgeBaseService

class CompetitorAnalyzerService:
    """DeepSeek版本 竞品分析服务"""
    
    def __init__(self):
        self.kb_service = KnowledgeBaseService()

        self.prompt_template = """
你是华为云竞争分析专家。分析{competitor}在{industry}行业的解决方案，生成华为云差异化优势和销售话术。

华为云资料：
{context}

请按以下格式回答：

## 1. {competitor}方案分析
列出3个核心卖点和主要劣势

## 2. 华为云优势
列出3个差异化优势（含量化对比）

## 3. 销售话术
针对价格、功能质疑的应对话术

## 4. 成功案例
华为云在{industry}行业的成功案例

## 5. 竞争策略
差异化打法建议

内容要客观、具体、有说服力。
        """

    def analyze(self, competitor, industry):
        # 构造检索关键词
        search_query = f"华为云在{industry}行业的解决方案和竞争优势，与{competitor}的对比"
        docs = self.kb_service.search(search_query)
        context_content = "\n".join([doc.page_content for doc in docs])
        
        # 如果知识库为空，使用通用提示词
        if not docs or not context_content.strip():
            fallback_prompt = f"""
你是华为云资深竞争分析专家。请分析华为云在{industry}行业与{competitor}的竞争态势。

虽然当前知识库中暂时没有相关的竞争分析文档，但请你基于华为云的核心优势和行业最佳实践，给出以下分析：

## 1. {competitor}在{industry}行业的可能卖点
基于公开信息，列出{competitor}在{industry}行业可能的3-5个宣传卖点

## 2. {competitor}方案可能的劣势
列出{competitor}在{industry}行业可能存在的客观不足

## 3. 华为云的核心优势
列出华为云的3-5个差异化优势：
- 端云协同优势（华为拥有完整的终端和云产品线）
- AI技术优势（盘古大模型、ModelArts等）
- 安全可信优势（自主可控的技术体系）
- 服务网络优势（全国范围的本地化服务）
- 行业深耕优势（在各行业的深厚积累）

## 4. 销售应对建议
给出3-5个针对{competitor}的销售应对建议

## 5. 建议下一步行动
建议联系华为云行业专家获取详细的竞争分析资料

注意：
1. 明确说明当前是基于通用知识给出的分析
2. 建议补充更多行业竞争分析文档以获得更精准的分析
"""
            answer_result = get_llm_response(fallback_prompt)
            return {
                "answer": answer_result,
                "source_documents": []
            }

        # 拼接提示词
        final_prompt = self.prompt_template.format(
            competitor=competitor,
            industry=industry,
            context=context_content
        )

        # 调用模型
        answer_result = get_llm_response(final_prompt)

        return {
            "answer": answer_result,
            "source_documents": docs
        }

# 测试运行
if __name__ == "__main__":
    try:
        analyzer = CompetitorAnalyzerService()

        test_text = """
华为云智慧农业解决方案竞争优势：
1. 端云协同优势：华为拥有完整的终端设备和云服务产品线，能够提供从传感器到云平台的一体化解决方案
2. AI技术优势：华为云盘古大模型在农业领域有深厚的积累，能够提供更精准的生长预测和病虫害识别
3. 服务优势：华为在全国有完善的服务网络，能够提供快速的本地化技术支持
4. 安全优势：华为云提供自主可控的安全解决方案，保障农业数据安全

成功案例：
- 某大型农业集团项目，击败阿里云，采用华为云智慧农业解决方案，实现产量提升25%
        """
        
        from langchain_core.documents import Document
        analyzer.kb_service.add_documents([Document(page_content=test_text, metadata={"industry": "智慧农业"})])

        res = analyzer.analyze("阿里云", "智慧农业")
        print("✅ 竞品分析服务测试成功")
        print("分析结果：\n", res["answer"])

        analyzer.kb_service.vector_db.delete_collection()

    except Exception as e:
        print("❌ 竞品分析测试失败")
        print("错误：", str(e))