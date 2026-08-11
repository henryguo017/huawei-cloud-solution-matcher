# 统一 Agent 入口 —— 完整开发方案

> 作者：从产品经理视角梳理
> 目标：把 cloudsol.cn 的零散功能入口合成一个 Agent 对话框，同时保留旧版入口给老用户
> 适用版本：`feature/agent-platform` 分支（领先 main 54 commits）

---

## 一、产品愿景（为什么做）

### 1.1 问题
当前 cloudsol.cn 的功能入口零散：
- 侧边栏 9 个独立页面（方案 / 产品 / 仪表盘 / 知识库 / 设置 / 成就 / 历史 / 客户 / 关于）
- 顶栏 3 个弹窗（资讯 / AI助手 / 快速体验）
- **两个 AI 入口并存**（顶栏 `AI 助手` 用 `/ai/chat`；方案页 `Agent 对话` 用 `/agent/match/stream`），本身就是零散的最典型例子

用户要做事必须在脑子里记"哪个功能在哪个菜单"，学习成本高。

### 1.2 目标
**让用户用一句话完成平台任何操作。** Agent 对话框成为主入口，零散入口降级为"深度管理"出口。

### 1.3 关键约束
- **渐进迁移**：老用户不能被强制改习惯，必须能回退到旧版视图
- **数据隔离铁律不变**：所有平台操作按 uid 过滤，工具层读不到别人的数据
- **agentic workflow 不变**：Agent 是受控工作流，不是 autonomous agent；对外口径不叫"自研 Agent"
- **生产部署走标准 cp 流程**：铁律②b（requirements 变更需手动 pip install）

---

## 二、目标架构

### 2.1 总体形态：双视图

```
┌─────────── 顶栏 ──────────────────────────────────┐
│  [视图切换: 🤖 Agent | 🗂 经典]  [资讯] [用户]   │
├──────────────┬───────────────────────────────────┤
│  侧边栏       │  主区                             │
│              │                                    │
│  🤖 Agent 视图 │  🤖 Agent 对话框                  │
│  · 能力面板    │  · 欢迎语 + 10 个功能卡片          │
│  · 任务列表    │  · 对话流 + 卡片事件渲染            │
│  · 经典入口🔗  │  · 输入栏                          │
│              │                                    │
│  🗂 经典视图   │  🗂 当前功能页（方案匹配/仪表盘…）   │
│  · 现有菜单    │  · 与现状一致                       │
└──────────────┴───────────────────────────────────┘
```

### 2.2 功能工具化映射表

| 经典入口 | Agent 指令示例 | 工具 | 状态 |
|---|---|---|---|
| 方案匹配 | "做个智慧园区方案" | analyze_demand + search_kb | ✅ 已有 |
| 竞品对比 | "对比华为云和阿里云" | search_competitor | ✅ 已有 |
| 产品图谱 / 报价 | "ECS 多少钱" | query_pricing | ✅ 已有 |
| 客户管理 | "我还有多少客户" | manage_client | ✅ 已有 |
| 历史记录 | "我上次做的方案" | get_my_history | ✅ 已有 |
| 报告导出 | "导成 Word" | export_report | ✅ 已有 |
| **仪表盘统计** | "我这个月匹配了几次" | **get_my_stats** | ❌ **新做** |
| **知识库管理** | "我的知识库有哪些文档" | **manage_kb** | ❌ **新做** |
| **我的成就** | "我拿了哪些徽章" | **get_my_achievements** | ❌ **新做** |
| **行业资讯** | "最近行业有啥大事" | **get_news** | ❌ **新做** |

> 不做：run_code 沙箱生成文件下载（你明确说网页端做不了这个闭环，应降级/移除；不在本方案范围）

---

## 三、前端页面设计（基于当前页面改造）

> 设计原则：**不推倒重来**，复用现有 `topbar / sidebar / .page / switchTo` 体系，
> 通过 `body.view-agent | view-classic` 两个状态类切换两套布局，最小侵入。

### 3.1 页面布局总览（两套视图线框）

**🤖 Agent 视图（新用户默认 / 可切换）**

```
┌─ topbar ────────────────────────────────────────────────┐
│ [≡] [天气]   |  [🤖Agent ▸|▸ 🗂经典]   | [资讯] [体验] [登录] │
├─ sidebar ──────┬─ main ─────────────────────────────────┤
│ ⚡ 能力面板      │  ┌─ chat-home（一张大白卡·顶部红边）───┐    │
│  ▸ 智能匹配     │  │  华为云解决方案智能匹配              │    │
│  ▸ 竞品对比     │  │  6→10 个功能卡片（3×3+1 / 网格）    │    │
│  ▸ 报价查询     │  ├───────────────────────────────────┤    │
│  ▸ 客户档案     │  │  客户需求描述（标签）               │    │
│  ▸ 历史方案     │  │  ───分隔线───                       │    │
│  ▸ 报告导出     │  │  [textarea] [工具栏:附件|模式|发送]  │    │
│  ▸ 仪表盘统计   │  └───────────────────────────────────┘    │
│  ▸ 知识库       │  ┌─ chat-stream（对话流+卡片事件）───┐     │
│  ▸ 我的成就     │  │  (有对话时显示，空态隐藏)          │     │
│  ▸ 行业资讯     │  └───────────────────────────────────┘    │
│ ─────────────  │  ┌─ chat-inputbar（贴底）────────────┐     │
│ 📋 任务列表     │  │  (Agent 对话中：输入卡贴底)         │     │
│ ─────────────  │  └───────────────────────────────────┘    │
│ 🗂 切到经典视图  │                                          │
└────────────────┴──────────────────────────────────────────┘
```

**🗂 经典视图（老用户默认 / 现状保留）**

```
┌─ topbar ────────────────────────────────────────────────┐
│ [≡] [天气] | [🤖Agent ▸|▸ 🗂经典] | [资讯] [体验] [登录]   │
├─ sidebar ──────┬─ main ─────────────────────────────────┤
│ 方案匹配(active)│  现有功能页（page-competitor /         │
│ 产品图谱        │  page-products / page-dashboard /      │
│ 数据仪表盘      │  page-knowledge / page-clients /       │
│ 知识库          │  page-history / page-achievement ...）  │
│ 设置            │  ← 与现状 100% 一致，零改动             │
│ ▸我的:成就/历史/客户/关于                                │
│ 📋 任务列表      │                                        │
└────────────────┴────────────────────────────────────────┘
```

### 3.2 顶栏改造：视图切换（放 `topbar-center`，替换现有 AI bar）

**现状**：`topbar-center` 是 AI 助手浮窗入口（`#topbar-ai-btn`，走 `/ai/chat`）。

**改法**：AI bar 位置改为「视图切换 segmented control」，AI 助手浮窗废弃（Agent 对话框就是 AI 入口，消灭双 AI）。

```html
<!-- index.html topbar-center 替换为： -->
<div class="topbar-center">
    <div class="view-toggle" id="view-toggle" title="切换 Agent 对话 / 经典功能">
        <button type="button" class="view-option active" data-view="agent">
            <svg class="icon" aria-hidden="true"><use href="#i-sparkle"></use></svg>Agent 对话
        </button>
        <button type="button" class="view-option" data-view="classic">
            <svg class="icon" aria-hidden="true"><use href="#i-grid"></use></svg>经典功能
        </button>
    </div>
</div>
```

```css
/* style.css 新增 */
.view-toggle {
    display: inline-flex; align-items: center; gap: 2px;
    background: rgba(255,255,255,.14); border-radius: 999px;
    padding: 3px; border: 1px solid rgba(255,255,255,.22);
}
.view-option {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 6px 16px; border-radius: 999px; border: none;
    background: transparent; color: rgba(255,255,255,.85);
    font-size: 13px; cursor: pointer;
    font-family: var(--font-family);
    transition: background .15s, color .15s;
}
.view-option .icon { width: 14px; height: 14px; }
.view-option.active {
    background: var(--primary-color); color: #fff;
    box-shadow: 0 2px 8px rgba(0,0,0,.25);
}
```

### 3.3 侧边栏改造：Agent 视图下显示「能力面板」

**现状**：`#sidebar .sidebar-menu` 是 9 个 `sidebar-item[data-page]` + 「我的」折叠区 + 任务列表。

**改法**：在 `sidebar-menu` 之上插入一个「能力面板」分区，仅 `body.view-agent` 时显示。
侧边栏经典菜单保留（Agent 视图下点击任一 `sidebar-item` → 自动切到经典视图并打开该页）。

```html
<!-- index.html sidebar 内、sidebar-menu 之前插入： -->
<div class="ability-panel" id="ability-panel">
    <div class="ability-panel-title">
        <svg class="icon" aria-hidden="true"><use href="#i-zap"></use></svg>
        能力面板 <span class="ability-hint">点击填入对话框</span>
    </div>
    <div class="ability-grid">
        <button type="button" class="ability-item" data-preset="帮我生成一个智慧园区的解决方案，预算500万">
            <svg class="icon" aria-hidden="true"><use href="#i-sparkles"></use></svg>智能匹配
        </button>
        <button type="button" class="ability-item" data-preset="对比华为云和阿里云在智慧城市的差异">
            <svg class="icon" aria-hidden="true"><use href="#i-swords"></use></svg>竞品对比
        </button>
        <button type="button" class="ability-item" data-preset="查一下 ECS 云服务器的参考价格">
            <svg class="icon" aria-hidden="true"><use href="#i-tag"></use></svg>报价查询
        </button>
        <button type="button" class="ability-item" data-preset="我有哪些客户？帮我列一下">
            <svg class="icon" aria-hidden="true"><use href="#i-building-2"></use></svg>客户档案
        </button>
        <button type="button" class="ability-item" data-preset="我最近做过哪些方案？">
            <svg class="icon" aria-hidden="true"><use href="#i-clock"></use></svg>历史方案
        </button>
        <button type="button" class="ability-item" data-preset="帮我导出一份方案报告（Word）">
            <svg class="icon" aria-hidden="true"><use href="#i-file-text"></use></svg>报告导出
        </button>
        <button type="button" class="ability-item" data-preset="我这个月匹配了多少次方案？">
            <svg class="icon" aria-hidden="true"><use href="#i-chart"></use></svg>仪表盘统计
        </button>
        <button type="button" class="ability-item" data-preset="我的知识库里有哪些文档？">
            <svg class="icon" aria-hidden="true"><use href="#i-book-open"></use></svg>知识库
        </button>
        <button type="button" class="ability-item" data-preset="我解锁了哪些成就徽章？">
            <svg class="icon" aria-hidden="true"><use href="#i-award"></use></svg>我的成就
        </button>
        <button type="button" class="ability-item" data-preset="最近华为云有什么新动态？">
            <svg class="icon" aria-hidden="true"><use href="#i-globe"></use></svg>行业资讯
        </button>
    </div>
</div>
```

```css
.ability-panel { padding: 8px 10px; border-bottom: 1px solid var(--sidebar-border); }
.view-classic .ability-panel { display: none; }
.ability-panel-title {
    display: flex; align-items: center; gap: 6px;
    font-size: 12px; font-weight: 600; color: var(--sidebar-text-muted);
    margin: 0 4px 8px;
}
.ability-hint { font-weight: 400; font-size: 11px; opacity: .7; }
.ability-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.ability-item {
    display: flex; align-items: center; gap: 6px;
    padding: 8px 10px; border-radius: 8px;
    border: 1px solid var(--sidebar-border);
    background: rgba(255,255,255,.06);
    color: var(--sidebar-text); font-size: 12.5px; cursor: pointer;
    text-align: left; font-family: var(--font-family);
    transition: background .15s, border-color .15s, color .15s;
}
.ability-item:hover {
    background: rgba(199,0,11,.12); border-color: rgba(199,0,11,.4); color: #fff;
}
.ability-item .icon { width: 14px; height: 14px; flex: none; }
```

### 3.4 chat-home 空态：功能卡片 6 → 10

**现状**：`.chat-home-quick` 是 3×2 网格 6 卡（智能匹配/竞品对比/知识库/报告导出/客户档案/历史方案）。

**改法**：扩到 10 卡（补报价查询/仪表盘统计/我的成就/行业资讯），网格 `repeat(3, 1fr)` 变成
3×3+1（第 10 张单独一行或直接 5×2）。**建议 5 列 × 2 行**（卡片更小、更紧凑，与能力面板呼应），
窄屏回退 3/2/1 列。

```html
<!-- 在现有 6 个 quick-chip 后追加 4 个： -->
<button type="button" class="quick-chip" data-preset="查一下 ECS 云服务器的参考价格">
    <svg class="icon" aria-hidden="true"><use href="#i-tag"></use></svg>报价查询
</button>
<button type="button" class="quick-chip" data-preset="我这个月匹配了多少次方案？">
    <svg class="icon" aria-hidden="true"><use href="#i-chart"></use></svg>仪表盘统计
</button>
<button type="button" class="quick-chip" data-preset="我解锁了哪些成就徽章？">
    <svg class="icon" aria-hidden="true"><use href="#i-award"></use></svg>我的成就
</button>
<button type="button" class="quick-chip" data-preset="最近华为云有什么新动态？">
    <svg class="icon" aria-hidden="true"><use href="#i-globe"></use></svg>行业资讯
</button>
```

```css
/* .chat-home-quick 网格调整 */
.chat-home-quick { grid-template-columns: repeat(5, 1fr); }
@media (max-width: 900px) { .chat-home-quick { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 600px) { .chat-home-quick { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 420px) { .chat-home-quick { grid-template-columns: 1fr; } }
/* 卡片纵向排版 → 横向紧凑排版（图标左+文字右，适配 5 列） */
.quick-chip { flex-direction: row; align-items: center; gap: 8px; padding: 12px 10px; }
.quick-chip .icon { width: 18px; height: 18px; }
```

> 空态高度预算：10 卡 5×2 比 6 卡 3×2 少一行，反而更省高度，`bodyH` 预算更宽裕（上一版 805<808）。

### 3.5 经典视图：现状保留 + 一处小改动

- **零改动**：经典视图下所有 page、sidebar 菜单、`switchTo` 逻辑与现状完全一致。
- **唯一联动**：Agent 视图下点击侧边栏 `sidebar-item[data-page]` → 先 `setView('classic')` 再 `switchTo(page)`。
- 经典视图下，`#view-toggle` 仍显示，用户可一键切回 Agent。

### 3.6 CSS 样式设计要点（沿用华为红 + 大白卡体系）

| 元素 | 设计 |
|---|---|
| 视图切换 | 顶栏内胶囊 segmented control，active 用华为红底 |
| 能力面板 | 侧边栏内 2 列网格，暗色侧边栏上用半透明白底卡 + hover 红边 |
| 功能卡片 10 卡 | 空态大白卡内 5 列网格，浅灰边框 + hover 红字红底（与现 6 卡一致） |
| 4 个新卡片事件 | 白底圆角 + 顶部 3px 红边（与 solution_card 一致） |
| 经典页角标（P4） | 各 page 头部右侧小徽标"也可用对话完成 ↗"点击填指令 |

### 3.7 前端 JS 逻辑

```javascript
// ===== 视图管理（新增 ViewManager）=====
const VIEW_KEY = 'huawei_view_preference';

function getView() {
    return localStorage.getItem(VIEW_KEY) || 'agent';
}
function setView(v) {
    localStorage.setItem(VIEW_KEY, v);
    document.body.classList.toggle('view-agent', v === 'agent');
    document.body.classList.toggle('view-classic', v === 'classic');
    // 顶栏按钮 active 态
    document.querySelectorAll('.view-option').forEach(b =>
        b.classList.toggle('active', b.dataset.view === v));
    // Agent 视图 → 强制切到 page-solution；经典视图 → 恢复原页
    if (v === 'agent') switchTo('solution');
}

// 初始化：老用户（注册>7天）首次进入默认 classic
function initView() {
    if (!localStorage.getItem(VIEW_KEY)) {
        const isOld = (userCreatedAt && (Date.now() - new Date(userCreatedAt)) > 7*86400_000);
        setView(isOld ? 'classic' : 'agent');
        if (isOld) showToast('已为你保留经典视图；想试试 Agent 对话？右上角可切换');
    } else {
        setView(getView());
    }
}

// 能力面板 / 功能卡片 → 填指令到对话框（不自动发送）
document.addEventListener('click', e => {
    const el = e.target.closest('.ability-item, .quick-chip[data-preset]');
    if (!el) return;
    const input = document.getElementById('demand-input');
    if (input) {
        input.value = el.dataset.preset;
        input.focus();
        input.dispatchEvent(new Event('input'));
        // 若当前不在 Agent 视图，先切过去
        if (getView() !== 'agent') setView('agent');
    }
});

// Agent 视图下点侧边栏经典菜单 → 切经典视图再开页
document.addEventListener('click', e => {
    const item = e.target.closest('.sidebar-item[data-page]');
    if (item && getView() === 'agent') setView('classic'); // switchTo 由原逻辑处理
});
```

### 3.8 前端 SSE 卡片事件（渲染扩展）

| 事件类型 | 用途 | 前端渲染组件 |
|---|---|---|
| `solution_card` | 方案摘要卡 | ✅ 已有 |
| `competitor_table` | 竞品对比表 | ✅ 已有 |
| `pricing_info` | 价目卡片 | ✅ 已有 |
| `history_list` | 历史记录列表 | ✅ 已有 |
| `export_ready` | 导出文件就绪 | ✅ 已有 |
| **`stats_card`** | 仪表盘统计 | ❌ **新加** |
| **`kb_overview`** | 知识库概览 | ❌ **新加** |
| **`achievement_card`** | 成就列表 | ❌ **新加** |
| **`news_digest`** | 行业资讯摘要 | ❌ **新加** |

### 3.9 前端交互流程

1. 新用户打开 → `initView()` 判定 → Agent 视图（老用户进经典视图 + 一次性提示）
2. Agent 视图主区 = page-solution：空态大白卡（标题 + 10 功能卡 + 输入区）
3. 用户操作三选一：
   - 打字 → Agent 路由工具 → 对话流渲染对应卡片事件
   - 点能力面板 / 功能卡 → 指令填入输入框 → 回车发送
   - 点侧边栏经典菜单 → 切经典视图打开该页
4. 对话中：chat-stream 显示 + 输入卡贴底（现有逻辑不变）
5. 经典视图：一切照旧，`#view-toggle` 可切回

---

## 四、后端开发

### 4.1 新增 4 个工具的实现规格

> 通用约定：所有工具读 `get_agent_user_context()` 取 uid，按 uid 过滤；uid<=0 时读操作返回空、写操作拒绝。返回 JSON 字符串给 LLM 作为 Observation。

#### 4.1.1 `get_my_stats`

```python
async def _tool_get_my_stats(period: str = "month") -> str:
    """
    工具: get_my_stats
    作用: 查当前用户的使用统计（匹配次数/竞品分析/导出次数/最近活跃）
    参数:
      period: 'day' | 'week' | 'month' | 'all'，默认 'month'
    返回:
      { match_count, analyze_count, export_count, days_active,
        recent_trend: [{date, match, analyze}], ... }
    发事件: stats_card
    """
```

- 对接：`api/routes.py::get_dashboard_stats` + `UsageLoggerService.get_recent_counts(days, user_id)`
- 读取：`get_recent_counts(days=period_days, user_id=uid)` + `usage_logs.db` 趋势
- 注册域：`platform`

#### 4.1.2 `manage_kb`

```python
async def _tool_manage_kb(action: str, query: str = "", doc_id: int = 0) -> str:
    """
    工具: manage_kb
    作用: 查/删/重建当前用户独立知识库
    参数:
      action: 'list' | 'search' | 'delete' | 'rebuild' | 'stats'
      query: 搜索关键词（action=search 时用）
      doc_id: 删除时必填
    返回:
      list: { items: [{id, name, industry, size, created_at}], total }
      search: { items: [...], total }
      stats: { total_docs, total_chunks, industries, last_rebuild }
    发事件: kb_overview
    """
```

- 对接：`api/routes.py::list_knowledge_documents` + `get_knowledge_stats` + `delete_knowledge_document` + `knowledge/rebuild`
- 强制 `current_user` 登录（已登录则 uid 隔离）
- 不允许 Agent 改 KB 文档内容，只允许查 / 删 / 触发重建（重建是异步任务，发回 task_id 给前端轮询）
- 注册域：`platform`

#### 4.1.3 `get_my_achievements`

```python
async def _tool_get_my_achievements() -> str:
    """
    工具: get_my_achievements
    作用: 查当前用户的成就列表（已解锁 + 未解锁占位）
    返回:
      { items: [{name, description, unlocked, unlocked_at?, icon}],
        total, unlocked, percent }
    发事件: achievement_card
    """
```

- 对接：`api/achievement_routes.py::get_achievements`（`GET /api/achievements`）
- 直接调用 `get_achievement_service().get_user_achievements(uid)` + `get_user_stats(uid)`
- 注册域：`platform`

#### 4.1.4 `get_news`

```python
async def _tool_get_news(category: str = "all", limit: int = 5) -> str:
    """
    工具: get_news
    作用: 取科技资讯 / 华为云动态 / 行业展会摘要
    参数:
      category: 'all' | 'tech' | 'huawei' | 'events'
      limit: 返回条数（默认 5，最多 10）
    返回:
      { category, items: [{title, source, url, pub_date}], updated_at }
    发事件: news_digest
    """
```

- 对接：`api/routes.py::tech_news` + `huawei_news` + `industry_events`
- 复用现有 24h 缓存，不重新抓
- 注册域：`platform`

### 4.2 新增 4 个 SSE 卡片事件（事件协议）

后端 harness.py `_execute_tool` 后通过 `event_callback` 发事件，前端 chat_ui.js 监听并渲染。

```python
# 后端事件格式（harness 在工具回调里 push）
{
  "type": "stats_card",       # 事件名
  "user_id": 123,
  "payload": { ... },         # 卡片数据
  "tool": "get_my_stats",     # 触发该事件的工具名（前端可选渲染"来源"角标）
  "ts": "2026-08-11T20:30:00"
}
```

四种新事件 + 对应 payload：

| 事件 | payload 字段 | 渲染建议 |
|---|---|---|
| `stats_card` | `period, match_count, analyze_count, export_count, recent_trend[]` | KPI 卡片 + 趋势图 |
| `kb_overview` | `action, total_docs, total_chunks, industries[], items[]?` | 文档列表 + 统计条 |
| `achievement_card` | `total, unlocked, percent, items[]` | 徽章网格（已解锁彩色 / 未解锁灰） |
| `news_digest` | `category, items[]` | 资讯条目（标题/来源/日期/外链） |

前端渲染组件（chat_ui.js）：
- 在 `renderEvent` 函数中增加对应 case
- 新建 `_renderStatsCard(payload)` / `_renderKBOverview(payload)` / `_renderAchievementCard(payload)` / `_renderNewsDigest(payload)` 4 个函数
- 风格沿用现有 `solution_card` / `competitor_table` 卡片（白底 + 圆角 + 顶部红边）

### 4.3 工具注册

在 `app/agent/tools.py::create_default_tools()` 末尾追加 4 个 `registry.register(Tool(...))`，domain 全部为 `platform`（与现有 `get_my_history / manage_client / export_report` 一致）。`ToolRegistry` 已按域分组做 prompt 展示，无需改动。

---

## 五、Agent System Prompt 设计（前端/Agent 配置文件层面）

> 用户问的"前端提示词"——本质上是 Agent 的 system prompt。本方案的核心交付物之一。

### 5.1 Prompt 设计目标

让 Agent 能：
1. 识别 10 类功能意图（不仅是方案/竞品/报价，新增 4 类平台操作）
2. 识别后精准路由到对应工具，**不擅自做答**（必须工具调用）
3. 工具调用后用卡片事件 + 简短文字回答**两段式输出**（卡片承载数据，文字给总结/操作建议）
4. 不混淆意图（用户说"我还有多少客户"不要去 search_kb）

### 5.2 新 Prompt 草案（替换 `app/agent/harness.py::REACT_SYSTEM_PROMPT_BASE`）

```text
你是华为云售前智能助手 Copilot。用户既可能让你做方案、查报价、对比竞品，
也可能让你查自己的数据（客户/历史/知识库/成就）、看平台统计、看行业资讯，
还能闲聊、问云计算概念、要写作辅助（周报/邮件/话术）。

你必须按下面的意图分类处理，**禁止乱猜**。

【A. 方案推荐】
特征词：方案、解决、架构、推荐、上云、规划、选型
工具链：analyze_demand → search_kb → (提及竞品则 search_competitor) → Final Answer
输出：14 章方案报告 + solution_card 事件

【B. 竞品对比】
特征词：对比、vs、阿里云、腾讯云、AWS、谁好、优劣、差异
工具链：search_competitor → **立即** Final Answer + competitor_table 事件
★★★ 完成后禁止调 analyze_demand / search_kb / query_pricing

【C. 报价 / 价目】
特征词：多少钱、报价、价格、费用、成本、TCO、预算、包月、包年
工具链：query_pricing → **立即** Final Answer + pricing_info 事件
★★★ 完成后禁止调 analyze_demand / search_kb / search_competitor

【D. 我的客户 / 客户管理】
特征词：我的客户、客户数、记个客户、建客户、删客户、改客户
工具链：manage_client(action=list/get/create/update/delete) → Final Answer + history_list 事件
完成标志：操作成功即汇报，禁止追加方案生成

【E. 我的历史方案】
特征词：我的历史、我上次、我做过什么、找出之前、导成 Word/PDF
工具链：get_my_history（可接 export_report）→ Final Answer + export_ready 事件

【F. 我的知识库】
特征词：我的知识库、KB 文档、查文档、删文档、重建知识库
工具链：manage_kb(action=list/search/delete/rebuild/stats) → Final Answer + kb_overview 事件
（重建是异步操作，发回 task_id 让用户在前端看进度）

【G. 我的仪表盘 / 使用统计】
特征词：我用了多少次、匹配了多少、最近活跃、统计、本月、本周
工具链：get_my_stats(period) → Final Answer + stats_card 事件

【H. 我的成就】
特征词：我的成就、徽章、解锁了多少
工具链：get_my_achievements → Final Answer + achievement_card 事件

【I. 行业资讯】
特征词：最近有啥新闻、行业动态、华为云动态、展会、活动
工具链：get_news(category=tech/huawei/events/all) → Final Answer + news_digest 事件

【J. 通用问答 / 平台助手 / 闲聊】
特征：云计算概念、平台怎么用、写作辅助（周报/邮件）、任意不属于 A-I 的问题
工具链：**无需工具**，直接 Final Answer
★★★ 绝不套方案结构

---

【K. 文件生成 / 沙箱】DEPRECATED
特征：生成 PPT、生成 Excel、做报表
行为：直接拒绝并引导——"网页端不做文件下载，建议到 /knowledge/ 页面用文档管理工具，
      或用 export_report 导出方案为 Word/PDF。"
（run_code 工具保留后端代码但 prompt 不再引导 Agent 主动调用）

---

## ⚠️ 核心纪律
1. 识别意图后只走该意图的工具链，不混用
2. 工具完成 = 立即 Final Answer + 对应卡片事件，不追加
3. B/C/F-I 输出简短精炼（几段话+卡片），不是 14 章方案
4. J 类绝不动工具
5. K 类已下架，明确拒绝并引导到正确路径
6. 明确请求禁止反问：用户给出"行业+场景"直接走工具链
7. 用户数据隐私：所有平台工具查不到的就是没有，绝不猜测

## 可用工具
{tools}

## 输出格式（严格遵守）

调用工具时：
Thought: [分析]
Action: [工具名]
Action Input: {"k": "v"}

最终答案时：
Thought: 我已收集到足够信息。
Final Answer: [2-3 段精炼总结+操作建议]
（系统会自动根据已用工具生成对应卡片事件）

澄清（仅当 A 类信息真的不全时）：
Clarify: [{"question": "...", "options": [...]}]

最多 {max_steps} 步。
```

### 5.3 意图词表变更

`app/agent/harness.py` 现有 Prompt 含 A–G 七类。本次：
- 保留 A、B、C、E、F、J
- **新增 G、H、I**（平台操作 / 仪表盘 / 资讯）
- **删除 D 文件生成意图**（K 段说明拒绝引导）
- 编号顺延为 A–J + K(deprecated)

`_build_intent_nudge()` 也要同步扩展，匹配新意图"完成即 Final Answer"规则。

---

## 六、前端 Chat 卡片渲染

### 6.1 chat_ui.js 新增事件 case

在现有 `case 'pricing_info'` / `'competitor_table'` 等后追加：

```javascript
// stats_card → KPI 卡片 + 趋势
function _renderStatsCard(payload) {
  // 返回 DOM：白底圆角 + 顶部红边
  // 4 个 KPI 数字（本月匹配 / 分析 / 导出 / 活跃天数）
  // 折线图（最近 7 天每日匹配数，可用 SVG 或 canvas）
}

// kb_overview → 文档列表
function _renderKBOverview(payload) {
  // 按 action 渲染：list → 表格；stats → 统计条；rebuild → 进度提示
}

// achievement_card → 徽章网格
function _renderAchievementCard(payload) {
  // 6 列网格，已解锁彩色，未解锁灰色+???
  // 顶部进度条（百分比）
}

// news_digest → 资讯条目
function _renderNewsDigest(payload) {
  // 列表：标题（链接到 source url）/ 来源 / 时间
}
```

### 6.2 渲染分发

```javascript
const eventHandlers = {
  // 已有
  'solution_card': renderSolutionCard,
  'competitor_table': renderCompetitorTable,
  'pricing_info': renderPricingInfo,
  'history_list': renderHistoryList,
  'export_ready': renderExportReady,
  // 新增
  'stats_card': _renderStatsCard,
  'kb_overview': _renderKBOverview,
  'achievement_card': _renderAchievementCard,
  'news_digest': _renderNewsDigest,
};
```

### 6.3 视图切换前端逻辑

```javascript
// 视图偏好
const VIEW_KEY = 'huawei_view_preference';
function getView() {
  return localStorage.getItem(VIEW_KEY) || 'agent'; // 新用户默认 agent
}
function setView(v) {
  localStorage.setItem(VIEW_KEY, v);
  document.body.classList.toggle('view-agent', v === 'agent');
  document.body.classList.toggle('view-classic', v === 'classic');
}

// 老用户首次进入检测（注册时间 > 7 天）
const regAt = user.created_at; // 从 /auth/me 取
const isOldUser = (Date.now() - new Date(regAt)) > 7 * 86400_000;
if (isOldUser && !localStorage.getItem(VIEW_KEY)) {
  localStorage.setItem(VIEW_KEY, 'classic'); // 老用户默认经典
  // 弹一次小提示："想试试 Agent 视图？顶栏右上角可切换"
}
```

---

## 七、渐进式迁移路线（4 个阶段，每步可独立发布）

| 阶段 | 后端 | 前端 | 用户感知 |
|---|---|---|---|
| **P1** | 新增 4 个工具 + 4 个 SSE 事件 | 渲染 4 种新卡片 | Agent 能答"我的数据"问题 |
| **P2** | — | 空态卡片 6→10 + 能力面板按钮 | 每个功能"一句话唤起" |
| **P3** | — | 视图切换开关 + 偏好记忆 + 合并顶栏 AI 助手 | 统一入口成型，老用户可回退 |
| **P4** | — | 经典页加"用对话完成"角标 | 引导用户慢慢迁移 |

每步独立测试 + 灰度。

---

## 八、验收标准（每个阶段都要过的检查项）

### 8.1 功能验收
- [ ] Agent 能正确回答每个 A–J 意图的样例提问
- [ ] 卡片事件正确返回且前端正确渲染（无错位、无报错）
- [ ] 用户数据严格隔离：换用户登录看不到对方数据
- [ ] 经典视图所有页面照旧可用（无 regression）
- [ ] 视图切换平滑，刷新后记住偏好

### 8.2 性能验收
- [ ] 单次 Agent 调用 90% 在 30s 内完成（含 1–2 个工具调用）
- [ ] 工具失败有兜底（不挂、不让对话卡死）
- [ ] SSE 断线重连正常

### 8.3 测试用例样例（必须过的 10 条）

```
1. "我还有多少客户"          → manage_client(list) + history_list 卡片
2. "我上次做的方案"          → get_my_history + history_list
3. "把这个方案导成 Word"      → export_report + export_ready
4. "我这个月匹配了几次"      → get_my_stats + stats_card
5. "我的知识库有什么文档"     → manage_kb(list) + kb_overview
6. "我拿了哪些徽章"          → get_my_achievements + achievement_card
7. "最近华为云有啥动态"      → get_news(huawei) + news_digest
8. "做个智慧园区方案"        → analyze_demand + search_kb + solution_card
9. "对比华为云和阿里云"      → search_competitor + competitor_table
10. "ECS 多少钱"             → query_pricing + pricing_info
```

---

## 九、风险与回滚

| 风险 | 影响 | 回滚方案 |
|---|---|---|
| 新 prompt 误识别导致工具乱选 | Agent 答非所问 | 保留旧 prompt 在 `app/agent/prompts/v1.py`，新增 `v2.py`，通过 `AGENT_PROMPT_VERSION` env var 切换 |
| 新工具调用过慢 | Agent 响应慢 | 每个工具加超时（10s），超时返回降级答案 |
| 用户不喜欢新视图 | 体验差 | 视图切换开关 + 默认经典（老用户） |
| SSE 事件未注册 | 前端不渲染 | 后端加事件类型枚举，前端 case 缺失时 fallback 文字显示 |
| 知识库管理误删 | 数据丢失 | manage_kb 删文档需二次确认（前端弹窗）+ 后端软删除（先标记 deleted，30 天后清理） |

---

## 十、开发工作量估算

| 阶段 | 后端 | 前端 | 测试 |
|---|---|---|---|
| P1：4 工具 + 4 卡片事件 | 2 天 | 1.5 天（渲染 4 卡） | 1 天 |
| P2：空态 10 卡 + 能力面板 | — | 1.5 天 | 0.5 天 |
| P3：视图切换 + 偏好 + 合并 AI bar | — | 1.5 天 | 0.5 天 |
| P4：经典页"对话可达"角标 | — | 1 天 | 0.5 天 |
| **合计** | **2 天** | **5.5 天** | **2.5 天** |

约 2.5 人周工作量。

---

## 十一、交付物清单

1. `app/agent/tools.py`：新增 4 个工具函数（get_my_stats / manage_kb / get_my_achievements / get_news）+ 注册
2. `app/agent/harness.py`：REACT_SYSTEM_PROMPT_BASE 替换 + `_build_intent_nudge` 扩展
3. `app/agent/prompts/v2.py`（可选，新 prompt 单独文件，env 切换版本）
4. `frontend/index.html`：视图切换（topbar-center）+ 能力面板（sidebar）+ 空态 10 卡（chat-home）
5. `frontend/style.css`：`.view-toggle` / `.ability-panel` / `.ability-item` / 10 卡网格响应式
6. `frontend/script.js`：`ViewManager`（getView/setView/initView）+ 指令填充 + 侧边栏联动
7. `frontend/js/chat_ui.js`：4 个新渲染函数（stats_card/kb_overview/achievement_card/news_digest）+ 渲染分发
8. `docs/unified_agent_entry_plan.md`：本方案
9. 测试用例覆盖（`tests/`）

---

## 十二、建议优先级

**先做 P1 的 `get_my_stats` + `get_my_achievements`**（最简单，对接现有 service，无需新路由），20 分钟验证 Agent 工具链路打通，立刻见效。然后决定是否继续 P1 剩余两个工具。

你对哪个点想先动手？或者直接说「按 P1 全做」我就开工。