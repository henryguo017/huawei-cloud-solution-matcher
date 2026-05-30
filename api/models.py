from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

class MatchRequest(BaseModel):
    demand: str = Field(..., description="客户需求描述", min_length=1, max_length=5000)
    
    class Config:
        json_schema_extra = {
            "example": {
                "demand": "我们是一家中型制造企业，有50台生产设备，经常因为设备突发故障导致生产线停工，每次停工损失约5万元。"
            }
        }

class AnalyzeRequest(BaseModel):
    competitor: str = Field(..., description="竞争对手名称")
    industry: str = Field(..., description="行业名称")
    
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
    history_id: Optional[int] = Field(default=None, description="本次匹配的历史记录ID，用于后续更新优化方案")

class AnalyzeResponse(BaseModel):
    answer: str = Field(..., description="分析结果（Markdown格式）")
    source_documents: List[SourceDocument] = Field(default_factory=list, description="参考文档列表")
    history_id: Optional[int] = Field(default=None, description="本次分析的历史记录ID")

class KnowledgeStatsResponse(BaseModel):
    total_documents: int = Field(..., description="总文档片段数")
    supported_industries: List[str] = Field(default_factory=list, description="支持的行业列表")
    industry_counts: Dict[str, int] = Field(default_factory=dict, description="各行业文档数量")
    accuracy: int = Field(default=50, description="匹配准确率（百分比）")

class RebuildResponse(BaseModel):
    count: int = Field(..., description="重建的文档数量")
    message: str = Field(default="知识库重建成功", description="操作消息")

class ClearResponse(BaseModel):
    success: bool = Field(..., description="操作是否成功")
    message: str = Field(default="知识库已清空", description="操作消息")

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


class DashboardStatsResponse(BaseModel):
    industry_coverage: Dict[str, int] = Field(default_factory=dict, description="各行业文档覆盖数量")
    match_trends: List[Dict[str, Any]] = Field(default_factory=list, description="最近7天匹配趋势")
    competitor_frequency: Dict[str, float] = Field(default_factory=dict, description="竞品分析频次统计（百分比，全局共享）")
    recent_matches: int = Field(default=0, description="近7天匹配次数")
    recent_analyses: int = Field(default=0, description="近7天分析次数")
    match_growth: Optional[float] = Field(default=None, description="方案匹配7日环比涨幅（百分比），None表示前一区间无数据（新增长）")
    analyze_growth: Optional[float] = Field(default=None, description="竞品分析7日环比涨幅（百分比），None表示前一区间无数据（新增长）")
    total_documents: int = Field(default=0, description="知识库文档总数")
    accuracy: int = Field(default=87, description="匹配准确率（百分比）")
    system_uptime: str = Field(default="--", description="系统运行时间")
    last_update: str = Field(default="--", description="最后更新时间")
    version: str = Field(default="v1.0.0", description="系统版本号")


class ExportRequest(BaseModel):
    report_type: str = Field(..., description="报告类型: solution/competitor")
    format: str = Field(default="word", description="导出格式: word/pdf")
    title: Optional[str] = Field(default=None, description="报告标题")
    content: str = Field(..., description="报告内容（Markdown格式）")
    source_documents: Optional[List[Dict[str, Any]]] = Field(default=None, description="参考文档")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="元数据")


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

class MatchHistoryDetail(BaseModel):
    id: int = Field(..., description="记录ID")
    demand_text: str = Field(..., description="客户需求描述")
    solution: str = Field(..., description="完整方案内容（Markdown）")
    industry: str = Field(default="", description="识别出的行业")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="参考文档列表")
    created_at: str = Field(..., description="创建时间")

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

class CompetitorHistoryDetail(BaseModel):
    id: int = Field(..., description="记录ID")
    competitor: str = Field(..., description="竞品名称")
    industry: str = Field(default="", description="行业名称")
    analysis: str = Field(..., description="完整分析报告（Markdown）")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="参考文档列表")
    created_at: str = Field(..., description="创建时间")

class CompetitorHistoryListResponse(BaseModel):
    items: List[CompetitorHistoryItem] = Field(default_factory=list, description="历史记录列表")
    total: int = Field(default=0, description="总记录数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页条数")
    total_pages: int = Field(default=0, description="总页数")
