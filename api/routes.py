from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse, FileResponse
from fastapi import UploadFile, File, BackgroundTasks, Form
from api.models import (
    MatchRequest, MatchResponse,
    AnalyzeRequest, AnalyzeResponse,
    KnowledgeStatsResponse, ClearResponse,
    TaskStatusResponse,
    HealthResponse, SourceDocument,
    DashboardStatsResponse,
    MatchHistoryListResponse, MatchHistoryItem, MatchHistoryDetail, CompareRequest, CompareResponse,
    CompareSummaryRequest, CompareSummaryResponse,
    RefineSolutionRequest, RefineSolutionResponse,
    UpdateSolutionRequest, UpdateSolutionResponse,
    RefineCompetitorRequest, RefineCompetitorResponse,
    CompetitorHistoryListResponse, CompetitorHistoryItem, CompetitorHistoryDetail,
    KBDocumentListResponse, KBDocumentCreateRequest,
    KBDocumentCreateResponse, KBDocumentUpdateRequest,
    KBDocumentUpdateResponse, KBDocumentDeleteResponse,
    KBDocumentReindexResponse, HistoryFlagResponse,
    HistoryFollowUpRequest, HistoryFollowUpResponse, ClientCreateRequest, ClientUpdateRequest,
    ClarifyRequest, UpdateHistoryClientRequest,
    HistoryGroupResponse, FinalizeResponse, RollbackResponse,
)
from api.platform_knowledge import PLATFORM_GUIDE, PLATFORM_BRIEF
from app.services.report_generator import ReportGeneratorService, ReportType, ExportFormat
from api.dependencies import (
    get_solution_matcher,
    get_competitor_analyzer,
    get_knowledge_base,
    get_usage_logger,
    get_achievement_service_dep,
    get_user_knowledge_base,
    get_solution_matcher_for_user,
    get_competitor_analyzer_for_user,
    _user_kb_cache,
)
from app.models.llm import get_llm_response, get_embedding_vectors
from app.services.knowledge_base import KnowledgeBaseService, set_kb_user_context, clear_kb_search_cache
from app.services.usage_logger import UsageLoggerService
from app.config import APP_VERSION, USER_DOCS_BASE_DIR, KNOWLEDGE_BASE_DIRECTORY, COMPETITOR_DIRECTORY, SUPPORTED_INDUSTRIES
from app.config import SSE_HEARTBEAT_ENABLED, SSE_HEARTBEAT_INTERVAL, SSE_TIMEOUT
from app.config import KB_REBUILD_CONCURRENCY
from app.agent.parsers.read_file import ALLOWED_EXT, extract_text
from typing import Optional, Dict
from datetime import datetime, date
import os
import re
import json
import asyncio
import time
import logging
import shutil
import threading
import uuid

from api.auth_dependencies import get_current_user, get_current_user_optional, require_login
import api.dependencies as _kb_deps  # 用于后台重建后刷新全局 KB 缓存（_global_kb）

# Agent 模块导入
from app.agent import get_agent

logger = logging.getLogger(__name__)

# SSE 生成器防御：遇到非标准 JSON 类型（Pydantic 模型/日期/集合等）时安全降级，
# 避免 json.dumps 抛 TypeError 静默切断流式连接（如 SourceDocument 序列化问题）
def _sse_json_default(obj):
    for attr in ("model_dump", "dict"):
        if hasattr(obj, attr):
            try:
                return getattr(obj, attr)()
            except Exception:
                pass
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", "replace")
    return str(obj)

router = APIRouter()

@router.get("/debug/echo-headers", tags=["调试"])
async def debug_echo_headers(request: Request):
    """
    临时诊断端点：回显后端实际收到的全部请求头。
    用于在浏览器登录后访问 https://www.cloudsol.cn/api/debug/echo-headers
    确认 Authorization 头是否真正到达后端（排查"刚登录即401"问题）。
    """
    headers = dict(request.headers)
    auth = headers.get('authorization', '(无)')
    return {
        "authorization_present": auth != '(无)',
        "authorization_preview": (auth[:30] + '...') if auth != '(无)' else None,
        "authorization_length": len(auth) if auth != '(无)' else 0,
        "origin": headers.get('origin', '(无)'),
        "host": headers.get('host', '(无)'),
        "all_header_keys": sorted(headers.keys()),
    }

@router.get("/health", response_model=HealthResponse, tags=["系统"])
async def health_check():
    """
    健康检查接口
    """
    try:
        kb_service = get_knowledge_base()
        kb_stats = kb_service.get_stats()
        
        return HealthResponse(
            status="healthy",
            version=APP_VERSION,
            services={
                "knowledge_base": True,
                "solution_matcher": True,
                "competitor_analyzer": True,
                "vector_db": kb_stats["total_documents"] > 0
            }
        )
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return HealthResponse(
            status="unhealthy",
            version=APP_VERSION,
            services={
                "knowledge_base": False,
                "solution_matcher": False,
                "competitor_analyzer": False,
                "vector_db": False
            }
        )

# ==================== 成本参考（方案成本估算器基础数据） ====================
# 数据文件 data/pricing_reference.json 被 gitignore，部署时需单独 scp 到服务器 data/ 目录。
# 进程内缓存 + 文件 mtime 重载，避免每次请求读盘。
_PRICING_CACHE: dict = {"data": None, "mtime": 0.0}

def _load_pricing_reference(force: bool = False) -> dict:
    """读取 data/pricing_reference.json（带 mtime 缓存）。文件缺失时返回空骨架，不抛 500。"""
    global _PRICING_CACHE
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pricing_reference.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    if force or _PRICING_CACHE["data"] is None or _PRICING_CACHE["mtime"] != mtime:
        try:
            with open(path, "r", encoding="utf-8") as f:
                _PRICING_CACHE["data"] = json.load(f)
            _PRICING_CACHE["mtime"] = mtime
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"读取价目表失败: {e}")
            _PRICING_CACHE["data"] = {"profiles": {}, "default_profile": "通用", "disclaimer": "", "collected_at": "", "region": ""}
            _PRICING_CACHE["mtime"] = mtime
    return _PRICING_CACHE["data"]


@router.get("/pricing/industries", tags=["成本参考"])
async def pricing_industries():
    """返回价目表支持的行业骨架列表（供前端校验/回退）。"""
    data = _load_pricing_reference()
    profiles = data.get("profiles", {})
    return {
        "industries": list(profiles.keys()),
        "default_profile": data.get("default_profile", "通用"),
        "collected_at": data.get("collected_at", ""),
        "region": data.get("region", ""),
        "disclaimer": data.get("disclaimer", ""),
    }


@router.get("/pricing/reference", tags=["成本参考"])
async def pricing_reference(industry: Optional[str] = None):
    """
    返回成本参考数据：按行业过滤后的成本骨架。
    - industry 命中 profiles 则返回该行业；否则回退到 default_profile（通用）。
    - 商务定价产品（business_only=True）不出数字，仅含提示文案。
    """
    data = _load_pricing_reference()
    profiles = data.get("profiles", {})
    default = data.get("default_profile", "通用")
    key = industry if industry in profiles else default
    profile = profiles.get(key, {})
    return {
        "industry": key,
        "is_default": key == default,
        "description": profile.get("description", ""),
        "items": profile.get("items", []),
        "collected_at": data.get("collected_at", ""),
        "region": data.get("region", ""),
        "annual_discount": data.get("annual_discount", 0.85),
        "disclaimer": data.get("disclaimer", ""),
        "business_only_products": data.get("business_only_products", []),
    }


@router.get("/pricing/products", tags=["成本参考"])
async def pricing_products():
    """
    返回全量价目产品（去重），供产品图谱「产品介绍」按产品名查参考价。
    优先使用 JSON 顶层 all_items（扁平全量，独立于行业成本参考 profiles）；
    旧版 JSON 无 all_items 时回退到遍历各行业 profile.items + 商务定价项。
    """
    data = _load_pricing_reference()
    all_items = data.get("all_items")
    if all_items:
        seen = set()
        items = []
        for it in all_items:
            name = it.get("product", "")
            if not name or name in seen:
                continue
            seen.add(name)
            items.append({
                "product": name,
                "spec": it.get("spec", ""),
                "billing": it.get("billing", ""),
                "unit_label": it.get("unit_label", ""),
                "ref_price": it.get("ref_price", 0),
                "qty": it.get("qty", 1),
                "tier": it.get("tier", None),
                "source_url": it.get("source_url", ""),
                "verified": it.get("verified", True),
                "note": it.get("note", ""),
                "business_only": bool(it.get("business_only", False)),
                "no_price": bool(it.get("no_price", False)),
                "free": bool(it.get("free", False)),
            })
        return {
            "items": items,
            "region": data.get("region", ""),
            "annual_discount": data.get("annual_discount", 0.85),
        }
    # 回退路径（兼容旧版 JSON：无 all_items）
    profiles = data.get("profiles", {})
    bop = data.get("business_only_products", [])
    seen = set()
    items = []
    # 1) 各行业 items（已含 no_price 项）
    for prof in profiles.values():
        for it in prof.get("items", []):
            name = it.get("product", "")
            if not name or name in seen:
                continue
            seen.add(name)
            items.append({
                "product": name,
                "spec": it.get("spec", ""),
                "billing": it.get("billing", ""),
                "unit_label": it.get("unit_label", ""),
                "ref_price": it.get("ref_price", 0),
                "qty": it.get("qty", 1),
                "tier": it.get("tier", None),
                "source_url": it.get("source_url", ""),
                "verified": it.get("verified", True),
                "note": it.get("note", ""),
                "business_only": bool(it.get("business_only", False)),
                "no_price": bool(it.get("no_price", False)),
                "free": bool(it.get("free", False)),
            })
    # 2) 顶层商务定价产品（可能是名称字符串列表，也可能是完整 dict）
    for it in bop:
        if isinstance(it, dict):
            name = it.get("product", "")
            spec = it.get("spec", "")
            note = it.get("note", "商务报价，请咨询华为云销售")
            src = it.get("source_url", "")
        else:
            name = str(it)
            spec = ""
            note = "商务报价，请咨询华为云销售"
            src = ""
        if not name or name in seen:
            continue
        seen.add(name)
        items.append({
            "product": name,
            "spec": spec,
            "billing": "",
            "unit_label": "",
            "ref_price": 0,
            "qty": 1,
            "tier": None,
            "source_url": src,
            "verified": True,
            "note": note,
            "business_only": True,
            "no_price": False,
            "free": False,
        })
    return {
        "items": items,
        "region": data.get("region", ""),
        "annual_discount": data.get("annual_discount", 0.85),
    }


async def _build_match_response(result: dict, user, request, original_demand: str, user_id: int, client_context_meta: Optional[dict] = None) -> dict:
    """标准/向导匹配结果统一后处理：来源文档 + 历史 + 成就 → MatchResponse 字段 dict。
    供 /match 与 /match/stream 共用，单一事实来源避免逻辑分叉。"""
    source_docs = [
        SourceDocument(page_content=doc.page_content, metadata=doc.metadata)
        for doc in result.get("source_documents", [])
    ]

    history_id = None
    newly_unlocked = None
    _version_meta: dict = {}

    if user and user.get('id'):
        newly_unlocked = []  # 已登录默认空列表；非快速体验才检测成就
        try:
            usage_logger = get_usage_logger()
            # 使用原始 demand 记录（空输入不会被默认 prompt 覆盖）
            usage_logger.log_match(original_demand or "", user_id=user['id'], mode=request.mode)
        except Exception as log_err:
            logger.warning(f"记录使用日志失败: {log_err}")

        try:
            industry_hint = ""
            try:
                for doc in result.get("source_documents", []):
                    if hasattr(doc, "metadata") and doc.metadata:
                        ind = doc.metadata.get("industry", "")
                        if ind:
                            industry_hint = ind
                            break
            except:
                pass
            history_id = usage_logger.save_match_history(
                demand_text=original_demand or "",
                solution=result["answer"],
                industry=industry_hint,
                sources=[{"source": d.metadata.get("source", ""), "industry": d.metadata.get("industry", "")} for d in result.get("source_documents", [])],
                user_id=user['id'],
                group_id=request.group_id,
                client_id=request.client_id,
            )
            _version_meta = usage_logger.get_match_history_meta(history_id, user_id=user['id']) or {}
        except Exception as hist_err:
            logger.warning(f"保存匹配历史记录失败: {hist_err}")

        # 成就检测（快速体验不触发）
        if not request.is_quick_demo:
            try:
                achievement_svc = get_achievement_service_dep()
                industry_hint = ""
                try:
                    for doc in result.get("source_documents", []):
                        if hasattr(doc, "metadata") and doc.metadata:
                            ind = doc.metadata.get("industry", "")
                            if ind:
                                industry_hint = ind
                                break
                except:
                    pass
                newly_unlocked = achievement_svc.check_after_match(
                    user_id=user['id'],
                    demand_text=original_demand,
                    mode=request.mode if hasattr(request, 'mode') else "standard",
                    industry=industry_hint,
                )
            except Exception as ach_err:
                logger.warning(f"成就检测失败: {ach_err}")

    return {
        "answer": result["answer"],
        "source_documents": source_docs,
        "solution_json": result.get("solution_json"),
        "history_id": history_id,
        "newly_unlocked": newly_unlocked,
        "group_id": _version_meta.get("group_id"),
        "version": _version_meta.get("version"),
        "is_final": _version_meta.get("is_final", False),
        "title": _version_meta.get("title"),
        "client_context_used": client_context_meta,
    }


@router.post("/match", response_model=MatchResponse, tags=["解决方案匹配"])
async def match_solution(
    request: MatchRequest,
    user: Optional[dict] = Depends(get_current_user_optional)
):
    """
    解决方案智能匹配接口（匿名可用）
    
    - **demand**: 客户需求描述（1-5000字符）
    
    即使知识库为空，AI也会基于华为云产品体系给出建议
    - 匿名调用走全局知识库；登录用户走其独立知识库
    - 注意：前端"快速体验"入口(isQuickDemo)走此接口实现免登录尝鲜，
      正式三种匹配模式(标准/Agent/向导)由前端登录拦截保证需登录。
    """
    try:
        # 使用用户独立知识库（登录用户）；匿名用户使用全局知识库
        user_id = user.get('id') if user else 0
        matcher = get_solution_matcher_for_user(user_id) if user_id > 0 else get_solution_matcher()
        # 匿名用户不进入下方 user 分支，_version_meta 不会被赋值；这里预置空 dict，
        # 避免响应构造时引用未定义变量（历史遗留：匿名 POST /api/match 会 500）
        _version_meta: dict = {}

        # 保存原始 demand（用于成就检测，不被默认 prompt 覆盖）
        original_demand = request.demand

        # 空输入处理：用于"无声胜有声"隐藏成就，给 LLM 一个默认 prompt
        if not request.demand or not request.demand.strip():
            request.demand = "（用户未输入需求，请介绍华为云的核心解决方案和产品体系）"
            logger.info("检测到空输入，使用默认 prompt")

        # 阶段1：把上传的客户资料文本并入需求（标准/向导模式直接消费，不丢失文件内容）
        enriched_demand = request.demand
        if request.customer_files:
            file_text = _read_customer_files_text(user_id, request.customer_files)
            if file_text:
                enriched_demand = (
                    f"[用户上传的客户资料]\n{file_text}\n[/用户上传的客户资料]\n\n"
                    f"{request.demand}"
                )
                logger.info(f"[匹配] 已并入 {len(request.customer_files)} 个客户资料文件")

        # 方案 A：关联客户时注入『背景 + 历史方案』上下文（智能相关性选取）
        client_block, client_meta = "", None
        if request.client_id and user_id > 0:
            client_block, client_meta = await _build_client_context_block(
                request.client_id, user_id, request.demand
            )

        client_industry = client_meta.get("industry") if client_meta else None
        result = await matcher.match(enriched_demand, industry=client_industry, client_context=client_block)

        logger.info("解决方案匹配成功")

        resp = await _build_match_response(result, user, request, original_demand, user_id, client_context_meta=client_meta)
        return MatchResponse(**resp)
    except Exception as e:
        logger.error(f"解决方案匹配失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"匹配失败: {str(e)}"
        )
    
@router.post("/match/stream", tags=["解决方案匹配"])
async def match_solution_stream(
    request: MatchRequest,
    user: Optional[dict] = Depends(get_current_user_optional)
):
    """
    标准/向导模式 SSE 流式匹配接口（匿名可用，与 /match 同源）。

    实时推送：
    - event: token  → 生成增量（前端逐字渲染）
    - event: step   → 进度步骤(2=生成中)
    - event: result → 完整结果（answer/source_documents/solution_json + 历史/成就后处理）
    - event: error  → 错误
    """
    user_id = user.get('id') if user else 0
    matcher = get_solution_matcher_for_user(user_id) if user_id > 0 else get_solution_matcher()

    # 预处理：空输入兜底 + 客户文件并入需求（与 /match 完全一致）
    original_demand = request.demand
    if not request.demand or not request.demand.strip():
        request.demand = "（用户未输入需求，请介绍华为云的核心解决方案和产品体系）"
    enriched_demand = request.demand
    if request.customer_files:
        file_text = _read_customer_files_text(user_id, request.customer_files)
        if file_text:
            enriched_demand = (
                f"[用户上传的客户资料]\n{file_text}\n[/用户上传的客户资料]\n\n"
                f"{request.demand}"
            )

    # 方案 A：关联客户时注入『背景 + 历史方案』上下文（必须在 generate() 外层，否则闭包内引用为 free variable）
    client_block, client_meta = "", None
    if request.client_id and user_id > 0:
        client_block, client_meta = await _build_client_context_block(
            request.client_id, user_id, request.demand
        )
    client_industry = client_meta.get("industry") if client_meta else None

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def run_match(ci=client_industry, cb=client_block):
            try:
                await matcher.match_stream(enriched_demand, queue, industry=ci, client_context=cb)
            except Exception as e:
                logger.error(f"[match/stream] 执行失败: {e}")
                await queue.put({"type": "error", "message": str(e)})
            finally:
                try:
                    await queue.put(None)  # 结束信号
                except Exception:
                    pass

        task = asyncio.ensure_future(run_match())

        start_time = time.time()
        try:
            while True:
                if SSE_HEARTBEAT_ENABLED:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_INTERVAL)
                    except asyncio.TimeoutError:
                        if time.time() - start_time > SSE_TIMEOUT:
                            logger.info("[match/stream] 流式超过超时上限,主动结束")
                            break
                        yield ": ping\n\n"
                        continue
                else:
                    event = await queue.get()
                if event is None:
                    break
                if event.get("type") == "error":
                    yield f"event: error\ndata: {json.dumps(event, ensure_ascii=False, default=_sse_json_default)}\n\n"
                    break
                if event.get("type") == "result":
                    # 统一后处理（历史/成就/来源文档），与 /match 共用 _build_match_response
                    payload = await _build_match_response(event["data"], user, request, original_demand, user_id, client_context_meta=client_meta)
                    yield f"event: result\ndata: {json.dumps({'type': 'result', 'data': payload}, ensure_ascii=False, default=_sse_json_default)}\n\n"
                    continue
                # token / step 透传
                yield f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, ensure_ascii=False, default=_sse_json_default)}\n\n"
        except asyncio.CancelledError:
            logger.info("[match/stream] 客户端断开连接")
            task.cancel()
        except Exception as gen_err:
            logger.error(f"[match/stream] 生成器异常(连接将中断): {gen_err}")
            try:
                yield f"event: error\ndata: {json.dumps({'type':'error','message':f'内部错误: {gen_err}'}, ensure_ascii=False)}\n\n"
            except Exception:
                pass
        finally:
            await task

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )


# ========== 客户资料文件上传（阶段1） ==========

@router.post("/upload/customer-file", tags=["文件交互"])
async def upload_customer_file(
    file: UploadFile = File(...),
    user: Optional[dict] = Depends(get_current_user),
):
    """
    上传客户资料文件到用户白名单目录 data/user_docs/{user_id}/customer_uploads/。

    校验：扩展名白名单 + 单文件 ≤100MB。返回相对路径供匹配接口使用。
    最多同时上传 10 个由前端控制；并发安全（每次独立写）。
    """
    try:
        user_id = user.get('id') if user else None
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录后再上传")

        # 扩展名白名单校验
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的文件格式: {ext}（仅支持 {', '.join(sorted(ALLOWED_EXT))}）"
            )

        # 读取内容并校验大小（单文件 ≤100MB）
        data = await file.read()
        max_bytes = 100 * 1024 * 1024
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"文件超过 100MB 上限（当前 {len(data) // (1024 * 1024)}MB）"
            )

        # 安全落盘（仅限用户白名单目录）
        from app.agent.file_security import safe_upload_path, ensure_user_dirs
        ensure_user_dirs(user_id)
        save_path = safe_upload_path(user_id, file.filename)
        with open(save_path, "wb") as f:
            f.write(data)

        rel = os.path.relpath(save_path, os.path.join(USER_DOCS_BASE_DIR, str(user_id)))
        logger.info(f"[Upload] 用户 {user_id} 上传文件: {rel} ({len(data)} bytes)")
        return {
            "success": True,
            "filename": os.path.basename(save_path),
            "path": rel,
            "size": len(data),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Upload] 上传失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传失败: {str(e)}"
        )


# ========== 客户文件辅助（阶段1） ==========

def _read_customer_files_text(user_id: int, paths: list) -> str:
    """
    读取用户上传的客户资料文件，合并为纯文本。
    任一文件失败不影响其余（返回 Error 说明）。用于标准/向导模式直接注入需求。
    """
    if not paths:
        return ""
    from app.agent.file_security import safe_resolve
    from app.agent.parsers.read_file import extract_text
    parts = []
    for p in paths:
        try:
            abs_path = safe_resolve(user_id, p)
        except ValueError as e:
            parts.append(f"[文件 {p} 跳过: {e}]")
            continue
        if not os.path.exists(abs_path):
            parts.append(f"[文件 {p} 跳过: 不存在]")
            continue
        text = extract_text(abs_path)
        parts.append(f"===== 客户资料：{p} =====\n{text}")
    return "\n\n".join(parts)


# ========== Agent 智能匹配（单 Agent + Tool Calling） ==========

def _resolve_agent_session_id(user: dict, client_id: Optional[int]) -> str:
    """Agent 记忆的 session_id：提供 client_id 时按 用户:客户 维度隔离，避免多客户串味；否则沿用全局（按用户）。"""
    if client_id:
        return f"{user['id']}:{client_id}"
    return str(user['id'])


async def _process_and_emit_agent_result(queue, result: dict, user: dict, original_demand: str, is_quick_demo: bool, group_id=None, client_id=None, client_context_meta: Optional[dict] = None):
    """
    Agent 流式结束后统一处理：保存历史（含版本化）、成就检测、提取来源文档、推送 result 事件。
    供 /agent/match/stream 与 /agent/clarify 共用，单一事实来源避免逻辑分叉。

    - 澄清暂停（result.paused=True）：不保存历史、不触发成就，直接下发 result（前端据此保留提问卡等待作答）；
    - 正常完成：保存历史并回填版本元信息(group_id/version/is_final/title)到 result。
    """
    # 澄清暂停或会话过期：不落库、不触发成就，直接下发 result 事件
    if result.get("paused") or result.get("expired"):
        result["newly_unlocked"] = []
        result["history_id"] = None
        result["source_documents"] = []
        await queue.put({"type": "result", "data": result})
        return

    history_id = None
    if user and user.get('id'):
        try:
            usage_logger = get_usage_logger()
            usage_logger.log_match(original_demand or "", user_id=user['id'], mode="agent")
            # 提取行业信息
            industry_hint = ""
            for tc in result.get("tool_calls", []):
                if tc.get("tool") in ("search_kb", "search_competitor") and tc.get("result"):
                    try:
                        rd = json.loads(tc["result"]) if isinstance(tc["result"], str) else tc["result"]
                        for doc in rd.get("results", []):
                            ind = doc.get("industry", "")
                            if ind:
                                industry_hint = ind
                                break
                    except Exception:
                        pass
                if industry_hint:
                    break
            history_id = usage_logger.save_match_history(
                demand_text=original_demand or "",
                solution=result.get("answer", ""),
                industry=industry_hint,
                sources=[],
                user_id=user['id'],
                group_id=group_id,
                client_id=client_id,
            )
            # 回填版本元信息
            meta = usage_logger.get_match_history_meta(history_id, user_id=user['id'])
            if meta:
                result["group_id"] = meta["group_id"]
                result["version"] = meta["version"]
                result["is_final"] = meta["is_final"]
                result["title"] = meta["title"]
        except Exception as log_err:
            logger.warning(f"[Agent SSE] 保存历史失败: {log_err}")

    # ── 成就检测 ──
    newly_unlocked = []
    if user and user.get('id') and not is_quick_demo:
        try:
            achievement_svc = get_achievement_service_dep()
            industry_hint = ""
            for tc in result.get("tool_calls", []):
                if tc.get("tool") in ("search_kb", "search_competitor") and tc.get("result"):
                    try:
                        rd = json.loads(tc["result"]) if isinstance(tc["result"], str) else tc["result"]
                        for doc in rd.get("results", []):
                            ind = doc.get("industry", "")
                            if ind:
                                industry_hint = ind
                                break
                    except Exception:
                        pass
                if industry_hint:
                    break
            newly_unlocked = achievement_svc.check_after_match(
                user_id=user['id'],
                demand_text=original_demand,
                mode="agent",
                industry=industry_hint,
            )
        except Exception as ach_err:
            logger.warning(f"[Agent SSE] 成就检测失败: {ach_err}")

    result["newly_unlocked"] = newly_unlocked
    result["history_id"] = history_id
    result["client_context_used"] = client_context_meta

    # 从 tool_calls 中提取 source_documents（与非流式 /agent/match 保持一致）
    _sdocs = []
    for _tc in result.get("tool_calls", []):
        if _tc.get("tool") in ("search_kb", "search_competitor") and _tc.get("result"):
            try:
                _rd = json.loads(_tc["result"]) if isinstance(_tc["result"], str) else _tc["result"]
                for _d in _rd.get("results", []):
                    _sdocs.append(SourceDocument(
                        page_content=_d.get("content", ""),
                        metadata={
                            "source": _d.get("source", ""),
                            "industry": _d.get("industry", ""),
                        }
                    ).model_dump())
            except (json.JSONDecodeError, TypeError):
                pass
    result["source_documents"] = _sdocs

    await queue.put({"type": "result", "data": result})


@router.post("/agent/match", response_model=MatchResponse, tags=["解决方案匹配"])
async def agent_match_solution(
    request: MatchRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: dict = Depends(require_login)
):
    """
    Agent 智能匹配接口（ReAct + Tool Calling）

    先分析意图，再检索知识库，最后生成方案——适合模糊输入场景。
    """
    try:
        # 设置用户上下文，Agent 工具可使用用户独立知识库
        user_id = user['id']
        set_kb_user_context(user_id)

        # 保存原始 demand（用于成就检测，不被默认 prompt 覆盖）
        original_demand = request.demand

        # 空输入处理
        if not request.demand or not request.demand.strip():
            request.demand = "（用户未输入需求，请介绍华为云的核心解决方案和产品体系）"
            logger.info("[Agent] 检测到空输入，使用默认 prompt")

        agent = get_agent()
        session_id = _resolve_agent_session_id(user, request.client_id)

        # 方案 A：关联客户时构造『背景 + 历史方案』上下文
        client_block, client_meta = "", None
        if request.client_id and user_id > 0:
            client_block, client_meta = await _build_client_context_block(
                request.client_id, user_id, request.demand
            )

        # 阶段1：把上传的客户文件路径注入 Agent，引导其用 read_customer_file 读取
        extra_context = ""
        if request.customer_files:
            file_list = "\n".join(f"- {p}" for p in request.customer_files)
            extra_context = (
                "\n\n[用户上传了以下客户资料文件，请务必先用 read_customer_file 工具逐一读取并提取需求要点，"
                "再综合生成方案]\n" + file_list
            )
            logger.info(f"[Agent] 注入 {len(request.customer_files)} 个客户资料文件路径")

        # 方案 A：把客户背景上下文拼进 Agent 提示词（不与文件注入冲突）
        if client_block:
            extra_context = (extra_context + "\n\n" if extra_context else "") + client_block

        result = await agent.run(
            user_input=request.demand,
            session_id=str(session_id),
            extra_context=extra_context,
        )

        # 阶段2：后台异步更新用户画像（best-effort，不阻断主响应）
        background_tasks.add_task(agent.update_user_profile, user['id'], str(session_id))

        answer = result.get("answer", "Agent 未能生成有效方案")
        tool_calls = result.get("tool_calls", [])
        steps = result.get("steps", 0)

        # 从工具调用中提取 source_documents
        source_docs = []
        for tc in tool_calls:
            if tc.get("tool") in ("search_kb", "search_competitor") and tc.get("result"):
                try:
                    result_data = json.loads(tc["result"]) if isinstance(tc["result"], str) else tc["result"]
                    for doc in result_data.get("results", []):
                        source_docs.append(SourceDocument(
                            page_content=doc.get("content", ""),
                            metadata={
                                "source": doc.get("source", ""),
                                "industry": doc.get("industry", ""),
                            }
                        ))
                except (json.JSONDecodeError, TypeError):
                    pass  # 无法解析的跳过

        logger.info(f"[Agent] 匹配完成: {steps} 步, {len(tool_calls)} 次工具调用")

        # 记录使用日志
        history_id = None
        if user and user.get('id'):
            try:
                usage_logger = get_usage_logger()
                usage_logger.log_match(original_demand or "", user_id=user['id'], mode="agent")
                industry_hint = ""
                for doc in source_docs:
                    ind = doc.metadata.get("industry", "")
                    if ind:
                        industry_hint = ind
                        break
                history_id = usage_logger.save_match_history(
                    demand_text=original_demand or "",
                    solution=answer,
                    industry=industry_hint,
                    sources=[{"source": d.metadata.get("source", ""), "industry": d.metadata.get("industry", "")} for d in source_docs],
                    user_id=user['id'],
                    client_id=request.client_id,
                )
            except Exception as log_err:
                logger.warning(f"[Agent] 保存历史失败: {log_err}")

        # 成就检测（Agent 模式）
        achievement_result = []
        if user and user.get('id') and not request.is_quick_demo:
            try:
                achievement_svc = get_achievement_service_dep()
                industry_hint = ""
                for doc in source_docs:
                    ind = doc.metadata.get("industry", "")
                    if ind:
                        industry_hint = ind
                        break
                achievement_result = achievement_svc.check_after_match(
                    user_id=user['id'],
                    demand_text=original_demand,
                    mode="agent",
                    industry=industry_hint,
                )
            except Exception as ach_err:
                logger.warning(f"[Agent] 成就检测失败: {ach_err}")

        return MatchResponse(
            answer=answer,
            source_documents=source_docs,
            solution_json=result.get("solution_json"),
            history_id=history_id,
            newly_unlocked=achievement_result if user and user.get('id') else None,
            client_context_used=client_meta,
        )
    except Exception as e:
        logger.error(f"[Agent] 智能匹配失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent 匹配失败: {str(e)}"
        )


# ========== Agent SSE 流式匹配（实时进度推送） ==========

@router.post("/agent/match/stream", tags=["解决方案匹配"])
async def agent_match_stream(
    request: MatchRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: dict = Depends(require_login)
):
    """
    Agent 智能匹配 SSE 流式接口

    通过 Server-Sent Events 实时推送 ReAct 循环的每一步进度：
    - event: step     → 新步骤开始
    - event: tool_start → 开始执行工具
    - event: tool_end   → 工具执行完成
    - event: final      → Agent 完成
    - event: result     → 最终结果（answer, steps, elapsed, tool_calls）
    """
    session_id = _resolve_agent_session_id(user, request.client_id)

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def event_callback(event):
            await queue.put(event)

        async def run_agent():
            try:
                # 设置用户上下文，Agent 工具可使用用户独立知识库
                set_kb_user_context(user['id'])

                # 保存原始 demand（用于成就检测，不被默认 prompt 覆盖）
                original_demand = request.demand

                # 空输入处理
                if not request.demand or not request.demand.strip():
                    request.demand = "（用户未输入需求，请介绍华为云的核心解决方案和产品体系）"

                agent = get_agent()

                # 方案 A：关联客户时构造『背景 + 历史方案』上下文
                client_block, client_meta = "", None
                if request.client_id and user.get('id'):
                    client_block, client_meta = await _build_client_context_block(
                        request.client_id, user['id'], request.demand
                    )

                # 阶段1：注入客户文件路径，引导 Agent 用 read_customer_file 读取
                extra_context = ""
                if request.customer_files:
                    file_list = "\n".join(f"- {p}" for p in request.customer_files)
                    extra_context = (
                        "\n\n[用户上传了以下客户资料文件，请务必先用 read_customer_file 工具逐一读取并提取需求要点，"
                        "再综合生成方案]\n" + file_list
                    )

                # 方案 A：把客户背景上下文拼进 Agent 提示词
                if client_block:
                    extra_context = (extra_context + "\n\n" if extra_context else "") + client_block

                result = await agent.run(
                    user_input=request.demand,
                    session_id=session_id,
                    extra_context=extra_context,
                    event_callback=event_callback,
                )

                # 阶段2：后台异步更新用户画像（best-effort，不阻断流式响应）
                if user and user.get('id'):
                    background_tasks.add_task(agent.update_user_profile, user['id'], session_id)

                # ── 统一后处理：保存历史（含版本化）+ 成就检测 + 来源文档 + 下发 result ──
                await _process_and_emit_agent_result(
                    queue, result, user, original_demand, request.is_quick_demo,
                    group_id=request.group_id,
                    client_id=request.client_id,
                    client_context_meta=client_meta,
                )
            except Exception as e:
                logger.error(f"[Agent SSE] 执行失败: {e}")
                await queue.put({"type": "error", "message": str(e)})
            finally:
                try:
                    await queue.put(None)  # 结束信号
                except Exception:
                    pass

        task = asyncio.ensure_future(run_agent())

        start_time = time.time()
        try:
            while True:
                if SSE_HEARTBEAT_ENABLED:
                    # 受控路径：心跳保活 + 超时主动结束（防止悬挂连接拖垮 worker）
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_INTERVAL)
                    except asyncio.TimeoutError:
                        if time.time() - start_time > SSE_TIMEOUT:
                            logger.info("[Agent SSE] 流式超过超时上限,主动结束")
                            break
                        yield ": ping\n\n"  # SSE 注释行,客户端忽略,仅保活
                        continue
                else:
                    # 默认路径：与原行为完全一致
                    event = await queue.get()
                if event is None:
                    break
                event_type = event.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False, default=_sse_json_default)}\n\n"
        except asyncio.CancelledError:
            logger.info("[Agent SSE] 客户端断开连接")
            task.cancel()
        except Exception as gen_err:
            logger.error(f"[Agent SSE] 生成器异常(连接将中断): {gen_err}")
            try:
                yield f"event: error\ndata: {json.dumps({'type':'error','message':f'内部错误: {gen_err}'}, ensure_ascii=False)}\n\n"
            except Exception:
                pass
        finally:
            await task

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        background=background_tasks,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )


@router.post("/agent/clarify", tags=["解决方案匹配"])
async def agent_clarify(
    request: ClarifyRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: dict = Depends(require_login)
):
    """
    Agent 交互式澄清续跑接口（阶段 2.5）

    用户回答完 Agent 暂停时提出的问题后，带上 clarify_id 与答案调此接口，
    后端恢复到暂停时的 ReAct 循环状态，把答案作为 Observation 接回并继续生成方案（不是重头再来）。
    """
    session_id = _resolve_agent_session_id(user, request.client_id)

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def event_callback(event):
            await queue.put(event)

        async def run_agent():
            result_emitted = False
            try:
                from app.agent.clarify_store import ClarifySessionStore
                set_kb_user_context(user['id'])
                agent = get_agent()

                # 恢复原始需求（用于历史落库与成就检测）
                state = ClarifySessionStore.get(request.clarify_id)
                original_demand = state.get("user_input", "") if state else ""

                logger.info(f"[Agent Clarify] 续跑开始 clarify_id={request.clarify_id} answers_count={len(request.answers or [])}")

                result = await agent.run(
                    user_input="",
                    session_id=session_id,
                    event_callback=event_callback,
                    clarify_id=request.clarify_id,
                    answers=request.answers,
                )

                logger.info(f"[Agent Clarify] agent.run 返回 success={result.get('success')} paused={result.get('paused')} expired={result.get('expired')}")

                if user and user.get('id'):
                    background_tasks.add_task(agent.update_user_profile, user['id'], session_id)

                # 安全包装：即使落库/成就检测失败，也保证发出 result 事件
                try:
                    await _process_and_emit_agent_result(
                        queue, result, user, original_demand, is_quick_demo=False, group_id=None,
                        client_id=request.client_id,
                    )
                    result_emitted = True
                except Exception as proc_err:
                    logger.warning(f"[Agent Clarify] 落库处理失败（仍下发结果）: {proc_err}")
                    result["newly_unlocked"] = []
                    result["history_id"] = None
                    result["source_documents"] = []
                    await queue.put({"type": "result", "data": result})
                    result_emitted = True

            except asyncio.CancelledError:
                logger.warning("[Agent Clarify] 任务被取消")
                await queue.put({"type": "error", "message": "请求被取消"})
                result_emitted = True
            except Exception as e:
                logger.error(f"[Agent Clarify] 执行失败: {e}", exc_info=True)
                await queue.put({"type": "error", "message": str(e)})
                result_emitted = True
            finally:
                if not result_emitted:
                    logger.error("[Agent Clarify] 未发出任何结果事件！发送兜底错误")
                    try:
                        await queue.put({"type": "error", "message": "内部异常：未生成结果"})
                    except Exception:
                        pass
                try:
                    await queue.put(None)
                except Exception:
                    pass

        task = asyncio.ensure_future(run_agent())

        start_time = time.time()
        try:
            while True:
                if SSE_HEARTBEAT_ENABLED:
                    # 受控路径：心跳保活 + 超时主动结束（防止悬挂连接拖垮 worker）
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_INTERVAL)
                    except asyncio.TimeoutError:
                        if time.time() - start_time > SSE_TIMEOUT:
                            logger.info("[Agent Clarify] 流式超过超时上限,主动结束")
                            break
                        yield ": ping\n\n"  # SSE 注释行,客户端忽略,仅保活
                        continue
                else:
                    # 默认路径：与原行为完全一致
                    event = await queue.get()
                if event is None:
                    break
                event_type = event.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False, default=_sse_json_default)}\n\n"
        except asyncio.CancelledError:
            logger.info("[Agent Clarify] 客户端断开连接")
            task.cancel()
        except Exception as gen_err:
            logger.error(f"[Agent Clarify] 生成器异常: {gen_err}")
            try:
                yield f"event: error\ndata: {json.dumps({'type':'error','message':f'内部错误: {gen_err}'}, ensure_ascii=False)}\n\n"
            except Exception:
                pass
        finally:
            await task

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        background=background_tasks,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ===== 客户档案（方案B：Agent 记忆按客户维度隔离） =====

# 客户结构化字段清单（与 db_init.py 迁移列保持一致，name/note 之外的新增列）
CLIENT_STRUCT_FIELDS = [
    "industry", "company_size", "region",
    "contact_name", "contact_title", "contact_phone", "contact_email",
    "stage", "budget", "pain_points", "decision_chain", "tags",
]
_CLIENT_SELECT_COLS = "id, name, note, created_at, updated_at, " + ", ".join(CLIENT_STRUCT_FIELDS)


def _client_row_to_dict(row) -> dict:
    """把 clients 行转成 API 响应 dict（含全部结构化字段）"""
    d = {
        "id": row["id"], "name": row["name"], "note": row["note"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }
    for f in CLIENT_STRUCT_FIELDS:
        d[f] = row[f]
    return d


# ============================================================
# 方案 A：匹配时参考客户「基本信息 + 历史方案」（智能相关性选取）
# 客户历史方案绝不进向量库/知识库，仅在本条匹配提示词内临时注入，用完即弃。
# ============================================================
def _cosine(a, b) -> float:
    """余弦相似度（纯 Python，零依赖）"""
    try:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
    except Exception:
        return 0.0


def _extract_solution_excerpt(solution: str, maxlen: int = 1200) -> str:
    """从历史方案正文截取要点摘录（在段落边界尽量截断）"""
    if not solution:
        return "（无方案内容）"
    s = solution.strip()
    if len(s) <= maxlen:
        return s
    cut = s[:maxlen]
    # 尽量在换行处截断，避免句子被劈半
    last_nl = cut.rfind("\n")
    if last_nl > maxlen * 0.6:
        cut = cut[:last_nl]
    return cut + "\n…（摘录截断）"


async def _select_relevant_client_solutions(new_demand: str, solutions: list, top_k: int = 5) -> list:
    """用 BGE 嵌入（get_embedding_vectors，全局单例模型）对新需求与各历史方案做余弦相似度排序，取 top-k。

    - 嵌入失败兜底按时间倒序（solutions 已倒序）取前 top_k。
    - 相似度阈值 0.3 以上才视为『相关』；相关项不足 top_k 用时间倒序补充，保证总有内容。
    """
    if not solutions:
        return []
    try:
        cand_texts = []
        for s in solutions:
            txt = f"{s.get('demand_text', '')}\n{(s.get('solution', '') or '')[:400]}"
            cand_texts.append(txt[:800])
        all_texts = [new_demand[:800]] + cand_texts
        # 在独立线程跑本地模型推理，避免阻塞事件循环（模型常驻全局单例，无加载开销）
        vecs = await asyncio.to_thread(get_embedding_vectors, all_texts)
        if not vecs or len(vecs) != len(all_texts):
            raise RuntimeError("嵌入返回为空或不完整")
        q_vec = vecs[0]
        scored = []
        for i, s in enumerate(solutions):
            sim = _cosine(q_vec, vecs[i + 1])
            scored.append((sim, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        above = [s for sim, s in scored if sim >= 0.30]
        if above:
            # 只注入相关项，宁缺毋滥（符合"智能化选取"设计：不灌无关历史）
            chosen = above[:top_k]
        elif scored and scored[0][0] >= 0.15:
            # 全部低于 0.30 但有一条稍相关：兜底取相似度最高的一条，避免全丢
            chosen = [scored[0][1]]
        else:
            # 完全无关：不注入任何历史，避免噪声干扰（客户档案仍会注入）
            chosen = []
        return chosen
    except Exception as e:
        logger.warning(f"[客户上下文] 嵌入排序失败，回退时间倒序: {e}")
        return solutions[:top_k]


async def _build_client_context_block(client_id: int, user_id: int, new_demand: str):
    """方案 A 核心：为本次匹配构造『客户背景 + 历史方案摘要』上下文块。

    返回 (block_text, meta)：
      - block_text: 注入提示词的 Markdown 段落；无有效内容时返回 ("", None)。
      - meta: dict {client_name, history_count} 供前端小字提示；无则返回 None。
    严格按 user_id 归属校验，杜绝跨客户读取（物理隔离，绝不串客户）。
    """
    if not client_id or not user_id:
        return "", None
    try:
        from app.utils.db_init import get_db_connection
        # 1. 归属校验：该客户必须属于当前用户
        uconn = get_db_connection()
        try:
            row = uconn.execute(
                f"SELECT {_CLIENT_SELECT_COLS} FROM clients WHERE id=? AND user_id=?",
                (client_id, user_id),
            ).fetchone()
        finally:
            uconn.close()
        if not row:
            return "", None
        client = _client_row_to_dict(row)
        client_name = client.get("name", "")

        # 2. 取该客户历史方案（含正文，上限 50）
        solutions = get_usage_logger().get_client_solutions_with_body(user_id, client_id, limit=50)

        # 3. 客户档案段落（小字段，始终注入，作为对齐锚点）
        profile_lines = []
        def _add(label, val, maxlen=500):
            if val:
                s = str(val)
                if len(s) > maxlen:
                    s = s[:maxlen] + "…"
                profile_lines.append(f"- {label}：{s}")
        _add("行业", client.get("industry"))
        _add("规模", client.get("company_size"))
        _add("地区", client.get("region"))
        _add("商机阶段", client.get("stage"))
        _add("预算", client.get("budget"))
        _add("痛点", client.get("pain_points"))
        _add("决策链", client.get("decision_chain"))
        _add("标签", client.get("tags"))
        _add("备注", client.get("note"))
        profile_block = "\n".join(profile_lines)

        # 4. 历史方案智能选取（BGE 嵌入余弦相似度）
        selected = await _select_relevant_client_solutions(new_demand, solutions, top_k=5)

        history_block = ""
        if selected:
            items = []
            for idx, s in enumerate(selected, 1):
                title = s.get("title") or s.get("demand_text") or f"历史方案{idx}"
                demand = (s.get("demand_text") or "")[:200]
                excerpt = _extract_solution_excerpt(s.get("solution") or "", maxlen=1200)
                items.append(
                    f"### 历史方案 {idx}（{title}）\n"
                    f"- 当时需求：{demand}\n"
                    f"- 方案要点摘录：\n{excerpt}"
                )
            history_block = "\n\n".join(items)

        # 5. 拼装最终 block
        parts = [
            "## 客户背景与历史方案（仅供本次匹配对齐口径，请勿作为公开事实对外陈述）",
            f"当前匹配关联客户：{client_name}（id={client_id}）",
        ]
        if profile_block:
            parts.append("【客户档案】\n" + profile_block)
        if history_block:
            parts.append(
                f"【该客户历史方案（智能选取最相关的 {len(selected)} / 共 {len(solutions)} 条）】\n"
                + history_block
            )
        parts.append(
            "【对齐要求】\n"
            "- 优先复用该客户过往已验证的产品选型与方案思路；与历史冲突时，以本次需求为准。\n"
            "- 已知信息（行业/痛点/决策链）不重复追问，直接基于其口径展开。\n"
            "- 客户档案与历史方案为内部参考，对外方案中不出现『该客户历史』等字眼。"
        )
        block = "\n\n".join(parts)
        meta = {"client_name": client_name, "history_count": len(selected), "industry": client.get("industry") or None}
        return block, meta
    except Exception as e:
        logger.warning(f"[客户上下文] 构造失败: {e}")
        return "", None


@router.get("/clients", tags=["客户档案"])
async def list_clients(user: dict = Depends(require_login)):
    """列出当前用户的所有客户档案（按创建时间倒序，含结构化字段）"""
    from app.utils.db_init import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT {_CLIENT_SELECT_COLS} FROM clients WHERE user_id=? ORDER BY created_at DESC",
        (user['id'],),
    )
    rows = cur.fetchall()
    conn.close()
    return {"clients": [_client_row_to_dict(r) for r in rows]}


@router.post("/clients", tags=["客户档案"])
async def create_client(req: ClientCreateRequest, user: dict = Depends(require_login)):
    """为当前用户新建客户档案（同名去重，支持结构化字段）"""
    from app.utils.db_init import get_db_connection
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="客户名称不能为空")
    if not req.industry or req.industry not in SUPPORTED_INDUSTRIES:
        raise HTTPException(status_code=400, detail="所属行业为必填项，且须为系统支持行业之一")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM clients WHERE user_id=? AND name=?", (user['id'], name))
    if cur.fetchone():
        conn.close()
        raise HTTPException(status_code=409, detail="该客户名称已存在")
    cols = ["user_id", "name", "note"] + CLIENT_STRUCT_FIELDS
    vals = [user['id'], name, req.note] + [getattr(req, f) for f in CLIENT_STRUCT_FIELDS]
    placeholders = ", ".join(["?"] * len(cols))
    cur.execute(
        f"INSERT INTO clients ({', '.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    cid = cur.lastrowid
    conn.commit()
    cur.execute(f"SELECT {_CLIENT_SELECT_COLS} FROM clients WHERE id=?", (cid,))
    row = cur.fetchone()
    conn.close()
    return _client_row_to_dict(row)


@router.get("/clients/{client_id}", tags=["客户档案"])
async def get_client_detail(client_id: int, user: dict = Depends(require_login)):
    """客户详情：结构化档案 + 该客户名下的方案历史列表（供客户详情页/轻量全景使用）"""
    from app.utils.db_init import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT {_CLIENT_SELECT_COLS} FROM clients WHERE id=? AND user_id=?",
        (client_id, user['id']),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="客户不存在或无权限")
    detail = _client_row_to_dict(row)
    # 该客户名下的方案历史（按时间倒序，最多 50 条）
    try:
        solutions = get_usage_logger().get_client_solutions(user_id=user['id'], client_id=client_id, limit=50)
    except Exception as e:
        logger.warning(f"读取客户方案列表异常: {e}")
        solutions = []
    detail["solutions"] = solutions
    return detail


@router.put("/clients/{client_id}", tags=["客户档案"])
async def update_client(client_id: int, req: ClientUpdateRequest, user: dict = Depends(require_login)):
    """编辑客户档案：仅更新传入的非 None 字段；改名时做同名去重"""
    from app.utils.db_init import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM clients WHERE id=? AND user_id=?", (client_id, user['id']))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="客户不存在或无权限")

    updates = {}
    if req.name is not None:
        new_name = req.name.strip()
        if not new_name:
            conn.close()
            raise HTTPException(status_code=400, detail="客户名称不能为空")
        cur.execute("SELECT id FROM clients WHERE user_id=? AND name=? AND id<>?",
                    (user['id'], new_name, client_id))
        if cur.fetchone():
            conn.close()
            raise HTTPException(status_code=409, detail="该客户名称已存在")
        updates["name"] = new_name
    for f in ["note"] + CLIENT_STRUCT_FIELDS:
        v = getattr(req, f)
        if v is not None:
            updates[f] = v

    # 行业合法性校验（部分更新：仅当传入了 industry 时才校验）
    if "industry" in updates and updates["industry"] not in SUPPORTED_INDUSTRIES:
        conn.close()
        raise HTTPException(status_code=400, detail="所属行业须为系统支持行业之一")

    if updates:
        set_clause = ", ".join([f"{k}=?" for k in updates]) + ", updated_at=datetime('now', 'localtime')"
        cur.execute(
            f"UPDATE clients SET {set_clause} WHERE id=? AND user_id=?",
            list(updates.values()) + [client_id, user['id']],
        )
        conn.commit()
    cur.execute(f"SELECT {_CLIENT_SELECT_COLS} FROM clients WHERE id=?", (client_id,))
    row = cur.fetchone()
    conn.close()
    return _client_row_to_dict(row)


@router.delete("/clients/{client_id}", tags=["客户档案"])
async def delete_client(client_id: int, user: dict = Depends(require_login)):
    """删除客户档案，并级联清除该客户的 Agent 记忆（避免孤儿记忆）"""
    from app.utils.db_init import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM clients WHERE id=? AND user_id=?", (client_id, user['id']))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="客户不存在或无权限")
    session_id = f"{user['id']}:{client_id}"
    cur.execute("DELETE FROM agent_memory WHERE user_id=? AND session_id=?", (user['id'], session_id))
    cur.execute("DELETE FROM agent_memory_archive WHERE user_id=? AND session_id=?", (user['id'], session_id))
    cur.execute("DELETE FROM clients WHERE id=? AND user_id=?", (client_id, user['id']))
    # 同步清理运行中的 Agent 记忆单例缓存，避免残留（客户已删，入口消失，但要干净）
    try:
        from app.agent import get_agent
        get_agent().memory.clear_session(session_id)
    except Exception:
        pass
    conn.commit()
    conn.close()
    return {"deleted": True, "client_id": client_id}


@router.post("/analyze", response_model=AnalyzeResponse, tags=["竞争对手分析"])
async def analyze_competitor(
    request: AnalyzeRequest,
    user: Optional[dict] = Depends(get_current_user_optional)
):
    """
    竞争对手方案分析接口
    
    - **competitor**: 竞争对手名称
    - **industry**: 行业名称
    """
    try:
        # 使用用户独立知识库（登录用户）；匿名用户使用全局知识库
        user_id = user.get('id') if user else 0
        analyzer = get_competitor_analyzer_for_user(user_id) if user_id > 0 else get_competitor_analyzer()
        logger.info(f"开始分析竞争对手: {request.competitor}, 行业: {request.industry}")
        
        result = await analyzer.analyze(request.competitor, request.industry)
        
        source_docs = [
            SourceDocument(
                page_content=doc.page_content,
                metadata=doc.metadata
            )
            for doc in result.get("source_documents", [])
        ]
        
        logger.info("竞争对手分析成功")
        
        # 记录使用日志（仅登录用户保存历史）
        history_id = None
        if user and user.get('id'):
            try:
                usage_logger = get_usage_logger()
                usage_logger.log_analyze(request.competitor, request.industry, user_id=user['id'])
                history_id = usage_logger.save_competitor_history(
                    competitor=request.competitor,
                    industry=request.industry,
                    analysis=result["answer"],
                    sources=[{"source": d.metadata.get("source", ""), "industry": d.metadata.get("industry", "")} for d in result.get("source_documents", []) if hasattr(d, "metadata")],
                    user_id=user['id']
                )
            except Exception as log_err:
                logger.warning(f"记录使用日志或保存历史失败: {log_err}")
        
        # 成就检测
        achievement_result = []
        if user and user.get('id') and not request.is_quick_demo:
            try:
                achievement_svc = get_achievement_service_dep()
                achievement_result = achievement_svc.check_after_analyze(
                    user_id=user['id'],
                    competitor=request.competitor,
                )
            except Exception as ach_err:
                logger.warning(f"成就检测失败: {ach_err}")

        return AnalyzeResponse(
            answer=result["answer"],
            source_documents=source_docs,
            history_id=history_id,
            newly_unlocked=achievement_result if user and user.get('id') else None
        )
    except Exception as e:
        logger.error(f"竞争对手分析失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分析失败: {str(e)}"
        )

@router.get("/knowledge/stats", response_model=KnowledgeStatsResponse, tags=["知识库管理"])
async def get_knowledge_stats(
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base)
):
    """
    获取知识库统计信息
    """
    try:
        stats = kb_service.get_stats()
        
        return KnowledgeStatsResponse(
            total_documents=stats["total_documents"],
            supported_industries=stats["supported_industries"],
            industry_counts=stats["industry_counts"],
            accuracy=stats.get("accuracy", 50),
            total_solution_files=stats.get("total_solution_files", 0),
            competitor_companies=stats.get("competitor_companies", [])
        )
    except Exception as e:
        logger.error(f"获取知识库统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取统计失败: {str(e)}"
        )


# ===== 后台任务（知识库重建/同步异步化） =====
# 单 uvicorn worker 下，同步重建会占满 worker 导致全站 60s 超时（之前"点重构卡死全站"的根因）。
# 改为后台线程执行重活，端点立即返回 task_id（202），前端轮询进度；多用户并发互不阻塞。
# 注意：任务记录存于进程内存，服务重启后任务会丢失（前端轮询拿到 404 即提示用户重试）。
_task_store: Dict[str, dict] = {}
_task_store_lock = threading.Lock()
# 全局并发信号量：最多同时跑 N 个重嵌任务（CPU 密集），其余排队，避免把 CPU 抢爆。
# N 由 env KB_REBUILD_CONCURRENCY 决定（默认 2）。CPU 受限的机器可设为 1，重嵌基本串行最稳。
# 说明：允许任意多用户"同时发起"（各自立即拿到 task_id），但真正跑嵌入的最多 N 路，
# 其余在此排队，前端显示"前面还有 N 个任务"。这是 CPU 受限下支撑 10+ 人的正解——
# 排队而非真并行，避免多任务抢核互相拖慢甚至内存爆掉。
_rebuild_semaphore = threading.Semaphore(KB_REBUILD_CONCURRENCY)
# 正在排队等待槽位的任务数（用于给前端反馈"前面还有几个"）
_kb_waiting = 0
_kb_waiting_lock = threading.Lock()
# 每用户锁：同一用户不允许并发发起自己的同步
_user_sync_locks: Dict[int, threading.Lock] = {}
_user_sync_locks_guard = threading.Lock()

def _get_user_sync_lock(user_id: int) -> threading.Lock:
    with _user_sync_locks_guard:
        if user_id not in _user_sync_locks:
            _user_sync_locks[user_id] = threading.Lock()
        return _user_sync_locks[user_id]

def _update_task(task_id: str, **fields):
    with _task_store_lock:
        t = _task_store.get(task_id)
        if t:
            t.update(fields)

def _acquire_slot_with_feedback(task_id: str, overall_timeout: int = 3600) -> bool:
    """带排队反馈地获取全局重嵌槽位。

    循环短超时 acquire，等待期间周期性把"前面还有 N 个任务"写进任务状态，
    让 10 人同时发起时排队者能看到进度而不是干等。返回 True=拿到槽位，False=超时。
    """
    global _kb_waiting
    with _kb_waiting_lock:
        _kb_waiting += 1
    waited = 0
    try:
        while True:
            if _rebuild_semaphore.acquire(timeout=2):
                return True
            waited += 2
            if waited >= overall_timeout:
                return False
            with _kb_waiting_lock:
                ahead = max(_kb_waiting - 1, 0)
            if ahead > 0:
                msg = f"排队中，前面还有 {ahead} 个任务，请稍候..."
            else:
                msg = "排队中，正在等待空闲计算资源..."
            _update_task(task_id, status="queued", progress=0, message=msg)
    finally:
        with _kb_waiting_lock:
            _kb_waiting -= 1

def _run_rebuild_task(task_id: str):
    """后台线程：重建全局知识库（user_id=0）。"""
    try:
        _update_task(task_id, status="queued", progress=0, message="任务已提交，正在等待空闲资源...")
        acquired = _acquire_slot_with_feedback(task_id)
        if not acquired:
            _update_task(task_id, status="failed", progress=0, message="任务排队超时，请稍后重试")
            return
        try:
            _update_task(task_id, status="running", progress=10, message="正在重建全局知识库（加载文档）...")
            svc = KnowledgeBaseService(user_id=0)

            def on_progress(done, total, stage):
                _update_task(task_id, status="running",
                             progress=10 + int(85 * done / max(total, 1)), message=stage)

            count = svc.build_from_directory(use_default_dirs=True, on_progress=on_progress)
            if count <= 0:
                _update_task(task_id, status="failed", progress=0,
                             message="重建未添加任何文档片段，可能文档目录为空或加载失败，请检查服务器日志")
                return
            # 刷新全局缓存实例，使后续请求（含匿名标准匹配）使用新向量库
            _kb_deps._global_kb = None
            clear_kb_search_cache()  # 重建后清空检索缓存，避免命中旧库结果
            _update_task(task_id, status="success", progress=100,
                         message=f"知识库重建完成，共 {count} 个文档片段",
                         result={"count": count})
        finally:
            _rebuild_semaphore.release()
    except Exception as e:
        logger.error(f"[后台重建] 失败: {e}")
        _update_task(task_id, status="failed", progress=0, message=f"重建失败: {str(e)}")

def _run_sync_task(task_id: str, user_id: int):
    """后台线程：把默认库增量同步进用户库（方案B：保留用户自定义内容）。"""
    user_lock = _get_user_sync_lock(user_id)
    if not user_lock.acquire(blocking=False):
        _update_task(task_id, status="failed", progress=0,
                     message="你已有一个同步任务在进行中，请稍后再试")
        return
    try:
        _update_task(task_id, status="queued", progress=0, message="任务已提交，正在等待空闲资源...")
        acquired = _acquire_slot_with_feedback(task_id)
        if not acquired:
            _update_task(task_id, status="failed", progress=0, message="任务排队超时，请稍后重试")
            return
        try:
            _update_task(task_id, status="running", progress=5,
                         message="正在合并官方最新方案到你的知识库...")
            # 清掉内存缓存，避免后续请求仍用旧实例
            _user_kb_cache.pop(user_id, None)

            user_base = os.path.join(USER_DOCS_BASE_DIR, str(user_id))
            user_huawei = os.path.join(user_base, "sample_solutions")
            user_competitor = os.path.join(user_base, "competitors")
            os.makedirs(user_base, exist_ok=True)

            if os.path.exists(KNOWLEDGE_BASE_DIRECTORY):
                shutil.copytree(KNOWLEDGE_BASE_DIRECTORY, user_huawei, dirs_exist_ok=True)
            if os.path.exists(COMPETITOR_DIRECTORY):
                shutil.copytree(COMPETITOR_DIRECTORY, user_competitor, dirs_exist_ok=True)

            kb_service = get_user_knowledge_base(user_id)

            def on_progress(done, total, stage):
                _update_task(task_id, status="running",
                             progress=10 + int(85 * done / max(total, 1)), message=stage)

            total = kb_service.build_from_directory(on_progress=on_progress)
            if total <= 0:
                _update_task(task_id, status="failed", progress=0,
                             message="同步后未生成任何文档片段，可能文档目录为空或加载失败，请检查服务器日志")
                return
            _update_task(task_id, status="success", progress=100,
                         message=f"已同步最新官方方案，并保留你的自定义文档，共 {total} 个文档片段",
                         result={"total_documents": total})
            clear_kb_search_cache()  # 同步后清空检索缓存，避免命中旧库结果
        finally:
            _rebuild_semaphore.release()
    except Exception as e:
        logger.error(f"[后台同步] 用户 {user_id} 失败: {e}")
        _update_task(task_id, status="failed", progress=0, message=f"同步失败: {str(e)}")
    finally:
        user_lock.release()


@router.post("/knowledge/rebuild", response_model=TaskStatusResponse, status_code=202, tags=["知识库管理"])
async def rebuild_knowledge(
    current_user: dict = Depends(get_current_user)
):
    """
    后台重建全局知识库（需登录）

    端点立即返回 task_id，重活在后台线程执行；前端轮询 /api/knowledge/task/{task_id} 获取进度。
    这样不会阻塞单 worker，多用户并发互不卡死。
    """
    task_id = str(uuid.uuid4())
    with _task_store_lock:
        _task_store[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "message": "任务已创建，等待执行...",
            "result": None,
        }
    threading.Thread(target=_run_rebuild_task, args=(task_id,), daemon=True).start()
    logger.info(f"用户 {current_user['id']} 提交后台重建任务 {task_id}")
    return TaskStatusResponse(
        task_id=task_id,
        status="pending",
        progress=0,
        message="重建任务已提交，正在后台运行（可在本页面查看进度）"
    )

@router.post("/knowledge/clear", response_model=ClearResponse, tags=["知识库管理"])
async def clear_knowledge(
    current_user: dict = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base)
):
    """
    清空全局知识库（需登录）
    
    删除全局向量数据库中的所有文档
    """
    try:
        logger.info(f"用户 {current_user['id']} 开始清空全局知识库")
        
        kb_service.vector_db.delete_collection()
        
        logger.info("知识库已清空")
        
        return ClearResponse(
            success=True,
            message="知识库已清空"
        )
    except Exception as e:
        logger.error(f"清空知识库失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"清空失败: {str(e)}"
        )

@router.post("/knowledge/sync-mine", response_model=TaskStatusResponse, status_code=202, tags=["知识库管理"])
async def sync_my_knowledge_base(
    current_user: dict = Depends(get_current_user)
):
    """
    后台增量同步当前用户知识库（方案B：保留用户自定义内容）。

    端点立即返回 task_id，重活在后台线程执行；前端轮询 /api/knowledge/task/{task_id} 获取进度。
    把全局默认库(user_id=0)的最新官方方案合并进用户库：
    - 默认库新增/更新的文档 → 复制进用户库（覆盖同名默认文档）
    - 用户自己添加/修改的文档 → 原样保留（不会被删除）
    - 客户档案等其它用户私有数据 → 不受影响
    最后重建用户向量库，使最新官方方案+用户自定义内容都可被检索。
    """
    user_id = current_user["id"]
    if user_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的用户身份")

    task_id = str(uuid.uuid4())
    with _task_store_lock:
        _task_store[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "message": "任务已创建，等待执行...",
            "result": None,
        }
    threading.Thread(target=_run_sync_task, args=(task_id, user_id), daemon=True).start()
    logger.info(f"用户 {user_id} 提交后台同步任务 {task_id}")
    return TaskStatusResponse(
        task_id=task_id,
        status="pending",
        progress=0,
        message="同步任务已提交，正在后台运行（可在本页面查看进度）"
    )

# ===== 后台任务进度查询 =====

@router.get("/knowledge/task/{task_id}", response_model=TaskStatusResponse, tags=["知识库管理"])
async def get_knowledge_task_status(task_id: str):
    """查询后台知识库任务（重建/同步）的进度与结果。"""
    with _task_store_lock:
        task = _task_store.get(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在或已过期（服务重启后任务记录会清空，请重新发起操作）"
        )
    return TaskStatusResponse(
        task_id=task["task_id"],
        status=task["status"],
        progress=task["progress"],
        message=task["message"],
        result=task.get("result")
    )

# ===== 知识库文档管理 CRUD =====

@router.get("/knowledge/documents", response_model=KBDocumentListResponse, tags=["知识库管理"])
async def list_knowledge_documents(
    current_user: dict = Depends(get_current_user)
):
    """列出当前用户独立知识库的文档（强制登录）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        docs = kb_service.list_documents()
        return KBDocumentListResponse(total=len(docs), documents=docs)
    except Exception as e:
        logger.error(f"列出文档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/knowledge/documents/{doc_id}", tags=["知识库管理"])
async def get_knowledge_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user)
):
    """获取当前用户独立知识库的文档内容（强制登录）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        return kb_service.get_document(doc_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    except Exception as e:
        logger.error(f"获取文档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/knowledge/documents", response_model=KBDocumentCreateResponse, tags=["知识库管理"])
async def create_knowledge_document(
    req: KBDocumentCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建新文档（写入当前用户的知识库）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        result = kb_service.create_document(req.category, req.industry, req.title, req.content)
        # 成就检测
        if current_user and current_user.get('id'):
            try:
                achievement_svc = get_achievement_service_dep()
                # 获取知识库总文档数
                total_docs = 0
                try:
                    stats = kb_service.get_stats()
                    industry_counts = stats.get("industry_counts", {}) if isinstance(stats, dict) else {}
                    total_docs = sum(industry_counts.values()) if industry_counts else 0
                except:
                    pass
                newly = achievement_svc.check_after_kb_add(current_user['id'], total_docs)
                if newly:
                    logger.info(f"[Achievement] 知识库新增文档成就解锁: {[a['name'] for a in newly]}")
            except Exception as ach_err:
                logger.warning(f"成就检测失败: {ach_err}")
        return KBDocumentCreateResponse(**result)
    except FileExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error(f"创建文档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ===== 知识库文件上传（Word/PDF/PPT 等 → 解析/OCR → 入库） =====

# 知识库文件上传支持的扩展名（与前端 accept 保持一致）
KB_UPLOAD_EXT = {".docx", ".pptx", ".pdf", ".txt", ".md", ".csv"}


def _unique_kb_title(kb_service, category: str, industry: str, title: str) -> str:
    """在目标目录下生成不重复的文档标题，避免 create_document 因同名 .txt 已存在而报错。"""
    base_dir = kb_service._get_doc_base_dir(category)
    target_dir = os.path.join(base_dir, industry)
    candidate = title
    i = 2
    while True:
        if not os.path.exists(os.path.join(target_dir, f"{candidate}.txt")):
            return candidate
        candidate = f"{title} ({i})"
        i += 1


def _run_upload_task(task_id: str, user_id: int, tmp_path: str, original_filename: str,
                      category: str, industry: str):
    """后台线程：解析上传文件 → 提取纯文本（扫描件走 OCR）→ 写入并向量化入库。"""
    try:
        _update_task(task_id, status="queued", progress=0, message="任务已提交，正在等待空闲资源...")
        acquired = _acquire_slot_with_feedback(task_id)
        if not acquired:
            _update_task(task_id, status="failed", progress=0, message="任务排队超时，请稍后重试")
            return
        try:
            _update_task(task_id, status="running", progress=10,
                         message=f"正在解析文件「{original_filename}」（提取文字 / OCR）...")
            # extract_text 已在模块顶部导入（app.agent.parsers.read_file）
            text = extract_text(tmp_path)
            if text.startswith("Error:"):
                _update_task(task_id, status="failed", progress=0, message=text)
                return
            if not text.strip():
                _update_task(task_id, status="failed", progress=0,
                             message="未能从文件中提取到任何文字（可能是空文件，或扫描件 OCR 失败）")
                return

            kb_service = get_user_knowledge_base(user_id)
            raw_title = os.path.splitext(os.path.basename(original_filename))[0] or "未命名文档"
            title = _unique_kb_title(kb_service, category, industry, raw_title)

            _update_task(task_id, status="running", progress=60,
                         message=f"文字提取完成（{len(text)} 字），正在写入并向量化...")
            result = kb_service.create_document(category, industry, title, text)

            # 刷新检索缓存，使新入库内容立即可被检索
            _user_kb_cache.pop(user_id, None)
            clear_kb_search_cache()

            _update_task(task_id, status="success", progress=100,
                         message=f"已解析并入库「{title}」，共 {result['chunks']} 个文档片段",
                         result={
                             "id": result["id"], "title": title,
                             "chunks": result["chunks"], "content": text,
                             "content_length": len(text),
                         })
        finally:
            _rebuild_semaphore.release()
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"[后台上传解析] 用户 {user_id} 失败: {e}")
        _update_task(task_id, status="failed", progress=0, message=f"上传解析失败: {str(e)}")


@router.post("/knowledge/documents/upload", response_model=TaskStatusResponse, status_code=202,
             tags=["知识库管理"])
async def upload_knowledge_document_file(
    file: UploadFile = File(...),
    category: str = Form("huawei"),
    industry: str = Form("智慧农业"),
    current_user: dict = Depends(get_current_user),
):
    """
    上传文件（Word/PDF/PPT 等）到知识库：解析 + OCR + 向量化入库。

    端点立即返回 task_id（202），重活在后台线程执行（含 CPU 嵌入，受全局并发信号量限流），
    前端轮询 /api/knowledge/task/{task_id} 获取进度。解析能力复用 app.agent.parsers.read_file.extract_text，
    支持 .docx/.pptx/.pdf（扫描件自动 OCR）/.txt/.md/.csv。成功后在用户知识库写入 .txt 并索引，
    doc_origin=user_uploaded（与平台默认库副本区分），manifest 同步更新（增量重建/修剪链路无需改动）。
    """
    try:
        user_id = current_user["id"]
        original_filename = file.filename or ""
        ext = os.path.splitext(original_filename)[1].lower()
        if ext not in KB_UPLOAD_EXT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的文件格式: {ext}（仅支持 {', '.join(sorted(KB_UPLOAD_EXT))}）"
            )

        data = await file.read()
        max_bytes = 100 * 1024 * 1024
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"文件超过 100MB 上限（当前 {len(data) // (1024 * 1024)}MB）"
            )

        from app.agent.file_security import safe_upload_path, ensure_user_dirs
        ensure_user_dirs(user_id)
        # 临时落盘（uuid 前缀避免并发同名覆盖），供 extract_text 读取
        safe_name = f"{uuid.uuid4().hex}_{original_filename}"
        save_path = safe_upload_path(user_id, safe_name)
        with open(save_path, "wb") as f:
            f.write(data)

        if category not in ("huawei", "competitor"):
            category = "huawei"

        task_id = str(uuid.uuid4())
        with _task_store_lock:
            _task_store[task_id] = {
                "task_id": task_id, "status": "pending", "progress": 0,
                "message": "任务已创建，等待执行...", "result": None,
            }
        threading.Thread(
            target=_run_upload_task,
            args=(task_id, user_id, save_path, original_filename, category, industry),
            daemon=True,
        ).start()
        logger.info(f"用户 {user_id} 提交知识库文件上传任务 {task_id}: {original_filename}")
        return TaskStatusResponse(
            task_id=task_id, status="pending", progress=0,
            message="文件已接收，正在后台解析与入库（可在本页面查看进度）"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[上传] 失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"上传失败: {str(e)}")


@router.put("/knowledge/documents/{doc_id}", response_model=KBDocumentUpdateResponse, tags=["知识库管理"])
async def update_knowledge_document(
    doc_id: str,
    req: KBDocumentUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """更新文档内容（修改当前用户的知识库）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        result = kb_service.update_document(doc_id, req.content)
        return KBDocumentUpdateResponse(**result)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    except Exception as e:
        logger.error(f"更新文档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/knowledge/documents/{doc_id}", response_model=KBDocumentDeleteResponse, tags=["知识库管理"])
async def delete_knowledge_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user)
):
    """删除文档（从当前用户的知识库中删除）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        result = kb_service.delete_document(doc_id, delete_file=True)
        return KBDocumentDeleteResponse(success=True, **result)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    except Exception as e:
        logger.error(f"删除文档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/knowledge/documents/{doc_id}/reindex", response_model=KBDocumentReindexResponse, tags=["知识库管理"])
async def reindex_knowledge_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    """重新索引单个文档（当前用户的知识库）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        result = kb_service.reindex_document(doc_id)
        # 成就检测
        if current_user and current_user.get('id'):
            try:
                achievement_svc = get_achievement_service_dep()
                newly = achievement_svc.check_after_reindex(current_user['id'])
                if newly:
                    logger.info(f"[Achievement] 重索引成就解锁: {[a['name'] for a in newly]}")
            except Exception as ach_err:
                logger.warning(f"成就检测失败: {ach_err}")
        return KBDocumentReindexResponse(**result)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    except Exception as e:
        logger.error(f"重新索引失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/dashboard/stats", response_model=DashboardStatsResponse, tags=["数据仪表盘"])
async def get_dashboard_stats(
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    获取仪表盘统计数据
    
    返回行业覆盖、匹配趋势、竞品分析频次等**真实使用数据**
    所有趋势和频次数据均来自 SQLite 日志数据库的实际操作记录
    """
    try:
        import os
        from datetime import datetime
        from app.config import APP_VERSION

        # 获取用户独立知识库统计
        kb_service = get_user_knowledge_base(current_user['id'])
        kb_stats = kb_service.get_stats()
        
        # 行业覆盖数据（来自知识库，真实）
        industry_coverage = kb_stats.get("industry_counts", {})
        
        # ========== 真实使用日志统计 ==========
        user_id = current_user.get('id')

        # 获取最近7天操作次数（用于 KPI 卡片）
        recent_counts = usage_logger.get_recent_counts(days=7, user_id=user_id)
        recent_matches = recent_counts.get("match", 0)
        recent_analyses = recent_counts.get("analyze", 0)

        # 获取最近7天每日趋势（真实日志）
        match_trends = usage_logger.get_daily_trends(days=7, user_id=user_id)

        # 获取竞品分析频次（全局数据，所有用户共享 → 转换为百分比防泄露）
        competitor_frequency_raw = usage_logger.get_competitor_frequency(user_id=None)  # 全局，不限用户
        total_analyses = sum(competitor_frequency_raw.values())
        if total_analyses > 0:
            competitor_frequency = {
                k: round(v / total_analyses * 100, 1)
                for k, v in sorted(competitor_frequency_raw.items(), key=lambda x: -x[1])
            }
        else:
            competitor_frequency = {}

        # 获取涨幅（7日环比）
        growth_rates = usage_logger.get_growth_rates(days=7, user_id=user_id)
        match_growth = growth_rates.get("match_growth", None)
        analyze_growth = growth_rates.get("analyze_growth", None)

        # 如果日志为空，提供兜底：从竞品文档目录生成基础数据（同样转为百分比）
        if not competitor_frequency:
            competitor_dir = os.getenv("COMPETITOR_DIRECTORY", "./data/competitors")
            if os.path.exists(competitor_dir):
                fallback_raw = {}
                for competitor in os.listdir(competitor_dir):
                    comp_path = os.path.join(competitor_dir, competitor)
                    if os.path.isdir(comp_path):
                        try:
                            files = [f for f in os.listdir(comp_path) if f.endswith((".txt", ".pdf", ".md"))]
                            fallback_raw[competitor] = len(files)
                        except:
                            pass
                total_fallback = sum(fallback_raw.values())
                if total_fallback > 0:
                    competitor_frequency = {
                        k: round(v / total_fallback * 100, 1)
                        for k, v in sorted(fallback_raw.items(), key=lambda x: -x[1])
                    }
        
        # 系统运行时间
        try:
            import psutil
            proc = psutil.Process()
            uptime_sec = int((datetime.now() - datetime.fromtimestamp(proc.create_time())).total_seconds())
            hours = uptime_sec // 3600
            mins = (uptime_sec % 3600) // 60
            system_uptime = f"{hours}小时 {mins}分钟"
        except:
            system_uptime = "运行中"
        
        return DashboardStatsResponse(
            industry_coverage=industry_coverage,
            match_trends=match_trends,
            competitor_frequency=competitor_frequency,
            recent_matches=recent_matches,
            recent_analyses=recent_analyses,
            match_growth=match_growth,
            analyze_growth=analyze_growth,
            total_documents=kb_stats.get("total_documents", 0),
            competitor_companies=kb_stats.get("competitor_companies", []),
            accuracy=kb_stats.get("accuracy", 87),
            system_uptime=system_uptime,
            last_update=datetime.now().strftime("%Y-%m-%d %H:%M"),
            version=APP_VERSION
        )
    except Exception as e:
        logger.error(f"获取仪表盘数据失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取仪表盘数据失败: {str(e)}"
        )

# ========== 历史记录（方案匹配回溯 & 对比） ==========

def _fetch_client_name_map(user_id: int, client_ids):
    """跨库：根据 client_id 列表查 clients 表，返回 {id: name} 映射，供历史记录回填客户名"""
    try:
        from app.utils.db_init import get_db_connection
        cids = [c for c in client_ids if c]
        if not cids:
            return {}
        conn = get_db_connection()
        placeholders = ",".join("?" * len(cids))
        rows = conn.execute(
            f"SELECT id, name FROM clients WHERE user_id=? AND id IN ({placeholders})",
            [user_id, *cids]
        ).fetchall()
        conn.close()
        return {r["id"]: r["name"] for r in rows}
    except Exception as e:
        logger.warning(f"查询客户名称映射失败: {e}")
        return {}


@router.get("/history/list", response_model=MatchHistoryListResponse, tags=["历史记录"])
async def get_match_history_list(
    current_user: dict = Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
    limit: int = 100,
    client_id: Optional[int] = None,
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    获取方案匹配历史记录列表

    按时间倒序返回最近的匹配记录，支持分页
    """
    try:
        # 参数校验
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20
        if page_size > 100:
            page_size = 100
        if limit < 1:
            limit = 100

        # 获取总数
        total = usage_logger.get_match_history_count(user_id=current_user.get('id'))

        # 计算分页
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        offset = (page - 1) * page_size
        effective_limit = min(page_size, limit)

        items = usage_logger.get_match_history_list(limit=effective_limit, offset=offset, user_id=current_user.get('id'), client_id=client_id)
        name_map = _fetch_client_name_map(current_user.get('id'), [it.get("client_id") for it in items])
        return MatchHistoryListResponse(
            items=[
                MatchHistoryItem(
                    id=item["id"],
                    demand_text=item["demand_text"],
                    solution_preview=(item.get("solution") or "")[:500],
                    industry=item["industry"],
                    created_at=item["created_at"],
                    downloaded=bool(item.get("downloaded", False)),
                    archived=bool(item.get("archived", False)),
                    client_id=item.get("client_id"),
                    client_name=name_map.get(item.get("client_id")) if item.get("client_id") else None,
                )
                for item in items
            ],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
    except Exception as e:
        logger.error(f"获取历史记录列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史记录失败: {str(e)}"
        )

@router.get("/history/{history_id}", response_model=MatchHistoryDetail, tags=["历史记录"])
async def get_match_history_detail(
    history_id: int,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    获取单条历史记录详情

    包含完整的需求描述、方案内容和参考文档
    """
    try:
        item = usage_logger.get_match_history_by_id(history_id, user_id=current_user.get("id"))
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="历史记录不存在"
            )
        name_map = _fetch_client_name_map(current_user.get("id"), [item.get("client_id")])
        return MatchHistoryDetail(
            id=item["id"],
            demand_text=item["demand_text"],
            solution=item["solution"],
            industry=item["industry"],
            sources=item["sources"],
            created_at=item["created_at"],
            downloaded=item.get("downloaded", False),
            archived=item.get("archived", False),
            conversation=item.get("conversation", []),
            client_id=item.get("client_id"),
            client_name=name_map.get(item.get("client_id")) if item.get("client_id") else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取历史记录详情失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史记录详情失败: {str(e)}"
        )

@router.put("/history/{history_id}/client", tags=["历史记录"])
async def update_history_client(
    history_id: int,
    req: UpdateHistoryClientRequest,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """改挂 / 解除关联客户（方案历史与客户的后期绑定，供历史详情页使用）"""
    try:
        ok = usage_logger.set_match_history_client(history_id, current_user.get("id"), req.client_id)
        if not ok:
            # 要么记录不存在，要么 client_id 越权
            exist = usage_logger.get_match_history_by_id(history_id, user_id=current_user.get("id"))
            if exist is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="历史记录不存在")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="关联的客户不存在或不属于当前用户")
        return {"success": True, "history_id": history_id, "client_id": req.client_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"改挂客户失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"改挂客户失败: {str(e)}"
        )

@router.post("/history/compare", response_model=CompareResponse, tags=["历史记录"])
async def compare_match_history(
    request: CompareRequest,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    对比两条历史记录

    同时返回方案A和方案B的完整内容，前端做差异化展示
    """
    try:
        item_a = usage_logger.get_match_history_by_id(request.id_a, user_id=current_user.get("id"))
        item_b = usage_logger.get_match_history_by_id(request.id_b, user_id=current_user.get("id"))

        if item_a is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"历史记录 {request.id_a} 不存在"
            )
        if item_b is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"历史记录 {request.id_b} 不存在"
            )

        return CompareResponse(
            item_a=MatchHistoryDetail(
                id=item_a["id"],
                demand_text=item_a["demand_text"],
                solution=item_a["solution"],
                industry=item_a["industry"],
                sources=item_a["sources"],
                created_at=item_a["created_at"],
                downloaded=item_a.get("downloaded", False),
                archived=item_a.get("archived", False),
                conversation=item_a.get("conversation", [])
            ),
            item_b=MatchHistoryDetail(
                id=item_b["id"],
                demand_text=item_b["demand_text"],
                solution=item_b["solution"],
                industry=item_b["industry"],
                sources=item_b["sources"],
                created_at=item_b["created_at"],
                downloaded=item_b.get("downloaded", False),
                archived=item_b.get("archived", False),
                conversation=item_b.get("conversation", [])
            )
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"对比历史记录失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"对比失败: {str(e)}"
        )

@router.post("/history/ai-summary", response_model=CompareSummaryResponse, tags=["历史记录"])
async def compare_ai_summary(
    request: CompareSummaryRequest,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """为两条历史记录生成AI智能对比总结"""
    try:
        item_a = usage_logger.get_match_history_by_id(request.id_a, user_id=current_user.get("id"))
        item_b = usage_logger.get_match_history_by_id(request.id_b, user_id=current_user.get("id"))

        if item_a is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"历史记录 {request.id_a} 不存在")
        if item_b is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"历史记录 {request.id_b} 不存在")

        compare_prompt = f"""你是华为云解决方案资深专家。请对比分析以下两份华为云方案匹配的输出结果，给出简洁、专业的智能总结。

## 方案A
- 客户需求：{item_a.get('demand_text', '')}
- 推荐方案摘要：
{item_a.get('solution', '')[:2000]}

## 方案B
- 客户需求：{item_b.get('demand_text', '')}
- 推荐方案摘要：
{item_b.get('solution', '')[:2000]}

请从以下维度进行对比总结（控制在300字以内，用Markdown格式）：
1. **需求差异**：两份方案的客户需求有何不同
2. **方案侧重点**：两份方案各自的核心推荐点和差异
3. **产品组合差异**：关键华为云产品的使用差异
4. **演进建议**：如果是同一客户的迭代需求，给出从方案A到方案B的演进思路

请用中文输出，结构清晰、专业简练。"""
        summary = await get_llm_response(compare_prompt)
        return CompareSummaryResponse(summary=summary)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI对比总结生成失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI总结生成失败: {str(e)}"
        )



@router.patch("/history/{history_id}/solution", response_model=UpdateSolutionResponse, tags=["历史记录"])
async def update_history_solution(
    history_id: int,
    request: UpdateSolutionRequest,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """更新历史记录中的方案内容（用于追问优化后保存最终版）"""
    try:
        # 归档记录禁止修改
        _existing = usage_logger.get_match_history_by_id(history_id, user_id=current_user.get("id"))
        if _existing and _existing.get("archived"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该记录已归档，无法修改")
        success = usage_logger.update_match_history_solution(history_id, request.solution, user_id=current_user.get("id"))
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"历史记录 {history_id} 不存在或更新失败")
        return UpdateSolutionResponse(success=True, message="方案已更新")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新历史方案失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新失败: {str(e)}"
        )


@router.get("/history/group/{group_id}", response_model=HistoryGroupResponse, tags=["历史记录"])
async def get_history_group(
    group_id: int,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """获取同一方案分组的全部版本（v1/v2/v3...），用于版本对比 / 回滚 / 定稿。"""
    try:
        group = usage_logger.get_match_history_group(group_id, user_id=current_user.get("id"))
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本分组不存在")
        return HistoryGroupResponse(**group)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取版本分组失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"获取版本分组失败: {str(e)}")


@router.post("/history/{history_id}/finalize", response_model=FinalizeResponse, tags=["历史记录"])
async def finalize_history(
    history_id: int,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """将某版本标记为「定稿」：同组仅保留一个定稿版本。"""
    try:
        res = usage_logger.finalize_match_history(history_id, user_id=current_user.get("id"))
        if res is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="历史记录不存在或无权限")
        return FinalizeResponse(
            success=True, id=res["id"], group_id=res["group_id"], version=res["version"],
            message="已定稿，该版本将作为正式交付版本",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"定稿失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"定稿失败: {str(e)}")


@router.post("/history/{history_id}/rollback", response_model=RollbackResponse, tags=["历史记录"])
async def rollback_history(
    history_id: int,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """回滚（非破坏性）：把选定版本的方案内容复制为同组的新版本，原版本不变。"""
    try:
        res = usage_logger.rollback_match_history(history_id, user_id=current_user.get("id"))
        if res is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="历史记录不存在或无权限")
        return RollbackResponse(
            success=True, source_id=res["source_id"], new_id=res["new_id"],
            group_id=res["group_id"], version=res["version"],
            message=f"已基于 v{res['version']-1 if res['version']>1 else 1} 生成新版本 v{res['version']}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"回滚失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"回滚失败: {str(e)}")


@router.patch("/competitor/history/{history_id}/solution", response_model=UpdateSolutionResponse, tags=["历史记录"])
async def update_competitor_history_solution(
    history_id: int,
    request: UpdateSolutionRequest,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """更新竞品分析历史记录中的分析内容（用于追问优化后保存最终版）"""
    try:
        # 归档记录禁止修改
        _existing = usage_logger.get_competitor_history_by_id(history_id, user_id=current_user.get("id"))
        if _existing and _existing.get("archived"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该记录已归档，无法修改")
        success = usage_logger.update_competitor_history_solution(history_id, request.solution, user_id=current_user.get("id"))
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"竞品分析历史记录 {history_id} 不存在或更新失败")
        return UpdateSolutionResponse(success=True, message="分析报告已更新")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新竞品分析历史失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新失败: {str(e)}"
        )


# ========== 历史记录：归档 / 下载 / 追问优化 ==========

@router.post("/history/{history_id}/archive", response_model=HistoryFlagResponse, tags=["历史记录"])
async def archive_history(
    history_id: int,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """归档历史记录（归档后不可修改，仅可查看/下载）"""
    try:
        ok = usage_logger.set_history_flags(history_id, user_id=current_user.get("id"), archived=True)
        if not ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"历史记录 {history_id} 不存在")
        return HistoryFlagResponse(success=True, archived=True, message="已归档")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"归档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"归档失败: {str(e)}")


@router.post("/history/{history_id}/unarchive", response_model=HistoryFlagResponse, tags=["历史记录"])
async def unarchive_history(
    history_id: int,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """取消归档历史记录"""
    try:
        ok = usage_logger.set_history_flags(history_id, user_id=current_user.get("id"), archived=False)
        if not ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"历史记录 {history_id} 不存在")
        return HistoryFlagResponse(success=True, archived=False, message="已取消归档")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消归档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"取消归档失败: {str(e)}")


@router.post("/history/{history_id}/download", tags=["历史记录"])
async def download_history_file(
    history_id: int,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    从历史记录重新生成方案/分析报告 Word 文件并下载，同时标记已下载。
    浏览器无法访问用户本地文件，故采用「重新下载服务器副本」方式。
    """
    try:
        item = usage_logger.get_match_history_by_id(history_id, user_id=current_user.get("id"))
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="历史记录不存在")
        content = item.get("solution") or ""
        if not content.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该记录无方案内容，无法生成文件")
        is_analyze = item.get("type") == "analyze"
        report_type = ReportType.COMPETITOR if is_analyze else ReportType.SOLUTION
        title = (item.get("competitor") or item.get("demand_text") or "华为云方案")[:60]
        service = ReportGeneratorService()
        task = service.generate_report(
            report_type=report_type,
            content=content,
            format=ExportFormat.WORD,
            metadata={"title": title, "customer": title},
        )
        if not task or task.status.value != "completed" or not task.file_path:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"文件生成失败: {getattr(task, 'error_message', '未知错误')}"
            )
        # 标记已下载
        usage_logger.set_history_flags(history_id, user_id=current_user.get("id"), downloaded=True)
        return FileResponse(
            path=task.file_path,
            filename=task.file_name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"历史下载失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"下载失败: {str(e)}")


@router.post("/history/{history_id}/followup", response_model=HistoryFollowUpResponse, tags=["历史记录"])
async def history_followup(
    history_id: int,
    request: HistoryFollowUpRequest,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """在历史记录内继续追问优化：追加对话记录并更新方案正文（归档记录禁止）"""
    try:
        existing = usage_logger.get_match_history_by_id(history_id, user_id=current_user.get("id"))
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="历史记录不存在")
        if existing.get("archived"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该记录已归档，无法修改")
        conv = usage_logger.append_history_conversation(
            history_id,
            user_id=current_user.get("id"),
            follow_up=request.follow_up,
            refined_solution=request.refined_solution,
            conversation_history=request.conversation_history,
        )
        if conv is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="历史记录不存在或更新失败")
        return HistoryFollowUpResponse(success=True, conversation=conv, message="已保存优化结果")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"历史追问保存失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"追问保存失败: {str(e)}")


# ========== 竞品分析历史记录 ==========

@router.get("/competitor/history/list", response_model=CompetitorHistoryListResponse, tags=["历史记录"])
async def get_competitor_history_list(
    current_user: dict = Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
    limit: int = 100,
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    获取竞品分析历史记录列表

    按时间倒序返回最近的竞品分析记录，支持分页
    """
    try:
        # 参数校验
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20
        if page_size > 100:
            page_size = 100
        if limit < 1:
            limit = 100

        # 获取总数
        total = usage_logger.get_competitor_history_count(user_id=current_user.get('id'))

        # 计算分页
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        offset = (page - 1) * page_size
        effective_limit = min(page_size, limit)

        items = usage_logger.get_competitor_history_list(limit=effective_limit, offset=offset, user_id=current_user.get('id'))
        return CompetitorHistoryListResponse(
            items=[
                CompetitorHistoryItem(
                    id=item["id"],
                    competitor=item["competitor"],
                    industry=item["industry"],
                    analysis_preview=(item.get("solution") or "")[:500],
                    created_at=item["created_at"],
                    downloaded=bool(item.get("downloaded", False)),
                    archived=bool(item.get("archived", False))
                )
                for item in items
            ],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
    except Exception as e:
        logger.error(f"获取竞品分析历史列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史记录失败: {str(e)}"
        )

@router.get("/competitor/history/{history_id}", response_model=CompetitorHistoryDetail, tags=["历史记录"])
async def get_competitor_history_detail(
    history_id: int,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    获取单条竞品分析历史记录详情

    包含完整的分析报告和参考文档
    """
    try:
        item = usage_logger.get_competitor_history_by_id(history_id, user_id=current_user.get("id"))
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="历史记录不存在"
            )
        return CompetitorHistoryDetail(
            id=item["id"],
            competitor=item["competitor"],
            industry=item["industry"],
            analysis=item["analysis"],
            sources=item.get("sources", []),
            created_at=item["created_at"],
            downloaded=item.get("downloaded", False),
            archived=item.get("archived", False),
            conversation=item.get("conversation", [])
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取竞品分析历史详情失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史记录详情失败: {str(e)}"
        )

@router.post("/solution/refine", response_model=RefineSolutionResponse, tags=["解决方案优化"])
async def refine_solution(request: RefineSolutionRequest):
    """方案追问优化接口 - 基于原始需求+当前方案+用户追问，生成优化方案"""
    try:
        # 构造对话历史上下文
        history_text = ""
        if request.conversation_history:
            for h in request.conversation_history:
                role = h.get('role', 'user')
                content = h.get('content', '')
                history_text += f"{role}: {content}\n"
        
        refine_prompt = f"""你是华为云解决方案资深专家。请根据用户的追问，对已有方案进行优化改写。

## 原始客户需求
{request.original_demand}

## 当前方案（Markdown格式）
{request.current_solution}

## 历史追问记录
{history_text if history_text else '（无）'}

## 本次用户追问
{request.follow_up}

---
**任务要求**：
1. 基于当前方案，根据用户的追问要求进行针对性优化
2. 保持方案的专业性和实用性，符合华为云产品体系
3. 如果追问涉及价格/成本，给出具体计费参考（华为云官方价格体系）
4. 如果追问涉及竞品对比，突出华为云差异化优势
5. 输出完整优化后的方案（Markdown格式，结构清晰）
6. 不要输出解释性文字，直接输出优化后的完整方案

请用中文输出，格式规范、专业简练。"""
        
        refined = await get_llm_response(refine_prompt)
        return RefineSolutionResponse(
            refined_solution=refined,
            follow_up=request.follow_up
        )
    except Exception as e:
        logger.error(f"方案优化失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"方案优化失败: {str(e)}"
        )

@router.post("/competitor/refine", response_model=RefineCompetitorResponse, tags=["竞品分析优化"])
async def refine_competitor_analysis(request: RefineCompetitorRequest):
    """竞品分析追问优化接口 - 基于竞品+行业+当前分析+用户追问，生成优化分析报告"""
    try:
        # 构造对话历史上下文
        history_text = ""
        if request.conversation_history:
            for h in request.conversation_history:
                role = h.get('role', 'user')
                content = h.get('content', '')
                history_text += f"{role}: {content}\n"

        refine_prompt = f"""你是华为云竞争分析资深专家。请根据用户的追问，对已有的竞品分析报告进行优化改写。

## 竞品名称
{request.original_competitor}

## 行业场景
{request.original_industry}

## 当前分析报告（Markdown格式）
{request.current_analysis}

## 历史追问记录
{history_text if history_text else '（无）'}

## 本次用户追问
{request.follow_up}

---
**任务要求**：
1. 基于当前分析报告，根据用户的追问要求进行针对性优化
2. 保持报告的专业性和实战性，聚焦华为云 vs {request.original_competitor} 的差异化竞争
3. 如果追问涉及技术架构/价格/生态/服务对比，给出具体的对比细节
4. 如果追问涉及销售话术，给出可直接用于客户沟通的实战话术
5. 输出完整优化后的分析报告（Markdown格式，结构清晰）
6. 不要输出解释性文字，直接输出优化后的完整报告

请用中文输出，格式规范、专业简练。"""

        refined = await get_llm_response(refine_prompt)
        return RefineCompetitorResponse(
            refined_analysis=refined,
            follow_up=request.follow_up
        )
    except Exception as e:
        logger.error(f"竞品分析优化失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"竞品分析优化失败: {str(e)}"
        )


# ==================== AI 智能助手 ====================

# 单次对话上下文的 token 预算：尽量长，但预留 system + 检索 + 回复 空间。
# deepseek-v4 上下文窗口较大，30000 token（约 4.8 万中文字）已非常充裕，可按需调大。
HISTORY_TOKEN_BUDGET = int(os.getenv("AI_CHAT_HISTORY_TOKEN_BUDGET", "30000"))


def _estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文约 1.6 字符/token，英文约 4 字符/token。仅用于历史截断预算。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
    non_cjk = len(text) - cjk
    return max(1, int(cjk / 1.6) + non_cjk / 4)


def _truncate_history_by_tokens(raw_history: list, max_tokens: int = HISTORY_TOKEN_BUDGET) -> list:
    """从最新一条往前累计 token，尽量保留长上下文；至少保留最近 2 条，避免一轮对话被截断。"""
    if not raw_history:
        return []
    selected = []
    used = 0
    for msg in reversed(raw_history):
        content = msg.get("text", "") or msg.get("content", "") or ""
        t = _estimate_tokens(content)
        if selected and used + t > max_tokens:
            break
        selected.append(msg)
        used += t
        if len(selected) >= len(raw_history):
            break
    selected.reverse()
    return selected


def _strip_markdown(text: str) -> str:
    """兜底清洗 AI 回复里的 Markdown 符号（LLM 常无视 prompt 的"禁止 Markdown"要求）。
    只去格式符号，保留正文与 "1." "2." 列表编号、换行。"""
    if not text:
        return text
    s = text
    # 代码块围栏 ```lang ... ``` → 去围栏保留内容
    s = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", s)
    # 行内代码 `code` → code
    s = re.sub(r"`([^`]+)`", r"\1", s)
    # 加粗/斜体 **x** / __x__ → x
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    # Markdown 链接 [text](url) → text
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    # 行首标题符 # ## ###
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)
    # 行首引用符 >
    s = re.sub(r"(?m)^\s{0,3}>\s?", "", s)
    # 残留的成对 ** 兜底
    s = s.replace("**", "")
    # 残留孤立行内代码反引号
    s = s.replace("`", "")
    return s


@router.post("/ai/chat", tags=["AI 助手"])
async def ai_chat(
    request: dict,
    user: Optional[dict] = Depends(get_current_user_optional)
):
    """
    AI 智能助手 - 四路自由问答
    1. 平台使用类 → 使用向导（纯 LLM，基于 PLATFORM_GUIDE）
    2. 个人知识类 → 基于用户私有资料作答（仅已登录）
    3. 云计算/IT/技术业务类 → 对话式 RAG（专业回答）
       3.5 兜底检索：关键词未命中时，用一次极小 LLM 调用判断是否云/IT/方案问题，
           命中则补走 RAG（解决口语化提问漏检索知识库的问题）
    4. 其他所有话题 → 通用 AI 助手（什么都能聊）
    """
    try:
        question = request.get("question", "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="问题不能为空")

        # ---- 提取对话历史（用于上下文）----
        raw_history = request.get("history", [])
        # 按 token 预算动态截断，尽量保留长上下文（单次对话内上下文尽量长）
        recent_history = _truncate_history_by_tokens(raw_history, HISTORY_TOKEN_BUDGET)
        # 格式化为文本："用户：...\n助手：..."
        history_text = ""
        for msg in recent_history[:-1]:  # 排除当前这一轮的最后一条（就是 question 本身）
            role_label = "用户" if msg.get("role") == "user" else "助手"
            history_text += f"{role_label}：{msg.get('text', '')}\n"

        # ---- 路由判断 ----
        # 第一优先级：平台使用类问题
        # 个人知识类问题——已登录时基于用户私有数据作答，置于 usage 之前判定：
        # 个人关键词均含"我的/我们"等专属指代，不会与 usage 的泛化功能词冲突；
        # 同时必须在 cloud 之前，否则"我的客户档案"会被 cloud 的泛化"客户"关键词抢走。
        personal_keywords = [
            "我的客户", "我的资料", "我的知识库", "我上传", "我的文档",
            "我记得", "我的偏好", "关于我", "我的信息", "我存的", "我的方案",
            "我的账号", "我的历史", "我之前", "我整理", "我收集", "个人知识",
            "我的笔记", "我的需求", "我们客户", "我的项目", "我的经历", "我的记忆",
            "我这边", "我的客户档案", "我之前做的", "我保存", "我的客户资料",
        ]
        is_personal = bool(user) and any(kw in question for kw in personal_keywords)
        if is_personal:
            answer = await _answer_personal_question(question, user, history_text)
            return {"answer": _strip_markdown(answer)}

        # 平台使用类问题（纯 LLM，基于 PLATFORM_GUIDE）
        usage_keywords = [
            "怎么用", "如何使用", "怎么使用", "如何操作",
            "功能怎么用", "功能使用", "功能介绍",
            "三种模式", "标准模式", "智能模式", "向导模式",
            "匹配功能", "方案匹配", "匹配怎么",
            "知识库管理", "知识库怎么", "知识库上传", "上传到知识库", "知识库导入", "导入到知识库",
            "添加文档", "上传文档", "导入文档", "文档上传", "索引文档", "重建索引",
            "历史记录", "历史怎么", "导出", "报告导出",
            "产品图谱", "产品分类",
            "仪表盘", "统计数据", "数据含义",
            "账号设置", "登录注册", "个人偏好",
            "这个平台", "本平台", "你们这个网站", "这个网站",
            "这个系统", "本系统",
            "有什么区别", "什么区别", "区别是什么",
            "有什么功能", "哪些功能", "功能有哪些",
            "怎么开始", "从哪开始", "第一步",
            "新手指南", "使用教程", "使用帮助",
            "对比", "比对", "客户记忆", "追问", "多轮", "澄清",
            "定稿", "回滚", "归档", "版本", "版本管理", "迭代",
            "成就", "勋章", "产品图谱", "新手", "上手", "入门",
            "怎么导出", "怎么对比", "怎么保存", "怎么升级", "怎么用这个",
            "功能清单", "所有功能", "能干嘛", "能做什么", "有什么用",
            "客户管理", "CRM", "客户crm", "客户CRM", "客户列表", "客户详情",
            "商机阶段", "客户档案", "名下方案", "客户跟进", "客户归集",
            "关联客户", "关联到客户", "把方案关联", "把客户关联", "方案关联", "关联方案",
            "方案怎么关联", "方案如何关联", "方案绑定客户", "指定给客户", "挂给客户",
            "挂到客户", "归属客户", "归集到客户", "补挂客户", "补挂", "取消关联",
            "方案归给客户", "方案指定给", "历史方案关联", "怎么把方案", "方案怎么挂",
            "解除关联", "解除客户", "客户关系", "方案与客户", "方案和客户", "关联方案客户",
            "成本参考", "成本附表", "报价参考", "报价估算", "成本估算",
            "所属行业", "行业必填", "行业下拉", "行业怎么选", "支持哪些行业",
            "行业精准", "行业检索", "行业过滤", "行业收敛", "参考资料行业",
        ]
        is_usage = any(kw in question for kw in usage_keywords)

        if is_usage:
            answer = await _answer_usage_question(question, history_text)
            return {"answer": _strip_markdown(answer)}

        # 第三优先级：云计算/IT/技术业务类问题（走 RAG）
        cloud_keywords = [
            "华为云", "阿里云", "腾讯云", "AWS", "Azure", "Google Cloud",
            "云服务", "云计算", "云服务器", "云数据库", "云存储",
            "ECS", "OBS", "RDS", "GaussDB", "ModelArts", "CDN",
            "弹性计算", "对象存储", "关系型数据库", "分布式数据库",
            "容器", "Kubernetes", "Docker", "微服务",
            "服务器", "数据库", "负载均衡", "VPC", "VPN",
            "人工智能", "AI", "机器学习", "深度学习", "大模型",
            "物联网", "IoT", "边缘计算", "5G",
            "数字化转型", "智慧城市", "智慧园区", "智慧医疗", "智慧教育",
            "智慧交通", "智慧农业", "智慧能源", "智慧金融", "智慧文旅",
            "工业互联网", "智能制造", "DevOps",
            "公有云", "私有云", "混合云", "多云",
            "SaaS", "PaaS", "IaaS",
            "方案匹配", "解决方案", "售前", "架构设计", "技术选型",
            "竞品", "对比", "哪个好", "推荐", "选型",
            "带宽", "延迟", "可用性", "容灾", "备份",
            "安全组", "防火墙", "WAF", "DDoS",
            "大数据", "数据分析", "数据仓库", "ETL",
            "虚拟化", "OpenStack", "VMware",
            "代码托管", "CI/CD", "持续集成", "持续部署",
            "消息队列", "Redis", "MongoDB", "MySQL", "PostgreSQL",
            "API 网关", "函数计算", "Serverless",
            "视频点播", "直播", "RTC",
            "域名", "DNS", "SSL", "HTTPS", "证书",
            "监控", "日志", "告警", "Prometheus", "ELK",
        ]
        # 纳入全部支持行业名 + 常见方案场景词，避免"XX行业上云方案"类问题落入通用闲聊不检索
        cloud_keywords += list(SUPPORTED_INDUSTRIES)
        cloud_keywords += ["上云", "规划", "架构", "选型", "招投标", "售前", "客户", "方案框架", "建设方案", "整体方案", "技术方案", "落地", "部署"]
        is_cloud = any(kw in question for kw in cloud_keywords)

        if is_cloud:
            user_id = user.get('id') if user else 0
            kb = get_user_knowledge_base(user_id) if user_id > 0 else get_knowledge_base()
            answer = await _answer_business_question(question, kb, history_text)
            return {"answer": _strip_markdown(answer)}

        # 兜底检索：关键词表未命中，但可能是「口语化」的云计算/IT/方案问题
        # （如"数据不能丢怎么设计""系统扛不住高峰怎么办"——一个关键词都不含）
        # 用一次极小 LLM 调用判断是否属于云/IT/方案范畴，命中则转 RAG，
        # 避免辛苦建的知识库对口语化提问完全失效。判断失败安全降级为通用闲聊。
        if await _is_cloud_question_llm(question):
            user_id = user.get('id') if user else 0
            kb = get_user_knowledge_base(user_id) if user_id > 0 else get_knowledge_base()
            answer = await _answer_business_question(question, kb, history_text)
            return {"answer": _strip_markdown(answer)}

        # 第四优先级：其他所有话题 → 通用 AI 助手
        answer = await _answer_general_question(question, history_text)
        return {"answer": _strip_markdown(answer)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI 助手请求失败: {e}")
        # 不返回 500（易被误判为系统故障），改为 200 + 友好兜底文案
        return {
            "answer": "抱歉，AI 助手暂时开小差了，请稍后再试一次。如果问题持续，可以稍后重试或换个问法。",
            "error": "ai_unavailable"
        }


async def _answer_usage_question(question: str, history_text: str = "") -> str:
    """回答平台使用类问题（不检索知识库，直接 LLM 回答）"""
    history_block = f"\n【之前的对话】\n{history_text}\n" if history_text.strip() else ""
    system_prompt = """你是「智能方案助手」— 本平台（cloudsol.cn）的AI使用向导。

【本平台简介】
本平台由郭鸿宇独立开发（杭州电子科技大学，电气工程及其自动化专业），是一个独立的云计算方案匹配工具，不属于任何云厂商。知识库收录了华为云、阿里云、腾讯云、AWS等多家云厂商的公开资料供参考。

【你能帮用户做什么】
1. 平台使用指引：如何匹配方案、管理知识库、导出报告等
2. 云计算知识问答：基于知识库资料回答华为云/竞品相关问题
3. 日常闲聊：任何话题都可以自然交流

【回答原则】
- 必须优先依据下方《平台功能完整说明》回答用户关于本平台功能/使用/细节的问题，做到准确、具体、不编造
- 针对用户的具体问题回答，不要跑题或长篇大论；如果用户问的是某个功能，聚焦讲该功能，必要时可顺带提一句相关功能入口
- 语气专业但亲切，像微信聊天一样自然
- 禁止 Markdown：用纯文本+换行，不要写 # ## ** ``` 等符号

【平台功能完整说明】
""" + PLATFORM_GUIDE + """

用户问题："""
    full_prompt = system_prompt + history_block + question
    return await get_llm_response(full_prompt)


async def _answer_business_question(question: str, kb, history_text: str = "") -> str:
    """回答华为云业务类问题（对话式RAG：检索文档→自然回答，不是生成方案）"""
    # 1. 检索相关文档
    docs = []
    try:
        # 华为云方案 + 全部竞品厂商各取 6 段，覆盖所有平台知识（原竞品仅 2 段，冷门竞品/行业易答不出）
        docs = kb.search_huawei(question, k=6)
        comp_docs = kb.search_competitor(question, k=6)
        docs = (docs or []) + (comp_docs or [])
    except Exception as e:
        logger.warning(f"AI助手向量检索异常: {e}")
        docs = []

    # 格式化上下文
    context_text = ""
    if docs:
        context_parts = []
        for i, doc in enumerate(docs, 1):
            meta = doc.metadata or {}
            source = meta.get("source", "未知来源")
            content = doc.page_content.strip()[:1000]  # 截断避免超token（放宽以保留完整方案表述）
            context_parts.append(f"[资料{i}] 来源：{source}\n{content}")
        context_text = "\n\n".join(context_parts)

    # 2. 对话式 Prompt（纯文本对话，禁止Markdown）
    system_prompt = """你是「智能方案助手」— 一位专业的云计算方案顾问。

你的任务是直接回答用户的云计算相关问题，基于下方参考资料给出专业建议。参考资料涵盖华为云及 12 家竞品厂商（阿里云、腾讯云、AWS、Azure 等）的方案文档，覆盖 25 个行业。
像微信/钉钉聊天那样自然对话，用"您"称呼用户，简洁实用（一般300-500字）。

【格式要求】
- 禁止 Markdown：不要写 # ## ** ``` | []() 等符号
- 用纯文本+换行组织内容，列表用 "1." "2." 开头

"""
    history_block = f"\n【之前的对话】\n{history_text}\n" if history_text.strip() else ""

    if context_text:
        full_prompt = f"{system_prompt}{history_block}【参考资料（基于知识库检索）】：\n\n{context_text}\n\n【用户提问】：{question}"
    else:
        full_prompt = f"{system_prompt}{history_block}（注：当前知识库暂无相关资料，请根据您的专业知识尽量准确回答）\n\n【用户提问】：{question}"

    return await get_llm_response(full_prompt)


async def _is_cloud_question_llm(question: str) -> bool:
    """兜底判断：关键词表未命中时，用一次极小 LLM 调用判断问题是否属于
    【云计算/IT技术/企业数字化/解决方案·售前】范畴。命中则转 RAG 路由，
    避免口语化云问题（如"数据不能丢怎么设计"）掉进通用闲聊不检索知识库。
    判断失败时安全降级为 False（走通用闲聊，保持原行为，绝不阻断问答）。"""
    try:
        prompt = (
            "你是一个分类器。判断下面这句用户提问是否属于"
            "【云计算、IT技术架构、企业数字化转型、行业解决方案/售前咨询】范畴。\n"
            "只回答一个字：是 或 否。禁止任何解释、标点或多余文字。\n\n"
            "示例：\n"
            "「数据不能丢应该怎么设计」→ 是\n"
            "「系统扛不住流量高峰怎么办」→ 是\n"
            "「想做个能弹性扩容的架构」→ 是\n"
            "「医院信息化要考虑什么」→ 是\n"
            "「帮我写一首关于春天的诗」→ 否\n"
            "「今天天气怎么样」→ 否\n"
            "「推荐个午饭吃什么」→ 否\n\n"
            f"这句提问：{question}\n回答："
        )
        resp = (await get_llm_response(prompt) or "").strip()
        head = resp[:6]
        # 先拦否定词（"不是""否""不属于"都含或不含"是"，必须优先判断）
        if ("否" in head) or ("不是" in head) or ("不属于" in head) or ("no" in head.lower()):
            return False
        if ("是" in head) or ("yes" in head.lower()):
            return True
        # 无法解析 → 安全降级
        return False
    except Exception as e:
        logger.warning(f"兜底云问题 LLM 判断失败，降级为通用闲聊: {e}")
        return False


async def _answer_general_question(question: str, history_text: str = "") -> str:
    """回答通用话题（非平台使用、非云计算业务）— 纯 LLM，不检索知识库"""
    history_block = f"\n【之前的对话】\n{history_text}" if history_text.strip() else ""
    system_prompt = """你是「智能方案助手」— cloudsol.cn（华为云解决方案智能匹配系统）的内置 AI 助手。

【你的身份】
- 你是本平台的 AI 助手，不是独立产品
- 本平台由郭鸿宇独立开发（杭州电子科技大学），是一个云计算方案匹配工具
- 你不属于任何 AI 模型公司（如 DeepSeek、OpenAI 等），不要提及底层技术栈

【平台能力速览（被问到"平台能干嘛/有什么功能"时据此作答）】
""" + PLATFORM_BRIEF + """

【回答原则】
- 任何话题都可以自然聊天，像微信朋友一样轻松亲切
- 用"你"称呼用户，简洁实用（200-500字）
- 如果被问到"你是谁/谁开发的/哪家公司的"，回答：你是「智能方案助手」，cloudsol.cn 平台的 AI 助手，由郭鸿宇开发
- 如果用户问的是本平台功能怎么用，请直接给出清晰的使用指引（你已掌握平台全部功能细节）
- 禁止 Markdown：纯文本+换行，不要写 # ## ** ``` 等符号

用户问题："""
    full_prompt = system_prompt + history_block + question
    return await get_llm_response(full_prompt)


async def _answer_personal_question(question: str, user: dict, history_text: str = "") -> str:
    """回答个人知识类问题：基于用户真实私有资料（上传文档 + 客户档案 + 画像 + 偏好）作答，
    严格区分「用户私有资料」与「平台公开参考」，避免把平台案例当成用户客户。"""
    user_id = user.get('id')
    username = user.get('username', '用户')

    # 1. 检索用户真实上传/新建的私有文档（排除平台默认库副本）
    private_docs_text = ""
    kb = None
    try:
        kb = get_user_knowledge_base(user_id)
        docs = kb.search_user_uploaded(question, k=6)
        if docs:
            parts = []
            for i, doc in enumerate(docs, 1):
                meta = doc.metadata or {}
                source = meta.get("source", "未知来源")
                content = doc.page_content.strip()[:1000]
                parts.append(f"[我的私有资料{i}] 来源：{source}\n{content}")
            private_docs_text = "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"个人知识库检索异常: {e}")

    # 2. 客户档案 + 用户画像 + 偏好（来自 DB，客户档案优先）
    profile_text = ""
    has_clients = False
    conn = None
    try:
        from app.utils.db_init import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        # 客户档案（结构化拼装：行业/规模/区域/阶段/预算/痛点/决策链/联系人/标签/备注）
        cur.execute(
            "SELECT name, note, industry, company_size, region, stage, budget, "
            "pain_points, decision_chain, contact_name, contact_title, tags "
            "FROM clients WHERE user_id=?",
            (user_id,),
        )
        clients = cur.fetchall()
        if clients:
            has_clients = True
            lines = []
            for c in clients:
                parts = []
                if c["industry"]:
                    parts.append(f"行业：{c['industry']}")
                if c["company_size"]:
                    parts.append(f"规模：{c['company_size']}")
                if c["region"]:
                    parts.append(f"区域：{c['region']}")
                if c["stage"]:
                    parts.append(f"阶段：{c['stage']}")
                if c["budget"]:
                    parts.append(f"预算：{c['budget']}")
                if c["pain_points"]:
                    parts.append(f"痛点：{c['pain_points']}")
                if c["decision_chain"]:
                    parts.append(f"决策链：{c['decision_chain']}")
                if c["contact_name"]:
                    contact = c["contact_name"] + (f"({c['contact_title']})" if c["contact_title"] else "")
                    parts.append(f"联系人：{contact}")
                if c["tags"]:
                    parts.append(f"标签：{c['tags']}")
                if c["note"]:
                    parts.append(f"备注：{c['note']}")
                lines.append(f"- {c['name']}" + ("｜" + "；".join(parts) if parts else ""))
            profile_text += "【我的客户档案】\n" + "\n".join(lines) + "\n"
        # 用户画像
        cur.execute("SELECT profile_json FROM user_profile WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row and row[0]:
            try:
                pj = json.loads(row[0])
                summary = pj.get("summary") or json.dumps(pj, ensure_ascii=False)
                profile_text += f"【我的用户画像】\n{summary}\n"
            except Exception:
                pass
        # 偏好
        cur.execute("SELECT preferred_industries, theme, language FROM user_preferences WHERE user_id=?", (user_id,))
        prow = cur.fetchone()
        if prow:
            pref_parts = []
            if prow[0]:
                pref_parts.append(f"偏好行业：{prow[0]}")
            if prow[1]:
                pref_parts.append(f"主题：{prow[1]}")
            if prow[2]:
                pref_parts.append(f"语言：{prow[2]}")
            if pref_parts:
                profile_text += "【我的偏好】\n" + "；".join(pref_parts) + "\n"
    except Exception as e:
        logger.warning(f"读取个人档案异常: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    has_personal = bool(private_docs_text or profile_text)
    history_block = f"\n【之前的对话】\n{history_text}\n" if history_text.strip() else ""

    system_prompt = f"""你是「智能方案助手」— cloudsol.cn 平台的 AI 助手，正在与用户「{username}」对话。

【你的任务】
用户正在询问与其个人知识/资料相关的问题。你只能基于下方【我的私有资料】和【我的客户档案与画像】作答，这些是用户本人上传/录入的真实资料。

【重要规则】
- 平台是支持保存客户档案与个人资料的：用户在平台的「客户档案」功能中录入客户后，本助手即可识别并调取。绝不可说「我没有存储/访问客户档案的能力」「每次对话都是独立的」这类否定平台能力的话。
- 若用户问「我的客户档案/我的客户」但【我的客户档案与画像】中没有客户，必须明确回答：「你目前还没有在系统里录入任何客户档案。」然后简短引导：可以在平台的『客户档案』功能中添加客户，录入后我就能帮你调取、分析和做竞品对标。严禁罗列任何不属于用户的公司或案例来充数。
- 若私有资料与画像中均无相关信息，坦诚说明「我这边暂时没有记录到你的相关资料」，可再给一句通用建议，但要点明这不是来自你的资料。

像微信朋友一样自然交流，用"你"称呼用户。
【格式要求】纯文本+换行，不要写 # ## ** ``` 等符号；简洁实用（150-400字）。
"""

    if has_personal:
        full_prompt = f"{system_prompt}{history_block}【我的私有资料】：\n\n{private_docs_text}\n\n【我的客户档案与画像】：\n\n{profile_text}\n\n【用户提问】：{question}"
    else:
        full_prompt = f"{system_prompt}{history_block}（注：当前系统中未检索到你的私有资料，也未录入客户档案）\n【用户提问】：{question}"

    return await get_llm_response(full_prompt)
