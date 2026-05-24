from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from api.models import ExportRequest
from app.models.export_models import ExportFormat, ReportType, ExportResult, TaskStatus
from app.services.report_generator import ReportGeneratorService
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

report_generator = ReportGeneratorService()


@router.post("/export/report", tags=["报告导出"])
async def export_report(request: ExportRequest):
    """
    导出报告
    
    - **report_type**: 报告类型（solution/competitor）
    - **format**: 导出格式（word/pdf）
    - **content**: 报告内容（Markdown格式）
    - **metadata**: 元数据（标题、客户名称等）
    """
    try:
        logger.info(f"开始生成报告，类型: {request.report_type}, 格式: {request.format}")
        
        task = report_generator.generate_report(
            report_type=request.report_type,
            content=request.content,
            format=request.format,
            metadata=request.metadata or {}
        )
        
        if task.status == TaskStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"报告生成失败: {task.error_message}"
            )
        
        return ExportResult(
            task_id=task.task_id,
            status=task.status,
            file_name=task.file_name,
            download_url=task.download_url,
            file_size=task.file_size
        )
        
    except Exception as e:
        logger.error(f"报告导出失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出失败: {str(e)}"
        )


@router.get("/export/task/{task_id}", tags=["报告导出"])
async def get_export_task(task_id: str):
    """
    查询导出任务状态
    
    - **task_id**: 任务ID
    """
    task = report_generator.get_task(task_id)
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}"
        )
    
    return ExportResult(
        task_id=task.task_id,
        status=task.status,
        file_name=task.file_name,
        download_url=task.download_url,
        file_size=task.file_size,
        error_message=task.error_message
    )


@router.get("/export/download/{task_id}", tags=["报告导出"])
async def download_report(task_id: str):
    """
    下载报告文件
    
    - **task_id**: 任务ID
    """
    file_path = report_generator.get_file_path(task_id)
    
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"文件不存在或任务未完成: {task_id}"
        )
    
    task = report_generator.get_task(task_id)
    
    return FileResponse(
        path=file_path,
        filename=task.file_name,
        media_type="application/octet-stream"
    )
