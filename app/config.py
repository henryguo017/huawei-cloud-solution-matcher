import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# ==================== 应用基本配置 ====================
APP_NAME = "华为云解决方案智能匹配系统"
APP_VERSION = "1.1.0"
APP_DESCRIPTION = "基于大模型和向量数据库的华为云行业解决方案智能匹配系统"

# ==================== LLM大模型配置 ====================
# 支持的LLM提供商：openai, deepseek, aliyun, baidu (华为云盘古后续添加)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")

# OpenAI配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo-16k")
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.1"))

# DeepSeek配置 (国内推荐)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL_NAME = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_TEMPERATURE = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.1"))

# 阿里云百炼配置 (国内推荐)
ALIYUN_API_KEY = os.getenv("ALIYUN_API_KEY", "")
ALIYUN_MODEL_NAME = os.getenv("ALIYUN_MODEL_NAME", "qwen-turbo")
ALIYUN_BASE_URL = os.getenv("ALIYUN_BASE_URL", "https://dashscope.aliyuncs.com/api/v1")
ALIYUN_TEMPERATURE = float(os.getenv("ALIYUN_TEMPERATURE", "0.1"))

# 百度文心配置 (国内推荐)
BAIDU_API_KEY = os.getenv("BAIDU_API_KEY", "")
BAIDU_SECRET_KEY = os.getenv("BAIDU_SECRET_KEY", "")
BAIDU_MODEL_NAME = os.getenv("BAIDU_MODEL_NAME", "ernie-bot")
BAIDU_BASE_URL = os.getenv("BAIDU_BASE_URL", "https://aip.baidubce.com/rpc/2.0/ai_custom/v1")
BAIDU_TEMPERATURE = float(os.getenv("BAIDU_TEMPERATURE", "0.1"))

# ==================== 向量数据库配置 ====================
# 支持的向量数据库：chroma (华为云GaussDB后续添加)
# 项目根目录（绝对路径，防止工作目录切换导致加载错误路径的向量库）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _resolve_data_path(p):
    """相对路径统一基于项目根目录解析，避免工作目录(cwd)切换导致加载错误路径的库"""
    return p if os.path.isabs(p) else os.path.join(BASE_DIR, p.lstrip("./\\"))

VECTOR_DB_PROVIDER = os.getenv("VECTOR_DB_PROVIDER", "chroma")
VECTOR_DB_PERSIST_DIRECTORY = _resolve_data_path(os.getenv("VECTOR_DB_PERSIST_DIRECTORY", os.path.join(BASE_DIR, "data", "vector_db")))

# 向量检索配置
VECTOR_SEARCH_TOP_K = int(os.getenv("VECTOR_SEARCH_TOP_K", "5"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

# 向量模型配置 (国内镜像加速)
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")
EMBEDDING_MODEL_LOCAL_PATH = _resolve_data_path(os.getenv("EMBEDDING_MODEL_LOCAL_PATH", os.path.join(BASE_DIR, "data", "embedding_model")))
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
# 批量嵌入 batch_size：批量编码知识库时一次推理多少条（越大越快但越吃内存，CPU 环境 32 较稳）
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
# 知识库重建/同步的全局并发上限（CPU 密集，受限机器建议 1-2，避免多任务抢核拖慢）
KB_REBUILD_CONCURRENCY = int(os.getenv("KB_REBUILD_CONCURRENCY", "2"))

# 网络环境配置
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "false").lower() == "true"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
RETRY_INTERVAL = int(os.getenv("RETRY_INTERVAL", "2"))
DETECTION_TIMEOUT = int(os.getenv("DETECTION_TIMEOUT", "5"))

# ==================== 检索增强 & 流式治理开关（ruoyi-ai 学习项）====================
# 生产默认开启：ENABLE_HYBRID_RETRIEVAL(混合召回) 与 SSE_HEARTBEAT_ENABLED(心跳保活)。
# ENABLE_RERANK 默认关闭（无重排模型时为空操作，安全透传）。
# 如需回退，在 .env 设置对应变量为 false 后重启服务即可。

# RAG 三段式：向量召回 + 关键词全文召回 → RRF 融合 → 重排 → 阈值
ENABLE_HYBRID_RETRIEVAL = os.getenv("ENABLE_HYBRID_RETRIEVAL", "true").lower() == "true"
ENABLE_RERANK = os.getenv("ENABLE_RERANK", "false").lower() == "true"
RAG_RRF_ALPHA = float(os.getenv("RAG_RRF_ALPHA", "0.5"))   # 向量召回在 RRF 中的权重（1-alpha 给关键词召回）
RAG_RRF_K = int(os.getenv("RAG_RRF_K", "60"))               # RRF 常数，避免并列时除零
RAG_THRESHOLD = float(os.getenv("RAG_THRESHOLD", "0.0"))    # 融合后低于该分的片段过滤掉（0=不过滤）

# SSE 流式连接治理
SSE_HEARTBEAT_ENABLED = os.getenv("SSE_HEARTBEAT_ENABLED", "true").lower() == "true"  # 生产已开启：发心跳+超时清理
SSE_HEARTBEAT_INTERVAL = int(os.getenv("SSE_HEARTBEAT_INTERVAL", "30"))  # 心跳间隔（秒）
SSE_TIMEOUT = int(os.getenv("SSE_TIMEOUT", "300"))          # 单次流式最长时长（秒），超时主动结束

# ==================== 知识库配置 ====================
KNOWLEDGE_BASE_DIRECTORY = _resolve_data_path(os.getenv("KNOWLEDGE_BASE_DIRECTORY", os.path.join(BASE_DIR, "data", "sample_solutions")))
COMPETITOR_DIRECTORY = _resolve_data_path(os.getenv("COMPETITOR_DIRECTORY", os.path.join(BASE_DIR, "data", "competitors")))

# 用户独立知识库根目录（注册时自动创建 data/user_docs/{user_id}/ 子目录）
USER_DOCS_BASE_DIR = _resolve_data_path(os.getenv("USER_DOCS_BASE_DIR", os.path.join(BASE_DIR, "data", "user_docs")))

# ==================== 支持的行业列表 ====================
SUPPORTED_INDUSTRIES = [
    "智慧农业",
    "工业互联网",
    "智慧园区",
    "智慧城市",
    "智慧医疗",
    "智慧金融",
    "智慧能源",
    "智慧交通",
    "智慧教育",
    "智慧文旅",
    # ===== 2026-07-18 知识库扩充：新增4个行业（原先仅有华为文档，本次补齐12家竞品）=====
    "制造",
    "政务",
    "零售",
    "汽车",
    # ===== 2026-07-18 第二轮：华为云文档大幅扩充，新增8个华为强势行业 =====
    "矿山",
    "钢铁冶金",
    "化工",
    "智慧物流",
    "传媒文娱",
    "应急管理",
    "智慧水利",
    "国资云",
    # ===== 2026-07-18 补注册3个历史已有但未纳入的行业(互联网/游戏/生物医药) =====
    "互联网",
    "游戏",
    "生物医药"
]

# ==================== 支持的竞争对手列表 ====================
# 分为三大类：国内主流云服务商、国际主流云服务商、行业解决方案提供商
SUPPORTED_COMPETITORS = [
    # === 国内主流云服务商 ===
    "阿里云",          # 阿里巴巴旗下云计算平台
    "腾讯云",          # 腾讯旗下云计算平台
    "字节跳动火山引擎", # 字节跳动旗下企业级技术服务平台
    "天翼云",          # 中国电信旗下云计算品牌
    "移动云",          # 中国移动旗下云计算品牌
    "联通云",          # 中国联通旗下云计算品牌
    # === 国际主流云服务商 ===
    "AWS",             # Amazon Web Services，全球最大云服务商
    "微软Azure",       # Microsoft Azure云计算平台
    "Google Cloud",    # Google Cloud Platform
    "Oracle Cloud",    # Oracle云计算平台
    # === 行业解决方案提供商 ===
    "西门子",          # 德国工业自动化巨头
    "施耐德电气"       # 法国能源管理与自动化专家
]

# ==================== JWT认证配置 ====================
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "huawei-cloud-solution-matcher-secret-key-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24小时

# ==================== 验证码配置 ====================
CAPTCHA_LENGTH = int(os.getenv("CAPTCHA_LENGTH", "4"))
CAPTCHA_EXPIRE_MINUTES = int(os.getenv("CAPTCHA_EXPIRE_MINUTES", "5"))

# ==================== 登录安全配置 ====================
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))  # 最大失败次数
LOCK_DURATION_MINUTES = int(os.getenv("LOCK_DURATION_MINUTES", "15"))  # 锁定时长（分钟）

# ==================== 密码配置 ====================
MIN_PASSWORD_LENGTH = int(os.getenv("MIN_PASSWORD_LENGTH", "6"))
MAX_PASSWORD_LENGTH = int(os.getenv("MAX_PASSWORD_LENGTH", "50"))
BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))

# ==================== 用户限制配置 ====================
MAX_FAVORITES_PER_USER = int(os.getenv("MAX_FAVORITES_PER_USER", "100"))

# ==================== 数据库配置 ====================
# DATABASE_URL 中的相对 sqlite 路径也基于项目根解析（防止 cwd 切换错误）
_db_url = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'data', 'users.db')}")
if _db_url.startswith("sqlite:///") and not os.path.isabs(_db_url[len("sqlite:///"):]):
    _db_url = "sqlite:///" + os.path.join(BASE_DIR, _db_url[len("sqlite:///"):].lstrip("./\\"))
DATABASE_URL = _db_url

# ==================== 邮件配置（密码重置）====================
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.163.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")  # 163邮箱（发件人），生产环境务必在 .env 中配置
SMTP_PASS = os.getenv("SMTP_PASS", "")  # 163邮箱授权码，生产环境务必在 .env 中配置（切勿写死在代码里）
RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", "30"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://cloudsol.cn")