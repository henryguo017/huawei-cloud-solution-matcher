# **1. 实现模型**

## **1.1 上下文视图**

本设计方案在华为云解决方案匹配系统的前端架构基础上,新增欢迎引导页和快速体验 Demo 功能模块。新模块将与现有前端系统无缝集成,复用现有的 UI 组件、动画系统和 API 调用层。

### **1.1.1 系统上下文**

```
┌─────────────────────────────────────────────────────────────┐
│                    华为云解决方案匹配系统                      │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  欢迎引导页  │  │  快速体验Demo │  │  现有主系统  │       │
│  │  WelcomePage │  │  QuickDemo   │  │  MainSystem  │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│         │                  │                  │              │
│         └──────────────────┴──────────────────┘              │
│                          │                                   │
│                 ┌────────▼────────┐                         │
│                 │   共享基础设施   │                         │
│                 │  UI Components  │                         │
│                 │  Animation Sys  │                         │
│                 │   API Layer     │                         │
│                 └─────────────────┘                         │
└─────────────────────────────────────────────────────────────┘
                          │
                ┌─────────▼─────────┐
                │  localStorage     │
                │  (skipWelcome)    │
                └───────────────────┘
```

### **1.1.2 集成边界**

- **与现有系统集成**: 通过 DOM 操作和事件系统与现有页面交互,不修改现有核心逻辑
- **状态存储边界**: 仅使用 localStorage 存储 `skipWelcome` 状态,不涉及其他数据存储
- **API 调用边界**: 复用现有 `API.match()` 方法,不新增后端接口
- **样式边界**: 复用现有 CSS 变量和样式类,新增样式通过独立的类名命名空间隔离

## **1.2 服务/组件总体架构**

### **1.2.1 组件架构图**

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend Application                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │              WelcomeManager (新增)                  │     │
│  │  ┌──────────────┐    ┌──────────────┐             │     │
│  │  │ WelcomePage  │    │ StorageMgr   │             │     │
│  │  │  - render()  │    │ - getState() │             │     │
│  │  │  - animate() │    │ - setState() │             │     │
│  │  └──────────────┘    └──────────────┘             │     │
│  └────────────────────────────────────────────────────┘     │
│                          │                                   │
│                          ▼                                   │
│  ┌────────────────────────────────────────────────────┐     │
│  │              QuickDemoManager (新增)                │     │
│  │  ┌──────────────┐    ┌──────────────┐             │     │
│  │  │ DemoSelector │    │ AutoMatchFlow│             │     │
│  │  │  - show()    │    │ - fill()     │             │
│  │  │  - hide()    │    │ - trigger()  │             │
│  │  └──────────────┘    └──────────────┘             │     │
│  └────────────────────────────────────────────────────┘     │
│                          │                                   │
│                          ▼                                   │
│  ┌────────────────────────────────────────────────────┐     │
│  │              现有前端系统 (复用)                     │     │
│  │  ┌──────────────┐    ┌──────────────┐             │     │
│  │  │  UI Utils    │    │  API Layer   │             │     │
│  │  │ - showToast()│    │ - match()    │             │     │
│  │  │ - switchPage│    │ - analyze()   │             │     │
│  │  └──────────────┘    └──────────────┘             │     │
│  └────────────────────────────────────────────────────┘     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### **1.2.2 模块依赖关系**

```
WelcomePage
    ├── StorageManager (状态管理)
    ├── AnimationUtils (动画工具,复用粒子系统)
    └── UI (复用现有UI工具)

QuickDemoManager
    ├── DemoSelector (案例选择器)
    ├── AutoMatchFlow (自动匹配流程)
    ├── API.match (复用现有API)
    └── UI (复用现有UI工具)

DemoSelector
    ├── DOMUtils (DOM操作)
    └── AnimationUtils (动画)

AutoMatchFlow
    ├── API.match (后端匹配服务)
    └── UI (结果显示)
```

## **1.3 实现设计文档**

### **1.3.1 欢迎引导页实现设计**

#### **1.3.1.1 HTML 结构设计**

```html
<!-- 欢迎引导页容器 - 插入到 body 开头 -->
<div id="welcome-page" class="welcome-overlay">
    <div class="welcome-container">
        <!-- 背景粒子画布 (复用现有粒子系统) -->
        <canvas id="welcome-particle-canvas"></canvas>
        
        <!-- 背景光效层 -->
        <div class="welcome-glow-layer">
            <div class="glow-circle glow-1"></div>
            <div class="glow-circle glow-2"></div>
            <div class="glow-circle glow-3"></div>
        </div>
        
        <!-- 主内容区 -->
        <div class="welcome-content">
            <!-- 顶部标题区 -->
            <div class="welcome-header">
                <div class="logo-wrapper">
                    <span class="logo-icon">☁️</span>
                    <h1 class="system-title">华为云解决方案智能匹配系统</h1>
                </div>
                <p class="system-subtitle">让销售方案准备时间从 2 小时缩短至 1 分钟</p>
            </div>
            
            <!-- 功能介绍卡片组 -->
            <div class="feature-cards">
                <div class="feature-card glass-card" data-delay="0">
                    <div class="feature-icon">🔍</div>
                    <h3 class="feature-title">智能解决方案匹配</h3>
                    <p class="feature-desc">基于客户需求自动匹配最合适的华为云行业解决方案</p>
                </div>
                
                <div class="feature-card glass-card" data-delay="200">
                    <div class="feature-icon">⚔️</div>
                    <h3 class="feature-title">竞争对手分析</h3>
                    <p class="feature-desc">生成华为云与竞争对手的差异化优势和应对话术</p>
                </div>
                
                <div class="feature-card glass-card" data-delay="400">
                    <div class="feature-icon">📚</div>
                    <h3 class="feature-title">知识库管理</h3>
                    <p class="feature-desc">支持一键导入华为云官方解决方案文档</p>
                </div>
            </div>
            
            <!-- 核心价值展示区 -->
            <div class="value-showcase">
                <div class="value-item">
                    <div class="value-number" data-target="87">0</div>
                    <div class="value-unit">%</div>
                    <div class="value-label">匹配准确率</div>
                </div>
                <div class="value-item">
                    <div class="value-number" data-target="95">0</div>
                    <div class="value-unit">%</div>
                    <div class="value-label">效率提升</div>
                </div>
                <div class="value-item">
                    <div class="value-number" data-target="10">0</div>
                    <div class="value-unit">+</div>
                    <div class="value-label">覆盖行业</div>
                </div>
            </div>
            
            <!-- 操作按钮区 -->
            <div class="welcome-actions">
                <button class="btn btn-primary btn-large btn-glow" id="start-experience-btn">
                    <span class="btn-text">立即体验</span>
                    <span class="btn-icon">→</span>
                </button>
                <button class="btn btn-skip" id="skip-welcome-btn">
                    跳过引导,直接进入
                </button>
            </div>
        </div>
    </div>
</div>
```

**插入位置**: 在 `<body>` 标签后,`<canvas id="particle-canvas">` 之前插入

**结构说明**:
- **welcome-overlay**: 全屏遮罩层,z-index 高于主系统,负责覆盖整个页面
- **welcome-particle-canvas**: 独立的粒子画布,与主系统粒子分离,可配置不同参数
- **welcome-glow-layer**: 背景光效层,使用 CSS 动画实现流动光效
- **feature-cards**: 功能介绍卡片,使用现有 `glass-card` 类实现玻璃拟态效果
- **value-showcase**: 核心价值展示,使用数字递增动画从 0 递增至目标值

#### **1.3.1.2 CSS 样式设计**

```css
/* ========== 欢迎引导页样式 ========== */

/* 全屏遮罩层 */
.welcome-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: 9999;
    background: linear-gradient(135deg, 
        var(--bg-dark-primary) 0%, 
        var(--bg-dark-secondary) 50%, 
        var(--bg-dark-tertiary) 100%);
    background-size: 400% 400%;
    animation: welcome-gradient-shift 20s ease infinite;
    overflow-y: auto;
    overflow-x: hidden;
}

@keyframes welcome-gradient-shift {
    0% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}

/* 主容器 */
.welcome-container {
    position: relative;
    width: 100%;
    min-height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 40px 20px;
}

/* 欢迎页粒子画布 */
#welcome-particle-canvas {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: 0;
    pointer-events: none;
}

/* 背景光效层 */
.welcome-glow-layer {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: 1;
    pointer-events: none;
    overflow: hidden;
}

.glow-circle {
    position: absolute;
    border-radius: 50%;
    filter: blur(80px);
    opacity: 0.3;
}

.glow-circle.glow-1 {
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, var(--huawei-red) 0%, transparent 70%);
    top: 10%;
    left: 10%;
    animation: glow-float-1 15s ease-in-out infinite;
}

.glow-circle.glow-2 {
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, var(--tech-blue) 0%, transparent 70%);
    top: 50%;
    right: 10%;
    animation: glow-float-2 18s ease-in-out infinite;
}

.glow-circle.glow-3 {
    width: 350px;
    height: 350px;
    background: radial-gradient(circle, var(--tech-purple) 0%, transparent 70%);
    bottom: 10%;
    left: 30%;
    animation: glow-float-3 20s ease-in-out infinite;
}

@keyframes glow-float-1 {
    0%, 100% { transform: translate(0, 0) scale(1); }
    33% { transform: translate(100px, 50px) scale(1.1); }
    66% { transform: translate(50px, 100px) scale(0.9); }
}

@keyframes glow-float-2 {
    0%, 100% { transform: translate(0, 0) scale(1); }
    33% { transform: translate(-80px, 60px) scale(1.15); }
    66% { transform: translate(-40px, -80px) scale(0.95); }
}

@keyframes glow-float-3 {
    0%, 100% { transform: translate(0, 0) scale(1); }
    33% { transform: translate(70px, -50px) scale(1.1); }
    66% { transform: translate(-60px, 70px) scale(0.9); }
}

/* 主内容区 */
.welcome-content {
    position: relative;
    z-index: 2;
    max-width: 1200px;
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 48px;
    animation: welcome-fade-in 0.8s ease-out;
}

@keyframes welcome-fade-in {
    from {
        opacity: 0;
        transform: translateY(30px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* 顶部标题区 */
.welcome-header {
    text-align: center;
    animation: welcome-fade-in 0.8s ease-out 0.2s both;
}

.logo-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    margin-bottom: 20px;
}

.logo-icon {
    font-size: 48px;
    filter: drop-shadow(0 0 20px rgba(255, 255, 255, 0.4));
    animation: logo-pulse 3s ease-in-out infinite;
}

@keyframes logo-pulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.1); }
}

.system-title {
    font-size: 48px;
    font-weight: 800;
    background: linear-gradient(135deg, 
        var(--text-primary) 0%, 
        var(--tech-blue) 50%,
        var(--tech-purple) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: 2px;
    text-shadow: 0 0 40px rgba(74, 144, 226, 0.3);
}

.system-subtitle {
    font-size: 20px;
    color: var(--text-secondary);
    margin-top: 16px;
    font-weight: 500;
    letter-spacing: 1px;
}

/* 功能介绍卡片组 */
.feature-cards {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
    width: 100%;
    animation: welcome-fade-in 0.8s ease-out 0.4s both;
}

.feature-card {
    padding: 32px 24px;
    text-align: center;
    transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    animation: card-float 6s ease-in-out infinite;
}

.feature-card:nth-child(1) { animation-delay: 0s; }
.feature-card:nth-child(2) { animation-delay: 2s; }
.feature-card:nth-child(3) { animation-delay: 4s; }

@keyframes card-float {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-10px); }
}

.feature-card:hover {
    transform: translateY(-15px) scale(1.02);
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4), 
                0 0 40px rgba(100, 150, 255, 0.3);
}

.feature-icon {
    font-size: 56px;
    margin-bottom: 20px;
    display: inline-block;
    animation: icon-bounce 2s ease-in-out infinite;
}

@keyframes icon-bounce {
    0%, 100% { transform: scale(1) rotate(0deg); }
    25% { transform: scale(1.1) rotate(-5deg); }
    75% { transform: scale(1.1) rotate(5deg); }
}

.feature-title {
    font-size: 22px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 16px;
}

.feature-desc {
    font-size: 15px;
    color: var(--text-secondary);
    line-height: 1.6;
}

/* 核心价值展示区 */
.value-showcase {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 48px;
    padding: 40px 60px;
    background: var(--bg-glass);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 20px;
    animation: welcome-fade-in 0.8s ease-out 0.6s both;
}

.value-item {
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
}

.value-number {
    font-size: 64px;
    font-weight: 800;
    background: linear-gradient(135deg, 
        var(--huawei-red) 0%, 
        var(--tech-blue) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1;
}

.value-unit {
    font-size: 32px;
    font-weight: 700;
    color: var(--tech-blue);
    margin-left: -8px;
}

.value-label {
    font-size: 16px;
    color: var(--text-secondary);
    font-weight: 500;
    margin-top: 8px;
}

/* 操作按钮区 */
.welcome-actions {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 20px;
    animation: welcome-fade-in 0.8s ease-out 0.8s both;
}

.btn-large {
    padding: 16px 48px;
    font-size: 18px;
    font-weight: 600;
}

.btn-glow {
    position: relative;
    box-shadow: 0 0 30px rgba(255, 0, 0, 0.5),
                0 0 60px rgba(255, 0, 0, 0.3),
                inset 0 0 20px rgba(255, 255, 255, 0.1);
    animation: btn-glow-pulse 2s ease-in-out infinite;
}

@keyframes btn-glow-pulse {
    0%, 100% { 
        box-shadow: 0 0 30px rgba(255, 0, 0, 0.5),
                    0 0 60px rgba(255, 0, 0, 0.3);
    }
    50% { 
        box-shadow: 0 0 40px rgba(255, 0, 0, 0.7),
                    0 0 80px rgba(255, 0, 0, 0.5);
    }
}

.btn-icon {
    margin-left: 12px;
    font-size: 20px;
    transition: transform 0.3s ease;
}

.btn-glow:hover .btn-icon {
    transform: translateX(8px);
}

.btn-skip {
    background: transparent;
    color: var(--text-secondary);
    border: none;
    padding: 12px 24px;
    font-size: 15px;
    cursor: pointer;
    transition: all 0.3s ease;
    text-decoration: underline;
    text-underline-offset: 4px;
}

.btn-skip:hover {
    color: var(--text-primary);
    text-decoration-color: var(--huawei-red);
}

/* 欢迎页淡出动画 */
.welcome-overlay.fade-out {
    animation: welcome-fade-out 0.5s ease-out forwards;
}

@keyframes welcome-fade-out {
    from {
        opacity: 1;
        transform: scale(1);
    }
    to {
        opacity: 0;
        transform: scale(0.95);
    }
}

/* ========== 响应式设计 ========== */

@media (max-width: 1023px) {
    .feature-cards {
        grid-template-columns: repeat(2, 1fr);
    }
    
    .system-title {
        font-size: 40px;
    }
    
    .value-showcase {
        padding: 30px 40px;
        gap: 32px;
    }
    
    .value-number {
        font-size: 48px;
    }
}

@media (max-width: 767px) {
    .welcome-container {
        padding: 30px 16px;
    }
    
    .feature-cards {
        grid-template-columns: 1fr;
        gap: 16px;
    }
    
    .system-title {
        font-size: 32px;
    }
    
    .system-subtitle {
        font-size: 16px;
    }
    
    .value-showcase {
        grid-template-columns: 1fr;
        gap: 24px;
        padding: 24px;
    }
    
    .value-number {
        font-size: 40px;
    }
    
    .value-unit {
        font-size: 24px;
    }
    
    .logo-icon {
        font-size: 36px;
    }
    
    .feature-icon {
        font-size: 48px;
    }
    
    .btn-large {
        padding: 14px 36px;
        font-size: 16px;
    }
    
    .welcome-header {
        gap: 32px;
    }
}

@media (min-width: 1440px) {
    .system-title {
        font-size: 56px;
    }
    
    .value-number {
        font-size: 72px;
    }
    
    .feature-card {
        padding: 40px 32px;
    }
}
```

#### **1.3.1.3 JavaScript 逻辑设计**

```javascript
/**
 * 欢迎引导页管理器
 * 职责: 管理欢迎引导页的显示、动画和用户交互
 */
class WelcomeManager {
    constructor() {
        this.welcomePage = null;
        this.particleSystem = null;
        this.animationFrameId = null;
        this.init();
    }
    
    /**
     * 初始化欢迎引导页
     */
    init() {
        // 检查是否需要显示欢迎引导页
        const shouldShow = this.shouldShowWelcome();
        
        if (shouldShow) {
            this.createWelcomePage();
            this.startAnimations();
            this.bindEvents();
        } else {
            // 直接隐藏欢迎页(如果存在)
            this.hideWelcomePage();
        }
    }
    
    /**
     * 判断是否应该显示欢迎引导页
     * @returns {boolean}
     */
    shouldShowWelcome() {
        try {
            const skipWelcome = localStorage.getItem('skipWelcome');
            // 如果状态不存在或为 "false",则显示欢迎页
            return skipWelcome !== 'true';
        } catch (error) {
            // localStorage 不可用时,默认显示欢迎页
            console.warn('localStorage 不可用:', error);
            return true;
        }
    }
    
    /**
     * 创建欢迎引导页 DOM 结构
     */
    createWelcomePage() {
        // 创建欢迎页容器
        const welcomeHTML = `
            <div id="welcome-page" class="welcome-overlay">
                <!-- 内容见 HTML 结构设计部分 -->
            </div>
        `;
        
        // 插入到 body 开头
        document.body.insertAdjacentHTML('afterbegin', welcomeHTML);
        this.welcomePage = document.getElementById('welcome-page');
    }
    
    /**
     * 启动所有动画
     */
    startAnimations() {
        // 启动粒子动画
        this.initParticleSystem();
        
        // 启动数字递增动画
        this.startNumberAnimation();
        
        // 启动功能卡片入场动画
        this.startCardAnimation();
    }
    
    /**
     * 初始化粒子系统
     */
    initParticleSystem() {
        const canvas = document.getElementById('welcome-particle-canvas');
        if (!canvas) return;
        
        // 使用与主系统相似的粒子系统,但参数更柔和
        this.particleSystem = new ParticleSystem(canvas, {
            particleCount: 60,
            connectionDistance: 120,
            particleSpeed: 0.3,
            particleColor: 'rgba(100, 150, 255, 0.5)'
        });
    }
    
    /**
     * 数字递增动画
     */
    startNumberAnimation() {
        const valueNumbers = document.querySelectorAll('.value-number');
        
        valueNumbers.forEach((element) => {
            const target = parseInt(element.dataset.target, 10);
            const duration = 2000; // 动画持续时间 2 秒
            const startTime = performance.now();
            
            const animate = (currentTime) => {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);
                
                // 使用缓动函数实现平滑过渡
                const easeOutQuart = 1 - Math.pow(1 - progress, 4);
                const currentValue = Math.floor(easeOutQuart * target);
                
                element.textContent = currentValue;
                
                if (progress < 1) {
                    requestAnimationFrame(animate);
                }
            };
            
            // 延迟 800ms 后开始动画(等待入场动画完成)
            setTimeout(() => {
                requestAnimationFrame(animate);
            }, 800);
        });
    }
    
    /**
     * 功能卡片入场动画
     */
    startCardAnimation() {
        const cards = document.querySelectorAll('.feature-card');
        
        cards.forEach((card, index) => {
            const delay = parseInt(card.dataset.delay, 10) || 0;
            card.style.opacity = '0';
            card.style.transform = 'translateY(30px)';
            
            setTimeout(() => {
                card.style.transition = 'all 0.6s cubic-bezier(0.4, 0, 0.2, 1)';
                card.style.opacity = '1';
                card.style.transform = 'translateY(0)';
            }, 400 + delay);
        });
    }
    
    /**
     * 绑定事件监听器
     */
    bindEvents() {
        // 立即体验按钮
        const startBtn = document.getElementById('start-experience-btn');
        startBtn?.addEventListener('click', () => {
            this.hideWelcomePage();
        });
        
        // 跳过引导按钮
        const skipBtn = document.getElementById('skip-welcome-btn');
        skipBtn?.addEventListener('click', () => {
            this.saveSkipState();
            this.hideWelcomePage();
        });
        
        // ESC 键跳过
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.welcomePage) {
                this.saveSkipState();
                this.hideWelcomePage();
            }
        });
    }
    
    /**
     * 保存跳过状态到 localStorage
     */
    saveSkipState() {
        try {
            localStorage.setItem('skipWelcome', 'true');
            
            // 验证写入是否成功
            const saved = localStorage.getItem('skipWelcome');
            if (saved !== 'true') {
                console.warn('localStorage 写入验证失败');
            }
        } catch (error) {
            console.error('保存跳过状态失败:', error);
        }
    }
    
    /**
     * 隐藏欢迎引导页
     */
    hideWelcomePage() {
        if (!this.welcomePage) return;
        
        // 添加淡出动画类
        this.welcomePage.classList.add('fade-out');
        
        // 动画结束后移除 DOM
        setTimeout(() => {
            if (this.particleSystem) {
                this.particleSystem.destroy();
            }
            this.welcomePage.remove();
            this.welcomePage = null;
            
            // 触发欢迎页关闭事件
            window.dispatchEvent(new CustomEvent('welcomeClosed'));
        }, 500);
    }
    
    /**
     * 销毁欢迎页管理器
     */
    destroy() {
        if (this.particleSystem) {
            this.particleSystem.destroy();
        }
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
        }
        this.welcomePage?.remove();
    }
}
```

### **1.3.2 快速体验 Demo 实现设计**

#### **1.3.2.1 Demo 案例数据结构设计**

```javascript
/**
 * Demo 案例配置
 * 包含预设的典型客户需求场景
 */
const DemoCases = {
    cases: [
        {
            id: 'demo_1',
            name: '制造业预测性维护',
            industry: '工业互联网',
            shortDesc: '设备故障预测,减少停机损失',
            description: `我们是一家中型制造企业,拥有50台生产设备,主要生产精密零部件。目前面临的主要问题是:
1. 设备突发故障频繁,平均每月发生8-10次非计划停机
2. 每次停机造成的直接经济损失约5万元,包括产能损失、人工成本和延期交付赔偿
3. 维修团队主要采用事后维修模式,无法提前预判故障
4. 关键设备缺乏实时监控,故障发现滞后

我们希望能够实现设备的预测性维护,通过实时监测设备状态,提前发现故障隐患,减少非计划停机时间,降低维修成本,提高生产效率和设备利用率。期望通过数字化手段,将设备综合效率(OEE)从目前的65%提升到85%以上。`,
            tags: ['IoT', '大数据分析', 'AI预测']
        },
        {
            id: 'demo_2',
            name: '智慧农业植物方舱',
            industry: '智慧农业',
            shortDesc: '智能环境控制,提升作物产量',
            description: `我们是一家现代农业科技公司,计划在全国建设100个智能植物方舱,用于高价值经济作物的周年生产。目前面临的主要挑战是:
1. 不同作物对温度、湿度、光照、CO2浓度的要求差异大,人工控制难以精准
2. 传统种植模式产量不稳定,受季节和气候影响大,品质难以保证
3. 方舱分布在全国各地,现场管理人员有限,需要远程集中管理
4. 能耗成本占运营成本的40%,需要优化能耗管理降低成本

我们希望构建智慧农业植物方舱管理系统,实现环境参数的智能调控、作物生长周期的自动管理、远程视频监控和诊断、能耗优化分析等功能。目标是实现全年无休生产,产量提升30%,能耗降低20%。`,
            tags: ['IoT', '边缘计算', 'AI视觉']
        },
        {
            id: 'demo_3',
            name: '智慧园区综合管理',
            industry: '智慧园区',
            shortDesc: '一体化管理,提升园区运营效率',
            description: `我们管理着一个大型科技园区,占地200亩,入驻企业超过200家,日均人流3万人次。目前园区管理面临以下问题:
1. 安防管理分散,门禁、监控、消防等系统独立运行,无法联动响应
2. 停车资源紧张,车位利用率仅70%,访客车辆管理混乱,经常造成拥堵
3. 能源管理粗放,水电空调等能耗数据不透明,月均能耗成本超过200万元
4. 物业服务响应慢,报修、投诉处理平均耗时48小时,客户满意度仅75%

我们希望打造智慧园区综合管理平台,实现安防一体化联动、智能停车引导、能耗精细化管理和物业服务在线化,将园区运营成本降低15%,客户满意度提升至90%以上。`,
            tags: ['统一管理', '大数据', 'AI分析']
        }
    ],
    
    /**
     * 获取所有案例
     */
    getAll() {
        return this.cases;
    },
    
    /**
     * 根据 ID 获取案例
     */
    getById(id) {
        return this.cases.find(c => c.id === id);
    },
    
    /**
     * 获取随机案例
     */
    getRandom() {
        const index = Math.floor(Math.random() * this.cases.length);
        return this.cases[index];
    }
};
```

#### **1.3.2.2 案例选择器 HTML 结构**

```html
<!-- 案例选择器模态框 -->
<div id="demo-selector-modal" class="demo-selector-overlay" style="display: none;">
    <div class="demo-selector-container glass-card">
        <div class="demo-selector-header">
            <h3 class="demo-selector-title">🚀 选择 Demo 案例</h3>
            <button class="demo-selector-close" id="close-selector-btn" aria-label="关闭">×</button>
        </div>
        
        <div class="demo-selector-content">
            <p class="demo-selector-desc">选择一个行业场景,快速体验系统的解决方案匹配能力</p>
            
            <div class="demo-cases-list">
                <!-- 案例 1 -->
                <div class="demo-case-item" data-demo-id="demo_1">
                    <div class="demo-case-icon">🏭</div>
                    <div class="demo-case-info">
                        <h4 class="demo-case-name">制造业预测性维护</h4>
                        <p class="demo-case-desc">设备故障预测,减少停机损失</p>
                        <div class="demo-case-tags">
                            <span class="tag">IoT</span>
                            <span class="tag">大数据分析</span>
                            <span class="tag">AI预测</span>
                        </div>
                    </div>
                    <div class="demo-case-arrow">→</div>
                </div>
                
                <!-- 案例 2 -->
                <div class="demo-case-item" data-demo-id="demo_2">
                    <div class="demo-case-icon">🌱</div>
                    <div class="demo-case-info">
                        <h4 class="demo-case-name">智慧农业植物方舱</h4>
                        <p class="demo-case-desc">智能环境控制,提升作物产量</p>
                        <div class="demo-case-tags">
                            <span class="tag">IoT</span>
                            <span class="tag">边缘计算</span>
                            <span class="tag">AI视觉</span>
                        </div>
                    </div>
                    <div class="demo-case-arrow">→</div>
                </div>
                
                <!-- 案例 3 -->
                <div class="demo-case-item" data-demo-id="demo_3">
                    <div class="demo-case-icon">🏢</div>
                    <div class="demo-case-info">
                        <h4 class="demo-case-name">智慧园区综合管理</h4>
                        <p class="demo-case-desc">一体化管理,提升园区运营效率</p>
                        <div class="demo-case-tags">
                            <span class="tag">统一管理</span>
                            <span class="tag">大数据</span>
                            <span class="tag">AI分析</span>
                        </div>
                    </div>
                    <div class="demo-case-arrow">→</div>
                </div>
            </div>
        </div>
        
        <div class="demo-selector-footer">
            <button class="btn btn-secondary" id="cancel-demo-btn">取消</button>
        </div>
    </div>
</div>

<!-- 快速体验按钮 - 插入到解决方案匹配页面顶部 -->
<div class="quick-demo-section">
    <button class="btn btn-demo" id="quick-demo-btn">
        <span class="btn-icon">⚡</span>
        <span class="btn-text">快速体验</span>
    </button>
</div>
```

#### **1.3.2.3 案例选择器 CSS 样式**

```css
/* ========== 快速体验按钮样式 ========== */

.quick-demo-section {
    margin-bottom: 24px;
    animation: fade-in 0.5s ease;
}

.btn-demo {
    background: linear-gradient(135deg, 
        rgba(255, 215, 0, 0.2) 0%, 
        rgba(255, 165, 0, 0.2) 100%);
    border: 2px solid rgba(255, 215, 0, 0.5);
    color: #FFD700;
    padding: 14px 32px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.3s ease;
    box-shadow: 0 4px 20px rgba(255, 215, 0, 0.2);
}

.btn-demo:hover {
    background: linear-gradient(135deg, 
        rgba(255, 215, 0, 0.3) 0%, 
        rgba(255, 165, 0, 0.3) 100%);
    border-color: rgba(255, 215, 0, 0.8);
    box-shadow: 0 6px 30px rgba(255, 215, 0, 0.4);
    transform: translateY(-2px);
}

.btn-demo .btn-icon {
    font-size: 20px;
    margin-right: 8px;
    animation: lightning-pulse 1.5s ease-in-out infinite;
}

@keyframes lightning-pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.6; transform: scale(1.2); }
}

/* ========== 案例选择器模态框样式 ========== */

.demo-selector-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: 10000;
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
    animation: overlay-fade-in 0.3s ease;
}

@keyframes overlay-fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
}

.demo-selector-container {
    max-width: 600px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
    padding: 0;
    animation: modal-slide-in 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes modal-slide-in {
    from {
        opacity: 0;
        transform: translateY(-50px) scale(0.95);
    }
    to {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
}

.demo-selector-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 24px 28px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.demo-selector-title {
    font-size: 22px;
    font-weight: 600;
    color: var(--text-primary);
}

.demo-selector-close {
    width: 36px;
    height: 36px;
    background: rgba(255, 255, 255, 0.1);
    border: none;
    border-radius: 50%;
    color: var(--text-secondary);
    font-size: 24px;
    cursor: pointer;
    transition: all 0.3s ease;
    display: flex;
    align-items: center;
    justify-content: center;
}

.demo-selector-close:hover {
    background: rgba(255, 0, 0, 0.2);
    color: var(--huawei-red);
}

.demo-selector-content {
    padding: 24px 28px;
}

.demo-selector-desc {
    font-size: 15px;
    color: var(--text-secondary);
    margin-bottom: 24px;
    line-height: 1.6;
}

.demo-cases-list {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.demo-case-item {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 20px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.3s ease;
}

.demo-case-item:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: var(--tech-blue);
    transform: translateX(8px);
    box-shadow: 0 4px 20px rgba(74, 144, 226, 0.2);
}

.demo-case-item:focus {
    outline: 2px solid var(--tech-blue);
    outline-offset: 2px;
}

.demo-case-icon {
    font-size: 40px;
    flex-shrink: 0;
}

.demo-case-info {
    flex: 1;
}

.demo-case-name {
    font-size: 18px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 8px;
}

.demo-case-desc {
    font-size: 14px;
    color: var(--text-secondary);
    margin-bottom: 10px;
    line-height: 1.5;
}

.demo-case-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

.tag {
    padding: 4px 10px;
    background: rgba(74, 144, 226, 0.2);
    border: 1px solid rgba(74, 144, 226, 0.3);
    border-radius: 6px;
    font-size: 12px;
    color: var(--tech-blue);
}

.demo-case-arrow {
    font-size: 24px;
    color: var(--text-secondary);
    transition: transform 0.3s ease;
}

.demo-case-item:hover .demo-case-arrow {
    transform: translateX(8px);
    color: var(--tech-blue);
}

.demo-selector-footer {
    padding: 20px 28px;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    justify-content: flex-end;
}

/* 选择器淡出动画 */
.demo-selector-overlay.fade-out {
    animation: overlay-fade-out 0.3s ease forwards;
}

@keyframes overlay-fade-out {
    from { opacity: 1; }
    to { opacity: 0; }
}

/* ========== 响应式设计 ========== */

@media (max-width: 767px) {
    .demo-selector-overlay {
        align-items: flex-end;
        padding: 0;
    }
    
    .demo-selector-container {
        max-width: 100%;
        border-radius: 20px 20px 0 0;
        max-height: 80vh;
    }
    
    .demo-case-item {
        padding: 16px;
    }
    
    .demo-case-icon {
        font-size: 32px;
    }
    
    .demo-case-name {
        font-size: 16px;
    }
}
```

#### **1.3.2.4 自动匹配流程 JavaScript 设计**

```javascript
/**
 * 快速体验 Demo 管理器
 * 职责: 管理 Demo 案例选择和自动匹配流程
 */
class QuickDemoManager {
    constructor() {
        this.selectorModal = null;
        this.isSelectorOpen = false;
        this.isAutoMatching = false;
        this.selectedDemoId = null;
        this.init();
    }
    
    /**
     * 初始化
     */
    init() {
        // 等待欢迎页关闭后再初始化快速体验按钮
        if (document.getElementById('welcome-page')) {
            window.addEventListener('welcomeClosed', () => {
                this.createQuickDemoButton();
                this.createSelectorModal();
                this.bindEvents();
            });
        } else {
            this.createQuickDemoButton();
            this.createSelectorModal();
            this.bindEvents();
        }
    }
    
    /**
     * 创建快速体验按钮
     */
    createQuickDemoButton() {
        const buttonHTML = `
            <div class="quick-demo-section">
                <button class="btn btn-demo" id="quick-demo-btn">
                    <span class="btn-icon">⚡</span>
                    <span class="btn-text">快速体验</span>
                </button>
            </div>
        `;
        
        // 插入到解决方案匹配页面的表单上方
        const pageSolution = document.getElementById('page-solution');
        const contentCard = pageSolution?.querySelector('.content-card');
        
        if (contentCard) {
            contentCard.insertAdjacentHTML('beforebegin', buttonHTML);
        }
    }
    
    /**
     * 创建案例选择器模态框
     */
    createSelectorModal() {
        const modalHTML = `
            <div id="demo-selector-modal" class="demo-selector-overlay" style="display: none;">
                <!-- 内容见 HTML 结构设计部分 -->
            </div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', modalHTML);
        this.selectorModal = document.getElementById('demo-selector-modal');
        
        // 动态生成案例列表
        this.renderDemoCases();
    }
    
    /**
     * 渲染 Demo 案例列表
     */
    renderDemoCases() {
        const casesList = this.selectorModal?.querySelector('.demo-cases-list');
        if (!casesList) return;
        
        const casesHTML = DemoCases.getAll().map(demoCase => `
            <div class="demo-case-item" data-demo-id="${demoCase.id}" tabindex="0">
                <div class="demo-case-icon">${this.getCaseIcon(demoCase.industry)}</div>
                <div class="demo-case-info">
                    <h4 class="demo-case-name">${demoCase.name}</h4>
                    <p class="demo-case-desc">${demoCase.shortDesc}</p>
                    <div class="demo-case-tags">
                        ${demoCase.tags.map(tag => `<span class="tag">${tag}</span>`).join('')}
                    </div>
                </div>
                <div class="demo-case-arrow">→</div>
            </div>
        `).join('');
        
        casesList.innerHTML = casesHTML;
    }
    
    /**
     * 根据行业获取图标
     */
    getCaseIcon(industry) {
        const iconMap = {
            '工业互联网': '🏭',
            '智慧农业': '🌱',
            '智慧园区': '🏢',
            '智慧城市': '🏙️',
            '智慧交通': '🚦'
        };
        return iconMap[industry] || '📦';
    }
    
    /**
     * 绑定事件
     */
    bindEvents() {
        // 快速体验按钮点击
        const quickDemoBtn = document.getElementById('quick-demo-btn');
        quickDemoBtn?.addEventListener('click', () => {
            this.showSelector();
        });
        
        // 案例选择
        this.selectorModal?.addEventListener('click', (e) => {
            const caseItem = e.target.closest('.demo-case-item');
            if (caseItem) {
                const demoId = caseItem.dataset.demoId;
                this.selectDemo(demoId);
            }
        });
        
        // 键盘选择案例
        this.selectorModal?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                const caseItem = e.target.closest('.demo-case-item');
                if (caseItem) {
                    e.preventDefault();
                    const demoId = caseItem.dataset.demoId;
                    this.selectDemo(demoId);
                }
            }
        });
        
        // 关闭按钮
        const closeBtn = document.getElementById('close-selector-btn');
        closeBtn?.addEventListener('click', () => {
            this.hideSelector();
        });
        
        // 取消按钮
        const cancelBtn = document.getElementById('cancel-demo-btn');
        cancelBtn?.addEventListener('click', () => {
            this.hideSelector();
        });
        
        // 点击遮罩层关闭
        this.selectorModal?.addEventListener('click', (e) => {
            if (e.target === this.selectorModal) {
                this.hideSelector();
            }
        });
        
        // ESC 键关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isSelectorOpen) {
                this.hideSelector();
            }
        });
    }
    
    /**
     * 显示案例选择器
     */
    showSelector() {
        if (!this.selectorModal) return;
        
        this.selectorModal.style.display = 'flex';
        this.isSelectorOpen = true;
        
        // 记录用户行为
        console.log('[QuickDemo] 用户打开案例选择器');
    }
    
    /**
     * 隐藏案例选择器
     */
    hideSelector() {
        if (!this.selectorModal) return;
        
        this.selectorModal.classList.add('fade-out');
        
        setTimeout(() => {
            this.selectorModal.style.display = 'none';
            this.selectorModal.classList.remove('fade-out');
            this.isSelectorOpen = false;
        }, 300);
    }
    
    /**
     * 选择 Demo 案例
     */
    selectDemo(demoId) {
        const demoCase = DemoCases.getById(demoId);
        if (!demoCase) {
            console.error('[QuickDemo] 未找到案例:', demoId);
            return;
        }
        
        this.selectedDemoId = demoId;
        
        // 记录用户行为
        console.log('[QuickDemo] 用户选择案例:', demoCase.name);
        
        // 关闭选择器
        this.hideSelector();
        
        // 执行自动匹配流程
        setTimeout(() => {
            this.executeAutoMatch(demoCase);
        }, 400); // 等待选择器关闭动画完成
    }
    
    /**
     * 执行自动匹配流程
     */
    async executeAutoMatch(demoCase) {
        if (this.isAutoMatching) {
            console.warn('[QuickDemo] 自动匹配正在进行中');
            return;
        }
        
        this.isAutoMatching = true;
        
        try {
            // 1. 自动填充需求文本
            await this.fillDemandText(demoCase.description);
            
            // 2. 延迟 500ms 后触发匹配
            await this.delay(500);
            
            // 3. 自动触发匹配按钮
            await this.triggerMatch();
            
            // 4. 显示演示提示
            this.showDemoTip(demoCase.name);
            
        } catch (error) {
            console.error('[QuickDemo] 自动匹配失败:', error);
            UI.showToast('演示匹配失败,请稍后重试', 'error');
        } finally {
            this.isAutoMatching = false;
        }
    }
    
    /**
     * 填充需求文本
     */
    async fillDemandText(text) {
        const demandInput = document.getElementById('demand-input');
        const charCount = document.getElementById('demand-char-count');
        
        if (!demandInput) {
            throw new Error('未找到需求输入框');
        }
        
        // XSS 防护: 移除可能的 HTML 标签
        const safeText = text.replace(/<[^>]*>/g, '');
        
        // 清空现有内容
        demandInput.value = '';
        
        // 添加填充动画效果
        demandInput.style.transition = 'all 0.3s ease';
        demandInput.style.boxShadow = '0 0 30px rgba(74, 144, 226, 0.5)';
        demandInput.style.borderColor = 'var(--tech-blue)';
        
        // 逐字填充动画(可选,更流畅的体验)
        const chars = safeText.split('');
        for (let i = 0; i < chars.length; i++) {
            demandInput.value += chars[i];
            
            // 每填充 10 个字符更新一次字符计数
            if (i % 10 === 0) {
                charCount.textContent = demandInput.value.length;
            }
            
            // 控制填充速度(总时长约 200ms)
            if (i % 3 === 0) {
                await this.delay(1);
            }
        }
        
        // 最终更新字符计数
        charCount.textContent = demandInput.value.length;
        
        // 移除高亮效果
        setTimeout(() => {
            demandInput.style.boxShadow = '';
            demandInput.style.borderColor = '';
        }, 500);
        
        console.log('[QuickDemo] 需求文本填充完成,长度:', demandInput.value.length);
    }
    
    /**
     * 触发匹配按钮
     */
    async triggerMatch() {
        const matchBtn = document.getElementById('match-btn');
        
        if (!matchBtn) {
            throw new Error('未找到匹配按钮');
        }
        
        // 模拟点击匹配按钮
        matchBtn.click();
        
        console.log('[QuickDemo] 已触发匹配按钮');
    }
    
    /**
     * 显示演示提示
     */
    showDemoTip(caseName) {
        // 等待匹配结果返回后显示提示
        const checkResult = setInterval(() => {
            const resultContainer = document.getElementById('solution-result');
            
            if (resultContainer && resultContainer.style.display !== 'none') {
                clearInterval(checkResult);
                
                // 在结果顶部添加演示提示
                const tipHTML = `
                    <div class="demo-result-tip">
                        <span class="tip-icon">💡</span>
                        <span class="tip-text">
                            以上为 <strong>${caseName}</strong> 演示结果,您可以输入自己的需求进行匹配
                        </span>
                    </div>
                `;
                
                // 避免重复添加
                const existingTip = resultContainer.querySelector('.demo-result-tip');
                if (!existingTip) {
                    resultContainer.insertAdjacentHTML('afterbegin', tipHTML);
                }
            }
        }, 500);
        
        // 设置超时,避免无限等待
        setTimeout(() => {
            clearInterval(checkResult);
        }, 30000);
    }
    
    /**
     * 延迟工具函数
     */
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

/**
 * 演示提示样式(动态添加到页面)
 */
const demoTipStyles = `
.demo-result-tip {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 20px;
    background: linear-gradient(135deg, 
        rgba(255, 215, 0, 0.15) 0%, 
        rgba(255, 165, 0, 0.15) 100%);
    border: 1px solid rgba(255, 215, 0, 0.3);
    border-radius: 12px;
    margin-bottom: 20px;
    animation: tip-fade-in 0.5s ease;
}

@keyframes tip-fade-in {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
}

.tip-icon {
    font-size: 24px;
}

.tip-text {
    font-size: 15px;
    color: var(--text-secondary);
    line-height: 1.5;
}

.tip-text strong {
    color: #FFD700;
    font-weight: 600;
}
`;

// 动态添加演示提示样式
const styleSheet = document.createElement('style');
styleSheet.textContent = demoTipStyles;
document.head.appendChild(styleSheet);
```

### **1.3.3 集成与初始化设计**

```javascript
/**
 * 主初始化逻辑修改
 * 在现有 script.js 的 init() 函数中添加以下代码
 */

// 修改现有的 init() 函数
function init() {
    // 初始化粒子系统(原有代码)
    const canvas = document.getElementById('particle-canvas');
    if (canvas) {
        new ParticleSystem(canvas);
    }
    
    // 初始化事件监听器(原有代码)
    initEventListeners();
    
    // 加载知识库统计(原有代码)
    KnowledgeUI.loadStats();
    
    // ========== 新增代码 ==========
    // 初始化欢迎引导页管理器
    const welcomeManager = new WelcomeManager();
    
    // 初始化快速体验 Demo 管理器
    // (内部会等待欢迎页关闭后再显示快速体验按钮)
    const quickDemoManager = new QuickDemoManager();
    
    // ========== 新增代码结束 ==========
}

// 将新增类添加到 script.js 文件末尾
```

---

# **2. 接口设计**

## **2.1 总体设计**

本方案采用面向对象的设计模式,通过两个核心管理器类封装欢迎引导页和快速体验 Demo 的所有功能:

- **WelcomeManager**: 管理欢迎引导页的生命周期、动画和用户交互
- **QuickDemoManager**: 管理 Demo 案例选择、自动填充和自动匹配流程

两个管理器通过浏览器事件系统进行通信,实现松耦合集成。

## **2.2 接口清单**

### **2.2.1 WelcomeManager 接口**

| 方法名 | 输入参数 | 输出结果 | 职责说明 |
|--------|---------|---------|---------|
| `init()` | 无 | void | 初始化欢迎引导页,判断是否显示 |
| `shouldShowWelcome()` | 无 | boolean | 判断是否应该显示欢迎引导页 |
| `createWelcomePage()` | 无 | void | 创建欢迎引导页 DOM 结构 |
| `startAnimations()` | 无 | void | 启动所有动画(粒子、数字、卡片) |
| `initParticleSystem()` | 无 | void | 初始化粒子系统 |
| `startNumberAnimation()` | 无 | void | 启动数字递增动画 |
| `startCardAnimation()` | 无 | void | 启动功能卡片入场动画 |
| `bindEvents()` | 无 | void | 绑定按钮和键盘事件 |
| `saveSkipState()` | 无 | void | 保存跳过状态到 localStorage |
| `hideWelcomePage()` | 无 | void | 隐藏欢迎引导页 |
| `destroy()` | 无 | void | 销毁欢迎页管理器,清理资源 |

### **2.2.2 QuickDemoManager 接口**

| 方法名 | 输入参数 | 输出结果 | 职责说明 |
|--------|---------|---------|---------|
| `init()` | 无 | void | 初始化快速体验功能 |
| `createQuickDemoButton()` | 无 | void | 创建快速体验按钮 |
| `createSelectorModal()` | 无 | void | 创建案例选择器模态框 |
| `renderDemoCases()` | 无 | void | 渲染 Demo 案例列表 |
| `getCaseIcon(industry)` | string | string | 根据行业获取图标 emoji |
| `bindEvents()` | 无 | void | 绑定所有交互事件 |
| `showSelector()` | 无 | void | 显示案例选择器 |
| `hideSelector()` | 无 | void | 隐藏案例选择器 |
| `selectDemo(demoId)` | string | void | 选择并执行 Demo 案例 |
| `executeAutoMatch(demoCase)` | Object | Promise<void> | 执行自动匹配流程 |
| `fillDemandText(text)` | string | Promise<void> | 填充需求文本到输入框 |
| `triggerMatch()` | 无 | Promise<void> | 触发匹配按钮点击 |
| `showDemoTip(caseName)` | string | void | 显示演示结果提示 |
| `delay(ms)` | number | Promise<void> | 延迟工具函数 |

### **2.2.3 DemoCases 数据接口**

| 方法名 | 输入参数 | 输出结果 | 职责说明 |
|--------|---------|---------|---------|
| `getAll()` | 无 | Array<Object> | 获取所有 Demo 案例 |
| `getById(id)` | string | Object \| undefined | 根据 ID 获取案例 |
| `getRandom()` | 无 | Object | 获取随机案例 |

### **2.2.4 浏览器事件接口**

| 事件名 | 触发时机 | 事件数据 | 监听者 |
|--------|---------|---------|--------|
| `welcomeClosed` | 欢迎引导页关闭时 | 无 | QuickDemoManager |

---

# **3. 数据模型**

## **3.1 设计目标**

数据模型设计遵循以下原则:
1. **最小化存储**: 仅在 localStorage 存储必要的用户偏好状态
2. **类型安全**: 所有数据结构明确定义字段类型和取值范围
3. **内存管理**: Demo 案例数据定义在 JavaScript 常量中,不占用存储空间
4. **状态隔离**: 欢迎引导状态和快速体验状态相互独立,互不干扰

## **3.2 模型实现**

### **3.2.1 localStorage 数据模型**

```typescript
/**
 * localStorage 存储数据结构
 */

// 存储键名常量
const STORAGE_KEYS = {
    SKIP_WELCOME: 'skipWelcome'
};

// 存储值类型定义
type SkipWelcomeValue = 'true' | 'false';

// localStorage 存储模型
interface LocalStorageModel {
    [STORAGE_KEYS.SKIP_WELCOME]?: SkipWelcomeValue;
}

// 读取示例
function getSkipWelcome(): boolean {
    const value = localStorage.getItem(STORAGE_KEYS.SKIP_WELCOME);
    return value === 'true';
}

// 写入示例
function setSkipWelcome(value: boolean): void {
    localStorage.setItem(
        STORAGE_KEYS.SKIP_WELCOME, 
        value ? 'true' : 'false'
    );
}
```

### **3.2.2 Demo 案例数据模型**

```typescript
/**
 * Demo 案例数据结构
 */
interface DemoCase {
    /** 案例 ID,格式为 demo_1, demo_2, demo_3 */
    id: string;
    
    /** 案例显示名称,长度不超过 20 字符 */
    name: string;
    
    /** 所属行业 */
    industry: IndustryType;
    
    /** 简短描述,用于选择器展示 */
    shortDesc: string;
    
    /** 完整需求描述,长度 100-300 字符 */
    description: string;
    
    /** 技术标签列表 */
    tags: string[];
}

/**
 * 行业类型枚举
 */
type IndustryType = 
    | '制造业'
    | '智慧农业'
    | '智慧园区'
    | '工业互联网'
    | '智慧城市'
    | '智慧交通'
    | '智慧教育'
    | '智慧医疗'
    | '智慧金融'
    | '智慧能源'
    | '智慧文旅';

/**
 * Demo 案例集合
 */
interface DemoCasesModel {
    cases: DemoCase[];
    
    /** 获取所有案例 */
    getAll(): DemoCase[];
    
    /** 根据 ID 获取案例 */
    getById(id: string): DemoCase | undefined;
    
    /** 获取随机案例 */
    getRandom(): DemoCase;
}
```

### **3.2.3 运行时状态数据模型**

```typescript
/**
 * 运行时状态数据结构
 * 存储在 JavaScript 内存中,不持久化
 */

/**
 * WelcomeManager 状态
 */
interface WelcomeManagerState {
    /** 欢迎页 DOM 引用 */
    welcomePage: HTMLElement | null;
    
    /** 粒子系统实例 */
    particleSystem: ParticleSystem | null;
    
    /** 动画帧 ID */
    animationFrameId: number | null;
}

/**
 * QuickDemoManager 状态
 */
interface QuickDemoManagerState {
    /** 案例选择器 DOM 引用 */
    selectorModal: HTMLElement | null;
    
    /** 选择器是否打开 */
    isSelectorOpen: boolean;
    
    /** 自动匹配是否进行中 */
    isAutoMatching: boolean;
    
    /** 当前选中的案例 ID */
    selectedDemoId: string | null;
}

/**
 * 全局状态扩展
 * 扩展现有 State 对象
 */
interface GlobalState {
    currentPage: string;
    loadingStates: LoadingStates;
    knowledgeStats: KnowledgeStats | null;
    resultCache: ResultCache;
    
    // 新增状态
    welcomeState?: WelcomeManagerState;
    quickDemoState?: QuickDemoManagerState;
}
```

### **3.2.4 性能指标数据模型**

```typescript
/**
 * 性能指标数据结构
 * 用于性能监控和优化
 */
interface PerformanceMetrics {
    /** 欢迎页加载时间(ms),要求 <= 1500ms */
    welcomeLoadTime: number;
    
    /** 动画平均帧率(fps),要求 >= 60fps */
    animationFPS: number;
    
    /** 单帧渲染时间(ms),要求 <= 16.67ms */
    renderTime: number;
    
    /** 需求文本填充时间(ms),要求 <= 200ms */
    fillTextTime: number;
    
    /** 自动匹配触发延迟(ms),建议 500ms */
    autoMatchDelay: number;
}

/**
 * 性能指标验证函数
 */
function validateMetrics(metrics: PerformanceMetrics): boolean {
    return (
        metrics.welcomeLoadTime <= 1500 &&
        metrics.animationFPS >= 60 &&
        metrics.renderTime <= 16.67 &&
        metrics.fillTextTime <= 200
    );
}
```

### **3.2.5 用户行为日志模型**

```typescript
/**
 * 用户行为日志数据结构
 * 用于分析和优化用户体验
 */
interface UserActionLog {
    /** 时间戳 */
    timestamp: number;
    
    /** 行为类型 */
    action: 
        | 'welcome_shown'        // 欢迎页显示
        | 'welcome_skipped'      // 跳过欢迎页
        | 'welcome_started'      // 点击立即体验
        | 'selector_opened'      // 案例选择器打开
        | 'selector_closed'      // 案例选择器关闭
        | 'demo_selected'        // 选择 Demo 案例
        | 'auto_match_triggered' // 自动匹配触发
        | 'demo_completed';      // Demo 完成
    
    /** 附加数据 */
    data?: {
        demoId?: string;
        demoName?: string;
        duration?: number;
    };
}

/**
 * 日志记录函数
 */
function logUserAction(
    action: UserActionLog['action'],
    data?: UserActionLog['data']
): void {
    const log: UserActionLog = {
        timestamp: Date.now(),
        action,
        data
    };
    
    console.log('[UserAction]', log);
}
```

---

# **4. 性能优化方案**

## **4.1 首屏加载优化**

### **4.1.1 资源加载策略**

```javascript
/**
 * 延迟加载策略
 * 将非关键资源延迟到欢迎页渲染后加载
 */

// 1. Chart.js 延迟加载
function loadChartJS() {
    if (window.Chart) return Promise.resolve();
    
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
    });
}

// 2. 在欢迎页关闭后再加载图表库
window.addEventListener('welcomeClosed', () => {
    loadChartJS().then(() => {
        console.log('[Performance] Chart.js 加载完成');
    });
});
```

### **4.1.2 DOM 结构优化**

```javascript
/**
 * 虚拟 DOM 策略
 * 对于复杂的动画元素,使用 requestAnimationFrame 逐步渲染
 */

function renderWelcomeContentProgressively() {
    const content = document.querySelector('.welcome-content');
    const children = Array.from(content.children);
    
    let index = 0;
    
    function renderNext() {
        if (index >= children.length) return;
        
        const child = children[index];
        child.style.opacity = '1';
        child.style.transform = 'translateY(0)';
        
        index++;
        requestAnimationFrame(renderNext);
    }
    
    renderNext();
}
```

## **4.2 动画性能优化**

### **4.2.1 GPU 加速**

```css
/* 强制使用 GPU 加速 */
.welcome-overlay,
.welcome-content,
.feature-card,
.glow-circle,
.btn-glow {
    will-change: transform, opacity;
    transform: translateZ(0);
    backface-visibility: hidden;
}

/* 动画结束后移除 will-change */
.feature-card.animation-ended {
    will-change: auto;
}
```

### **4.2.2 requestAnimationFrame 优化**

```javascript
/**
 * 优化的数字递增动画
 * 使用 requestAnimationFrame 确保流畅
 */
function animateNumber(
    element: HTMLElement,
    target: number,
    duration: number = 2000
): void {
    const startTime = performance.now();
    let animationId: number;
    
    function update(currentTime: number) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        
        // 缓动函数
        const easeOutQuart = 1 - Math.pow(1 - progress, 4);
        const currentValue = Math.floor(easeOutQuart * target);
        
        element.textContent = String(currentValue);
        
        if (progress < 1) {
            animationId = requestAnimationFrame(update);
        }
    }
    
    animationId = requestAnimationFrame(update);
    
    // 返回取消函数
    return () => cancelAnimationFrame(animationId);
}
```

### **4.2.3 粒子系统优化**

```javascript
/**
 * 优化的粒子系统参数
 * 减少粒子数量和连接距离,降低计算开销
 */
const welcomeParticleConfig = {
    particleCount: 60,        // 比主系统少(主系统 80)
    connectionDistance: 120,  // 比主系统短(主系统 150)
    particleSpeed: 0.3,       // 比主系统慢(主系统 0.5)
    particleColor: 'rgba(100, 150, 255, 0.5)'
};

/**
 * 空间分割优化
 * 使用网格分割减少粒子距离计算次数
 */
class OptimizedParticleSystem extends ParticleSystem {
    constructor(canvas, config) {
        super(canvas, config);
        this.gridSize = config.connectionDistance;
        this.grid = new Map();
    }
    
    // 使用网格加速粒子查找
    updateGrid() {
        this.grid.clear();
        this.particles.forEach(p => {
            const gridX = Math.floor(p.x / this.gridSize);
            const gridY = Math.floor(p.y / this.gridSize);
            const key = `${gridX},${gridY}`;
            
            if (!this.grid.has(key)) {
                this.grid.set(key, []);
            }
            this.grid.get(key).push(p);
        });
    }
}
```

## **4.3 代码分离策略**

### **4.3.1 模块化分离**

```javascript
/**
 * 代码组织结构建议
 * 
 * frontend/
 * ├── index.html          # 主页面
 * ├── style.css           # 主样式
 * ├── script.js           # 主逻辑
 * ├── welcome/            # 欢迎引导页模块(新增)
 * │   ├── welcome.html    # 欢迎页 HTML 片段
 * │   ├── welcome.css     # 欢迎页样式
 * │   └── welcome.js      # 欢迎页逻辑
 * └── demo/               # 快速体验模块(新增)
 *     ├── demo.css        # Demo 样式
 *     └── demo.js         # Demo 逻辑
 */

/**
 * 按需加载模块
 */
async function loadWelcomeModule() {
    const [html, css, js] = await Promise.all([
        fetch('/frontend/welcome/welcome.html').then(r => r.text()),
        fetch('/frontend/welcome/welcome.css').then(r => r.text()),
        import('/frontend/welcome/welcome.js')
    ]);
    
    // 注入样式
    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
    
    // 初始化模块
    js.initWelcome(html);
}
```

## **4.4 性能监控**

```javascript
/**
 * 性能监控工具
 */
class PerformanceMonitor {
    constructor() {
        this.metrics = {};
    }
    
    /**
     * 记录性能指标
     */
    mark(name: string): void {
        this.metrics[name] = performance.now();
    }
    
    /**
     * 测量两个标记之间的时间
     */
    measure(name: string, startMark: string, endMark: string): number {
        const duration = this.metrics[endMark] - this.metrics[startMark];
        
        console.log(`[Performance] ${name}: ${duration.toFixed(2)}ms`);
        
        return duration;
    }
    
    /**
     * 报告性能指标
     */
    report(): void {
        const welcomeLoadTime = this.measure(
            '欢迎页加载时间',
            'welcome-start',
            'welcome-end'
        );
        
        if (welcomeLoadTime > 1500) {
            console.warn('[Performance] 欢迎页加载时间超标:', welcomeLoadTime);
        }
    }
}

// 使用示例
const perfMonitor = new PerformanceMonitor();

perfMonitor.mark('welcome-start');
// ... 欢迎页渲染 ...
perfMonitor.mark('welcome-end');
perfMonitor.report();
```

---

# **5. 测试方案**

## **5.1 单元测试设计**

```javascript
/**
 * 欢迎引导页单元测试
 */
describe('WelcomeManager', () => {
    beforeEach(() => {
        localStorage.clear();
    });
    
    test('首次访问应显示欢迎页', () => {
        const manager = new WelcomeManager();
        expect(manager.shouldShowWelcome()).toBe(true);
    });
    
    test('localStorage 为 true 时应跳过欢迎页', () => {
        localStorage.setItem('skipWelcome', 'true');
        const manager = new WelcomeManager();
        expect(manager.shouldShowWelcome()).toBe(false);
    });
    
    test('点击跳过应保存状态', () => {
        const manager = new WelcomeManager();
        manager.saveSkipState();
        expect(localStorage.getItem('skipWelcome')).toBe('true');
    });
});

/**
 * 快速体验 Demo 单元测试
 */
describe('QuickDemoManager', () => {
    test('应正确获取 Demo 案例', () => {
        const cases = DemoCases.getAll();
        expect(cases.length).toBeGreaterThanOrEqual(3);
    });
    
    test('应正确根据 ID 获取案例', () => {
        const demo = DemoCases.getById('demo_1');
        expect(demo).toBeDefined();
        expect(demo.name).toBe('制造业预测性维护');
    });
    
    test('需求描述长度应在有效范围', () => {
        const cases = DemoCases.getAll();
        cases.forEach(c => {
            expect(c.description.length).toBeGreaterThanOrEqual(100);
            expect(c.description.length).toBeLessThanOrEqual(500);
        });
    });
});
```

## **5.2 集成测试设计**

```javascript
/**
 * 端到端测试
 */
describe('欢迎引导与快速体验集成', () => {
    test('完整流程:欢迎页 -> 快速体验 -> 自动匹配', async () => {
        // 1. 首次访问显示欢迎页
        const welcomeManager = new WelcomeManager();
        expect(document.getElementById('welcome-page')).not.toBeNull();
        
        // 2. 点击跳过引导
        const skipBtn = document.getElementById('skip-welcome-btn');
        skipBtn.click();
        
        await delay(600);
        expect(document.getElementById('welcome-page')).toBeNull();
        expect(localStorage.getItem('skipWelcome')).toBe('true');
        
        // 3. 快速体验按钮应显示
        const quickDemoBtn = document.getElementById('quick-demo-btn');
        expect(quickDemoBtn).not.toBeNull();
        
        // 4. 点击快速体验,显示选择器
        quickDemoBtn.click();
        await delay(400);
        expect(document.getElementById('demo-selector-modal').style.display).not.toBe('none');
        
        // 5. 选择案例,自动填充
        const caseItem = document.querySelector('[data-demo-id="demo_1"]');
        caseItem.click();
        await delay(1000);
        
        const demandInput = document.getElementById('demand-input');
        expect(demandInput.value.length).toBeGreaterThan(100);
    });
});
```

---

# **6. 部署方案**

## **6.1 文件修改清单**

| 文件路径 | 修改类型 | 修改说明 |
|---------|---------|---------|
| `frontend/index.html` | 修改 | 在 `<body>` 开头插入欢迎页 HTML 片段 |
| `frontend/style.css` | 扩展 | 在文件末尾追加欢迎页和快速体验样式 |
| `frontend/script.js` | 扩展 | 在文件末尾追加 `WelcomeManager`、`QuickDemoManager` 类和 `DemoCases` 数据 |

## **6.2 兼容性检查清单**

- [ ] 现有粒子系统不受影响
- [ ] 现有 API 调用不受影响
- [ ] 现有 UI 组件不受影响
- [ ] 响应式布局正常工作
- [ ] localStorage 状态不影响其他功能
- [ ] 键盘导航和无障碍访问正常

## **6.3 性能验收标准**

| 性能指标 | 目标值 | 验收方法 |
|---------|--------|---------|
| 欢迎页加载时间 | ≤ 1.5s | Chrome DevTools Performance |
| 动画帧率 | ≥ 60fps | Chrome DevTools Performance |
| 数字递增动画流畅度 | 无卡顿 | 视觉检查 |
| 需求文本填充时间 | ≤ 200ms | console.time() |
| 自动匹配触发延迟 | 500ms | console.time() |
| localStorage 读写时间 | ≤ 10ms | console.time() |

---

**文档版本**: v1.0  
**创建时间**: 2025-05-24  
**作者**: 华为云码道(CodeArts)代码智能体  
**状态**: 待评审
