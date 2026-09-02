from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime
import uuid


class ExportFormat(str, Enum):
    WORD = "word"
    PDF = "pdf"
    # PPTX：P2-D4 演示稿导出。缺此项会导致 report_generator._render_and_save 中
    # `elif format == ExportFormat.PPTX` 抛 AttributeError，进而使 PDF 分支（else）
    # 也永远走不到 —— 即 PDF 与 PPTX 导出同时失效。改动此枚举务必同步检查该分支。
    PPTX = "pptx"


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportType(str, Enum):
    SOLUTION = "solution"
    COMPETITOR = "competitor"


class ExportRequest(BaseModel):
    report_type: ReportType
    format: ExportFormat = ExportFormat.WORD
    title: Optional[str] = None
    content: str
    source_documents: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None


class ExportTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    format: ExportFormat
    report_type: ReportType
    create_time: datetime = Field(default_factory=datetime.now)
    complete_time: Optional[datetime] = None
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    download_url: Optional[str] = None
    error_message: Optional[str] = None


class ExportResult(BaseModel):
    task_id: str
    status: TaskStatus
    file_name: Optional[str] = None
    download_url: Optional[str] = None
    file_size: Optional[int] = None
    generation_time_ms: Optional[int] = None
    error_message: Optional[str] = None


class ReportContent(BaseModel):
    title: str
    subtitle: Optional[str] = None
    create_date: str
    customer_name: Optional[str] = None
    chapters: List[Dict[str, Any]]
    appendix: Optional[List[Dict[str, Any]]] = None
