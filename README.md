# 华为云解决方案智能匹配系统

> 基于大模型（LLM）+ 向量数据库的华为云行业解决方案智能匹配系统  
> 让销售方案准备时间从 **2小时缩短至1分钟** ⚡

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688.svg)](https://fastapi.tiangolo.com/)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-cloudsol.cn-blueviolet)](https://www.cloudsol.cn)

---

## 项目简介

本系统面向华为云销售工程师和解决方案架构师，通过 **LLM 语义理解 + 向量知识库检索**，实现客户需求到华为云解决方案的秒级精准匹配。

**核心价值：**
- 🎯 输入客户需求 → 30秒内输出定制化解决方案
- 📊 覆盖 17 个行业、170 份方案文档、35 款华为云产品
- 🏆 内置 45 枚成就勋章，激励用户探索系统功能
- 📱 完美适配桌面端和移动端，随时随地使用

**在线体验：** [https://www.cloudsol.cn](https://www.cloudsol.cn)

---

## 功能全览

### 🔍 核心功能

| 功能 | 说明 |
|------|------|
| **智能方案匹配** | 输入客户需求，AI 自动匹配华为云行业解决方案并生成定制化方案 |
| **竞品分析** | 覆盖 12 家竞品，生成华为云差异化优势和实战销售话术 |
| **向导模式** | 4 步问答引导（行业→规模→痛点→确认），零门槛使用 |
| **智能 Agent 模式** | ReAct 循环自动拆解需求、检索知识库、分析竞品，SSE 实时推送思考流 |
| **产品图谱** | 35 款华为云真实产品全景展示，支持按分类筛选、产品详情查看 |
| **追问迭代优化** | 对匹配方案和竞品分析结果进行多轮 AI 追问，一键应用优化结果 |
| **历史记录管理** | 方案匹配/竞品分析独立历史，支持查看、对比、AI 智能总结 |
| **成就勋章系统** | 45 枚成就（铜🥉/银🥈/金🥇/钻💎/隐藏🎪），覆盖使用行为全链路 |
| **用户系统** | 注册/登录/个人中心，JWT 认证 + 图形验证码 + bcrypt 加密 |
| **报告导出** | 支持 Word (docx) 和 PDF 格式导出方案报告和竞品分析报告 |
| **数据仪表盘** | 行业覆盖统计、7日匹配趋势、竞品分析频次、系统运行时间 |
| **知识库管理** | 在线新增/编辑/删除文档，自动向量化建索引，覆盖 17 行业，每个用户独立知识库 |

### 🎨 交互体验

| 特性 | 说明 |
|------|------|
| **欢迎引导页** | 粒子动画背景、数字滚动统计、可选择跳过并记住偏好 |
| **Demo 一键体验** | 制造业预测性维护、智慧农业、智慧园区等预设案例一键匹配 |
| **科技感 UI** | 玻璃态卡片、流式渐变按钮、深色主题、动态光效 |
| **响应式设计** | 桌面端 + 移动端完美适配，移动端底部导航栏 |
| **SPA 架构** | 纯 Vanilla JS 前端，零框架依赖，极致轻量 |
| **方案收藏** | 支持收藏方案/竞品分析报告，个人中心侧边栏实时管理 |
| **彩虹竞品图表** | 竞品分析频次图采用暖→冷彩虹渐变配色（12 色） |

### 🏆 成就系统（45 枚勋章）

成就系统通过检测用户行为自动解锁勋章，增加产品粘性：

**分类：**
- 🥉 铜牌（7 枚）：初出茅庐、竞品初探、知识初窥、登录成功、向导学员、数据爱好者、分享达人
- 🥈 银牌（7 枚）：渐入佳境、竞品猎手、模式体验官、知识贡献者、三连击、行业探索者、夜猫子
- 🥇 金牌（8 枚）：方案大师、竞品专家、行业通、Agent 觉醒、知识库管理员、一周坚守、竞品全图鉴、索引工程师
- 💎 钻石（5 枚）：终极匹配王、终极分析师、成就达人、完美一周、早起鸟
- 🎪 隐藏（18 枚）：愚人快乐、跨年达人、520 告白、深夜修仙、生日快乐、周五狂欢、月圆之夜、鸿蒙探索者、Hello World、我是郭鸿宇、彩蛋猎人、无声胜有声、锲而不舍、Agent 觉醒(隐藏版)、模式大师、秘技大师、40.4 秒、彩蛋收藏家

**触发时机：** 方案匹配、竞品分析、登录、页面访问、知识库操作、连续使用天数等多种行为自动检测。

---

## 项目结构

```
huawei-cloud-solution-matcher/
├── api/                              # FastAPI 后端路由层
│   ├── main.py                       # 应用入口、中间件、路由注册
│   ├── routes.py                     # 方案匹配/竞品分析/历史记录路由
│   ├── auth_routes.py               # 认证路由（注册/登录/登出/个人资料）
│   ├── achievement_routes.py        # 成就系统路由
│   ├── export_routes.py             # 报告导出路由
│   ├── models.py                    # Pydantic 请求/响应模型
│   ├── dependencies.py              # 路由依赖注入
│   └── middleware.py               # CORS、请求日志、缓存控制中间件
├── app/                              # 核心业务模块
│   ├── config.py                    # 全局配置（LLM/向量库/行业/竞品）
│   ├── agent/                       # Agent 智能模式
│   │   └── react_agent.py          # ReAct 循环实现
│   ├── services/                    # 业务服务层
│   │   ├── auth_service.py         # 用户认证服务
│   │   ├── solution_matcher.py     # 方案匹配服务（LLM + 向量检索）
│   │   ├── competitor_analyzer.py  # 竞品分析服务
│   │   ├── knowledge_base.py        # 知识库管理服务（ChromaDB）
│   │   ├── achievement_service.py   # 成就勋章服务（45 枚）
│   │   ├── usage_logger.py         # 使用日志 & 历史记录服务
│   │   └── report_generator.py     # Word/PDF 报告生成服务
│   ├── models/
│   │   ├── llm.py                 # 多模型适配（DeepSeek/OpenAI/阿里/百度）
│   │   ├── vector_db.py            # ChromaDB 向量库封装
│   │   └── export_models.py       # 导出数据模型
│   └── utils/
│       ├── auth_utils.py            # JWT 生成/验证、密码哈希
│       ├── db_init.py               # SQLite 数据库初始化
│       ├── document_loader.py       # 文档加载解析（PDF/TXT/Markdown）
│       ├── network_checker.py       # 网络连通性检测
│       └── embedding_model.py       # 本地嵌入模型管理（BGE-small-zh）
├── frontend/                         # 前端界面（SPA，Vanilla JS）
│   ├── index.html                   # 主页面（所有视图 SPA 切换）
│   ├── style.css                    # 主样式（科技感深色主题、玻璃态、响应式）
│   ├── script.js                    # 主逻辑（SPA 路由、API 调用、产品图谱）
│   ├── welcome-styles.css           # 欢迎页样式
│   ├── welcome-script.js            # 欢迎页逻辑（粒子动画、数字滚动）
│   └── js/
│       ├── chart.umd.min.js        # Chart.js 本地化（去 CDN 依赖）
│       ├── achievement-ui.js        # 成就系统前端 UI
│       ├── page-transition.js        # 页面切换动画
│       └── auth-manager.js          # 认证管理器
├── data/                             # 数据目录
│   ├── sample_solutions/            # 17 个行业华为云解决方案文档（50 个文件）
│   ├── competitors/                 # 12 家竞品分析文档（120 个文件）
│   ├── vector_db/                   # ChromaDB 持久化向量库
│   ├── embedding_model/             # 本地嵌入模型缓存（BGE-small-zh-v1.5）
│   ├── exports/                     # 导出报告文件目录
│   ├── users.db                    # 用户认证 SQLite 数据库
│   ├── usage_logs.db              # 使用日志 SQLite 数据库
│   └── captcha.db                 # 图形验证码 SQLite 数据库
├── deploy/                           # 部署配置
│   ├── cloudsol-nginx.conf         # Nginx 反向代理配置（HTTPS, cloudsol.cn）
│   ├── setup-https.sh              # Let's Encrypt HTTPS 自动配置脚本
│   └── huawei-cloud-api.service   # Systemd 服务文件
├── .workbuddy/                      # WorkBuddy 项目数据（开发辅助）
├── requirements.txt                  # Python 依赖清单
├── start_api.bat                    # Windows 启动脚本
├── .env.example                     # 环境变量模板
├── README.md                        # 本文件
├── DEPLOY.md                       # 部署指南
└── QUICKSTART.md                   # 快速上手指南
```

---

## 技术栈

| 层次 | 技术 | 用途 |
|------|------|------|
| **Web 框架** | FastAPI + Uvicorn | 高性能异步 RESTful API |
| **AI 框架** | LangChain | LLM 应用编排、Prompt 模板 |
| **大模型** | DeepSeek / OpenAI / 阿里百炼 / 百度文心 | 自然语言理解与生成（可切换） |
| **向量数据库** | ChromaDB | 文档向量化存储与语义检索 |
| **嵌入模型** | BGE-small-zh-v1.5 (BAAI) | 中文文本向量化（384 维，本地运行） |
| **Agent 框架** | ReAct (LangChain) | 智能模式：自动拆解需求、检索、分析 |
| **文档处理** | PyPDF | PDF 文档加载与解析 |
| **报告导出** | python-docx + ReportLab | Word / PDF 报告生成 |
| **数据验证** | Pydantic v2 | 请求/响应模型定义 |
| **认证** | PyJWT + passlib(bcrypt) | JWT 令牌 + 密码哈希 |
| **数据库** | SQLite（3 个独立库） | 用户认证 / 使用日志 / 向量库 |
| **前端** | HTML5 + CSS3 + Vanilla JS | 零框架依赖，SPA 架构 |
| **图表** | Chart.js 4.4.0 | 仪表盘图表（热力图、趋势图、频次图） |
| **部署** | Nginx + Systemd | 反向代理 + HTTPS + 服务管理 |

---

## 快速开始

### 环境要求

- Python 3.11+
- 至少一个 LLM API Key（DeepSeek / OpenAI / 阿里百炼 / 百度文心）
- 磁盘空间 ≥ 2GB（用于本地嵌入模型）

### 1. 克隆项目

```bash
git clone https://github.com/yourusername/huawei-cloud-solution-matcher.git
cd huawei-cloud-solution-matcher
```

### 2. 安装依赖

**Windows:**
```bash
start_api.bat
```

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env`，至少配置一个 LLM 密钥：

```env
# DeepSeek（推荐，国内最优性价比）
DEEPSEEK_API_KEY=sk-xxxxxxxx
LLM_PROVIDER=deepseek

# 或 OpenAI
OPENAI_API_KEY=sk-xxxxxxxx
LLM_PROVIDER=openai

# 或阿里云百炼
DASHSCOPE_API_KEY=sk-xxxxxxxx
LLM_PROVIDER=dashscope
```

> **离线模式**：设置 `OFFLINE_MODE=true`，使用本地预先下载的嵌入模型，无需访问 HuggingFace。

### 4. 启动服务

**Windows:**
```bash
start_api.bat
```

**Linux / macOS:**
```bash
source venv/bin/activate
python -m uvicorn api.main:app --host 0.0.0.0 --port 8800 --reload
```

### 5. 访问应用

| 地址 | 说明 |
|------|------|
| http://localhost:8800 | 应用首页（SPA） |
| http://localhost:8800/docs | Swagger 交互式文档 |
| https://www.cloudsol.cn | 生产环境（已部署） |

### 6. 默认管理员账号

> ⚠️ 首次启动后自动创建管理员账号，**生产环境部署后请立即修改密码和邮箱**。

> 账号信息见 `app/utils/db_init.py` 中的初始化逻辑（或查看 `.env.example` 配置说明）。

---

## 使用场景

### 场景一：快速匹配方案

1. 在输入框粘贴客户需求（如"制造业企业想做设备预测性维护"）
2. 点击「智能匹配」，AI 自动检索知识库并生成方案
3. 方案不满意？在追问框输入优化指令继续迭代
4. 满意后点击「导出 Word」或「导出 PDF」保存

### 场景二：竞品攻坚

1. 切换到「竞品分析」标签
2. 选择竞品（如"阿里云"）和行业（如"智慧农业"）
3. 获取竞品 vs 华为云的优劣势对比和销售话术
4. 通过追问功能深入对比技术架构、价格、生态等维度

### 场景三：向导模式（零门槛）

1. 点击「向导模式」按钮
2. 依次选择：行业 → 企业规模 → 核心痛点 → 确认需求
3. 系统自动合成需求描述并提交匹配

### 场景四：产品全景洞察

1. 切换到「产品图谱」标签
2. 按分类筛选产品，点击产品卡片查看详细信息

### 场景五：成就探索

1. 登录后使用系统各项功能
2. 自动解锁对应成就勋章
3. 在「成就」页面查看进度和未解锁成就提示

---

## API 接口概览

### 认证接口 `/api/auth`

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/auth/register` | 无 | 用户注册（含图形验证码） |
| POST | `/api/auth/login` | 无 | 用户登录（含图形验证码） |
| GET | `/api/auth/captcha` | 无 | 获取图形验证码（Base64） |
| GET | `/api/auth/me` | Required | 获取当前用户信息 |
| POST | `/api/auth/logout` | Required | 退出登录（失效 Token） |
| PATCH | `/api/auth/profile` | Required | 更新个人资料 |
| POST | `/api/auth/change-password` | Required | 修改密码 |

### 方案匹配 `/api`

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/match` | Optional | 智能匹配华为云解决方案 |
| POST | `/api/agent/match` | Optional | Agent 智能模式匹配 |
| GET | `/api/agent/match/stream` | Optional | Agent SSE 流式思考推送 |
| POST | `/api/solution/refine` | 无 | 方案追问优化（多轮迭代） |

### 竞品分析 `/api`

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/analyze` | Optional | 竞争对手方案分析 |
| POST | `/api/competitor/refine` | 无 | 竞品分析追问优化 |

### 成就系统 `/api/achievements`

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/achievements` | Required | 获取用户成就列表 |
| POST | `/api/achievements/page-view` | Required | 页面访问成就检测 |

### 历史记录 `/api`（需登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/history/list` | 方案匹配历史列表（分页） |
| GET | `/api/history/{id}` | 方案匹配历史详情 |
| GET | `/api/competitor/history/list` | 竞品分析历史列表 |

### 知识库管理 `/api`

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/knowledge/documents` | Optional | 知识库文档列表（未登录显示全局KB） |
| POST | `/api/knowledge/documents` | Required | 新增文档 |
| PUT | `/api/knowledge/documents/{id}` | Required | 编辑文档 |
| DELETE | `/api/knowledge/documents/{id}` | Required | 删除文档 |
| GET | `/api/knowledge/stats` | Optional | 知识库统计信息 |
| POST | `/api/knowledge/rebuild` | Required | 重建知识库（重新向量化） |
| POST | `/api/knowledge/clear` | Required | 清空知识库 |

---

## 认证机制

### JWT Token 认证

- **算法**：HS256
- **Token 有效期**：24 小时
- **Token payload**：`user_id`、`username`、`role`、`token_version`、`exp`、`iat`
- **Token 失效机制**：登出时递增 `token_version`，使所有旧 Token 立即失效

### 安全措施

| 措施 | 说明 |
|------|------|
| **密码加密** | bcrypt 12 轮哈希，不可逆存储 |
| **Token 版本控制** | `token_version` 字段，登出即失效 |
| **登录失败锁定** | 连续失败 5 次锁定账户 15 分钟 |
| **图形验证码** | 4 位字母+数字，PIL 生成 |
| **Cache-Control** | 前端文件强制 `no-store` |

---

## 知识库

### 覆盖行业（17 个）

智慧农业 · 工业互联网 · 智慧园区 · 智慧城市 · 智慧医疗 · 智慧金融 · 智慧能源 · 智慧交通 · 智慧教育 · 智慧文旅 · 生物医药 · 零售 · 游戏 · 政务 · 汽车 · 互联网 · 制造

### 文档规模

- **华为云方案**：50 份（基于华为云官网真实页面内容）
- **竞品方案**：120 份（12 家竞品 × 10 行业）
- **总计**：170 份文档，向量库 277 个文档片段

### 用户独立知识库（v1.3.0 新增）

- 注册时自动从默认模板库复制完整知识库到用户专属目录 `data/user_docs/{user_id}/`
- 所有 CRUD 操作（增/删/改/重索引）完全隔离，用户之间互不影响
- 方案匹配、竞品分析、Agent 模式均使用用户自己的知识库
- 未登录用户可浏览全局模板知识库（只读），登录后拥有独立可编辑知识库

### 支持竞品（12 家）

| 类别 | 竞品 |
|------|------|
| 国内 | 阿里云 · 腾讯云 · 天翼云 · 移动云 · 联通云 · 字节跳动火山引擎 |
| 国际 | AWS · 微软 Azure · Google Cloud · Oracle Cloud |
| 行业 | 西门子 · 施耐德电气 |

---

## 生产环境部署

> ⚠️ 生产环境部署信息（IP、端口、路径、架构等）已从公开文档中移除，详见私有部署文档。
>
> 如需部署参考，请查看 [DEPLOY.md](DEPLOY.md) 或 [快速上手指南](QUICKSTART.md)。

**在线演示：** [https://www.cloudsol.cn](https://www.cloudsol.cn)

> ✅ 网站已完成 ICP 备案（豫ICP备2026027974号），备案号已加入页脚并链接至工信部备案查询系统。

### 通用部署架构

```
用户浏览器
    └──> Nginx (HTTPS, 443)
            └──> FastAPI (uvicorn, localhost:8xxx)
                        ├──> SQLite (用户认证 / 使用日志)
                        └──> ChromaDB (向量知识库)
```

### 基本部署步骤

```bash
# 1. 克隆代码
git clone https://github.com/henryguo017/huawei-cloud-solution-matcher.git
cd huawei-cloud-solution-matcher

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key 和密钥

# 3. 安装依赖
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. 启动服务
python -m uvicorn api.main:app --host 127.0.0.1 --port 8800 --reload
```

详细配置（Nginx 反向代理、HTTPS、Systemd 服务管理、防火墙规则等）请参考 [DEPLOY.md](DEPLOY.md)。

---

## 成就系统详解

成就系统通过 `achievement_service.py` 实现，包含 45 枚成就：

### 实现原理

1. **埋点检测**：在关键操作（匹配、分析、登录、页面访问、知识库操作）后调用对应检测方法
2. **自动解锁**：满足条件时自动解锁，通过 Toast 通知用户
3. **历史回填**：新用户首次触发时，自动解锁历史行为符合条件的成就（避免老用户遗漏）
4. **稀有度**：铜 < 银 < 金 < 钻 < 隐藏，影响 Toast 展示特效

### 前端展示

- **成就页面**：进度条 + 稀有度过滤 + 卡片网格
- **Toast 通知**：解锁时右上角滑入，显示成就图标、名称、描述、稀有度
- **进度追踪**：实时显示解锁进度（如 3/45，6.7%）

---

## 更新日志

### v1.3.0 (2026-07-01)

**新增：**
- 👤 用户独立知识库系统（注册时自动复制默认模板，各自独立增删改）
- 🔒 知识库权限前端 UI 控制（未登录隐藏编辑/删除/新增/重建/清空按钮）
- 📊 知识库隔离审计测试脚本（52 项端到端测试）

**修复：**
- 修复登录 Bug（3 个问题：数据库路径/token_version/timezone）
- 修复未登录用户可见知识库写操作 UI 按钮
- 修复登录后页面需手动刷新才显示操作按钮
- 修复 ChromaDB 遥测日志噪音（设置日志级别 CRITICAL 静默）
- 修复 `GET /documents` 未登录返回 403（改为 Optional Auth）

**优化：**
- 登录成功改为 `location.reload()` 整页刷新，彻底解决 UI 状态不一致
- 文档数从 276 增至 277 个向量片段

### v1.2.0 (2026-06-30)

**新增：**
- 🏆 成就勋章系统（45 枚，含铜/银/金/钻/隐藏 5 个稀有度）
- 📱 移动端底部导航栏（7 个 Tab：匹配/竞品/产品/仪表盘/知识库/历史/成就）
- 🔍 知识库在线文档编辑器（支持 TXT/Markdown 直接输入）
- ⚠️ 清空知识库二次确认弹窗
- 📋 ICP 备案号页脚（豫ICP备2026027974号，PC 端展示）
- 🔒 README 安全脱敏（移除生产环境 IP/端口/路径/默认账号）

**修复：**
- 修复竞品成就同时解锁（历史数据全量统计问题）
- 修复 `perfect_week` 成就未实现
- 修复连续天数成就只在 login 触发
- 修复非隐藏成就显示"???" 
- 修复 `late_night` 与 `early_bird` 时间重叠
- 修复知识库弹窗背景透明度过高的视觉问题
- 修复仪表盘右侧圆弧在移动端不可见
- 修复日志/历史记录保存空输入替换后的内容（改用 original_demand）

**优化：**
- 移动端成就卡片改为一行 4 个
- 向导模式导航按钮重排（上一步/下一步并排等宽）
- 知识库文档卡片移动端排版优化
- 空输入匹配支持（触发"无声胜有声"隐藏成就）
- 移动端隐藏备案号 footer（法规仅要求 PC 端展示）

### v1.1.0 (2026-06-05)

**知识库大幅扩充：**
- 竞品文档补齐至 12 家 × 10 行业 = 120 份
- 华为云方案新增 7 个行业（生物医药、零售、游戏等）
- 知识库总计 170 份文档，向量库 276 个文档片段

### v1.0.0 (2026-05-30)

**核心功能上线：**
- 智能方案匹配（标准/智能 Agent/向导 三种模式）
- 竞品分析（12 家竞品）
- 产品图谱（35 款华为云产品）
- 用户系统 + JWT 认证
- 报告导出（Word/PDF）
- 数据仪表盘
- 知识库管理

---

## 相关文档

- [快速上手指南](QUICKSTART.md)
- [部署指南](DEPLOY.md)
- [网络配置指南](NETWORK_GUIDE.md)

---

## 贡献指南

欢迎提交 Issue 和 Pull Request！

---

## 许可证

MIT License

---

**Made with ❤️ for Huawei Cloud**
