import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 关闭 ChromaDB 遥测（国内网络无法上报，避免日志噪音）
os.environ["ANONYMIZED_TELEMETRY"] = "False"

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from api.routes import router
from api.export_routes import router as export_router
from api.auth_routes import router as auth_router
from api.achievement_routes import router as achievement_router
from app.config import APP_NAME, APP_VERSION
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('api.log', encoding='utf-8')
    ]
)
# 静默 ChromaDB 遥测日志（国内网络无法上报）
logging.getLogger('chromadb.telemetry').setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="华为云解决方案智能匹配系统 RESTful API",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
        "http://0.0.0.0:3000",
        "http://0.0.0.0:8000",
        "http://0.0.0.0:8080",
        "http://localhost:5500",
        "http://127.0.0.1:5500"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    
    logger.info(f"请求开始: {request.method} {request.url}")
    
    try:
        response = await call_next(request)
        
        process_time = time.time() - start_time
        logger.info(
            f"请求完成: {request.method} {request.url} "
            f"- 状态码: {response.status_code} "
            f"- 耗时: {process_time:.3f}s"
        )
        
        response.headers["X-Process-Time"] = str(process_time)
        
        # 所有前端静态资源禁止浏览器缓存（解决切换账号后页面不更新的问题）
        path = request.url.path
        if path == "/" or path == "/index.html" or path.endswith(('.html', '.css', '.js', '.svg', '.png', '.jpg', '.ico', '.json', '.woff', '.woff2')):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        
        return response
    except Exception as e:
        logger.error(f"请求异常: {request.method} {request.url} - 错误: {e}")
        raise

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"全局异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器内部错误",
            "error": str(exc)
        }
    )

app.include_router(router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(achievement_router, prefix="/api")

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")
    logger.info(f"静态文件目录: {frontend_path}")

@app.get("/favicon.ico", tags=["前端"])
async def favicon():
    """返回网站图标"""
    favicon_svg = os.path.join(frontend_path, "favicon.svg")
    if os.path.exists(favicon_svg):
        return FileResponse(favicon_svg, media_type="image/svg+xml")
    raise HTTPException(status_code=404)

@app.get("/", tags=["前端"])
@app.get("/index.html", tags=["前端"])
async def root():
    """
    返回前端页面
    """
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "华为云解决方案匹配系统 API", "docs": "/docs"}

@app.get("/style.css", tags=["前端"])
async def style_css():
    """
    返回样式文件
    """
    css_path = os.path.join(frontend_path, "style.css")
    if os.path.exists(css_path):
        return FileResponse(css_path, media_type="text/css")
    return {"error": "Style file not found"}

@app.get("/script.js", tags=["前端"])
async def script_js():
    """
    返回脚本文件
    """
    js_path = os.path.join(frontend_path, "script.js")
    if os.path.exists(js_path):
        return FileResponse(js_path, media_type="application/javascript")
    return {"error": "Script file not found"}

@app.get("/welcome-styles.css", tags=["前端"])
async def welcome_styles():
    """
    返回欢迎页样式文件
    """
    css_path = os.path.join(frontend_path, "welcome-styles.css")
    if os.path.exists(css_path):
        return FileResponse(css_path, media_type="text/css")
    return {"error": "Welcome styles file not found"}

@app.get("/welcome-script.js", tags=["前端"])
async def welcome_script():
    """
    返回欢迎页脚本文件
    """
    js_path = os.path.join(frontend_path, "welcome-script.js")
    if os.path.exists(js_path):
        return FileResponse(js_path, media_type="application/javascript")
    return {"error": "Welcome script file not found"}

@app.get("/js/{filename:path}", tags=["前端"])
async def serve_js(filename: str):
    """
    返回 js/ 目录下的脚本文件
    """
    js_path = os.path.join(frontend_path, "js", filename)
    if os.path.exists(js_path):
        media_type = "application/javascript"
        if filename.endswith(".css"): media_type = "text/css"
        elif filename.endswith(".png"): media_type = "image/png"
        elif filename.endswith(".svg"): media_type = "image/svg+xml"
        return FileResponse(js_path, media_type=media_type)
    raise HTTPException(status_code=404)

@app.get("/{full_path:path}", tags=["前端SPA"])
async def spa_fallback(full_path: str):
    """
    SPA 路由回退：所有非 API、非静态文件的请求都返回 index.html
    支持 /reset-password?token=xxx 等前端路由
    """
    # 排除 API 路径（不应走到这里，但做防御性检查）
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="前端文件不存在")

@app.on_event("startup")
async def startup_event():
    logger.info("=" * 50)
    logger.info(f"{APP_NAME} v{APP_VERSION} 启动中...")
    logger.info("=" * 50)
    
    try:
        from app.utils.db_init import init_database, init_admin_user
        init_database()
        init_admin_user()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.warning(f"数据库初始化警告: {e}")
    
    try:
        from api.dependencies import get_knowledge_base
        kb_service = get_knowledge_base()
        stats = kb_service.get_stats()
        logger.info(f"知识库文档数: {stats['total_documents']}")
        logger.info(f"支持行业数: {len(stats['supported_industries'])}")

        # 预热：提前加载向量模型，避免第一次搜索时耗时
        from app.models.llm import get_embedding_vector
        _ = get_embedding_vector("预热测试")
        logger.info("向量模型预热完成")
    except Exception as e:
        logger.warning(f"知识库初始化警告: {e}")
    
    logger.info("API 服务启动完成")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("API 服务关闭")

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
