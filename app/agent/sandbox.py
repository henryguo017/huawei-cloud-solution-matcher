"""
Agent 代码沙箱执行器（S0：subprocess 隔离运行用户代码，生成真实产物）

设计要点（对齐 docs/sandbox_s0_architecture.md）：
- 沙箱目录：data/user_docs/{uid}/generated_solutions/sb_{uuid}/，复用 file_security.safe_resolve 做 jail。
- run_code() 在隔离 subprocess 里跑 Python，生成 pptx/xlsx 等真实文件。
- raw 优先：把 subprocess 的 stdout/stderr **逐行原样**透传为 exec_stdout/exec_stderr 事件，
  不加工成摘要（这是对标 Codex「看它干活」体感的关键）。
- 产物自动扫描：执行完扫描 jail，对 .pptx/.xlsx/.png 等发 file_created 事件。
- 安全底线：jail（safe_resolve）+ 低权限（继承 www-data）+ 禁网（Linux unshare）+ 资源限（RLIMIT）+ 超时硬杀 + env 剥离密钥 + 输出截断。

跨平台：Linux 用 preexec_fn 设 RLIMIT + unshare 禁网；Windows 开发环境无这些能力，自动跳过（仅缺 net-off，其余隔离仍生效）。
"""

import os
import sys
import json
import uuid
import asyncio
import logging
from typing import Optional, Callable, Awaitable, Dict, Any, List

from app.config import (
    SANDBOX_ENABLED,
    SANDBOX_TIMEOUT,
    SANDBOX_MAX_OUTPUT,
    SANDBOX_NET_OFF,
    SANDBOX_CPU,
    SANDBOX_MEM,
    SANDBOX_NPROC,
)
from app.agent.file_security import safe_resolve

logger = logging.getLogger(__name__)

# 允许交付的产物后缀
ARTIFACT_EXTS = (".pptx", ".xlsx", ".png", ".csv", ".json", ".txt", ".md", ".html")

# L2 结构化事件前缀：脚本 print('<<EVT>> {"type": "...", "data": {...}}') 触发
EVT_PREFIX = "<<EVT>>"

# CLONE_NEWNET（Linux 禁网用，避免 import 失败）
_CLONE_NEWNET = 0x40000000


def _sandbox_preexec() -> None:
    """仅 Linux：subprocess 启动前设资源限 + 禁网。Windows 不会传此函数。"""
    try:
        import resource  # type: ignore

        try:
            resource.setrlimit(resource.RLIMIT_CPU, (SANDBOX_CPU, SANDBOX_CPU))
        except Exception as e:
            logger.warning(f"[Sandbox] setrlimit CPU 失败: {e}")
        try:
            resource.setrlimit(resource.RLIMIT_AS, (SANDBOX_MEM, SANDBOX_MEM))
        except Exception as e:
            logger.warning(f"[Sandbox] setrlimit AS 失败: {e}")
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (SANDBOX_NPROC, SANDBOX_NPROC))
        except Exception as e:
            logger.warning(f"[Sandbox] setrlimit NPROC 失败: {e}")
    except ImportError:
        pass
    if SANDBOX_NET_OFF:
        try:
            os.unshare(_CLONE_NEWNET)
        except Exception as e:
            logger.warning(f"[Sandbox] unshare 禁网失败（可能无权限/非 Linux）: {e}")


def _build_safe_env(jail_abs: str) -> Dict[str, str]:
    """构造最小 env：剥离所有密钥，只保留运行 Python 必需项。"""
    env: Dict[str, str] = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": jail_abs,
        "TMPDIR": jail_abs,
        "TEMP": jail_abs,
        "TMP": jail_abs,
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",  # 强制子进程 stdout/stderr 用 UTF-8（Windows 默认 GBK 会乱码）
        "PYTHONUTF8": "1",
    }
    # Windows 需要这些才能跑 python；Linux 无关紧要，带上无害
    for k in ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "LANG", "LC_ALL", "USERPROFILE"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


async def run_code(
    code: str,
    user_id: int,
    event_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    """
    在隔离沙箱里运行 Python 代码，返回产物信息。

    返回结构（Observation 给 LLM 看，也驱动前端事件）：
    {
        "ok": bool, "error": str, "stdout": str, "stderr": str,
        "files": [{"path": rel, "name", "size", "kind"}], "sandbox_rel": str
    }
    """
    if not SANDBOX_ENABLED:
        return {"ok": False, "error": "沙箱未启用（SANDBOX_ENABLED=false）", "stdout": "", "stderr": "", "files": []}
    if user_id <= 0:
        return {"ok": False, "error": "未登录用户不可使用代码沙箱", "stdout": "", "stderr": "", "files": []}
    if not code or not code.strip():
        return {"ok": False, "error": "代码为空", "stdout": "", "stderr": "", "files": []}

    # 建 jail 目录（safe_resolve 校验落在用户根内）
    sb_id = uuid.uuid4().hex[:12]
    rel = f"generated_solutions/sb_{sb_id}"
    try:
        jail_abs = safe_resolve(user_id, rel)
    except ValueError as e:
        return {"ok": False, "error": f"路径校验失败: {e}", "stdout": "", "stderr": "", "files": []}
    os.makedirs(jail_abs, exist_ok=True)
    script_path = os.path.join(jail_abs, "task.py")

    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)
    except Exception as e:
        return {"ok": False, "error": f"写入脚本失败: {e}", "stdout": "", "stderr": "", "files": []}

    async def emit(ev: Dict[str, Any]) -> None:
        if event_callback:
            try:
                await event_callback(ev)
            except Exception as e:
                logger.warning(f"[Sandbox] 事件回调失败: {e}")

    await emit({"type": "exec_cmd", "cmd": f"python task.py  (sandbox: {rel})"})

    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []
    total_out = 0

    async def _pump(stream, chunks, ev_type):
        nonlocal total_out
        assert stream is not None
        while True:
            raw = await stream.readline()
            if not raw:
                break
            text = raw.decode("utf-8", errors="replace")
            stripped = text.rstrip("\n").rstrip("\r")

            # L2 结构化事件透传（脚本主动发 <<EVT>> {...}）
            if stripped.startswith(EVT_PREFIX):
                try:
                    payload = json.loads(stripped[len(EVT_PREFIX):].strip())
                    await emit({"type": payload.get("type", "tool_log"), **payload.get("data", {})})
                    continue
                except Exception:
                    pass

            chunks.append(text)
            total_out += len(text)
            if total_out > SANDBOX_MAX_OUTPUT:
                # 超限：只透传、不再累计，防撑爆
                await emit({"type": ev_type, "line": text})
                continue
            await emit({"type": ev_type, "line": text})

    # Windows 不支持 preexec_fn（asyncio 限制）；Linux 才传（设 RLIMIT + 禁网）
    use_preexec = os.name != "nt"

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "task.py",
            cwd=jail_abs,
            env=_build_safe_env(jail_abs),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **({"preexec_fn": _sandbox_preexec} if use_preexec else {}),
        )
        await asyncio.wait_for(
            asyncio.gather(
                _pump(proc.stdout, stdout_chunks, "exec_stdout"),
                _pump(proc.stderr, stderr_chunks, "exec_stderr"),
            ),
            timeout=SANDBOX_TIMEOUT,
        )
        rc = await proc.wait()
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        await emit({"type": "exec_status", "status": "error", "code": -1, "reason": "timeout"})
        return {
            "ok": False,
            "error": f"执行超时（>{SANDBOX_TIMEOUT}s 已被强制终止）",
            "stdout": "".join(stdout_chunks)[-SANDBOX_MAX_OUTPUT:],
            "stderr": "".join(stderr_chunks)[-SANDBOX_MAX_OUTPUT:],
            "files": [],
        }
    except Exception as e:
        logger.error(f"[Sandbox] 执行异常: {e}")
        await emit({"type": "exec_status", "status": "error", "code": -2, "reason": str(e)})
        return {
            "ok": False,
            "error": f"执行异常: {e}",
            "stdout": "".join(stdout_chunks)[-SANDBOX_MAX_OUTPUT:],
            "stderr": "".join(stderr_chunks)[-SANDBOX_MAX_OUTPUT:],
            "files": [],
        }

    # 清点产物
    files = []
    try:
        for name in sorted(os.listdir(jail_abs)):
            if name == "task.py":
                continue
            full = os.path.join(jail_abs, name)
            if os.path.isfile(full) and name.lower().endswith(ARTIFACT_EXTS):
                rel_path = f"{rel}/{name}"
                size = os.path.getsize(full)
                kind = os.path.splitext(name)[1].lstrip(".").lower()
                files.append({"path": rel_path, "name": name, "size": size, "kind": kind})
                await emit({"type": "file_created", "path": rel_path, "name": name, "size": size, "kind": kind})
    except Exception as e:
        logger.warning(f"[Sandbox] 产物清点失败: {e}")

    await emit({"type": "exec_status", "status": "done" if rc == 0 else "error", "code": rc})

    return {
        "ok": rc == 0,
        "error": "" if rc == 0 else f"脚本退出码 {rc}",
        "stdout": "".join(stdout_chunks)[-SANDBOX_MAX_OUTPUT:],
        "stderr": "".join(stderr_chunks)[-SANDBOX_MAX_OUTPUT:],
        "files": files,
        "sandbox_rel": rel,
    }
