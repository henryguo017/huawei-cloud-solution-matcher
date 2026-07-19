# 华为云解决方案智能匹配系统 · cloudsol.cn

> 面向 ToB 售前 / 解决方案工程师的**销售提效工具**——输入客户需求，一键生成华为云方案匹配 + 竞品对比，内置可在线维护的企业级知识库，并支持多客户记忆隔离与持久化。

🌐 线上地址：**https://cloudsol.cn**（已完成 ICP 备案，可正常访问）

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688.svg)
![License](https://img.shields.io/badge/license-个人开源-green.svg)
![Status](https://img.shields.io/badge/status-已上线-brightgreen.svg)

---

## 📌 项目简介

售前同学最头疼的两件事：**写方案慢**、**跟客户讲不清竞品差异**。

本项目把「华为云行业方案知识库 + 大模型」组合起来，让售前人员：

- 输入一段客户需求（甚至只是零散要点），自动生成结构化的华为云解决方案；
- 选定友商，自动产出与华为云的**客观对比 + 销售应对话术**；
- 把团队沉淀的案例、老方案、竞品笔记喂进**私有知识库**，越用越像"只属于你"的方案大脑；
- 按客户维度记住上下文，服务不同客户互不串味。

> ⚠️ **免责声明**：本项目为个人学习 / 演示项目，**非华为官方产品**，与华为技术有限公司无隶属或代言关系。AI 生成的方案仅供参考，正式投标 / 交付前务必由人工核对技术参数与最新报价。

---

## ✨ 核心特性

- **三种匹配模式**：标准（快、稳）、Agent（带思考流的可视化推理）、向导（零门槛填表式）。
- **免登录尝鲜**：提供独立的「快速体验」入口，无需注册即可走标准模式出结果；体验后可引导注册解锁完整能力。
- **竞品对比话术**：12 家主流厂商方案资料，一键生成差异化优势与应对建议。
- **私有知识库**：每个用户完全隔离的知识库，支持在线增删改与单文件重索引。
- **客户记忆隔离**：Agent 模式按「用户 × 客户」双维度隔离记忆，并沉淀跨对话持久记忆与用户画像。
- **多格式客户资料 + OCR**：上传 .txt/.docx/.pdf/.png/.jpg，图片自动 OCR 识别文字纳入上下文。
- **方案导出**：一键生成 Word / PDF 报告，直接发给客户或二次编辑。
- **历史版本化**：方案可归档、可追问精修、可回看来源文档。
- **成就系统 + 数据看板**：把"用工具"变成有反馈的事，一眼看清知识库家底。
- **内置 AI 助手**：三层路由回答「平台怎么用 / 云与竞品业务 / 闲聊」三类问题。
- **多主题 + 响应式**：多套主题皮肤，PC 端与移动端均可用，手机上也能现场给客户出方案。

---

## 🔐 登录与权限模型

为兼顾「低门槛尝鲜」与「私有数据安全」，系统采用分层登录策略：

| 功能 | 是否需要登录 |
|------|------------|
| 快速体验（标准模式尝鲜） | ❌ 免登录 |
| 竞品分析 | ❌ 免登录 |
| 方案导出（Word / PDF） | ❌ 免登录 |
| **标准 / 向导 / Agent 三种匹配模式** | ✅ 需登录 |
| 客户资料上传 / OCR、客户档案、Agent 记忆 | ✅ 需登录 |
| 私有知识库维护、历史方案、收藏、数据看板、成就 | ✅ 需登录 |

- **快速体验**：未登录用户点顶部「体验」按钮，系统强制走标准模式并匿名生成方案，结果页引导注册以解锁保存 / 历史 / 向导 / Agent 等能力。
- **正式三模式**：未登录点击会弹出登录框，登录后全部开放。
- 所有私有数据（知识库、记忆、历史）均通过 JWT 绑定的 `user_id` 隔离，跨用户不可见。

---

## 🧩 功能模块详解

### 1. 三种匹配模式
- **标准模式**：需求文本 → 向量检索 → LLM 生成结构化方案（固定章节结构，质量稳定）。
- **Agent 模式（智能 · Agentic Workflow）**：自写编排引擎驱动「需求分析 → 检索知识库 → 检索竞品 → 生成方案」循环，SSE 实时推送 AI 的**思考流**，能看到它一步步怎么推理。记忆与画像依赖账号。
- **向导模式**：行业 → 规模 → 痛点 → 确认，4 步引导自动合成需求后提交匹配，不会写需求也能出方案。

### 2. 客户档案与 Agent 记忆隔离（登录后）
- Agent 模式下显示「当前客户档案」栏，下拉选择客户（或「+ 新建」「× 删除」），记忆键为 `用户ID:客户ID`，**同一销售的不同客户记忆完全隔离**。
- 选择「（全局记忆 · 不限定客户）」时退化为账号级共享记忆。

### 3. Agent 持久记忆与用户画像（登录后）
- **跨对话记忆**：同一客户的多次匹配共享上下文，最近 15 轮进入窗口，超过 30 天自动归档（不删除），可溯源。
- **用户画像**：Agent 自动从对话中提炼销售风格 / 惯用打法，沉淀为「用户画像」（按账号维度），越用越懂你。

### 4. 用户独立知识库（登录后）
- 每个用户拥有**完全隔离**的知识库（文件 + ChromaDB 向量库），注册自动从默认库复制。
- 支持在线**增删改文档**，改动后一键**单文件重索引**。
- 知识库内置 **300+ 篇方案资料**：华为云方案 + **12 家竞品厂商**方案，全部切分为 **800+ 个向量片段**用于检索，覆盖 **25 个行业**。

### 5. 竞品分析（免登录）
- 内置 12 家主流厂商（阿里云 / 腾讯云 / AWS / 微软 Azure / Google Cloud / Oracle Cloud / 天翼云 / 移动云 / 联通云 / 字节跳动火山引擎 / 西门子 / 施耐德电气）方案对比资料。
- 选择「竞品 + 行业」即可生成与华为云方案的客观对比、差异化优势与销售应对话术。

### 6. 客户资料上传 + OCR（登录后）
- 支持 .txt / .docx / .pdf / .png / .jpg 多格式；图片自动 OCR 识别文字后纳入上下文。
- 路径经白名单校验，杜绝越权读取；单文件 100MB 上限，扩展名白名单过滤。

### 7. 方案导出（免登录）
- 匹配 / 竞品分析结果可一键生成 **Word / PDF 报告**（含方案正文 + 来源文档 + 元数据），直接发给客户或二次编辑。

### 8. 历史方案（登录后）
- **下载 / 归档**：导出报告、长期沉淀优质方案。
- **方案追问优化**：基于已有方案继续让 AI 精修（如"价格部分再详细一点"），保留追问历史。
- **详情查看**：回看完整方案与来源文档。

### 9. 账号与鉴权
- 账号注册（用户名 / 邮箱，带验证码）+ JWT 会话管理；支持邮箱找回密码。
- 登录失败次数限制与账号锁定，密码 bcrypt 加密。

### 10. 成就系统 / 数据看板 / 产品图谱
- 基于使用行为解锁成就徽章；看板展示文档数、行业覆盖与分布；产品图谱可视化浏览华为云产品体系。

### 11. 内置 AI 问答助手
- 顶部面板，三层智能路由：平台使用向导 / 对话式 RAG（检索你的知识库）/ 通用闲聊。
- 内置快捷提问卡片；身份锚定为「cloudsol.cn 内置 AI 助手」，不冒充任何第三方大模型。

---

## 🎨 视觉与体验

- **主题皮肤**：多套主题（如经典蓝 / 浅葱绿 / 盛夏黄 / 桃桃粉），一键切换并持久化偏好；品牌强调色为华为红。
- **统一设计语言**：卡片化布局、轻量阴影、圆角控件、统一图标体系。
- **响应式**：PC 端侧边导航 + 顶栏；移动端（≤767px）底部导航 + 抽屉化交互，独立重构而非简单缩放。

---

## 🛠 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI `0.109` + Uvicorn `0.27`（端口 8000） |
| 前端 | 原生 JS SPA（Vanilla，无构建步骤）+ 静态托管 + Nginx 反向代理 |
| 数据库 | SQLite（用户 / 历史 / 收藏 / 知识库元数据 / 客户档案 / Agent 记忆 / 用户画像）+ ChromaDB `0.4.24`（向量库） |
| AI 编排 | LangChain `0.1.x` + 自写 Agentic Workflow 引擎 |
| 向量模型 | BGE-small-zh（`sentence-transformers 5.5.1`，本地加载） |
| 大模型 | DeepSeek / 阿里云百炼 / 百度文心 / OpenAI（可配置切换） |
| 文档处理 | python-docx + reportlab（导出）、PyMuPDF + pytesseract + Pillow（解析 / OCR） |
| 鉴权 | PyJWT + passlib(bcrypt) + 验证码 |
| 部署 | 云服务器 + Nginx 反代 + systemd 守护 + HTTPS（已上线运行） |
| OCR | 生产环境 tesseract-ocr + chi_sim 中文语言包 |

---

## 📦 环境要求

- Python `3.11+`
- 内存建议 `2GB+`（向量模型与 ChromaDB 较吃资源）
- 如需 OCR：系统需安装 `tesseract-ocr` 与中文包

---

## 🚀 本地快速开始

```bash
# 1. 克隆
git clone https://github.com/henryguo017/huawei-cloud-solution-matcher.git
cd huawei-cloud-solution-matcher

# 2. 创建虚拟环境并安装依赖（国内建议加镜像）
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 3. 配置环境变量
cp .env.example .env              # 按需填写大模型 API Key（见下方配置说明）

# 4. 初始化数据库（幂等，可重复执行）
python -m app.utils.db_init

# 5. 启动后端（开发模式带热重载）
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

浏览器访问 `http://127.0.0.1:8000` 即可。

> 启用 OCR 需在系统中安装 `tesseract-ocr` 与中文包：`apt-get install -y tesseract-ocr tesseract-ocr-chi-sim`，并在 venv 中 `pip install pytesseract Pillow`。

> 首次启动会自动加载向量模型并预热，日志可见知识库文档数与行业数。知识库文档已随仓库 `data/` 提供，无需额外准备即可体验。

---

## ⚙️ 配置说明（`.env`）

所有配置通过环境变量注入，**切勿将真实密钥提交到仓库**。`.env.example` 已列出全部可选项，常用如下：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | 大模型提供商：`deepseek` / `aliyun` / `baidu` / `openai` | `deepseek` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key（国内推荐） | 空 |
| `ALIYUN_API_KEY` / `BAIDU_API_KEY` / `OPENAI_API_KEY` | 对应厂商 Key | 空 |
| `EMBEDDING_MODEL_NAME` | 向量模型名 | `BAAI/bge-small-zh-v1.5` |
| `EMBEDDING_MODEL_LOCAL_PATH` | 本地向量模型目录 | `./data/embedding_model` |
| `VECTOR_DB_PERSIST_DIRECTORY` | ChromaDB 持久化目录 | `./data/vector_db` |
| `KNOWLEDGE_BASE_DIRECTORY` | 华为云方案文档目录 | `./data/sample_solutions` |
| `COMPETITOR_DIRECTORY` | 竞品文档目录 | `./data/competitors` |
| `VECTOR_SEARCH_TOP_K` | 检索返回片段数 | `5` |
| `ENABLE_HYBRID_RETRIEVAL` | RAG 混合召回（向量+关键词 RRF 融合） | `true` |
| `SSE_HEARTBEAT_ENABLED` | SSE 流式心跳保活 | `true` |
| `JWT_SECRET_KEY` | JWT 签名密钥（**生产必须改为随机强密码**） | 占位值 |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASS` | 密码找回邮件 SMTP 配置 | 空 |
| `OFFLINE_MODE` | 离线模式（需预下载模型） | `false` |

完整列表与注释见 [`.env.example`](./.env.example)。

---

## 📂 目录结构

```
huawei-cloud-solution-matcher/
├── api/                    # FastAPI 路由层
│   ├── main.py             # 应用入口（挂载各 router + 启动初始化 + SPA 回退）
│   ├── routes.py           # 匹配 / 竞品分析 / 知识库 / 客户档案 / Agent 记忆
│   ├── auth_routes.py      # 认证 / 历史 / 收藏 / 密码找回
│   ├── auth_dependencies.py# JWT 鉴权（require_login 登录闸）
│   └── export_routes.py    # 方案导出（Word / PDF）
├── app/
│   ├── agent/              # Agent 编排引擎 + 客户记忆 + OCR 解析
│   ├── services/           # Auth / KnowledgeBase / Achievement / 报告生成
│   ├── models/             # Pydantic 数据模型 + LLM 封装
│   ├── core/               # 统一错误枚举与处理器
│   └── utils/              # db_init / captcha
├── frontend/               # 原生 JS SPA（index.html + script.js + style.css + welcome-*）
├── data/                   # 知识库文档 + 向量库 + 用户库（按用户隔离，随仓库提供样本）
├── deploy/                 # Nginx / systemd / HTTPS 部署脚本
├── docs/                   # 设计 / 学习笔记
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🔌 API 概览

后端以 `/api` 为前缀暴露 RESTful API，Swagger 文档见运行后的 `/docs`。

| 模块 | 主要能力 |
|------|----------|
| 匹配 | `POST /api/match`（标准）、`POST /api/agent/match/stream`（Agent SSE 流式） |
| 竞品分析 | `POST /api/competitor/analyze` |
| 知识库 | 文档增删改查、单文件重索引、`/rebuild` 与 `/sync-mine` 异步重建、stats |
| 导出 | 方案 Word / PDF 生成与下载 |
| 认证 | 注册 / 登录 / 当前用户 / 验证码 / 密码找回（JWT） |
| 客户与记忆 | 客户档案 CRUD、Agent 记忆读写、用户画像 |
| 历史 / 收藏 | 历史方案版本化、收藏管理 |
| 成就 / 看板 | 成就解锁查询、知识库统计 |

> 具体路径以 `api/` 下各 router 定义为准；前端已按上述分组调用。

---

## 🚢 生产部署（要点）

项目已上线运行于 `https://cloudsol.cn`。自建部署要点：

1. **代码部署**：将仓库文件覆盖到服务器目录（保留 `venv/` 与 `data/` 不被误删），重启后端服务。
2. **知识库变更**：若修改了 `data/sample_solutions/` 或 `data/competitors/` 下的文档，必须在**停服后**重建向量库（向量库不随代码 `cp` 部署），再启动。
3. **进程守护**：通过 systemd 管理 `uvicorn` 进程；Nginx 反代 `/api` 并托管前端静态资源，屏蔽 `/docs`、`/redoc` 等内部文档路径。
4. **HTTPS**：使用 Let's Encrypt 或其他证书 terminating 在 Nginx。
5. **密钥**：`JWT_SECRET_KEY`、各 `SMTP_PASS`、大模型 API Key 必须在服务器 `.env` 中设置为真实强密码，**切勿写入代码或提交仓库**。

> 部署脚本与 Nginx / systemd 模板见 [`deploy/`](./deploy) 目录。

---

## 🧭 Roadmap / 已知待办

- [ ] **阶段 3 命令沙箱**：设计文档已备，待真实出现"算 ROI / 查实时数据"类需求时再落地（高风险 shell 类能力暂缓）。
- [ ] **阶段 4 自治闭环**：多步自动执行能力，暂未启动。
- [ ] **无障碍（a11y）细节**：部分交互控件（如匹配模式切换标签）使用非原生可聚焦元素，屏幕阅读器用户不可见；已知技术债，按优先级暂未处理。

---

## 📄 License

个人开源项目，仅供学习与交流使用。请勿将 AI 生成内容直接用于生产交付而未经验证。
