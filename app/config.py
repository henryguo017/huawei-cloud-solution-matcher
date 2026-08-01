import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# ==================== 应用基本配置 ====================
APP_NAME = "华为云解决方案智能匹配系统"
APP_VERSION = "2.4.0"
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
DEEPSEEK_MODEL_NAME = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-v4-pro")
# 匹配生成专用模型（标准/向导模式）。Agent 模式仍使用上面的 DEEPSEEK_MODEL_NAME(pro)。
# 分流目的：标准/向导模式对延迟更敏感，flash 模型墙钟显著更短、基本不触发 60s 超时重试；
# 通过环境变量可随时切换回 pro（铁律③：改默认值须同步 .env.example，或直接改服务器 .env）。
MATCH_LLM_MODEL = os.getenv("MATCH_LLM_MODEL", "deepseek-v4-flash")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_TEMPERATURE = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.1"))

# DeepSeek V4 thinking 模式控制（2026-07-31 V4-Flash-0731 正式版起默认开启思考！
# 思考模式下：①每次请求先无上限输出 reasoning_content，匹配耗时从 ~50s 飙到 140-170s；
# ②temperature/top_p 等参数被静默忽略不生效。本项目生成"方案文本"无需深度推理，
# 默认 disabled 关闭思考；确需推理再在服务器 .env 设 DEEPSEEK_THINKING=enabled）。
DEEPSEEK_THINKING = os.getenv("DEEPSEEK_THINKING", "disabled")
# LLM 单次输出 token 上限（防 thinking/长文无上限拖慢响应；OpenAI 格式兼容字段）
# 4096 实测对一般方案够，但个别长方案"参考资料"段可能被截断，调到 8000 保险。
# 注意：max_tokens 是上限不是目标长度，调大不会让模型输出变长，也不会拖慢正常匹配。
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8000"))

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

# ==================== 天气查询（和风天气） ====================
# key 放服务端 .env（QWEATHER_API_KEY），绝不写进前端代码。
# 注册：https://console.qweather.com/（免费版约 1000 次/天，比高德 5000/月 大 6 倍）
# QWEATHER_API_HOST 为控制台项目里的专属域名（形如 abcdef.qweatherapi.com），每个项目不同。
QWEATHER_API_KEY = os.getenv("QWEATHER_API_KEY", "")
QWEATHER_API_HOST = os.getenv("QWEATHER_API_HOST", "")
QWEATHER_TIMEOUT = float(os.getenv("QWEATHER_TIMEOUT", "5"))

# ==================== 科技资讯聚合（RSS 源，零依赖零费用） ====================
# 顶栏「资讯」按钮数据源。每天刷新一次（NEWS_TTL_SECONDS），跨源去重后按时间取最新。
# 覆盖 AI / 云计算 / 互联网 / 消费电子 / 科技综合，不做细分类。
# 源均为公开 RSS 2.0，单源失败自动跳过不影响整体；源变更直接改这个列表即可。
NEWS_FEEDS = [
    {"name": "IT之家", "url": "https://www.ithome.com/rss/"},
    {"name": "36氪", "url": "https://36kr.com/feed"},
    {"name": "量子位", "url": "https://www.qbitai.com/feed"},
    {"name": "InfoQ", "url": "https://www.infoq.cn/feed"},
    {"name": "开源中国", "url": "https://www.oschina.net/news/rss"},
    {"name": "爱范儿", "url": "https://www.ifanr.com/feed"},
    {"name": "极客公园", "url": "https://www.geekpark.net/rss"},
    {"name": "虎嗅", "url": "https://www.huxiu.com/rss/0.xml"},
    {"name": "少数派", "url": "https://sspai.com/feed"},
]
NEWS_TTL_SECONDS = int(os.getenv("NEWS_TTL_SECONDS", str(24 * 3600)))  # 默认 24h
NEWS_TOP_N = int(os.getenv("NEWS_TOP_N", "10"))
NEWS_FETCH_TIMEOUT = float(os.getenv("NEWS_FETCH_TIMEOUT", "8"))

# ==================== 华为云官方动态聚合（华为云自家社区博客） ====================
# 顶栏「资讯」弹窗第二个标签页。只聚合华为云官方渠道（产品发布/版本更新/优惠活动/认证考试/技术博客）。
# 数据源：华为云社区博客 https://bbs.huaweicloud.com/blogs（华为云自家域名，服务端渲染 HTML，可抓取）。
# 注意：官网 www.huaweicloud.com/news 是 JS 动态渲染 + WAF 防护（非浏览器 UA 返回 JS 挑战页），无法稳定抓取；
# 社区博客 bbs.huaweicloud.com 服务端渲染，无 WAF 拦截，是华为云官方动态最可靠的抓取渠道。
HUAWEI_BLOG_URL = os.getenv("HUAWEI_BLOG_URL", "https://bbs.huaweicloud.com/blogs")
HUAWEI_TOP_N = int(os.getenv("HUAWEI_TOP_N", "10"))

# ==================== 向量数据库配置 ====================
# 支持的向量数据库：chroma (华为云GaussDB后续添加)
# 项目根目录（绝对路径，防止工作目录切换导致加载错误路径的向量库）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ==================== 行业展会 / 活动日历（人工维护 JSON） ====================
# 顶栏「资讯」弹窗第三个标签页。行业展会信息分散在各大会官网、无统一 RSS 源，
# 采用人工维护 JSON（data/industry_events.json，git 跟踪随部署更新）——
# 链接真实可核对，不编造。格式：[{name, city, date_range, location, url, note}]
INDUSTRY_EVENTS_FILE = os.path.join(BASE_DIR, "data", "industry_events.json")

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
# 如需回退，在 .env 设置对应变量为 false 后重启服务即可。

# RAG 召回增强：向量召回 + 关键词全文召回 → RRF 融合 → 阈值过滤
ENABLE_HYBRID_RETRIEVAL = os.getenv("ENABLE_HYBRID_RETRIEVAL", "true").lower() == "true"
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
_DEFAULT_JWT_KEY = "huawei-cloud-solution-matcher-secret-key-change-in-production"
# .env.example 中的占位值，直接复制未改同样视为不安全
_PLACEHOLDER_JWT_KEYS = {
    _DEFAULT_JWT_KEY,
    "change-in-production-please-set-a-random-secret-key",
}
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", _DEFAULT_JWT_KEY)
if JWT_SECRET_KEY in _PLACEHOLDER_JWT_KEYS:
    import warnings
    warnings.warn(
        "[SECURITY] JWT_SECRET_KEY 正在使用默认/占位密钥，登录令牌可被伪造！"
        "请在 .env 中设置随机强密钥（例如: python -c \"import secrets;print(secrets.token_urlsafe(48))\"）。",
        stacklevel=2,
    )
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "360"))  # 6小时

# ==================== 验证码配置 ====================
CAPTCHA_LENGTH = int(os.getenv("CAPTCHA_LENGTH", "4"))
CAPTCHA_EXPIRE_MINUTES = int(os.getenv("CAPTCHA_EXPIRE_MINUTES", "5"))

# ==================== 登录安全配置 ====================
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))  # 最大失败次数
LOCK_DURATION_MINUTES = int(os.getenv("LOCK_DURATION_MINUTES", "15"))  # 锁定时长（分钟）

# 初始管理员密码（留空则不自动创建/不轮换 admin；设置后仅覆盖仍使用默认密码的 admin）
ADMIN_INITIAL_PASSWORD = os.getenv("ADMIN_INITIAL_PASSWORD", "")

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
