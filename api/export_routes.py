from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from api.models import ExportRequest
from app.models.export_models import ExportResult, TaskStatus
from app.services.report_generator import ReportGeneratorService
from api.dependencies import rate_limit
from api.auth_dependencies import require_login
import logging
import os

logger = logging.getLogger(__name__)

router = APIRouter()

report_generator = ReportGeneratorService()


@router.post("/export/report", tags=["报告导出"])
async def export_report(
    request: ExportRequest,
    _: None = Depends(rate_limit(30, 60)),
):
    """
    导出报告
    
    - **report_type**: 报告类型（solution/competitor）
    - **format**: 导出格式（word/pdf）
    - **solution_json**: 结构化方案（章节+要点），优先于 content 直接生成报告
    - **content**: 报告内容（Markdown格式），solution_json 缺省时的兜底；二者至少提供一项
    - **metadata**: 元数据（标题、客户名称等）
    """
    try:
        logger.info(f"开始生成报告，类型: {request.report_type}, 格式: {request.format}")

        # 二者至少提供一项，否则明确报错（置于 try 外，避免被包裹成 500）
        if not request.solution_json and not request.content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="content 与 solution_json 至少需提供一项"
            )

        # 优先使用结构化 JSON（一键出方案书）；否则回退到 Markdown 解析
        if request.solution_json:
            task = report_generator.generate_report_from_json(
                report_type=request.report_type,
                chapters=request.solution_json,
                format=request.format,
                metadata=request.metadata or {},
                cost_reference=request.cost_reference
            )
        else:
            task = report_generator.generate_report(
                report_type=request.report_type,
                content=request.content,
                format=request.format,
                metadata=request.metadata or {},
                cost_reference=request.cost_reference
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
        
    except HTTPException:
        raise
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


# ============================================================
# Agent 代码沙箱产物下载（S0）
# ============================================================
# 沙箱生成的 .pptx/.xlsx 等落在 data/user_docs/{uid}/generated_solutions/sb_*/ 内，
# 经 file_security.safe_resolve 校验确保只落在当前登录用户的根目录内（防越权/穿越）。
_ALLOWED_ARTIFACT_EXTS = (".pptx", ".xlsx", ".png", ".csv", ".json", ".txt", ".md", ".html")


@router.get("/agent/artifact", tags=["Agent"])
async def agent_artifact(path: str, user: dict = Depends(require_login)):
    """
    下载 Agent 沙箱生成的产物文件。

    - **path**: 相对路径（如 generated_solutions/sb_xxx/cost.xlsx），由 run_code 事件回传。
      经 safe_resolve 强制落在当前用户 uid 根目录内，杜绝越权访问他人文件。
    """
    from app.agent.file_security import safe_resolve

    try:
        abs_path = safe_resolve(user["id"], path)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"非法路径: {e}")

    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在或已清理")

    if not abs_path.lower().endswith(_ALLOWED_ARTIFACT_EXTS):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的文件类型")

    return FileResponse(
        path=abs_path,
        filename=os.path.basename(abs_path),
        media_type="application/octet-stream",
    )
