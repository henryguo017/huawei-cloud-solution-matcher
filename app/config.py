import os

# numpy 2.x 兼容 shim：chromadb==0.4.24（requirements 锁定）使用了 numpy 1.x 已移除的别名
# （np.float_/np.int_/np.uint 等）。这里在 app 最早加载点补回，确保任何 import chromadb
# 的代码路径（包括 KnowledgeBaseService、向量检索、健康检查、文档列表等）都能正常初始化。
# 影响：当 numpy==2.x 时本 shim 生效；numpy==1.x 时所有 hasattr 已为 True，无副作用。
import numpy as _np
for _shim_name, _shim_val in [
    ("float_", _np.float64), ("int_", _np.int64), ("uint", _np.uint64),
    ("bool8", _np.bool_), ("object_", object), ("complex_", _np.complex128),
]:
    if not hasattr(_np, _shim_name):
        setattr(_np, _shim_name, _shim_val)

# Windows 本地：尽早限制 torch 线程数为 1（必须在任何 sentence-transformers/模型使用之前，
# 否则 torch 线程池已按多线程初始化，embedding 推理触发偶发段错误 SIGSEGV）。
# 生产 Linux 上无副作用（仅 CPU 推理线程收敛，不影响功能）。
try:
    import torch
    torch.set_num_threads(1)
except Exception:
    pass

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
DEEPSEEK_MODEL_NAME = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-v4-flash")
# 全局默认模型：deepseek-v4-flash（2026-08-29 起默认 flash，apikey 成本考量：方案生成/匹配 flash 足够）。
# Agent 模式主路径（harness._call_llm / 直接回复）已显式默认 MATCH_LLM_MODEL(flash)，
# 即使本变量在 .env 设为 pro，Agent 仍走 flash 不烧钱；pro 仅可通过前端模型切换（请求级 model=deepseek-v4-pro）触发。
# 如需全局恢复 pro：改此处为 deepseek-v4-pro 或改服务器 .env（铁律③：改默认值须同步 .env.example）。
MATCH_LLM_MODEL = os.getenv("MATCH_LLM_MODEL", "deepseek-v4-flash")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_TEMPERATURE = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.1"))

# Agent 上下文窗口上限（token）：供前端「上下文用量」预估展示（#1），非硬性截断。
AGENT_CONTEXT_WINDOW = int(os.getenv("AGENT_CONTEXT_WINDOW", "64000"))

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

# ==================== 联网检索（P1-2 知识库之外的互联网资料）====================
# provider 可插拔：tavily（默认推荐，面向 LLM 的搜索 API）/ serper（Google 聚合）。
# 留空 "" 表示关闭联网搜索（Agent 仅基于本地知识库作答，自动降级）。
# API Key 必须放服务端 .env（WEB_SEARCH_API_KEY），绝不写进代码。
# 未配置时 Agent 自动降级、不报错；配置后在工具内限流（每会话最多 WEB_SEARCH_MAX_PER_SESSION 次）。
WEB_SEARCH_PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "")
WEB_SEARCH_API_KEY = os.getenv("WEB_SEARCH_API_KEY", "")
WEB_SEARCH_MAX_PER_SESSION = int(os.getenv("WEB_SEARCH_MAX_PER_SESSION", "3"))

# ==================== P2 多智能体执行开关 ====================
# AGENT_TWO_PHASE=1：真·两阶段执行（plan 驱动工具调用顺序）；=0 回退旧 ReAct 自由循环。
# AGENT_MULTI_AGENT=1：三角色 Orchestrator-Workers（分析师→架构师→校验官）；=0 退化为单角色两阶段。
# 均默认开启；任一异常都会自动降级到已验证的旧路径（稳定性铁律）。
AGENT_TWO_PHASE = os.getenv("AGENT_TWO_PHASE", "1")
AGENT_MULTI_AGENT = os.getenv("AGENT_MULTI_AGENT", "1")

# ==================== P3 推理可靠性开关 ====================
# AGENT_SELF_CHECK=1：交付前过「自检 Gate」（critic LLM 按 5 维 rubric 验收，不过则二次合成）。
# SELF_CHECK_PASS：critic 评分阈值（0-100），低于此值视为不通过、触发二次合成。
# 默认 70：critic 按「维度覆盖」而非「篇幅」评分，完整方案应达 80-95；仅明显缺维度才不过。
# SELF_CHECK_MAX_ITERS：最多二次合成次数（不含首次），达上限仍不过则放行并附 quality_warn。
# 均默认开启；异常自动跳过（稳定性铁律：自检永不阻断用户）。
AGENT_SELF_CHECK = os.getenv("AGENT_SELF_CHECK", "1")
SELF_CHECK_PASS = int(os.getenv("SELF_CHECK_PASS", "70"))
SELF_CHECK_MAX_ITERS = int(os.getenv("SELF_CHECK_MAX_ITERS", "2"))
# AGENT_REFLEXION_REPLAN=1：反思时做「真重规划」（读取失败步→planner 产 plan_v2→重跑失败步），
# 替代 P1-3 软重试；=0 回退 P1-3 单 retry 文本注入。
AGENT_REFLEXION_REPLAN = os.getenv("AGENT_REFLEXION_REPLAN", "1")
REFLEXION_MAX_REPLANS = int(os.getenv("REFLEXION_MAX_REPLANS", "2"))
# AGENT_PARALLEL_TOOLS=1：同 plan 步内只读工具（search_kb/search_competitor/web_search）经 asyncio.gather 并发。
AGENT_PARALLEL_TOOLS = os.getenv("AGENT_PARALLEL_TOOLS", "1")
MAX_PARALLEL = int(os.getenv("MAX_PARALLEL", "3"))

# ==================== P2 Skills 行业技能包开关 ====================
# AGENT_SKILL_PACKS=1：方案/竞品意图命中行业时，自动挂载 data/skill_packs/<slug>.json
# （行业专属提示词注入三角色 + 终稿口径，不改工具集）；=0 完全关闭（零副作用）。
# 生态特性默认关：上线需 .env 显式开启；加载/匹配异常一律静默降级，不阻断主链路。
AGENT_SKILL_PACKS = os.getenv("AGENT_SKILL_PACKS", "0")

# ==================== P2-3 MCP 远程工具客户端开关 ====================
# AGENT_MCP_CLIENT=1：启动时（首次 Agent 运行）按 MCP_SERVERS 配置连接外部 MCP Server，
# 把远端工具注册进本地 ToolRegistry，Agent 即可调用远端标准化工具。
# 默认关闭（0）：不拉起任何子进程、零副作用；任一 Server 连接失败自动跳过（优雅降级）。
AGENT_MCP_CLIENT = os.getenv("AGENT_MCP_CLIENT", "0")
# MCP_SERVERS：JSON 数组，每项 {"command":[...], "label":"命名空间"}。
# 例：'[{"command":["python","-m","app.agent.mcp_server"],"label":"self"}]'
# label 仅允许 [A-Za-z0-9_-]，用于工具名前缀 mcp__<label>__<tool>，避免重名冲突。
MCP_SERVERS = os.getenv("MCP_SERVERS", "")

# ==================== P1 飞书/钉钉群机器人通知（默认关） =================
# 群自定义机器人 webhook + 加签 secret。留空 "" 表示关闭该平台推送（零副作用）。
# 飞书：webhook 形如 https://open.feishu.cn/open-apis/bot/v2/hook/xxxx；secret 为安全设置里的签名校验密钥。
# 钉钉：webhook 形如 https://oapi.dingtalk.com/robot/send?access_token=xxxx；secret 为「加签」密钥。
# 触发：经典 match 完成 / Agent 生成成功；内容=方案名+行业+摘要+cloudsol 链接。
# 签名：HMAC-SHA256(timestamp+"\n"+secret) → base64（飞书/钉钉同公式）。详见 app/services/notify.py。
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")
FEISHU_SECRET = os.getenv("FEISHU_SECRET", "")
DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

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

# ==================== 行业展会自动聚合源 ====================
# 2026-08-02 起：展会 = 自动抓聚合站（AIWW + IDCTalk，24h 懒加载） + 人工 JSON 补充。
# 聚合站链接指向聚合站条目页（用户选 B 方案，接受聚合站链接，换取内容自动更新）；
# 人工 JSON 里的年度大会（华为/云栖等）作为兜底（链接=官网）。
EVENTS_FEEDS = [
    {"name": "AIWW", "url": "https://www.aiww.cn/aievent"},
    {"name": "IDCTalk", "url": "http://www.idctalk.com/huodong"},
]
EVENTS_TTL_SECONDS = int(os.getenv("EVENTS_TTL_SECONDS", str(24 * 3600)))  # 与资讯一致 24h

def _resolve_data_path(p):
    """相对路径统一基于项目根目录解析，避免工作目录(cwd)切换导致加载错误路径的库"""
    return p if os.path.isabs(p) else os.path.join(BASE_DIR, p.lstrip("./\\"))

VECTOR_DB_PROVIDER = os.getenv("VECTOR_DB_PROVIDER", "chroma")
VECTOR_DB_PERSIST_DIRECTORY = _resolve_data_path(os.getenv("VECTOR_DB_PERSIST_DIRECTORY", os.path.join(BASE_DIR, "data", "vector_db")))
# VECTOR_DB_PROVIDER=gaussdb 时的华为云 GaussDB（pgvector）扩展点凭据（默认 chroma 无需配置）。
# 启用 gaussdb 还需在 requirements.txt 增加 psycopg2-binary；当前 GaussDBVectorDB 为结构化扩展点，
# 凭据缺失/驱动未装时抛 VectorDBConfigError（可操作指引），不阻断默认 chroma 模式。
GAUSSDB_HOST = os.getenv("GAUSSDB_HOST", "")
GAUSSDB_PORT = os.getenv("GAUSSDB_PORT", "")
GAUSSDB_USER = os.getenv("GAUSSDB_USER", "")
GAUSSDB_PASSWORD = os.getenv("GAUSSDB_PASSWORD", "")
GAUSSDB_DATABASE = os.getenv("GAUSSDB_DATABASE", "")
GAUSSDB_EMBEDDING_TABLE = os.getenv("GAUSSDB_EMBEDDING_TABLE", "huawei_solutions")

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
