# 华为云解决方案智能匹配系统

> 基于大模型（LLM）+ 向量数据库的华为云行业解决方案智能匹配系统，让销售方案准备时间从 **2小时缩短至1分钟**。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-009688.svg)](https://fastapi.tiangolo.com/)

---

## 功能亮点

### 核心能力

- **智能方案匹配** — 输入客户需求，AI 自动匹配华为云行业解决方案并生成定制化方案
- **竞争对手分析** — 覆盖 12 家竞品（阿里云/AWS/腾讯云等），生成华为云差异化优势和实战销售话术
- **产品图谱** — 35 款华为云真实产品全景展示，支持按分类筛选、产品详情查看、3D 产品架构树形图
- **追问迭代优化** — 对匹配方案和竞品分析结果进行多轮 AI 追问，一键应用优化结果到方案并同步至历史记录
- **历史记录管理** — 方案匹配/竞品分析两套独立历史记录，支持查看详情、双方案对比、AI 智能对比总结
- **用户系统** — 注册/登录/个人中心，支持 JWT 认证、图形验证码、密码 bcrypt 加密
- **报告导出** — 支持 Word (docx) 和 PDF 格式导出方案报告和竞品分析报告
- **数据仪表盘** — 行业覆盖统计、7日匹配趋势、竞品分析频次、系统运行时间等真实运营数据
- **知识库管理** — 支持向量知识库构建、统计、重建和清空，覆盖 10 大行业、44 份方案文档

### 交互体验

- **欢迎引导页** — 粒子动画背景、数字滚动统计、可选择跳过并记住偏好
- **Demo 案例** — 制造业预测性维护、智慧农业、智慧园区等一键体验
- **科技感 UI** — 玻璃态卡片、流式渐变按钮、粒子网络动画、深色/浅色主题
- **响应式设计** — 支持桌面端和移动端自适应布局
- **SPA 架构** — 纯 Vanilla JS 前端，零框架依赖，极致轻量
- **方案收藏** — 支持收藏方案/竞品分析报告，个人中心侧边栏实时同步管理
- **彩虹色竞品图表** — 竞品分析频次图采用暖→冷彩虹渐变配色（12 色），一目了然
- **3D 产品架构图** — Canvas 3D 引擎，支持拖拽旋转、滚轮缩放、节点点击高亮、自动旋转

---

## 项目结构

```
huawei-cloud-solution-matcher/
├── api/                          # FastAPI 后端
│   ├── main.py                   # 应用入口、中间件、路由注册
│   ├── auth_routes.py            # 认证路由（注册/登录/登出/个人资料）
│   ├── auth_dependencies.py      # JWT 认证依赖注入（token_version 校验）
│   ├── export_routes.py          # 报告导出路由
│   ├── models.py                 # Pydantic 请求/响应模型
│   └── middleware.py             # CORS、请求日志、缓存控制中间件
├── app/                          # 核心业务模块
│   ├── config.py                 # 全局配置（LLM/向量库/行业/竞品）
│   ├── services/                 # 业务服务层
│   │   ├── auth_service.py       # 用户认证服务（注册/登录/登出/token_version）
│   │   ├── solution_matcher.py   # 方案匹配服务（LLM + 向量检索）
│   │   ├── competitor_analyzer.py # 竞品分析服务
│   │   ├── knowledge_base.py     # 知识库管理服务（ChromaDB）
│   │   ├── usage_logger.py       # 使用日志 & 历史记录服务
│   │   └── report_generator.py   # Word/PDF 报告生成服务
│   ├── models/                   # 模型层
│   │   ├── llm.py               # 多模型适配（DeepSeek/OpenAI/阿里/百度）
│   │   ├── vector_db.py          # ChromaDB 向量库封装
│   │   └── export_models.py     # 导出数据模型
│   └── utils/                    # 工具模块
│       ├── auth_utils.py          # JWT 生成/验证、密码哈希
│       ├── db_init.py             # SQLite 数据库初始化（users.db）
│       ├── document_loader.py    # 文档加载解析（PDF/TXT）
│       ├── network_checker.py    # 网络连通性检测（多 LLM 提供商）
│       └── embedding_model.py    # 本地嵌入模型管理（BGE-small-zh）
├── frontend/                     # 前端界面（SPA，Vanilla JS）
│   ├── index.html                # 主页面（方案匹配/竞品分析/产品图谱/历史/个人中心）
│   ├── style.css                 # 主样式（科技感深色主题、玻璃态、粒子动画）
│   ├── script.js                 # 主逻辑（SPA 路由、API 调用、DOM 操作、产品图谱、3D引擎）
│   ├── welcome-styles.css        # 欢迎页样式
│   └── welcome-script.js         # 欢迎页逻辑（粒子动画、数字滚动）
├── data/                         # 数据目录
│   ├── sample_solutions/         # 10 大行业解决方案文档（44 个文件）
│   ├── competitors/              # 12 家竞品分析文档（82 个文件）
│   ├── vector_db/                # ChromaDB 持久化向量库
│   ├── embedding_model/          # 本地嵌入模型缓存（BGE-small-zh-v1.5）
│   ├── exports/                  # 导出报告文件目录
│   ├── users.db                  # 用户认证 SQLite 数据库
│   ├── usage_logs.db            # 使用日志 SQLite 数据库
│   └── captcha.db               # 图形验证码 SQLite 数据库
├── deploy/                       # 部署配置
│   ├── nginx.conf                # Nginx 反向代理配置（HTTPS）
│   ├── supervisor.conf           # Supervisor 进程守护（4 worker）
│   └── huawei-matcher.service   # Systemd 服务文件
├── backup/                       # 历史版本备份
├── requirements.txt               # Python 依赖清单
├── install.bat                   # Windows 一键安装脚本
├── start_api.bat                 # Windows 启动脚本
├── .env.example                  # 环境变量模板
├── DEPLOY.md                     # 部署指南
├── QUICKSTART.md                 # 快速上手指南
└── README.md                     # 本文件
```

---

## 技术栈

| 层次           | 技术                              | 用途                                 |
| -------------- | --------------------------------- | ------------------------------------ |
| **Web 框架**   | FastAPI 0.109.0 + Uvicorn 0.27.0 | 高性能异步 RESTful API                |
| **AI 框架**    | LangChain 0.1.20                  | LLM 应用编排、Prompt 模板            |
| **大模型**      | DeepSeek / OpenAI / 阿里百炼 / 百度文心 | 自然语言理解与生成（可切换，4 家） |
| **向量数据库**  | ChromaDB 0.4.24                   | 文档向量化存储与语义检索             |
| **嵌入模型**    | BGE-small-zh-v1.5 (BAAI)          | 中文文本向量化（384 维，本地运行）  |
| **文档处理**    | PyPDF 4.2.0                       | PDF 文档加载与解析                  |
| **报告导出**    | python-docx 0.8.11 + ReportLab 4.0.4 | Word / PDF 报告生成               |
| **数据验证**    | Pydantic v2.5.3                   | 请求/响应模型定义                    |
| **认证**        | PyJWT + passlib(bcrypt)            | JWT 令牌 + 密码哈希（12 轮）        |
| **数据库**      | SQLite 3（3 个独立库）            | 用户认证 / 使用日志 / 向量库        |
| **前端**        | HTML5 + CSS3 + Vanilla JS          | 零框架依赖，SPA 架构                |
| **图表**        | Chart.js 4.4.0                    | 仪表盘图表（热力图、趋势图、频次图）|
| **3D 渲染**    | Canvas 2D（纯 JS 3D 引擎）         | 产品架构树形图（透视投影、拖拽旋转）|
| **部署**        | Nginx + Supervisor + Systemd       | 反向代理 + 进程守护 + 服务管理      |

---

## 快速开始

### 环境要求

- Python 3.8+
- 至少一个 LLM API Key（DeepSeek / OpenAI / 阿里云百炼 / 百度文心）
- 磁盘空间 ≥ 2GB（用于本地嵌入模型）

### 1. 安装依赖

**Windows:**

```bash
install.bat
```

**Linux / macOS:**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置 API Key

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

# 或百度文心
QIANFAN_API_KEY=xxxxxxxx
QIANFAN_SECRET_KEY=xxxxxxxx
LLM_PROVIDER=wenxin
```

> **离线模式**：设置 `OFFLINE_MODE=true`，使用本地预先下载的嵌入模型，无需访问 HuggingFace。

### 3. 启动服务

**Windows:**

```bash
start_api.bat
```

**Linux / macOS:**

```bash
source venv/bin/activate
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 访问应用

| 地址                     | 说明              |
| ------------------------ | ----------------- |
| http://localhost:8000    | 应用首页（SPA）   |
| http://localhost:8000/docs | Swagger 交互式文档 |
| http://localhost:8000/redoc | ReDoc 文档       |

### 5. 默认管理员账号

| 字段     | 值                    |
| -------- | --------------------- |
| 用户名   | `admin`               |
| 密码     | `admin123`            |
| 邮箱     | `admin@huawei.com`    |

> 首次登录后请立即修改密码。

---

## 产品图谱功能

###  Overview

产品图谱页面展示 **35 款华为云真实产品**，按 9 大分类组织，支持：

- **分类筛选**：点击分类按钮筛选产品（全部/计算/存储/数据库/AI/物联网/安全/媒体/企业应用/网络）
- **产品详情**：点击产品卡片查看详细描述、核心能力、适用场景、产品优势、技术亮点
- **3D 架构图**：点击标题栏「产品架构」按钮，打开 3D 产品架构树形图弹窗
  - 根节点：华为云
  - 一级节点：9 大产品分类（彩色编码）
  - 二级节点：具体产品
  - 支持鼠标拖拽旋转、滚轮缩放、点击高亮节点、自动旋转开关

### 3D 引擎技术说明

- 纯 Canvas 2D 实现 3D 透视效果（无 Three.js 依赖）
- 透视投影：`fov = 750 * zoom`
- 相机参数：`rx`（X轴旋转）、`ry`（Y轴旋转）、`zoom`（缩放）、`tx/ty`（平移）
- 节点布局：分类节点环形分布（`catRadius=210`），产品节点围绕分类分布（`prodRadius=125`）

---

## API 接口概览

### 认证接口 `/api/auth`

| 方法 | 路径                          | 认证   | 说明                     |
| ---- | ----------------------------- | ------ | ------------------------ |
| POST | `/api/auth/register`          | 无     | 用户注册（含图形验证码） |
| POST | `/api/auth/login`             | 无     | 用户登录（含图形验证码） |
| GET  | `/api/auth/captcha`           | 无     | 获取图形验证码（Base64） |
| GET  | `/api/auth/me`                | Required | 获取当前用户信息        |
| POST | `/api/auth/logout`            | Required | 退出登录（失效 Token）  |
| PATCH| `/api/auth/profile`           | Required | 更新个人资料            |
| POST | `/api/auth/change-password`   | Required | 修改密码                |
| GET  | `/api/auth/stats`             | Required | 用户使用统计            |

### 方案匹配 `/api`

| 方法 | 路径                          | 认证     | 说明                     |
| ---- | ----------------------------- | -------- | ------------------------ |
| POST | `/api/match`                  | Optional | 智能匹配华为云解决方案   |
| POST | `/api/solution/refine`        | 无       | 方案追问优化（多轮迭代） |

### 竞品分析 `/api`

| 方法 | 路径                          | 认证     | 说明                     |
| ---- | ----------------------------- | -------- | ------------------------ |
| POST | `/api/analyze`                | Optional | 竞争对手方案分析         |
| POST | `/api/competitor/refine`     | 无       | 竞品分析追问优化         |

### 历史记录 `/api`（需登录）

| 方法 | 路径                                      | 说明                         |
| ---- | ----------------------------------------- | ---------------------------- |
| GET  | `/api/history/list`                       | 方案匹配历史列表（分页）     |
| GET  | `/api/history/{id}`                       | 方案匹配历史详情             |
| PATCH| `/api/history/{id}/solution`               | 更新方案内容（追问后保存）   |
| POST | `/api/history/compare`                    | 双方案对比                   |
| POST | `/api/history/ai-summary`                 | AI 智能对比总结              |
| GET  | `/api/competitor/history/list`            | 竞品分析历史列表             |
| GET  | `/api/competitor/history/{id}`            | 竞品分析历史详情             |

### 知识库管理 `/api`

| 方法 | 路径                          | 说明                     |
| ---- | ----------------------------- | ------------------------ |
| GET  | `/api/knowledge/stats`        | 知识库统计信息           |
| POST | `/api/knowledge/rebuild`      | 重建知识库（重新向量化） |
| POST | `/api/knowledge/clear`        | 清空知识库               |

### 报告导出 `/api`

| 方法 | 路径                                  | 说明                         |
| ---- | ------------------------------------- | ---------------------------- |
| POST | `/api/export/report`                  | 导出 Word/PDF 报告          |
| GET  | `/api/export/task/{task_id}`          | 查询导出任务状态             |
| GET  | `/api/export/download/{task_id}`       | 下载报告文件                 |

### 数据仪表盘 `/api`（需登录）

| 方法 | 路径                          | 说明                         |
| ---- | ----------------------------- | ---------------------------- |
| GET  | `/api/dashboard/stats`        | 获取仪表盘统计数据           |

### 系统 `/api`

| 方法 | 路径                          | 说明                         |
| ---- | ----------------------------- | ---------------------------- |
| GET  | `/api/health`                 | 健康检查                     |

---

## 认证机制

### JWT Token 认证

- **算法**：HS256
- **Token 有效期**：24 小时（`JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 1440`）
- **Token payload**：`user_id`、`username`、`role`、`token_version`、`exp`、`iat`
- **Token 失效机制**：登出时递增 `token_version`，使所有旧 Token 立即失效

### 安全措施

| 措施                      | 说明                                               |
| ------------------------- | -------------------------------------------------- |
| **密码加密**              | bcrypt 12 轮哈希，不可逆存储                       |
| **Token 版本控制**        | `token_version` 字段，登出即失效，无需等待过期     |
| **登录失败锁定**          | 连续失败 5 次锁定账户 15 分钟                     |
| **图形验证码**            | 4 位字母+数字，PIL 生成，5 分钟过期，一次性使用  |
| **Cache-Control**         | 前端文件强制 `no-store`，防止浏览器缓存敏感页面     |
| **CORS 可控**            | 通过 `CORS_ORIGINS` 环境变量配置允许的源          |

### 认证模式

| 接口类型     | 认证方式                | 说明                                       |
| ------------ | ----------------------- | ------------------------------------------ |
| 方案匹配     | `get_current_user_optional` | 未登录可使用，但不保存历史记录           |
| 竞品分析     | `get_current_user_optional` | 同上                                     |
| 历史记录     | `get_current_user`      | 必须登录                                   |
| 仪表盘       | `get_current_user`      | 必须登录                                   |
| 个人中心     | `get_current_user`      | 必须登录                                   |

---

## 数据库架构

系统使用 **3 个数据存储**，轻量且无需额外安装数据库服务。

### 数据库 1：`data/users.db`（用户认证）

| 表名             | 用途                     | 关键字段                                                   |
| ----------------- | ------------------------ | ---------------------------------------------------------- |
| `users`           | 用户主表                 | id, username, email, password_hash, role, token_version...  |
| `history`         | 通用操作历史             | id, user_id, query_type, query_content, result_content...   |
| `favorites`       | 方案收藏                 | id, user_id, solution_name, solution_content, industry...   |
| `user_preferences`| 用户偏好设置             | id, user_id, preferred_industries, theme, language...       |
| `captchas`        | 图形验证码               | id, captcha_key, captcha_value, expires_at...              |
| `login_logs`      | 登录日志（预留）         | id, user_id, username, ip_address, login_status...          |

### 数据库 2：`data/usage_logs.db`（使用日志）

| 表名             | 用途                     | 关键字段                                                   |
| ----------------- | ------------------------ | ---------------------------------------------------------- |
| `usage_logs`      | 操作日志                 | id, action_type, detail, user_id, created_at...            |
| `match_history`   | 方案匹配/竞品分析历史    | id, demand_text, solution, industry, type, user_id...       |

> `match_history` 每种类型最多保留 100 条记录（`MAX_MATCH_HISTORY = 100`）。

### 数据库 3：ChromaDB 向量库（`data/vector_db/`）

- **Collection 名称**：`huawei_solutions`
- **存储内容**：行业解决方案文档片段 + 竞品方案文档片段
- **元数据**：`source`（文件名）、`industry`（行业名）
- **嵌入维度**：384（BGE-small-zh-v1.5）
- **检索 top_k**：5

---

## 知识库

### 覆盖行业（10 个）

智慧农业 · 工业互联网 · 智慧园区 · 智慧城市 · 智慧医疗 · 智慧金融 · 智慧能源 · 智慧交通 · 智慧教育 · 智慧文旅

### 支持竞品分析（12 家）

| 类别   | 竞品                                                         |
| ------ | ------------------------------------------------------------ |
| 国内   | 阿里云 · 腾讯云 · 天翼云 · 移动云 · 联通云 · 字节跳动火山引擎 |
| 国际   | AWS · 微软 Azure · Google Cloud · Oracle Cloud                |
| 行业   | 西门子 · 施耐德电气                                         |

### 产品图谱覆盖产品（35 款，9 大分类）

| 分类       | 产品数量 | 代表产品                                       |
| ---------- | -------- | ---------------------------------------------- |
| 计算       | 5        | ECS, Auto Scaling, 云耀云服务器 HECS, 裸金属服务器 BMS, 弹性云服务器 ECSV |
| 存储       | 4        | OBS, EVS, SFS Turbo, 云备份 CBR              |
| 数据库     | 5        | RDS, GaussDB, DDS, 云数据库 GeminiDB, DRS     |
| AI 大模型  | 5        | ModelArts, 盘古大模型, 昇腾 AI 推理, HiLens, 图引擎 GES |
| 物联网     | 4        | IoTDA, 设备管理 IoTDM, 智能边缘 IEF, 车联网平台 IoV  |
| 安全       | 5        | 态势感知 SA, 企业主机安全 HSS, WAF, DDoS 防护, 数据加密 DEW |
| 媒体服务   | 3        | 视频点播 VOD, 视频直播 Live, 媒体转码 MPC      |
| 企业应用   | 3        | 开天 aPaaS, 数字化供应链 SCM, 智能数据洞察 DLI |
| 网络       | 4        | VPC, 弹性负载均衡 ELB, 弹性公网 IP EIP, 云解析 DNS |

### 扩展知识库

将方案文档按行业分类放入对应目录，然后重建知识库：

```
data/sample_solutions/
├── 智慧农业/
│   └── 华为云智慧农业解决方案.pdf
├── 工业互联网/
│   └── 工业互联网白皮书.txt
└── ...
```

在前端「知识库管理」页面点击「重建知识库」，或调用 API：

```bash
curl -X POST http://localhost:8000/api/knowledge/rebuild
```

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

### 场景三：产品全景洞察

1. 切换到「产品图谱」标签
2. 按分类筛选产品，点击产品卡片查看详细信息
3. 点击「产品架构」按钮打开 3D 架构树形图
4. 拖拽旋转/滚轮缩放查看产品层级关系

### 场景四：方案回顾与对比

1. 登录后点击「历史记录」，查看过往方案
2. 选择两条历史记录进行并排对比
3. 使用「AI 智能总结」自动生成对比报告

### 场景五：运营数据分析

1. 登录后点击「仪表盘」，查看系统使用数据
2. 行业覆盖统计、7 日匹配趋势、竞品分析频次一目了然

---

## Docker 部署

```bash
# 构建镜像
docker build -t huawei-cloud-matcher .

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

> 注意：当前 `Dockerfile` 和 `docker-compose.yml` 需要进一步完善配置。

---

## 生产环境部署（Linux）

### 架构

```
用户浏览器
    └──> Nginx (HTTPS, 443)
            └──> FastAPI (uvicorn, 127.0.0.1:8000, 4 workers)
                        ├──> SQLite (users.db / usage_logs.db)
                        └──> ChromaDB (vector_db/)
```

### 步骤

1. **Nginx 配置**：参考 `deploy/nginx.conf`，配置 HTTPS（TLSv1.2/1.3）、静态文件服务、API 反向代理
2. **Supervisor 配置**：参考 `deploy/supervisor.conf`，管理 4 个 uvicorn worker
3. **Systemd 配置**：参考 `deploy/huawei-matcher.service`，开机自启

---

## 相关文档

- [快速上手指南](QUICKSTART.md)
- [部署指南](DEPLOY.md)
- [网络配置指南](NETWORK_GUIDE.md)

---

## 更新日志

### v20260531k (2026-05-31)

**Bug 修复：**
- 修复竞品分析/方案匹配完成后内容空白（`_resetView()` 不再销毁结果容器 DOM 结构）
- 修复竞品分析结果展示防御性恢复逻辑（检测到子元素丢失时自动重建）
- 修复 3D 产品架构弹窗位置偏下（CSS `align-items: center` → `flex-start` + `padding-top: 6vh`）
- 修复 3D 树初始状态偏小、各角度旋转时节点标签重叠（放大 35% + 增大分布半径）

**功能改进：**
- 3D 产品架构树形图：分类半径 `160→210`、产品半径 `90→125`、节点半径同步增大
- 透视 fov 基础值 `600→750`，大场景透视更平缓

### v1.1.0 (2026-05-30)

**Bug 修复：**
- 修复账号切换时 Edge 浏览器自动填充导致的"切换失败"问题（JWT token_version + 延迟二次清空）
- 修复竞品分析结果为空时页面空白（增加空答案兜底 + Markdown 渲染异常保护）
- 修复收藏列表时间差 8 小时（SQLite UTC 时区 → `datetime('now', 'localtime')`）
- 修复收藏列表不自动刷新（`toggle()` 成功后调用 `loadForProfile()` 同步侧边栏）
- 修复竞品分析结果容器 null 崩溃（添加 DOM 元素存在性检查 + toast 提示）

**功能改进：**
- 追问优化功能完善：分析完成后显示追问框，AI 对话结果可一键应用到方案并同步至历史记录
- 热门竞品对比频次图改为彩虹渐变色（12 色暖→冷）
- 邮箱编辑改为横向排列（input + 保存 + 取消同行显示）
- 邮箱仅在已设置时显示，未设置时隐藏

**体验优化：**
- 登录弹窗添加自动填充提示（显示实际将登录的账号名）
- 方案匹配/竞品分析结果渲染添加诊断日志，便于排查线上问题
- 无刷新账号切换（logout/login 后不刷新页面，就地清空 DOM）

---

## 贡献指南

欢迎提交 Issue 和 Pull Request！

---

## 许可证

MIT License

---

**Made with for Huawei Cloud**
