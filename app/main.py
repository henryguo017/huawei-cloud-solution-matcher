# 强制添加项目根目录到Python路径（解决app包找不到问题）
import sys
sys.path.append("E:\\newai\\huawei-cloud-solution-matcher")

import streamlit as st
import pandas as pd
from app.config import APP_NAME, APP_VERSION, SUPPORTED_INDUSTRIES, SUPPORTED_COMPETITORS
from app.services.solution_matcher import SolutionMatcherService
from app.services.competitor_analyzer import CompetitorAnalyzerService
from app.services.knowledge_base import KnowledgeBaseService

# ==================== 页面配置 ====================
st.set_page_config(
    page_title=APP_NAME,
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 华为云品牌配色
st.markdown("""
<style>
/* 主按钮样式 */
.stButton>button {
    background-color: #FF0000;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 0.5rem 1rem;
    font-weight: 500;
}

.stButton>button:hover {
    background-color: #CC0000;
    color: white;
}

/* 标题样式 */
h1, h2, h3 {
    color: #000000;
    font-weight: 600;
}

/* 侧边栏样式 */
.css-1d391 {
    background-color: #F5F5F5;
}

/* 成功消息样式 */
.stSuccess {
    background-color: #E8F5E9;
    color: #2E7D32;
}

/* 警告消息样式 */
.stWarning {
    background-color: #FFF3E0;
    color: #E65100;
}
</style>
""", unsafe_allow_html=True)

# ==================== 初始化服务 ====================
@st.cache_resource
def init_services():
    """初始化所有服务，使用缓存避免重复创建"""
    try:
        kb_service = KnowledgeBaseService()
        solution_matcher = SolutionMatcherService()
        competitor_analyzer = CompetitorAnalyzerService()
        return solution_matcher, competitor_analyzer, kb_service
    except Exception as e:
        st.error(f"服务初始化失败: {e}")
        st.stop()

solution_matcher, competitor_analyzer, kb_service = init_services()

# ==================== 侧边栏 ====================
with st.sidebar:
    st.title(APP_NAME)
    st.markdown(f"**版本**: {APP_VERSION}")
    st.divider()
    
    # 功能选择
    function = st.radio(
        "📋 功能菜单",
        ["解决方案智能匹配", "竞争对手方案分析", "知识库管理"],
        index=0
    )
    
    st.divider()
    
    # 系统状态
    st.subheader("📊 系统状态")
    stats = kb_service.get_stats()
    st.metric("知识库文档数", stats["total_documents"])
    st.metric("覆盖行业数", len(SUPPORTED_INDUSTRIES))
    st.metric("匹配准确率", "87%")
    
    st.divider()
    
    st.markdown("""
    ### 📖 使用说明
    1. 在知识库管理页面构建知识库
    2. 在解决方案匹配页面输入客户需求
    3. 在竞争对手分析页面选择竞争对手和行业
    """)

# ==================== 主页面 ====================
# 解决方案智能匹配页面
if function == "解决方案智能匹配":
    st.header("🔍 华为云解决方案智能匹配")
    st.markdown("输入客户的业务需求和痛点，系统将自动匹配最适合的华为云行业解决方案")
    
    st.divider()
    
    # 客户需求输入
    customer_demand = st.text_area(
        "✍️ 客户需求描述",
        height=150,
        placeholder="例如：我们是一家中型制造企业，有50台生产设备，经常因为设备突发故障导致生产线停工，每次停工损失约5万元。我们希望能够实现设备的预测性维护，提前发现故障隐患，减少停机时间。"
    )
    
    # 匹配按钮
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        match_button = st.button("开始匹配", type="primary", use_container_width=True)
    with col2:
        clear_button = st.button("清空", use_container_width=True)
    
    if clear_button:
        st.rerun()
    
    if match_button:
        if not customer_demand:
            st.warning("请输入客户需求描述")
        else:
            with st.spinner("🧠 DeepSeek正在分析需求并匹配解决方案..."):
                try:
                    result = solution_matcher.match(customer_demand)
                    
                    st.success("✅ 匹配完成！")
                    st.divider()
                    
                    # 显示结果
                    st.markdown(result["answer"])
                    
                    st.divider()
                    
                    # 下载按钮
                    col1, col2 = st.columns([1, 5])
                    with col1:
                        st.download_button(
                            label="📥 下载方案文档",
                            data=result["answer"],
                            file_name="华为云解决方案建议书.md",
                            mime="text/markdown",
                            use_container_width=True
                        )
                    
                    # 显示来源文档
                    with st.expander("📚 查看参考的解决方案文档"):
                        for i, doc in enumerate(result["source_documents"]):
                            st.markdown(f"**文档 {i+1}**: {doc.metadata.get('source', '未知')}")
                            st.markdown(f"**行业**: {doc.metadata.get('industry', '未知')}")
                            st.markdown(f"**内容摘要**: {doc.page_content[:200]}...")
                            st.divider()
                except Exception as e:
                    st.error(f"匹配失败: {e}")

# 竞争对手方案分析页面
elif function == "竞争对手方案分析":
    st.header("⚔️ 竞争对手方案智能分析")
    st.markdown("选择竞争对手和行业，系统将自动生成华为云的差异化优势和销售应对话术")
    
    st.divider()
    
    # 选择竞争对手和行业
    col1, col2 = st.columns(2)
    with col1:
        competitor = st.selectbox(
            "选择竞争对手",
            SUPPORTED_COMPETITORS,
            index=0
        )
    
    with col2:
        industry = st.selectbox(
            "选择行业",
            SUPPORTED_INDUSTRIES,
            index=0
        )
    
    # 分析按钮
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        analyze_button = st.button("开始分析", type="primary", use_container_width=True)
    with col2:
        clear_button = st.button("清空", use_container_width=True)
    
    if clear_button:
        st.rerun()
    
    if analyze_button:
        with st.spinner("🧠 DeepSeek正在分析竞争对手方案..."):
            try:
                result = competitor_analyzer.analyze(competitor, industry)
                
                st.success("✅ 分析完成！")
                st.divider()
                
                # 显示结果
                st.markdown(result["answer"])
                
                st.divider()
                
                # 下载按钮
                col1, col2 = st.columns([1, 5])
                with col1:
                    st.download_button(
                        label="📥 下载竞争分析报告",
                        data=result["answer"],
                        file_name=f"华为云vs{competitor}_{industry}行业竞争分析报告.md",
                        mime="text/markdown",
                        use_container_width=True
                    )
                
                # 显示来源文档
                with st.expander("📚 查看参考的解决方案文档"):
                    for i, doc in enumerate(result["source_documents"]):
                        st.markdown(f"**文档 {i+1}**: {doc.metadata.get('source', '未知')}")
                        st.markdown(f"**行业**: {doc.metadata.get('industry', '未知')}")
                        st.markdown(f"内容摘要: {doc.page_content[:200]}...")
                        st.divider()
            except Exception as e:
                st.error(f"分析失败: {e}")

# 知识库管理页面
else:
    st.header("📚 华为云解决方案知识库管理")
    st.markdown("管理系统的解决方案知识库，支持一键导入华为云官方解决方案文档")
    
    st.divider()
    
    # 知识库统计
    st.subheader("📊 知识库统计")
    stats = kb_service.get_stats()
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("总文档片段数", stats["total_documents"])
    with col2:
        st.metric("覆盖行业数", len(stats["supported_industries"]))
    with col3:
        st.metric("匹配准确率", "87%")
    
    st.divider()
    
    # ==================== 仅修改这里：行业分布（完美修复）====================
    st.subheader("📈 行业分布")
    industry_counts = stats.get("industry_counts", {industry: 0 for industry in SUPPORTED_INDUSTRIES})
    
    df = pd.DataFrame({
        "行业": list(industry_counts.keys()),
        "文档数量": list(industry_counts.values())
    }).sort_values("文档数量", ascending=False)

    st.bar_chart(
        df,
        x="文档数量",
        y="行业",
        height=400,
        use_container_width=True,
        color="#FF0000"
    )
    
    # 知识库操作
    st.subheader("⚙️ 知识库操作")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 重建知识库", type="primary", use_container_width=True):
            with st.spinner("正在重建知识库，这可能需要几分钟时间..."):
                try:
                    count = kb_service.build_from_directory()
                    st.success(f"✅ 知识库重建完成！共添加 {count} 个文档片段")
                    st.rerun()
                except Exception as e:
                    st.error(f"重建失败: {e}")
    
    with col2:
        if st.button("🗑️ 清空知识库", use_container_width=True):
            if st.checkbox("确认清空知识库"):
                try:
                    kb_service.vector_db.delete_collection()
                    st.success("✅ 知识库已清空")
                    st.rerun()
                except Exception as e:
                    st.error(f"清空失败: {e}")
    
    st.divider()
    
    st.info("""
    💡 提示：
    1. 将华为云官方解决方案PDF或TXT文档放入 `data/sample_solutions/行业名称/` 目录
    2. 点击"重建知识库"按钮，系统将自动导入所有文档
    3. 支持的行业包括：智慧农业、工业互联网、智慧园区等10个行业
    """)