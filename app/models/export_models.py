from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime
import uuid


class ExportFormat(str, Enum):
    WORD = "word"
    PDF = "pdf"


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
    task_id: str = str(uuid.uuid4())
    status: TaskStatus = TaskStatus.PENDING
    format: ExportFormat
    report_type: ReportType
    create_time: datetime = datetime.now()
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
