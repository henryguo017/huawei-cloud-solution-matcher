"""
统一错误枚举与全局异常（ruoyi-ai 学习项 #5）

设计原则（不破坏现有行为）：
- 现有接口仍走 FastAPI 默认的 HTTPException（返回 {"detail": ...}），前端依赖不变。
- 本模块新增 `AppError` + `ErrorCode` 枚举，供**新代码**抛出结构化错误。
- 仅注册 `AppError` 的全局 handler，返回 {"code","message","detail"}，不影响其它异常。
- 旧代码无需改动即可继续工作；未来新增接口建议统一使用 `raise AppError(ErrorCode.XXX, "...")`。
"""
from enum import IntEnum
from fastapi.responses import JSONResponse


class ErrorCode(IntEnum):
    """统一业务错误码。新增错误类型时在此追加，禁止复用已占用的数字。"""

    # 通用（1000+）
    INTERNAL_ERROR = 1000
    BAD_REQUEST = 1001
    FORBIDDEN = 1003
    NOT_FOUND = 1004
    RATE_LIMITED = 1005

    # 业务域（2000+）
    KB_NOT_READY = 2001          # 知识库未初始化
    KB_REBUILD_FAILED = 2002     # 知识库重建失败
    AGENT_RUN_FAILED = 2003      # Agent 执行失败
    RETRIEVAL_FAILED = 2004      # 检索失败
    EXPORT_FAILED = 2005         # 报告导出失败
    INVALID_PARAM = 2006         # 参数校验失败（业务层自定义）
    FILE_NOT_SUPPORTED = 2007    # 不支持的文件格式


class AppError(Exception):
    """统一应用异常。携带错误码 + 人类可读信息 + 可选细节。"""

    def __init__(self, code: ErrorCode, message: str, detail=None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.http_status = http_status

    def to_dict(self):
        return {
            "code": int(self.code),
            "message": self.message,
            "detail": self.detail,
        }


def app_error_handler(request, exc: AppError):
    """AppError 全局处理器：返回结构化错误体。"""
    return JSONResponse(
        status_code=exc.http_status,
        content=exc.to_dict(),
    )
