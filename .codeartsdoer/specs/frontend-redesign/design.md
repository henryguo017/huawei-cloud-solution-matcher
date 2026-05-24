# **1. 实现模型**

## **1.1 上下文视图**

### 1.1.1 系统上下文

本设计方案针对华为云解决方案智能匹配系统的前端界面重新设计，将现有AI应用风格（左侧边栏导航 + 深色科技风）转换为科技企业官网风格（顶部导航栏 + 专业企业风）。

**当前状态分析：**
- **导航方式**：左侧边栏垂直导航（280px固定宽度）
- **视觉风格**：深色背景(#0a0e27) + 粒子动画 + 玻璃拟态效果
- **布局结构**：Grid布局 `grid-template-columns: 280px 1fr`
- **色彩方案**：华为红(#FF0000) + 科技蓝(#4A90E2) + 深色背景
- **卡片风格**：玻璃拟态(backdrop-filter) + 半透明背景

**目标状态设计：**
- **导航方式**：顶部水平导航栏（固定定位，高度64px）
- **视觉风格**：白色/浅灰背景 + 品牌化配色 + 实体卡片
- **布局结构**：顶部固定导航 + 下方全宽内容区
- **色彩方案**：华为云品牌红(#C7000B) + 专业中性色 + 浅色背景
- **卡片风格**：实体白色卡片 + 微妙阴影 + 清晰边框

### 1.1.2 布局改造对比图

```
┌─────────────────────────────────────────────────────────────┐
│  当前布局（左侧边栏导航）                                      │
├──────────┬──────────────────────────────────────────────────┤
│          │                                                   │
│  左侧    │                 主内容区域                          │
│  边栏    │         - 页面标题                                   │
│  导航    │         - 功能表单                                   │
│  - Logo  │         - 结果展示                                   │
│  - 状态  │                                                   │
│  - 菜单  │                                                   │
│  - 说明  │                                                   │
│          │                                                   │
└──────────┴──────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  目标布局（顶部导航栏）                                        │
├─────────────────────────────────────────────────────────────┤
│  [Logo] 华为云解决方案匹配系统  [菜单项] [菜单项] [菜单项] [状态]│
├─────────────────────────────────────────────────────────────┤
│                                                              │
│                       主内容区域                              │
│              - 页面标题                                       │
│              - 功能表单                                       │
│              - 结果展示                                       │
│                                                              │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## **1.2 服务/组件总体架构**

### 1.2.1 HTML结构改造方案

**改造前结构：**
```html
<div class="app-container">
    <aside class="sidebar">
        <div class="sidebar-header">Logo + 版本</div>
        <div class="stats-card">系统状态</div>
        <nav class="nav-menu">导航菜单</nav>
        <div class="sidebar-footer">使用说明</div>
    </aside>
    <main class="main-content">
        <!-- 页面内容 -->
    </main>
</div>
```

**改造后结构：**
```html
<div class="app-container">
    <header class="navbar">
        <div class="navbar-brand">
            <span class="logo-icon">☁️</span>
            <span class="logo-text">华为云解决方案匹配系统</span>
        </div>
        <nav class="navbar-menu">
            <button class="navbar-item active" data-page="solution">
                <span class="item-icon">🔍</span>
                <span class="item-text">解决方案匹配</span>
            </button>
            <button class="navbar-item" data-page="competitor">
                <span class="item-icon">⚔️</span>
                <span class="item-text">竞争分析</span>
            </button>
            <button class="navbar-item" data-page="knowledge">
                <span class="item-icon">📚</span>
                <span class="item-text">知识库管理</span>
            </button>
        </nav>
        <div class="navbar-status">
            <span class="status-item">文档: <strong id="nav-stat-docs">--</strong></span>
            <span class="status-item">行业: <strong id="nav-stat-industries">--</strong></span>
            <span class="status-item">准确率: <strong id="nav-stat-accuracy">--%</strong></span>
        </div>
        <button class="navbar-toggle" id="mobile-navbar-toggle">☰</button>
    </header>
    
    <main class="main-content">
        <section id="page-solution" class="page active">
            <!-- 解决方案匹配页面 -->
        </section>
        <section id="page-competitor" class="page">
            <!-- 竞争对手分析页面 -->
        </section>
        <section id="page-knowledge" class="page">
            <!-- 知识库管理页面 -->
        </section>
    </main>
</div>
```

### 1.2.2 CSS模块重构方案

**新增CSS变量（企业风格）：**
```css
:root {
    /* 品牌色彩 */
    --brand-primary: #C7000B;      /* 华为云品牌红 */
    --brand-primary-light: #E8000D;
    --brand-primary-dark: #9E0008;
    
    /* 中性色系 */
    --neutral-white: #FFFFFF;
    --neutral-gray-50: #F9FAFB;
    --neutral-gray-100: #F3F4F6;
    --neutral-gray-200: #E5E7EB;
    --neutral-gray-300: #D1D5DB;
    --neutral-gray-600: #4B5563;
    --neutral-gray-800: #1F2937;
    --neutral-gray-900: #111827;
    
    /* 功能色 */
    --success-color: #10B981;
    --warning-color: #F59E0B;
    --error-color: #EF4444;
    --info-color: #3B82F6;
    
    /* 字体 */
    --font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 
                   'PingFang SC', 'Microsoft YaHei', sans-serif;
    --font-size-xs: 12px;
    --font-size-sm: 14px;
    --font-size-base: 16px;
    --font-size-lg: 18px;
    --font-size-xl: 20px;
    --font-size-2xl: 24px;
    --font-size-3xl: 32px;
    
    /* 间距 */
    --spacing-xs: 4px;
    --spacing-sm: 8px;
    --spacing-md: 16px;
    --spacing-lg: 24px;
    --spacing-xl: 32px;
    --spacing-2xl: 48px;
    
    /* 导航栏 */
    --navbar-height: 64px;
    --navbar-bg: #FFFFFF;
    --navbar-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    
    /* 卡片 */
    --card-bg: #FFFFFF;
    --card-border: #E5E7EB;
    --card-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    --card-shadow-hover: 0 4px 16px rgba(0, 0, 0, 0.12);
    --card-radius: 12px;
    
    /* 响应式断点 */
    --breakpoint-sm: 640px;
    --breakpoint-md: 768px;
    --breakpoint-lg: 1024px;
    --breakpoint-xl: 1280px;
    --breakpoint-2xl: 1536px;
}
```

**导航栏样式设计：**
```css
/* 顶部导航栏 */
.navbar {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: var(--navbar-height);
    background: var(--navbar-bg);
    box-shadow: var(--navbar-shadow);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--spacing-xl);
    z-index: 1000;
}

/* 品牌区域 */
.navbar-brand {
    display: flex;
    align-items: center;
    gap: var(--spacing-sm);
}

.navbar-brand .logo-icon {
    font-size: 28px;
}

.navbar-brand .logo-text {
    font-size: var(--font-size-xl);
    font-weight: 700;
    color: var(--brand-primary);
}

/* 导航菜单 */
.navbar-menu {
    display: flex;
    align-items: center;
    gap: var(--spacing-xs);
}

.navbar-item {
    display: flex;
    align-items: center;
    gap: var(--spacing-sm);
    padding: var(--spacing-sm) var(--spacing-md);
    background: transparent;
    border: none;
    border-radius: 8px;
    color: var(--neutral-gray-600);
    font-size: var(--font-size-sm);
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
}

.navbar-item:hover {
    background: var(--neutral-gray-100);
    color: var(--neutral-gray-800);
}

.navbar-item.active {
    background: rgba(199, 0, 11, 0.08);
    color: var(--brand-primary);
    font-weight: 600;
}

/* 系统状态 */
.navbar-status {
    display: flex;
    align-items: center;
    gap: var(--spacing-md);
    padding: var(--spacing-sm) var(--spacing-md);
    background: var(--neutral-gray-50);
    border-radius: 8px;
}

.navbar-status .status-item {
    font-size: var(--font-size-xs);
    color: var(--neutral-gray-600);
}

.navbar-status strong {
    color: var(--brand-primary);
    font-weight: 600;
}
```

**内容区域样式调整：**
```css
/* 主内容区域 */
.main-content {
    margin-top: var(--navbar-height);
    padding: var(--spacing-2xl);
    min-height: calc(100vh - var(--navbar-height));
    background: var(--neutral-gray-50);
}

/* 页面容器 */
.page {
    max-width: 1200px;
    margin: 0 auto;
}

/* 页面标题 */
.page-header {
    margin-bottom: var(--spacing-xl);
    padding-bottom: var(--spacing-lg);
    border-bottom: 2px solid var(--neutral-gray-200);
}

.page-title {
    font-size: var(--font-size-2xl);
    font-weight: 700;
    color: var(--neutral-gray-900);
    margin-bottom: var(--spacing-sm);
}

.page-subtitle {
    font-size: var(--font-size-base);
    color: var(--neutral-gray-600);
    line-height: 1.6;
}
```

**卡片样式重构（替换玻璃拟态）：**
```css
/* 企业风格卡片 */
.card {
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: var(--card-radius);
    box-shadow: var(--card-shadow);
    padding: var(--spacing-lg);
    transition: all 0.2s ease;
}

.card:hover {
    box-shadow: var(--card-shadow-hover);
    transform: translateY(-2px);
}

.card-title {
    font-size: var(--font-size-lg);
    font-weight: 600;
    color: var(--neutral-gray-900);
    margin-bottom: var(--spacing-md);
}
```

### 1.2.3 JavaScript逻辑调整

**导航切换逻辑更新：**
```javascript
// 更新导航切换函数
const UI = {
    switchPage(pageName) {
        // 更新页面显示
        document.querySelectorAll('.page').forEach(page => {
            page.classList.remove('active');
        });
        document.getElementById(`page-${pageName}`).classList.add('active');
        
        // 更新导航菜单状态
        document.querySelectorAll('.navbar-item').forEach(item => {
            item.classList.remove('active');
        });
        document.querySelector(`.navbar-item[data-page="${pageName}"]`).classList.add('active');
        
        // 更新状态
        State.currentPage = pageName;
        
        // 如果是知识库页面，加载统计数据
        if (pageName === 'knowledge') {
            KnowledgeUI.loadStats();
        }
    },
    
    // 其他方法保持不变
};
```

**系统状态显示更新：**
```javascript
const KnowledgeUI = {
    async loadStats() {
        try {
            const stats = await API.getKnowledgeStats();
            State.knowledgeStats = stats;
            
            const accuracy = stats.accuracy || 50;
            
            // 更新导航栏状态
            document.getElementById('nav-stat-docs').textContent = stats.total_documents || 0;
            document.getElementById('nav-stat-industries').textContent = stats.supported_industries?.length || 0;
            document.getElementById('nav-stat-accuracy').textContent = `${accuracy}%`;
            
            // 更新知识库页面统计卡片（保持原有功能）
            document.getElementById('kb-total-docs').textContent = stats.total_documents || 0;
            document.getElementById('kb-total-industries').textContent = stats.supported_industries?.length || 0;
            document.getElementById('kb-accuracy').textContent = `${accuracy}%`;
            
            // 渲染图表
            this.renderChart(stats.industry_counts || {});
        } catch (error) {
            console.error('加载统计失败:', error);
            UI.showToast('加载统计数据失败，请检查后端服务', 'warning');
        }
    }
};
```

**移动端导航适配：**
```javascript
function initMobileNavigation() {
    const toggle = document.getElementById('mobile-navbar-toggle');
    const menu = document.querySelector('.navbar-menu');
    const status = document.querySelector('.navbar-status');
    
    toggle?.addEventListener('click', () => {
        const isExpanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', !isExpanded);
        
        // 切换移动端菜单显示
        menu?.classList.toggle('mobile-open');
        status?.classList.toggle('mobile-open');
    });
    
    // 点击菜单项后关闭移动端菜单
    document.querySelectorAll('.navbar-item').forEach(item => {
        item.addEventListener('click', () => {
            if (window.innerWidth < 768) {
                menu?.classList.remove('mobile-open');
                status?.classList.remove('mobile-open');
                toggle?.setAttribute('aria-expanded', 'false');
            }
        });
    });
}
```

### 1.2.4 粒子动画调整

**降低粒子动画强度（更专业风格）：**
```javascript
const Config = {
    // ... 其他配置
    ANIMATION: {
        PARTICLE_COUNT: 40,        // 从80降低到40
        CONNECTION_DISTANCE: 120,  // 从150降低到120
        PARTICLE_SPEED: 0.3,       // 从0.5降低到0.3
        PARTICLE_OPACITY: 0.3      // 新增：降低粒子透明度
    }
};
```

**或完全移除粒子动画，使用简洁背景：**
```css
/* 简洁企业背景 */
body {
    background: linear-gradient(
        180deg,
        var(--neutral-gray-50) 0%,
        var(--neutral-white) 100%
    );
}
```

## **1.3 实现设计文档**

### 1.3.1 文件修改清单

| 文件路径 | 修改类型 | 修改内容 | 优先级 |
|---------|---------|---------|--------|
| `frontend/index.html` | 结构改造 | 删除`<aside class="sidebar">`，新增`<header class="navbar">` | P0 |
| `frontend/style.css` | 样式重构 | 重写导航栏、内容区、卡片样式，调整色彩方案 | P0 |
| `frontend/welcome-styles.css` | 样式调整 | 调整欢迎页配色，移除深色背景 | P1 |
| `frontend/script.js` | 逻辑调整 | 更新导航切换逻辑，调整状态显示位置 | P0 |
| `frontend/welcome-script.js` | 微调 | 无需修改（功能保持不变） | P2 |

### 1.3.2 详细改造步骤

**步骤1：HTML结构调整（index.html）**

删除左侧边栏相关代码（第133-181行）：
- 删除整个 `<aside class="sidebar">` 块
- 删除移动端菜单切换按钮（第184行）

新增顶部导航栏代码（在 `<div class="app-container">` 内部开头）：
```html
<header class="navbar">
    <!-- 品牌标识 -->
    <div class="navbar-brand">
        <span class="logo-icon">☁️</span>
        <span class="logo-text">华为云解决方案匹配系统</span>
    </div>
    
    <!-- 导航菜单 -->
    <nav class="navbar-menu">
        <button class="navbar-item active" data-page="solution">
            <span class="item-icon">🔍</span>
            <span class="item-text">解决方案匹配</span>
        </button>
        <button class="navbar-item" data-page="competitor">
            <span class="item-icon">⚔️</span>
            <span class="item-text">竞争分析</span>
        </button>
        <button class="navbar-item" data-page="knowledge">
            <span class="item-icon">📚</span>
            <span class="item-text">知识库管理</span>
        </button>
    </nav>
    
    <!-- 系统状态 -->
    <div class="navbar-status">
        <span class="status-item">文档: <strong id="nav-stat-docs">--</strong></span>
        <span class="status-item">行业: <strong id="nav-stat-industries">--</strong></span>
        <span class="status-item">准确率: <strong id="nav-stat-accuracy">--%</strong></span>
    </div>
    
    <!-- 移动端菜单切换 -->
    <button class="navbar-toggle" id="mobile-navbar-toggle" aria-label="菜单">☰</button>
</header>
```

**步骤2：CSS样式重构（style.css）**

保留并修改的部分：
- 保留：`:root` 变量定义（添加新变量）
- 保留：基础重置样式
- 保留：按钮样式（调整配色）
- 保留：表单样式（调整配色）
- 保留：Toast通知样式

删除的部分：
- 删除：侧边栏相关样式（`.sidebar`、`.sidebar-header`等）
- 删除：玻璃拟态效果（`.glass-card`中的`backdrop-filter`）
- 删除：深色背景和渐变动画
- 删除：粒子动画canvas样式（可选保留）

新增的部分：
- 新增：导航栏样式（`.navbar`系列）
- 新增：企业风格卡片样式
- 新增：浅色背景样式
- 新增：移动端导航响应式样式

**步骤3：JavaScript逻辑调整（script.js）**

修改的函数：
1. `UI.switchPage()` - 更新导航项选择器
2. `KnowledgeUI.loadStats()` - 同时更新导航栏状态和页面统计
3. `initEventListeners()` - 更新事件绑定选择器

新增的函数：
1. `initMobileNavigation()` - 移动端导航交互

删除的代码：
- 删除侧边栏相关的移动端切换逻辑

**步骤4：欢迎页样式调整（welcome-styles.css）**

调整内容：
- 将深色背景改为浅色背景
- 调整文字配色适应浅色背景
- 调整卡片样式使用新的色彩方案
- 保持欢迎页的整体布局和交互逻辑

### 1.3.3 响应式设计方案

**移动端布局（< 768px）：**
```css
@media (max-width: 767px) {
    /* 导航栏 */
    .navbar {
        padding: 0 var(--spacing-md);
    }
    
    .navbar-menu {
        position: fixed;
        top: var(--navbar-height);
        left: 0;
        right: 0;
        background: var(--navbar-bg);
        box-shadow: var(--navbar-shadow);
        flex-direction: column;
        padding: var(--spacing-md);
        transform: translateY(-100%);
        opacity: 0;
        transition: all 0.3s ease;
    }
    
    .navbar-menu.mobile-open {
        transform: translateY(0);
        opacity: 1;
    }
    
    .navbar-status {
        display: none; /* 移动端隐藏状态栏 */
    }
    
    .navbar-toggle {
        display: block;
    }
    
    /* 内容区 */
    .main-content {
        padding: var(--spacing-md);
    }
}
```

**平板端布局（768px - 1023px）：**
```css
@media (min-width: 768px) and (max-width: 1023px) {
    .navbar-status {
        gap: var(--spacing-sm);
    }
    
    .navbar-status .status-item {
        font-size: 11px;
    }
    
    .main-content {
        padding: var(--spacing-lg);
    }
}
```

**大屏布局（>= 1440px）：**
```css
@media (min-width: 1440px) {
    .page {
        max-width: 1400px;
    }
    
    .main-content {
        padding: var(--spacing-2xl) var(--spacing-2xl);
    }
}
```

### 1.3.4 兼容性保证措施

**功能完整性保证：**
1. ✅ 三大核心功能完整保留（解决方案匹配、竞争分析、知识库管理）
2. ✅ API接口调用逻辑不变
3. ✅ 欢迎引导页功能保留
4. ✅ Demo案例功能保留
5. ✅ 文档下载功能保留
6. ✅ Toast通知功能保留

**交互逻辑保证：**
1. ✅ 导航切换流程不变
2. ✅ 表单提交逻辑不变
3. ✅ 结果展示逻辑不变
4. ✅ 状态更新逻辑不变（仅调整显示位置）

**数据流保证：**
1. ✅ 前后端API接口不变
2. ✅ 请求参数格式不变
3. ✅ 响应数据处理不变
4. ✅ 本地缓存机制不变

---

# **2. 接口设计**

## **2.1 总体设计**

### 2.1.1 前端内部接口

**导航控制接口：**
```typescript
interface NavigationController {
    // 切换页面
    switchPage(pageName: 'solution' | 'competitor' | 'knowledge'): void;
    
    // 获取当前页面
    getCurrentPage(): string;
    
    // 更新导航状态
    updateNavigationState(pageName: string): void;
}
```

**状态管理接口：**
```typescript
interface StateManager {
    // 应用状态
    state: {
        currentPage: string;
        loadingStates: {
            match: boolean;
            analyze: boolean;
            rebuild: boolean;
            clear: boolean;
        };
        knowledgeStats: KnowledgeStats | null;
        resultCache: {
            solution?: MatchResult;
            competitor?: AnalyzeResult;
        };
    };
    
    // 更新状态
    setState(newState: Partial<typeof state>): void;
}
```

**UI组件接口：**
```typescript
interface UIComponents {
    // Toast通知
    showToast(message: string, type: 'success' | 'error' | 'warning' | 'info'): void;
    
    // 按钮加载状态
    setButtonLoading(button: HTMLElement, loading: boolean): void;
    
    // Markdown渲染
    renderMarkdown(content: string): string;
    
    // 文件下载
    downloadFile(content: string, filename: string): void;
}
```

### 2.1.2 API调用接口（保持不变）

```typescript
interface API {
    // 解决方案匹配
    match(demand: string): Promise<MatchResult>;
    
    // 竞争对手分析
    analyze(competitor: string, industry: string): Promise<AnalyzeResult>;
    
    // 获取知识库统计
    getKnowledgeStats(): Promise<KnowledgeStats>;
    
    // 重建知识库
    rebuildKnowledge(): Promise<{ count: number }>;
    
    // 清空知识库
    clearKnowledge(): Promise<{ success: boolean }>;
}
```

## **2.2 接口清单**

### 2.2.1 导航相关接口

| 接口名称 | 输入参数 | 返回值 | 说明 |
|---------|---------|--------|------|
| `switchPage` | `pageName: string` | `void` | 切换当前显示页面 |
| `updateNavbarStatus` | `stats: KnowledgeStats` | `void` | 更新导航栏状态显示 |
| `initMobileNavigation` | 无 | `void` | 初始化移动端导航交互 |

### 2.2.2 UI组件接口

| 接口名称 | 输入参数 | 返回值 | 说明 |
|---------|---------|--------|------|
| `showToast` | `message, type` | `void` | 显示Toast通知 |
| `setButtonLoading` | `button, loading` | `void` | 设置按钮加载状态 |
| `renderMarkdown` | `content` | `string` | 渲染Markdown内容 |
| `downloadFile` | `content, filename` | `void` | 下载文件 |

### 2.2.3 API接口（保持不变）

| 接口名称 | HTTP方法 | 端点 | 说明 |
|---------|---------|------|------|
| `match` | POST | `/api/match` | 解决方案匹配 |
| `analyze` | POST | `/api/analyze` | 竞争对手分析 |
| `getKnowledgeStats` | GET | `/api/knowledge/stats` | 获取知识库统计 |
| `rebuildKnowledge` | POST | `/api/knowledge/rebuild` | 重建知识库 |
| `clearKnowledge` | POST | `/api/knowledge/clear` | 清空知识库 |

---

# **4. 数据模型**

## **4.1 设计目标**

### 4.1.1 数据一致性保证

- ✅ 前后端数据交互格式不变
- ✅ 本地状态管理结构不变
- ✅ API响应数据结构不变

### 4.1.2 新增数据元素

- 新增：导航栏状态显示数据
- 新增：移动端导航展开状态

## **4.2 模型实现**

### 4.2.1 配置数据模型

```typescript
interface Config {
    API_BASE_URL: string;
    ANIMATION: {
        PARTICLE_COUNT: number;
        CONNECTION_DISTANCE: number;
        PARTICLE_SPEED: number;
        PARTICLE_OPACITY?: number;
    };
    INDUSTRIES: string[];
    COMPETITORS: string[];
}
```

### 4.2.2 状态数据模型

```typescript
interface State {
    currentPage: 'solution' | 'competitor' | 'knowledge';
    loadingStates: {
        match: boolean;
        analyze: boolean;
        rebuild: boolean;
        clear: boolean;
    };
    knowledgeStats: KnowledgeStats | null;
    resultCache: {
        solution?: MatchResult;
        competitor?: AnalyzeResult;
    };
}

interface KnowledgeStats {
    total_documents: number;
    supported_industries: string[];
    accuracy: number;
    industry_counts: Record<string, number>;
}
```

### 4.2.3 API响应数据模型（保持不变）

```typescript
interface MatchResult {
    answer: string;
    source_documents: SourceDocument[];
}

interface AnalyzeResult {
    answer: string;
    source_documents: SourceDocument[];
    competitor: string;
    industry: string;
}

interface SourceDocument {
    page_content: string;
    metadata: {
        source: string;
        industry: string;
    };
}
```

### 4.2.4 导航状态数据模型（新增）

```typescript
interface NavigationState {
    // 当前激活页面
    activePage: 'solution' | 'competitor' | 'knowledge';
    
    // 移动端菜单展开状态
    isMobileMenuOpen: boolean;
    
    // 导航栏统计数据显示
    navbarStats: {
        documents: number;
        industries: number;
        accuracy: number;
    };
}
```

---

# **5. 实施计划**

## **5.1 实施步骤**

### 阶段1：HTML结构调整（30分钟）
1. 备份现有文件
2. 修改 `index.html` 结构
3. 删除侧边栏代码
4. 新增顶部导航栏代码
5. 调整页面容器结构

### 阶段2：CSS样式重构（60分钟）
1. 更新CSS变量定义
2. 重写导航栏样式
3. 调整内容区域样式
4. 重构卡片样式
5. 调整色彩方案
6. 添加响应式样式

### 阶段3：JavaScript逻辑调整（30分钟）
1. 更新导航切换函数
2. 调整状态显示逻辑
3. 添加移动端导航交互
4. 更新事件绑定

### 阶段4：样式微调和测试（30分钟）
1. 调整欢迎页样式
2. 测试所有功能
3. 测试响应式布局
4. 修复样式问题

## **5.2 验收标准**

- [ ] 导航栏位于页面顶部，固定定位
- [ ] 品牌标识显示在导航栏左侧
- [ ] 导航菜单项横向排列
- [ ] 系统状态显示在导航栏右侧
- [ ] 内容区域占据全宽
- [ ] 视觉风格符合华为云企业官网风格
- [ ] 三大核心功能完整可用
- [ ] 响应式布局在各设备正常显示
- [ ] 移动端导航可折叠展开
- [ ] 所有交互功能正常工作

## **5.3 回滚方案**

如需回滚：
1. 恢复备份的原始文件
2. 清除浏览器缓存
3. 重新加载页面
