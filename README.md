# 华为云解决方案智能匹配系统

> 基于大模型 + 向量数据库的华为云行业解决方案智能匹配系统，让销售方案准备时间从 **2小时缩短至1分钟**。

## 🌟 功能亮点

### 核心能力
- ✅ **智能方案匹配** — 输入客户需求，AI自动匹配华为云行业解决方案并生成定制化方案
- ✅ **竞争对手分析** — 分析竞争对手方案，生成华为云差异化优势和实战销售话术
- ✅ **追问迭代优化** — 对匹配方案和竞品分析结果进行多轮追问，逐步精化输出
- ✅ **历史记录管理** — 方案匹配/竞品分析两套独立历史记录，支持查看详情、双方案对比、AI智能对比总结
- ✅ **报告导出** — 支持 Word (docx) 和 PDF 格式导出方案报告和竞品分析报告
- ✅ **数据仪表盘** — 行业覆盖统计、7日匹配趋势、竞品分析频次、系统运行时间等真实运营数据
- ✅ **知识库管理** — 支持向量知识库构建、统计、重建和清空，覆盖10大行业

### 交互体验
- 🎯 **Demo 案例** — 制造业预测性维护、智慧农业、智慧园区等一键体验案例
- ✨ **欢迎引导页** — 粒子动画背景、数字滚动统计、可选择跳过并记住偏好
- 🎨 **科技感 UI** — 玻璃态卡片、流式渐变按钮、粒子网络动画、深色主题
- 📱 **响应式设计** — 支持桌面端和移动端自适应布局

## 📦 项目结构

```
huawei-cloud-solution-matcher/
├── api/                          # FastAPI 后端
│   ├── main.py                   # 应用入口 & 中间件
│   ├── routes.py                 # 核心路由（匹配/分析/知识库/历史/追问）
│   ├── models.py                 # Pydantic 请求/响应模型
│   ├── export_routes.py          # 报告导出路由
│   ├── dependencies.py           # 依赖注入
├── app/                          # 核心业务模块
│   ├── config.py                 # 全局配置（LLM/向量库/行业/竞品）
│   ├── models/                   # 模型层
│   │   ├── llm.py                # 多模型适配（DeepSeek/OpenAI/阿里/百度）
│   │   ├── vector_db.py          # ChromaDB 向量库
│   │   └── export_models.py      # 导出数据模型
│   ├── services/                 # 业务服务
│   │   ├── solution_matcher.py   # 方案匹配服务
│   │   ├── competitor_analyzer.py # 竞品分析服务
│   │   ├── knowledge_base.py     # 知识库管理服务
│   │   ├── usage_logger.py       # 使用日志 & 历史记录
│   │   └── report_generator.py   # Word/PDF 报告生成
│   └── utils/                    # 工具模块
│       ├── document_loader.py    # 文档加载解析
│       ├── word_generator.py     # Word文档生成
│       └── network_checker.py    # 网络检测
├── frontend/                     # 前端界面
│   ├── index.html                # 主页面
│   ├── style.css                 # 主样式
│   ├── script.js                 # 主逻辑
│   ├── welcome-styles.css        # 欢迎页样式
│   └── welcome-script.js         # 欢迎页逻辑
├── data/                         # 数据目录
│   ├── sample_solutions/         # 10大行业解决方案文档
│   ├── competitors/              # 12家竞品分析文档
│   ├── vector_db/                # ChromaDB 持久化向量库
│   ├── embedding_model/          # 本地嵌入模型缓存
│   ├── exports/                  # 导出文件目录
│   └── usage_logs.db             # 使用日志 SQLite 数据库
├── deploy/                       # 部署配置
│   ├── nginx.conf                # Nginx 反向代理配置
│   ├── supervisor.conf           # Supervisor 进程守护
│   └── huawei-matcher.service    # Systemd 服务文件
├── backup/                       # 历史版本备份
├── requirements.txt              # Python 依赖
├── install.bat                   # Windows 一键安装脚本
├── start_api.bat                 # Windows 启动脚本
├── Dockerfile                    # Docker 镜像
├── docker-compose.yml            # Docker Compose 编排
├── DEPLOY.md                     # 部署指南
├── QUICKSTART.md                 # 快速上手指南
└── README.md                     # 本文件
```

## 🚀 快速开始

### 环境要求
- Python 3.8+
- 至少一个 LLM API Key（DeepSeek / OpenAI / 阿里云百炼 / 百度文心）

### 1. 安装依赖

**Windows:**
```bash
install.bat
```

**Linux/Mac:**
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
```

### 3. 启动服务

**Windows:**
```bash
start_api.bat
```

**Linux/Mac:**
```bash
source venv/bin/activate
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 访问应用

- 🌐 **应用首页**: http://localhost:8000
- 📖 **Swagger 文档**: http://localhost:8000/docs
- 📚 **ReDoc 文档**: http://localhost:8000/redoc

## 📡 API 接口概览

### 方案匹配
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/match` | 智能匹配华为云解决方案 |
| POST | `/api/solution/refine` | 方案追问优化（多轮迭代） |

### 竞品分析
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/analyze` | 竞争对手方案分析 |
| POST | `/api/competitor/refine` | 竞品分析追问优化（多轮迭代） |

### 历史记录
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/history/list` | 方案匹配历史列表 |
| GET | `/api/history/{id}` | 方案匹配历史详情 |
| PATCH | `/api/history/{id}/solution` | 更新历史方案内容 |
| POST | `/api/history/compare` | 双方案对比 |
| POST | `/api/history/ai-summary` | AI 智能对比总结 |
| GET | `/api/competitor/history/list` | 竞品分析历史列表 |
| GET | `/api/competitor/history/{id}` | 竞品分析历史详情 |
| PATCH | `/api/competitor/history/{id}/solution` | 更新竞品分析历史 |

### 知识库管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/knowledge/stats` | 知识库统计 |
| POST | `/api/knowledge/rebuild` | 重建知识库 |
| POST | `/api/knowledge/clear` | 清空知识库 |

### 报告导出
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/export/report` | 导出 Word/PDF 报告 |
| GET | `/api/export/task/{id}` | 查询导出任务状态 |
| GET | `/api/export/download/{id}` | 下载报告文件 |

### 数据仪表盘
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/dashboard/stats` | 获取仪表盘统计数据 |

### 系统
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |

## 🎯 使用场景

### 场景一：快速匹配方案
1. 在输入框粘贴客户需求（如"制造业企业想做设备预测性维护"）
2. 点击「智能匹配」，AI 自动检索知识库并生成方案
3. 方案不满意？点击「追问优化」继续迭代
4. 满意后点击「导出 Word」或「导出 PDF」保存

### 场景二：竞品攻坚
1. 切换到「竞品分析」标签
2. 选择竞品（如"阿里云"）和行业（如"智慧农业"）
3. 获取竞品 vs 华为云的优劣势对比和销售话术
4. 通过追问功能深入对比技术架构、价格、生态等维度

### 场景三：方案回顾与对比
1. 点击「历史记录」，查看过往方案
2. 选择两条历史记录进行并排对比
3. 使用「AI智能总结」自动生成对比报告

### 场景四：运营数据分析
1. 点击「仪表盘」，查看系统使用数据
2. 行业覆盖统计、7日匹配趋势、竞品分析频次一目了然

## 🛠️ 技术栈

| 层次 | 技术 | 用途 |
|------|------|------|
| **Web框架** | FastAPI + Uvicorn | 高性能异步 RESTful API |
| **AI框架** | LangChain | LLM 应用编排 |
| **大模型** | DeepSeek / OpenAI / 阿里百炼 / 百度文心 | 自然语言理解与生成 |
| **向量数据库** | ChromaDB | 文档向量化存储与语义检索 |
| **嵌入模型** | BGE-small-zh-v1.5 (BAAI) | 中文文本向量化 |
| **文档处理** | PyPDF + Sentence-Transformers | PDF解析 + 文本分块 |
| **报告导出** | python-docx + ReportLab | Word (docx) / PDF 生成 |
| **可视化** | Chart.js + Plotly | 仪表盘图表 |
| **数据库** | SQLite | 使用日志持久化 |
| **前端** | HTML5 + CSS3 + Vanilla JS | 零框架依赖，极致轻量 |
| **部署** | Docker + Nginx + Supervisor | 容器化 + 反向代理 + 进程守护 |

## 🐳 Docker 部署

```bash
# 构建镜像
docker build -t huawei-cloud-matcher .

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

## 📚 相关文档

- [快速上手指南](QUICKSTART.md)
- [部署指南](DEPLOY.md)
- [网络配置指南](NETWORK_GUIDE.md)

## 🌍 支持行业（10个）

智慧农业 · 工业互联网 · 智慧园区 · 智慧城市 · 智慧医疗 · 智慧金融 · 智慧能源 · 智慧交通 · 智慧教育 · 智慧文旅

## ⚔️ 支持竞品分析（12家）

**国内**: 阿里云 · 腾讯云 · 字节跳动火山引擎 · 天翼云 · 移动云 · 联通云
**国际**: AWS · 微软Azure · Google Cloud · Oracle Cloud
**行业**: 西门子 · 施耐德电气

## 📝 知识库扩展

将方案文档按行业分类放入对应目录，然后重建知识库：

```
data/sample_solutions/
├── 智慧农业/
│   └── 华为云智慧农业解决方案.pdf
├── 工业互联网/
│   └── 工业互联网白皮书.txt
└── ...
```

```
data/competitors/
├── 阿里云/
│   └── 阿里云行业方案对比.txt
├── AWS/
│   └── AWS对标分析.pdf
└── ...
```

在前端「知识库管理」页面点击「重建知识库」，或调用 API：

```bash
curl -X POST http://localhost:8000/api/knowledge/rebuild
```

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

---

**Made with ❤️ for Huawei Cloud**
