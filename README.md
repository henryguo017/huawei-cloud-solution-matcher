# 华为云解决方案智能匹配系统 · cloudsol.cn

> 面向 ToB 售前 / 解决方案工程师的**销售提效工具**——输入客户需求，一键生成华为云方案匹配 + 竞品对比，并内置可在线维护的企业级知识库。

🌐 线上地址：**https://cloudsol.cn**（备案号：豫ICP备2026027974号）

---

## ✨ 本次更新重点：大换肤 + 操作界面优化

本次版本对整体视觉与操作体验做了一次完整重构，核心变化如下：

### 1. 主题皮肤系统升级为 4 色

侧边栏 + 顶栏支持一键换肤，用户可在「设置」中自由切换，偏好持久化保存：

| 皮肤 | 标识 | 侧栏 / 顶栏配色 | 风格 |
|------|------|----------------|------|
| 经典蓝 | `classic-blue` | `#1B4F72` / `#154360` | 沉稳专业，默认皮肤 |
| 浅葱绿 | `teal` | `#17A58B` / `#148F77` | 清新科技 |
| 盛夏黄 | `summer-yellow` | `#D4AC0D` / `#B7950B` | 明快活力 |
| 桃桃粉 | `peach-pink` | `#E74C7A` / `#C23B65` | 柔和时尚 |

皮肤通过 `data-skin` 属性联动 CSS 变量（`--sidebar-bg` / `--topbar-bg` / `--frame-text`），所有框架内文字强制纯白，保证对比度与可读性。

### 2. 视觉语言整体刷新

- **品牌色**：统一为华为红 `#C7000B`（仅作强调，去除发光/光晕效果，界面更克制专业）
- **底色体系**：页面冷灰底 `#E8EAED` + 毛玻璃卡片（极浅米白→纯白渐变），层级清晰
- **文字层级**：主文字深墨 `#1A1C23`、副文字灰蓝 `#4A5067`、弱文字 `#8890A4`，三级层次分明
- **圆角与阴影**：统一圆角 + 轻量阴影（`0 4px 16px rgba(0,0,0,.06)`），去除 Heavy 阴影带来的廉价感
- **字体**：系统无衬线字体栈，移动端输入框/可点击元素最小 16px，避免 iOS 聚焦缩放

### 3. PC 端操作界面优化

- 左侧固定**侧边导航栏**：方案匹配 / 竞品分析 / 产品图谱 / 数据仪表盘 / 历史记录 / 成就中心 / 知识库 / 设置，图标 + 文字双标识，激活态高亮
- 顶栏与侧栏底色随皮肤联动，常驻用户状态与主题切换入口
- 全局表格支持横向滚动，长内容区不再撑破布局

### 4. 移动端专项重构（响应式）

手机端（≤767px）完全独立设计，不再只是 PC 端的缩放：

- **5 Tab 底部导航**：匹配 · 竞品 · 仪表盘 · 知识库 · 我的，固定底部 56px，拇指可达
- **「我的」聚合页**：用户信息 / 收藏 / 历史 / 成就 / 设置入口聚合，底部统计信息（文档数 · 行业数 · 版本号）自动沉底
- **子页独立返回导航条**：历史 / 成就 / 设置进入后顶部带返回键（独立 nav 条，非 header 内嵌），一键返回「我的」
- **抽屉化交互**：弹窗 / 详情改为底部滑入抽屉，符合移动端习惯
- **卡片布局**：成就卡片一行 3 列紧凑展示；设置项间距收窄，操作更密集高效
- **页面切换动效**：复制 PC 端「淡淡上滑」体验（`translateY(4px)` / 0.18s），不再生硬弹出
- **消除移动端留白**：精确像素硬锁内容区高度，根治过度滚动产生的 493px 空白

---

## 🧩 核心功能

- **三种匹配模式**
  - **标准模式**：输入需求文本 → 向量检索 → LLM 生成方案
  - **智能模式**（Agentic Workflow）：自写编排引擎驱动「需求分析 → 检索知识库 → 检索竞品 → 生成方案」循环，SSE 实时推送思考流
  - **向导模式**：行业 → 规模 → 痛点 → 确认，4 步引导自动合成需求后提交匹配
- **竞品分析**：12 家主流厂商（阿里云 / 腾讯云 / AWS / Azure / 天翼云 / 火山引擎等）方案对比
- **用户独立知识库**：每个用户拥有完全隔离的知识库（文件 + ChromaDB 向量库），注册自动从默认库复制，在线增删改文档并支持单文件重索引
- **方案收藏 / 历史**：登录用户可收藏方案、查看历史记录（已修复收藏/历史接口路由，详见下方说明）
- **成就系统**：使用行为解锁成就徽章
- **内置 AI 助手**：闲聊与答疑，身份锚定「cloudsol.cn 内置 AI 助手，由郭鸿宇开发，不属于 DeepSeek/OpenAI」

---

## 🛠 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI `0.109.0` + Uvicorn `0.27.0`（端口 8000） |
| 前端 | 原生 JS SPA（Vanilla，无构建步骤）+ 静态托管（Nginx 反代） |
| 数据库 | SQLite（用户 / 历史 / 收藏 / 知识库元数据）+ ChromaDB `0.4.24`（向量库） |
| AI | LangChain `0.1.20` + BGE-small-zh 中文 Embeddings + DeepSeek API |
| 部署 | 阿里云轻量应用服务器（Ubuntu 22.04）+ Nginx + systemd + Let's Encrypt HTTPS |

---

## 🚀 本地运行

```bash
# 1. 克隆
git clone https://github.com/henryguo017/huawei-cloud-solution-matcher.git
cd huawei-cloud-solution-matcher

# 2. 创建虚拟环境并安装依赖（国内建议加镜像）
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 3. 配置环境变量
cp .env.example .env   # 按需填写 DeepSeek API Key 等

# 4. 初始化数据库
python -m app.utils.db_init

# 5. 启动后端（开发模式带热重载）
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

浏览器访问 `http://127.0.0.1:8000` 即可。

---

## 📦 生产部署

```bash
# 服务器（root 下）
cd /tmp && rm -rf huawei-cloud-solution-matcher main.zip
wget https://github.com/henryguo017/huawei-cloud-solution-matcher/archive/refs/heads/main.zip
python3 -c "import zipfile; zipfile.ZipFile('main.zip').extractall('/tmp')"
cp -r /tmp/huawei-cloud-solution-matcher-main/* /var/www/huawei-cloud-solution-matcher/
systemctl restart huawei-cloud-api
```

> ⚠️ **部署铁律**：使用 `cp -r` 覆盖代码，**严禁** `rsync --delete`——会误删服务器 `venv` 导致服务 203/EXEC 宕机。
> 前端改动后浏览器需 **Ctrl+Shift+R** 硬刷（版本号已随提交升级）。

---

## 📂 目录结构

```
huawei-cloud-solution-matcher/
├── api/                    # FastAPI 路由层
│   ├── main.py             # 应用入口（挂载各 router）
│   ├── routes.py           # 匹配 / 分析 / 知识库 / 导出
│   ├── auth_routes.py      # 认证 / 历史 / 收藏
│   ├── auth_dependencies.py# JWT 鉴权
│   └── achievement_routes.py
├── app/
│   ├── services/           # AuthService / KnowledgeBaseService / Agent 编排
│   ├── models/             # Pydantic 数据模型
│   └── utils/              # db_init / captcha
├── frontend/               # 原生 JS SPA（index.html + script.js + style.css）
├── data/                   # 知识库文档 + 向量库 + 用户库
└── deploy/                 # Nginx / systemd / HTTPS 部署脚本
```

---

## 🐛 已知修复记录

- **收藏 / 历史接口 404**：`auth_routes.py` 子路由原为 `@router.get("/")` 注册路径带尾部斜杠，而前端调用无斜杠，FastAPI 子路由嵌套时不自动重定向 → 已改为 `@router.get("")` 匹配无斜杠请求。
- **移动端过度滚动留白**：JS 精确像素硬锁 `main-content` 高度，根治 493px 空白。
- **AI 身份暴露**：闲聊 prompt 加身份锚点，避免被误认为 DeepSeek。

---

## 📄 License

个人开源项目，仅供学习与交流使用。
