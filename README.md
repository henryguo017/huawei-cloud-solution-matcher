# 华为云解决方案智能匹配系统

> 基于大模型和向量数据库的华为云行业解决方案智能匹配系统，让销售方案准备时间从2小时缩短至1分钟

## 🌟 项目特点

- ✅ **智能匹配**: 基于大模型理解客户需求，智能匹配华为云解决方案
- ✅ **竞争分析**: 分析竞争对手方案，生成差异化优势和销售话术
- ✅ **知识库管理**: 支持知识库构建、统计、重建等管理功能
- ✅ **科技感界面**: 现代化前端界面，包含粒子动画、玻璃态效果
- ✅ **RESTful API**: 基于 FastAPI 的标准 API 接口
- ✅ **生产就绪**: 完整的部署方案和配置文件

## 📦 项目结构

```
huawei-cloud-solution-matcher/
├── api/                    # FastAPI 后端 API
│   ├── main.py            # API 应用入口
│   ├── routes.py          # API 路由定义
│   ├── models.py          # 请求/响应模型
│   └── dependencies.py    # 依赖注入
├── app/                    # 核心应用模块
│   ├── main.py            # Streamlit 应用（旧版）
│   ├── config.py          # 配置文件
│   ├── models/            # LLM 和向量数据库模型
│   ├── services/          # 业务服务层
│   └── utils/             # 工具函数
├── frontend/              # 前端界面
│   ├── index.html         # HTML 主文件
│   ├── style.css          # 样式文件
│   └── script.js          # JavaScript 逻辑
├── data/                  # 数据目录
│   ├── sample_solutions/  # 解决方案文档
│   └── vector_db/         # 向量数据库
├── deploy/                # 部署配置
│   ├── nginx.conf         # Nginx 配置
│   ├── supervisor.conf    # Supervisor 配置
│   └── *.service          # Systemd 服务文件
├── requirements.txt       # Python 依赖
├── .env.example          # 环境变量模板
├── DEPLOY.md             # 部署指南
└── README.md             # 项目说明
```

## 🚀 快速开始

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

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填写 OpenAI 或 DeepSeek API 密钥
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

- 🌐 前端界面: http://localhost:8000
- 📖 API 文档: http://localhost:8000/docs
- 📚 API 文档 (ReDoc): http://localhost:8000/redoc

## 📡 API 接口

### 解决方案匹配
```bash
POST /api/match
Content-Type: application/json

{
  "demand": "客户需求描述"
}
```

### 竞争对手分析
```bash
POST /api/analyze
Content-Type: application/json

{
  "competitor": "阿里云",
  "industry": "智慧农业"
}
```

### 知识库管理
```bash
GET  /api/knowledge/stats    # 获取统计信息
POST /api/knowledge/rebuild  # 重建知识库
POST /api/knowledge/clear    # 清空知识库
```

### 健康检查
```bash
GET /api/health
```

## 🎯 核心功能

### 1. 解决方案智能匹配
- 输入客户需求描述
- 基于向量检索匹配相关解决方案
- 大模型生成定制化方案建议
- 支持方案文档下载

### 2. 竞争对手分析
- 选择竞争对手和行业
- 分析竞品优劣势
- 生成华为云差异化优势
- 提供销售应对话术

### 3. 知识库管理
- 查看知识库统计信息
- 行业分布可视化图表
- 一键重建知识库
- 清空知识库（需确认）

## 🛠️ 技术栈

### 后端
- **FastAPI**: 高性能 Web 框架
- **LangChain**: LLM 应用框架
- **ChromaDB**: 向量数据库
- **OpenAI/DeepSeek**: 大语言模型

### 前端
- **HTML5 + CSS3 + JavaScript**: 纯原生技术栈
- **Chart.js**: 图表库
- **Marked.js**: Markdown 渲染

## 📚 部署文档

详细的部署指南请查看: [DEPLOY.md](DEPLOY.md)

### 快速部署到华为云
1. 购买华为云 ECS 实例（4核8GB）
2. 按照部署文档配置环境
3. 配置域名和 HTTPS 证书
4. 启动服务并验证

## 📝 开发说明

### 添加新的解决方案文档
将 PDF 或 TXT 文档放入对应行业目录：
```
data/sample_solutions/智慧农业/xxx.txt
```

然后在知识库管理页面点击"重建知识库"。

### 修改前端样式
编辑 `frontend/style.css` 文件，支持热重载。

### 扩展 API 接口
在 `api/routes.py` 中添加新的路由，遵循 RESTful 规范。

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

---

**Made with ❤️ for Huawei Cloud**
