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

class AnalyzeResponse(BaseModel):
    answer: str = Field(..., description="分析结果（Markdown格式）")
    source_documents: List[SourceDocument] = Field(default_factory=list, description="参考文档列表")

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
