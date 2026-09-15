"""
文件安全层 —— 阶段1 文件交互的基石

所有面向用户文件的操作（读取/落盘/列举）都必须先经过这里的校验，
确保路径永远落在 data/user_docs/{user_id}/ 内，杜绝 ../ 穿越与符号链接逃逸。
"""
import os
from pathlib import Path

from app.config import USER_DOCS_BASE_DIR

# 用户根目录下的两个受管子目录
UPLOAD_SUBDIR = "customer_uploads"
SOLUTION_SUBDIR = "generated_solutions"


def get_user_root(user_id: int) -> Path:
    """返回 data/user_docs/{user_id}/ 的 Path"""
    return Path(USER_DOCS_BASE_DIR) / str(user_id)


def ensure_user_dirs(user_id: int) -> Path:
    """创建并校验用户的受管子目录，返回用户根目录 Path"""
    root = get_user_root(user_id)
    (root / UPLOAD_SUBDIR).mkdir(parents=True, exist_ok=True)
    (root / SOLUTION_SUBDIR).mkdir(parents=True, exist_ok=True)
    return root


def safe_resolve(user_id: int, relative_path: str) -> str:
    """
    把相对路径（如 'customer_uploads/foo.docx'）解析为绝对路径字符串，
    并校验其落在 data/user_docs/{user_id}/ 内。

    Raises:
        ValueError: 路径越界（绝对路径 / ../ 穿越 / 符号链接逃逸）
    """
    if not relative_path:
        raise ValueError("path not allowed: empty")
    root = get_user_root(user_id).resolve()
    root.mkdir(parents=True, exist_ok=True)

    # 拒绝明显的绝对路径
    if os.path.isabs(relative_path):
        raise ValueError("path not allowed: absolute path")

    target = (root / relative_path).resolve()

    # 防 ../ 穿越与符号链接逃逸（resolve 已展开符号链接）
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("path not allowed: escapes user root")

    return str(target)


def safe_upload_path(user_id: int, filename: str) -> str:
    """返回文件应保存的绝对路径（落在 customer_uploads/ 内），并校验文件名安全"""
    # 去除可能携带的目录成分，仅保留纯文件名
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name in (".", ".."):
        raise ValueError("invalid filename")
    root = ensure_user_dirs(user_id)
    return str(root / UPLOAD_SUBDIR / safe_name)


def safe_solution_path(user_id: int, filename: str) -> str:
    """返回方案落盘的绝对路径（落在 generated_solutions/ 内）"""
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name in (".", ".."):
        raise ValueError("invalid filename")
    root = ensure_user_dirs(user_id)
    return str(root / SOLUTION_SUBDIR / safe_name)
