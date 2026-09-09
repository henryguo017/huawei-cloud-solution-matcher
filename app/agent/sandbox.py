"""
run_python 沙箱 —— 受限 Python 代码执行（L4 P0-T1.1）

安全模型（纵深五层，2026-09-09 设计定稿 docs/l4-roadmap-2026-09-09.md §T1.1）：
1. AST 静态预检（执行前）：白名单 import + 黑名单内建 + dunder 访问全禁，
   命中直接拒绝，代码根本不进子进程；
2. 隔解释释器：`python -I`（isolated）——不加载 site/user 包，不读 PYTHONPATH；
3. 最小环境变量：子进程 env 只含启动必需项，**拿不到任何 API key/token**；
4. POSIX rlimit 五重限制（Windows 本地开发自动降级，生产 ECS 全量生效）：
   CPU 5s / 内存 128MB / 禁写文件(FSIZE=0) / NPROC 16 / NOFILE 32；
5. 硬超时 kill + 输出截断（stdout 4KB / stderr 1KB）。

权限：默认 ask（harness.DEFAULT_TOOL_POLICY），走现有 human-in-the-loop 弹窗。
"""

import ast
import asyncio
import logging
import os
import subprocess
import sys
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------- 常量 ----------

CODE_MAX_CHARS = 8000
RUN_TIMEOUT = 5          # 秒（含启动），超时 kill
STDOUT_MAX = 4096
STDERR_MAX = 1024

# 白名单模块（标准库只读纯计算子集）
ALLOWED_MODULES = {
    "json", "re", "math", "statistics", "datetime", "itertools",
    "collections", "csv", "io", "textwrap", "decimal", "fractions",
}

# 黑名单内建名（逃逸/外联/挂起路径）
BANNED_BUILTINS = {
    "eval", "exec", "compile", "open", "input", "__import__",
    "getattr", "setattr", "delattr", "globals", "locals", "vars",
    "breakpoint", "help", "exit", "quit",
}

# POSIX rlimit 配置：(resource 常量, 软限, 硬限)
_RLIMITS = None  # 惰性初始化


def _get_rlimits():
    global _RLIMITS
    if _RLIMITS is None:
        try:
            import resource
            _RLIMITS = [
                (resource.RLIMIT_CPU, 5, 5),
                (resource.RLIMIT_AS, 128 * 1024 * 1024, 128 * 1024 * 1024),
                (resource.RLIMIT_FSIZE, 0, 0),                  # 禁写任何文件
                (resource.RLIMIT_NPROC, 16, 16),                # 防 fork 炸弹
                (resource.RLIMIT_NOFILE, 32, 32),
            ]
        except ImportError:
            # Windows 本地开发无 resource 模块：降级（AST+超时+隔离仍在）
            _RLIMITS = []
    return _RLIMITS


# ---------- AST 静态预检 ----------

def precheck(code: str) -> Optional[str]:
    """静态安全预检。返回 None=通过；返回字符串=拒绝原因。"""
    if not code or not code.strip():
        return "代码为空"
    if len(code) > CODE_MAX_CHARS:
        return f"代码超长（>{CODE_MAX_CHARS} 字符）"
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"语法错误：{e}"

    for node in ast.walk(tree):
        # import 白名单
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_MODULES:
                    return f"禁止 import {alias.name}（非白名单模块）"
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                return "禁止相对导入"
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_MODULES:
                return f"禁止 from {node.module} import（非白名单模块）"
        # 黑名单内建调用
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in BANNED_BUILTINS:
                return f"禁止调用 {fn.id}()"
        # dunder 访问全禁（__class__/__subclasses__/__globals__/__builtins__ 等逃逸路径）
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                return f"禁止访问双下划线属性 .{node.attr}()"
        elif isinstance(node, ast.Name):
            if node.id in BANNED_BUILTINS and isinstance(node.ctx, ast.Load):
                # 裸引用黑名单名（如 x = __builtins__）——调用在 Call 里拦，这里拦取值传递
                return f"禁止引用 {node.id}"
            if node.id.startswith("__") and node.id.endswith("__"):
                return f"禁止引用双下划线名称 {node.id}"
    return None


# ---------- 子进程执行 ----------

def _minimal_env() -> Dict[str, str]:
    """子进程最小环境：绝不含 API key/token；只保留解释器启动必需项。"""
    if os.name == "nt":
        # Windows 启动 Python 需要 SystemRoot，否则初始化失败
        return {"SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PATH": "",
                "PYTHONIOENCODING": "utf-8"}
    return {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8"}


def _set_rlimits_posix():
    import resource  # noqa: F401 已在 _get_rlimits 校验
    for res, soft, hard in _get_rlimits():
        try:
            resource.setrlimit(res, (soft, hard))
        except Exception:
            pass


def _exec_blocking(code: str) -> Dict[str, object]:
    """阻塞执行（运行在 to_thread 线程池，不阻塞事件循环）。"""
    t0 = time.time()
    popen_kwargs: Dict[str, object] = dict(
        input=code.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_minimal_env(),
    )
    if os.name != "nt":
        popen_kwargs["preexec_fn"] = _set_rlimits_posix
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-X", "utf8"],   # -I 忽略 PYTHON* 环境变量，UTF-8 须用 -X
            timeout=RUN_TIMEOUT,
            **popen_kwargs,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "stdout": "", "stderr": f"执行超时（>{RUN_TIMEOUT}s，已终止）",
            "elapsed": round(time.time() - t0, 2), "truncated": False,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False, "stdout": "", "stderr": f"沙箱启动失败: {e}",
            "elapsed": round(time.time() - t0, 2), "truncated": False,
        }

    out = (proc.stdout or b"").decode("utf-8", errors="replace")
    err = (proc.stderr or b"").decode("utf-8", errors="replace")
    truncated = len(out) > STDOUT_MAX or len(err) > STDERR_MAX
    return {
        "ok": proc.returncode == 0,
        "stdout": out[:STDOUT_MAX],
        "stderr": err[:STDERR_MAX],
        "elapsed": round(time.time() - t0, 2),
        "truncated": truncated,
        "returncode": proc.returncode,
    }


async def run_python(code: str = "") -> Dict[str, object]:
    """工具入口：预检 → 线程池执行 → 结构化结果。

    任何拒绝/失败都以 ok=False + stderr 说明返回，绝不抛异常打断 ReAct 循环。
    """
    reason = precheck(code or "")
    if reason:
        logger.info("[run_python] 预检拒绝: %s", reason)
        return {"ok": False, "stdout": "", "stderr": f"拒绝执行：{reason}", "elapsed": 0.0}
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_exec_blocking, code), timeout=RUN_TIMEOUT + 5
        )
        logger.info(
            "[run_python] 执行完成 ok=%s elapsed=%s stdout_len=%s",
            result.get("ok"), result.get("elapsed"), len(str(result.get("stdout", ""))),
        )
        return result
    except asyncio.TimeoutError:
        logger.error("[run_python] 外层硬超时（线程池异常），已放弃")
        return {"ok": False, "stdout": "", "stderr": "执行超时（外层硬超时）", "elapsed": RUN_TIMEOUT + 5}
