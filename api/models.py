from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

class MatchRequest(BaseModel):
    demand: str = Field(..., description="客户需求描述（可为空，对应'无声胜有声'隐藏成就）", min_length=0, max_length=5000)
    mode: Optional[str] = Field(default="standard", description="匹配模式: standard/agent/wizard")
    is_quick_demo: bool = Field(default=False, description="是否来自快速体验/Demo，为true时不触发成就")
    customer_files: List[str] = Field(default_factory=list, description="用户上传的客户资料相对路径列表（如 customer_uploads/xxx.docx），由上传接口返回")
    client_id: Optional[int] = Field(default=None, description="客户档案 ID；提供后 Agent 记忆按 用户:客户 维度隔离，避免多客户串味")
    group_id: Optional[int] = Field(default=None, description="版本分组 ID；提供后本次匹配作为同一方案的「新版本」保存（v2/v3...），不提供则新建分组存为 v1")
    
    class Config:
        json_schema_extra = {
            "example": {
                "demand": "我们是一家中型制造企业，有50台生产设备，经常因为设备突发故障导致生产线停工，每次停工损失约5万元。",
                "mode": "standard",
                "customer_files": []
            }
        }

class ClientCreateRequest(BaseModel):
    name: str = Field(..., description="客户名称", min_length=1, max_length=100)
    note: Optional[str] = Field(default=None, description="客户备注（可选）", max_length=500)

class AnalyzeRequest(BaseModel):
    competitor: str = Field(..., description="竞争对手名称")
    industry: str = Field(..., description="行业名称")
    is_quick_demo: bool = Field(default=False, description="是否来自快速体验/Demo，为true时不触发成就")
    
    class Config:
        json_schema_extra = {
            "example": {
                "competitor": "阿里云",
                "industry": "智慧农业"
            }
        }

class SourceDocument(BaseModel):
    page_content: str = Field(..., description="文档内容")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="文档元数据")

class MatchResponse(BaseModel):
    answer: str = Field(..., description="匹配结果（Markdown格式）")
    source_documents: List[SourceDocument] = Field(default_factory=list, description="参考文档列表")
    solution_json: Optional[Any] = Field(default=None, description="结构化方案（章节+要点），供报告生成器直接消费")
    history_id: Optional[int] = Field(default=None, description="本次匹配的历史记录ID，用于后续更新优化方案")
    newly_unlocked: Optional[List[dict]] = Field(default=None, description="新解锁的成就列表（前端用于弹窗提示）")
    # 方案版本化（阶段 2.5 配套）
    group_id: Optional[int] = Field(default=None, description="版本分组 ID（同组方案为 v1/v2/v3...）")
    version: Optional[int] = Field(default=None, description="本次保存的版本号，从 1 开始")
    is_final: Optional[bool] = Field(default=False, description="是否为定稿版本")
    title: Optional[str] = Field(default=None, description="方案分组标题（用于历史面板展示）")

class AnalyzeResponse(BaseModel):
    answer: str = Field(..., description="分析结果（Markdown格式）")
    source_documents: List[SourceDocument] = Field(default_factory=list, description="参考文档列表")
    history_id: Optional[int] = Field(default=None, description="本次分析的历史记录ID")
    newly_unlocked: Optional[List[dict]] = Field(default=None, description="新解锁的成就列表（前端用于弹窗提示）")

class KnowledgeStatsResponse(BaseModel):
    total_documents: int = Field(..., description="总文档片段数")
    supported_industries: List[str] = Field(default_factory=list, description="支持的行业列表")
    industry_counts: Dict[str, int] = Field(default_factory=dict, description="各行业文档数量")
    accuracy: int = Field(default=50, description="方案覆盖度（百分比）")
    total_solution_files: int = Field(default=0, description="解决方案文档总数（华为+竞品文件数）")
    competitor_companies: List[str] = Field(default_factory=list, description="竞品厂商列表")

class RebuildResponse(BaseModel):
    count: int = Field(..., description="重建的文档数量")
    message: str = Field(default="知识库重建成功", description="操作消息")

class ClearResponse(BaseModel):
    success: bool = Field(..., description="操作是否成功")
    message: str = Field(default="知识库已清空", description="操作消息")

class SyncMineResponse(BaseModel):
    success: bool = Field(..., description="操作是否成功")
    message: str = Field(default="知识库已同步为最新官方方案", description="操作消息")
    total_documents: int = Field(default=0, description="同步后用户知识库的文档片段数")

class TaskStatusResponse(BaseModel):
    """后台异步任务状态（知识库重建/同步返回 task_id，前端轮询此端点）"""
    task_id: str = Field(..., description="后台任务ID")
    status: str = Field(..., description="任务状态：pending / queued / running / success / failed")
    progress: int = Field(default=0, description="进度百分比 0-100")
    message: str = Field(default="", description="状态描述信息")
    result: Optional[dict] = Field(default=None, description="任务成功时的结果数据（如 count / total_documents）")

# ===== 知识库文档管理模型 =====
class KBDocumentItem(BaseModel):
    id: str = Field(..., description="文档唯一ID")
    category: str = Field(..., description="分类: huawei / competitor")
    title: str = Field(..., description="文档标题（文件名）")
    filename: str = Field(..., description="文件名")
    path: str = Field(..., description="相对路径")
    industry: str = Field(default="", description="所属行业")
    competitor: Optional[str] = Field(default=None, description="竞品名称")
    size: int = Field(default=0, description="文件大小（字节）")
    size_kb: float = Field(default=0, description="文件大小（KB）")

class KBDocumentListResponse(BaseModel):
    total: int = Field(..., description="文档总数")
    documents: List[KBDocumentItem] = Field(default_factory=list, description="文档列表")

class KBDocumentContentResponse(BaseModel):
    id: str = Field(..., description="文档ID")
    category: str = Field(..., description="分类")
    filename: str = Field(..., description="文件名")
    content: str = Field(..., description="文档内容")
    size: int = Field(default=0, description="文件大小")

class KBDocumentCreateRequest(BaseModel):
    category: str = Field(..., description="分类: huawei / competitor")
    industry: str = Field(..., description="行业名称或竞品名称")
    title: str = Field(..., description="文档标题", min_length=1, max_length=200)
    content: str = Field(..., description="文档内容", min_length=1)

class KBDocumentCreateResponse(BaseModel):
    id: str = Field(..., description="新文档ID")
    path: str = Field(..., description="文件路径")
    chunks: int = Field(default=0, description="索引片段数")

class KBDocumentUpdateRequest(BaseModel):
    content: str = Field(..., description="新文档内容", min_length=1)

class KBDocumentUpdateResponse(BaseModel):
    id: str = Field(..., description="文档ID")
    chunks: int = Field(default=0, description="更新后的索引片段数")

class KBDocumentDeleteResponse(BaseModel):
    success: bool = Field(..., description="操作是否成功")
    removed_vectors: int = Field(default=0, description="移除的向量数")

class KBDocumentReindexResponse(BaseModel):
    chunks: int = Field(default=0, description="重新索引的片段数")

class HealthResponse(BaseModel):
    status: str = Field(..., description="服务状态")
    version: str = Field(..., description="版本号")
    services: Dict[str, bool] = Field(..., description="各服务状态")

class RefineSolutionRequest(BaseModel):
    original_demand: str = Field(..., description="原始客户需求")
    current_solution: str = Field(..., description="当前方案内容（Markdown）")
    follow_up: str = Field(..., description="用户的追问/优化要求")
    conversation_history: Optional[List[Dict[str, str]]] = Field(default_factory=list, description="历史追问对话记录")

class RefineSolutionResponse(BaseModel):
    refined_solution: str = Field(..., description="优化后的方案（Markdown格式）")
    follow_up: str = Field(..., description="本次追问内容")

class RefineCompetitorRequest(BaseModel):
    original_competitor: str = Field(..., description="原始竞品名称")
    original_industry: str = Field(..., description="原始行业名称")
    current_analysis: str = Field(..., description="当前分析报告内容（Markdown）")
    follow_up: str = Field(..., description="用户的追问/优化要求", min_length=1)
    conversation_history: Optional[List[Dict[str, str]]] = Field(default_factory=list, description="历史追问对话记录")

class RefineCompetitorResponse(BaseModel):
    refined_analysis: str = Field(..., description="优化后的分析报告（Markdown格式）")
    follow_up: str = Field(..., description="本次追问内容")

class UpdateSolutionRequest(BaseModel):
    solution: str = Field(..., description="更新后的完整方案内容（Markdown格式）")

class UpdateSolutionResponse(BaseModel):
    success: bool = Field(..., description="更新是否成功")
    message: str = Field(default="方案已更新", description="操作消息")


class HistoryFlagResponse(BaseModel):
    success: bool = Field(..., description="操作是否成功")
    archived: Optional[bool] = Field(default=None, description="最新归档状态")
    downloaded: Optional[bool] = Field(default=None, description="最新下载状态")
    message: str = Field(default="", description="操作消息")


class HistoryFollowUpRequest(BaseModel):
    follow_up: str = Field(..., description="用户的追问/优化要求")
    refined_solution: str = Field(..., description="LLM 优化后的方案/分析报告（Markdown）")
    conversation_history: Optional[List[Dict[str, str]]] = Field(default=None, description="完整对话记录（提供则以此覆盖）")


class HistoryFollowUpResponse(BaseModel):
    success: bool = Field(..., description="操作是否成功")
    conversation: List[Dict[str, str]] = Field(default_factory=list, description="更新后的完整对话记录")
    message: str = Field(default="", description="操作消息")


class DashboardStatsResponse(BaseModel):
    industry_coverage: Dict[str, int] = Field(default_factory=dict, description="各行业文档覆盖数量")
    match_trends: List[Dict[str, Any]] = Field(default_factory=list, description="最近7天匹配趋势")
    competitor_frequency: Dict[str, float] = Field(default_factory=dict, description="竞品分析频次统计（百分比，全局共享）")
    recent_matches: int = Field(default=0, description="近7天匹配次数")
    recent_analyses: int = Field(default=0, description="近7天分析次数")
    match_growth: Optional[float] = Field(default=None, description="方案匹配7日环比涨幅（百分比），None表示前一区间无数据（新增长）")
    analyze_growth: Optional[float] = Field(default=None, description="竞品分析7日环比涨幅（百分比），None表示前一区间无数据（新增长）")
    total_documents: int = Field(default=0, description="知识库文档总数")
    competitor_companies: List[str] = Field(default_factory=list, description="竞品厂商列表")
    accuracy: int = Field(default=87, description="方案覆盖度（百分比）")
    system_uptime: str = Field(default="--", description="系统运行时间")
    last_update: str = Field(default="--", description="最后更新时间")
    version: str = Field(default="v1.0.0", description="系统版本号")


class ExportRequest(BaseModel):
    report_type: str = Field(..., description="报告类型: solution/competitor")
    format: str = Field(default="word", description="导出格式: word/pdf")
    title: Optional[str] = Field(default=None, description="报告标题")
    content: Optional[str] = Field(default="", description="报告内容（Markdown格式），优先使用 solution_json，content 为兜底")
    solution_json: Optional[Any] = Field(default=None, description="结构化方案（章节+要点），优先于 content 直接生成报告")
    source_documents: Optional[List[Dict[str, Any]]] = Field(default=None, description="参考文档")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="元数据")
    cost_reference: Optional[Dict[str, Any]] = Field(default=None, description="成本参考附表（前端成本卡片编辑态：industry/is_default/description/disclaimer/collected_at/region/rows[]），导出时以原生表格渲染，不进入 Markdown 正文")


class ExportResultResponse(BaseModel):
    task_id: str = Field(..., description="任务ID")
    status: str = Field(..., description="任务状态")
    file_name: Optional[str] = Field(default=None, description="文件名")
    download_url: Optional[str] = Field(default=None, description="下载链接")
    file_size: Optional[int] = Field(default=None, description="文件大小（字节）")
    error_message: Optional[str] = Field(default=None, description="错误信息")

# ========== 历史记录（方案匹配回溯 & 对比） ==========

class MatchHistoryItem(BaseModel):
    id: int = Field(..., description="记录ID")
    demand_text: str = Field(..., description="客户需求描述")
    solution_preview: str = Field(default="", description="方案内容预览（前500字）")
    industry: str = Field(default="", description="识别出的行业")
    created_at: str = Field(..., description="创建时间")
    downloaded: bool = Field(default=False, description="是否已下载到本地")
    archived: bool = Field(default=False, description="是否已归档锁定")
    # 方案版本化
    group_id: Optional[int] = Field(default=None, description="版本分组 ID")
    version: Optional[int] = Field(default=1, description="版本号，从 1 开始")
    is_final: bool = Field(default=False, description="是否为定稿版本")
    title: Optional[str] = Field(default=None, description="方案分组标题")

class MatchHistoryDetail(BaseModel):
    id: int = Field(..., description="记录ID")
    demand_text: str = Field(..., description="客户需求描述")
    solution: str = Field(..., description="完整方案内容（Markdown）")
    industry: str = Field(default="", description="识别出的行业")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="参考文档列表")
    created_at: str = Field(..., description="创建时间")
    downloaded: bool = Field(default=False, description="是否已下载到本地")
    archived: bool = Field(default=False, description="是否已归档锁定")
    conversation: List[Dict[str, str]] = Field(default_factory=list, description="追问优化对话记录")
    # 方案版本化
    group_id: Optional[int] = Field(default=None, description="版本分组 ID")
    version: Optional[int] = Field(default=1, description="版本号，从 1 开始")
    is_final: bool = Field(default=False, description="是否为定稿版本")
    title: Optional[str] = Field(default=None, description="方案分组标题")

class MatchHistoryListResponse(BaseModel):
    items: List[MatchHistoryItem] = Field(default_factory=list, description="历史记录列表")
    total: int = Field(default=0, description="总记录数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页条数")
    total_pages: int = Field(default=0, description="总页数")

class CompareRequest(BaseModel):
    id_a: int = Field(..., description="方案A的记录ID")
    id_b: int = Field(..., description="方案B的记录ID")

class CompareResponse(BaseModel):
    item_a: MatchHistoryDetail = Field(..., description="方案A详情")
    item_b: MatchHistoryDetail = Field(..., description="方案B详情")

class CompareSummaryRequest(BaseModel):
    id_a: int = Field(..., description="方案A的记录ID")
    id_b: int = Field(..., description="方案B的记录ID")

class CompareSummaryResponse(BaseModel):
    summary: str = Field(..., description="AI智能对比总结")

# ========== 竞品分析历史记录 ==========

class CompetitorHistoryItem(BaseModel):
    id: int = Field(..., description="记录ID")
    competitor: str = Field(..., description="竞品名称")
    industry: str = Field(default="", description="行业名称")
    analysis_preview: str = Field(default="", description="分析报告预览（前500字）")
    created_at: str = Field(..., description="创建时间")
    downloaded: bool = Field(default=False, description="是否已下载到本地")
    archived: bool = Field(default=False, description="是否已归档锁定")

class CompetitorHistoryDetail(BaseModel):
    id: int = Field(..., description="记录ID")
    competitor: str = Field(..., description="竞品名称")
    industry: str = Field(default="", description="行业名称")
    analysis: str = Field(..., description="完整分析报告（Markdown）")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="参考文档列表")
    created_at: str = Field(..., description="创建时间")
    downloaded: bool = Field(default=False, description="是否已下载到本地")
    archived: bool = Field(default=False, description="是否已归档锁定")
    conversation: List[Dict[str, str]] = Field(default_factory=list, description="追问优化对话记录")

class CompetitorHistoryListResponse(BaseModel):
    items: List[CompetitorHistoryItem] = Field(default_factory=list, description="历史记录列表")
    total: int = Field(default=0, description="总记录数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页条数")
    total_pages: int = Field(default=0, description="总页数")

# ========== 成就勋章 ==========

class AchievementItem(BaseModel):
    id: str = Field(..., description="成就ID")
    name: str = Field(..., description="成就名称（未解锁隐藏成就显示 ???）")
    description: str = Field(..., description="成就描述（未解锁隐藏成就显示占位文本）")
    rarity: str = Field(..., description="稀有度: copper/silver/gold/diamond/hidden")
    rarity_name: str = Field(..., description="稀有度中文名")
    icon: str = Field(..., description="成就图标")
    unlocked: bool = Field(..., description="是否已解锁")
    unlocked_at: Optional[str] = Field(default=None, description="解锁时间")
    is_hidden: Optional[bool] = Field(default=False, description="是否为隐藏成就")

class AchievementListResponse(BaseModel):
    items: List[AchievementItem] = Field(default_factory=list, description="成就列表")
    total: int = Field(..., description="成就总数")
    unlocked: int = Field(default=0, description="已解锁数量")
    hidden_total: int = Field(default=0, description="隐藏成就总数")
    hidden_unlocked: int = Field(default=0, description="已解锁隐藏成就数")
    percent: float = Field(default=0, description="完成百分比")

class AchievementUnlockNotification(BaseModel):
    id: str = Field(..., description="成就ID")
    name: str = Field(..., description="成就名称")
    description: str = Field(..., description="成就描述")
    rarity: str = Field(..., description="稀有度")
    rarity_name: str = Field(..., description="稀有度中文名")
    icon: str = Field(..., description="成就图标")
    is_hidden: bool = Field(default=False, description="是否为隐藏成就")

# ========== Agent 交互式澄清（阶段 2.5） ==========

class ClarifyRequest(BaseModel):
    clarify_id: str = Field(..., description="澄清会话 ID（由 Agent 首次暂停时下发）")
    answers: List[Dict[str, str]] = Field(default_factory=list, description="用户对每个问题的回答，形如 [{'question': '...', 'answer': '...'}]")
    client_id: Optional[int] = Field(default=None, description="客户档案 ID，需与首次匹配一致以复用同一记忆维度")

class ClarifyAnswer(BaseModel):
    question: str = Field(..., description="被回答的问题")
    answer: str = Field(..., description="用户给出的回答")

# ========== 方案版本化 ==========

class HistoryVersionItem(BaseModel):
    id: int = Field(..., description="版本记录ID")
    version: int = Field(..., description="版本号")
    is_final: bool = Field(default=False, description="是否定稿")
    title: str = Field(default="", description="方案分组标题")
    demand_text: str = Field(default="", description="关联需求")
    industry: str = Field(default="", description="行业")
    created_at: str = Field(..., description="创建时间")
    solution_preview: str = Field(default="", description="方案预览（前300字）")

class HistoryGroupResponse(BaseModel):
    group_id: int = Field(..., description="版本分组 ID")
    title: str = Field(default="", description="方案分组标题")
    demand_text: str = Field(default="", description="关联需求")
    total_versions: int = Field(default=0, description="版本总数")
    final_version: Optional[int] = Field(default=None, description="已定稿的版本号（若有）")
    versions: List[HistoryVersionItem] = Field(default_factory=list, description="按版本号升序排列的版本列表")

class FinalizeResponse(BaseModel):
    success: bool = Field(..., description="操作是否成功")
    id: int = Field(..., description="被定稿的版本记录ID")
    group_id: int = Field(..., description="所属分组ID")
    version: int = Field(..., description="被定稿的版本号")
    message: str = Field(default="", description="操作消息")

class RollbackResponse(BaseModel):
    success: bool = Field(..., description="操作是否成功")
    source_id: int = Field(..., description="被回滚（复制）的源版本ID")
    new_id: int = Field(..., description="新生成的版本记录ID")
    group_id: int = Field(..., description="所属分组ID")
    version: int = Field(..., description="新版本号")
    message: str = Field(default="", description="操作消息")
