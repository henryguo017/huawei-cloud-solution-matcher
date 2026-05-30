// [版本] 20260531k — 修复竞品分析/方案匹配结果容器被_resetView销毁导致空白的问题
const Config = {
    API_BASE_URL: '/api',
    ANIMATION: {
        PARTICLE_COUNT: 80,
        CONNECTION_DISTANCE: 150,
        PARTICLE_SPEED: 0.5
    },
    INDUSTRIES: [
        '智慧农业', '工业互联网', '智慧园区', '智慧城市', '智慧医疗',
        '智慧金融', '智慧能源', '智慧交通', '智慧教育', '智慧文旅'
    ],
    COMPETITORS: [
        // 国内主流云服务商
        '阿里云', '腾讯云', '字节跳动火山引擎', '天翼云', '移动云', '联通云',
        // 国际主流云服务商
        'AWS', '微软Azure', 'Google Cloud', 'Oracle Cloud',
        // 行业解决方案提供商
        '西门子', '施耐德电气'
    ]
};

const AuthManager = {
    STORAGE_KEY: 'hwcloud_auth',

    // 初始化：从 localStorage 恢复登录态
    async init() {
        const saved = localStorage.getItem(this.STORAGE_KEY);
        if (saved) {
            try {
                const data = JSON.parse(saved);
                if (data.token && data.user && data.expiresAt && Date.now() < data.expiresAt) {
                    State.authToken = data.token;
                    State.user = data.user;
                    // 先更新 UI 展示用户名（乐观渲染），然后后台验证
                    this._updateUI();
                    // await 服务端验证，确保 Token 确实有效
                    await this._verifyToken();
                } else {
                    this._clearAuth();
                }
            } catch (e) {
                this._clearAuth();
            }
        }
    },

    // 获取验证码
    async loadCaptcha(isLogin = true) {
        try {
            const resp = await fetch(`${Config.API_BASE_URL}/auth/captcha`);
            const data = await resp.json();
            const imgId = isLogin ? 'login-captcha-img' : 'register-captcha-img';
            const img = document.getElementById(imgId);
            if (img && data.captcha_image) {
                img.src = data.captcha_image;
                img.dataset.captchaKey = data.captcha_key;
            }
        } catch (e) {
            console.warn('获取验证码失败:', e);
        }
    },

    // 登录
    async login(username, password, captchaKey, captchaValue) {
        this._setSubmitLoading('login', true);
        this._hideError('login');
        try {
            const resp = await fetch(`${Config.API_BASE_URL}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username,
                    password,
                    captcha_key: captchaKey,
                    captcha_value: captchaValue
                })
            });
            const data = await resp.json();
            if (!resp.ok) {
                this._showError('login', data.detail || '登录失败');
                this.loadCaptcha(true);
                return false;
            }
            // 先清除旧认证状态，再保存新的（防止残留数据）
            this._clearAuth();
            this._saveAuth(data.access_token, data.user, data.expires_in);
            this._closeModal();
            this._updateUI();
            // 清空上一账号残留的页面数据
            this._resetView();
            return true;
        } catch (e) {
            this._showError('login', '网络错误，请稍后重试');
            return false;
        } finally {
            this._setSubmitLoading('login', false);
        }
    },

    // 注册
    async register(username, email, password, captchaKey, captchaValue) {
        this._setSubmitLoading('register', true);
        this._hideError('register');
        try {
            const body = { username, password, captcha_key: captchaKey, captcha_value: captchaValue };
            if (email) body.email = email;
            const resp = await fetch(`${Config.API_BASE_URL}/auth/register`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await resp.json();
            if (!resp.ok) {
                this._showError('register', data.detail || '注册失败');
                this.loadCaptcha(false);
                return false;
            }
            // 注册成功，切换到登录
            this._showError('login', '注册成功！请登录', true);
            this._switchTab('login');
            document.getElementById('login-username').value = username;
            document.getElementById('login-password').value = '';
            document.getElementById('login-captcha').value = '';
            this.loadCaptcha(true);
            return true;
        } catch (e) {
            this._showError('register', '网络错误，请稍后重试');
            return false;
        } finally {
            this._setSubmitLoading('register', false);
        }
    },

    // 退出
    async logout() {
        const token = this.getToken();
        // 先立即清除本地 UI 状态，让用户立即感受到退出
        this._clearAuth();
        this._updateUI();
        this._resetView();
        if (token) {
            // 等待服务器端 token_version 递增，超过 2 秒放弃
            try {
                await Promise.race([
                    fetch('/api/auth/logout', {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${token}` }
                    }),
                    new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 2000))
                ]);
            } catch (e) { /* 超时也不影响 */ }
        }
    },

    // 获取 Token（供其他模块调用）
    getToken() {
        return State.authToken;
    },

    // 检查是否登录
    isLoggedIn() {
        return !!State.authToken && !!State.user;
    },

    // === 内部方法 ===

    _cacheBustReload() {
        // 添加时间戳参数强制浏览器绕过 HTTP 缓存，重新请求服务器
        const sep = window.location.href.includes('?') ? '&' : '?';
        window.location.replace(window.location.href + sep + '_t=' + Date.now());
    },

    _saveAuth(token, user, expiresIn) {
        State.authToken = token;
        State.user = user;
        const expiresAt = Date.now() + expiresIn * 1000;
        const payload = JSON.stringify({ token, user, expiresAt });
        localStorage.setItem(this.STORAGE_KEY, payload);
        // 立即验证写入是否成功
        const saved = localStorage.getItem(this.STORAGE_KEY);
        if (!saved || saved !== payload) {
            console.error('AuthManager: localStorage 写入验证失败，重试一次');
            localStorage.setItem(this.STORAGE_KEY, payload);
        }
    },

    _clearAuth() {
        State.authToken = null;
        State.user = null;
        localStorage.removeItem(this.STORAGE_KEY);
    },

    _updateUI() {
        const loginBtn = document.getElementById('nav-login-btn');
        const userMenu = document.getElementById('nav-user-menu');
        const userName = document.getElementById('nav-user-name');
        if (State.user) {
            if (loginBtn) loginBtn.style.display = 'none';
            if (userMenu) userMenu.style.display = '';
            if (userName) userName.textContent = State.user.username;
        } else {
            if (loginBtn) loginBtn.style.display = '';
            if (userMenu) userMenu.style.display = 'none';
        }
    },

    _resetView() {
        // 切换账号后清除上一账号的所有页面数据，避免残留显示
        // 注意：不要对包含子结构的结果容器直接 innerHTML=''，否则会销毁子元素（如competitor-content）
        const ids = [
            'history-list', 'history-compare-section', 'history-compare-panel',
            'history-count', 'history-pagination',
            'follow-up-history', 'competitor-follow-up-history',
            'favorites-list'
        ];
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                    el.value = '';
                } else {
                    el.innerHTML = '';
                }
            }
        });
        // 结果容器单独处理：隐藏 + 清空内容子元素，不销毁结构
        [
            { container: 'solution-result', content: 'solution-content' },
            { container: 'competitor-result', content: 'competitor-content' }
        ].forEach(item => {
            const container = document.getElementById(item.container);
            const content = document.getElementById(item.content);
            if (container) container.style.display = 'none';
            if (content) content.innerHTML = '';
        });
        // 清除资料页统计数据
        ['stat-favorites', 'stat-history', 'profile-username', 'profile-avatar',
         'profile-role', 'info-username', 'info-email'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = '';
        });
        // 重置匹配表单（如果有）
        const matchForm = document.getElementById('match-demand');
        if (matchForm) matchForm.value = '';
        const competitorForm = document.getElementById('competitor-demand');
        if (competitorForm) competitorForm.value = '';
        // 关闭可能打开的详情弹窗
        const detailModal = document.getElementById('history-detail-modal');
        if (detailModal) detailModal.style.display = 'none';
    },

    async _verifyToken() {
        try {
            const resp = await fetch(`${Config.API_BASE_URL}/auth/me`, {
                headers: { 'Authorization': `Bearer ${State.authToken}` }
            });
            if (!resp.ok) {
                this._clearAuth();
                this._updateUI();
            }
        } catch (e) {
            // 网络错误等异常情况，静默清除认证状态
            this._clearAuth();
            this._updateUI();
        }
    },

    _openModal() {
        // 清除之前的延迟定时器
        if (this._autoFillGuardTimer) clearTimeout(this._autoFillGuardTimer);
        if (this._autoFillCheckTimer2) clearTimeout(this._autoFillCheckTimer2);

        const overlay = document.getElementById('auth-modal-overlay');
        if (overlay) overlay.style.display = '';
        this._switchTab('login');
        this.loadCaptcha(true);

        // 立即清空（处理表单残留）
        const userField = document.getElementById('login-username');
        const pwdField = document.getElementById('login-password');
        const captchaField = document.getElementById('login-captcha');
        userField.value = '';
        pwdField.value = '';
        captchaField.value = '';
        this._hideError('login');
        this._hideError('register');
        // 隐藏自动填充提示
        const hint = document.getElementById('login-auto-fill-hint');
        if (hint) hint.style.display = 'none';

        // 延迟二次清空：浏览器自动填充在 JS 清空后 ~50-200ms 触发
        // 必须覆盖掉，否则 Edge 会把旧账号填回去
        this._autoFillGuardTimer = setTimeout(() => {
            userField.value = '';
            pwdField.value = '';
        }, 250);
        // 250ms 后再次检测是否被浏览器填回
        this._autoFillCheckTimer2 = setTimeout(() => {
            const updatedVal = userField.value.trim();
            if (updatedVal) {
                const hint = document.getElementById('login-auto-fill-hint');
                const hintUser = document.getElementById('login-hint-username');
                if (hint && hintUser) {
                    hintUser.textContent = updatedVal;
                    hint.style.display = '';
                }
            }
        }, 500);
    },

    _closeModal() {
        // 清除延迟定时器
        if (this._autoFillGuardTimer) { clearTimeout(this._autoFillGuardTimer); this._autoFillGuardTimer = null; }
        if (this._autoFillCheckTimer2) { clearTimeout(this._autoFillCheckTimer2); this._autoFillCheckTimer2 = null; }

        const overlay = document.getElementById('auth-modal-overlay');
        if (overlay) overlay.style.display = 'none';
        document.getElementById('register-form').reset();
        document.getElementById('login-form').reset();
        this._hideError('login');
        this._hideError('register');
    },

    _switchTab(tab) {
        const loginForm = document.getElementById('login-form');
        const registerForm = document.getElementById('register-form');
        const switchText = document.getElementById('auth-switch-text');
        const switchBtn = document.getElementById('auth-switch-btn');
        const tabs = document.querySelectorAll('.auth-tab');
        if (tab === 'login') {
            loginForm.style.display = '';
            registerForm.style.display = 'none';
            switchText.textContent = '还没有账号？';
            switchBtn.textContent = '立即注册';
            tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === 'login'));
            this.loadCaptcha(true);
        } else {
            loginForm.style.display = 'none';
            registerForm.style.display = '';
            switchText.textContent = '已有账号？';
            switchBtn.textContent = '立即登录';
            tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === 'register'));
            this.loadCaptcha(false);
        }
    },

    _showError(type, msg, isSuccess) {
        const el = document.getElementById(`${type}-error`);
        if (!el) return;
        el.textContent = msg;
        el.classList.toggle('success', !!isSuccess);
        el.style.display = '';
    },

    _hideError(type) {
        const el = document.getElementById(`${type}-error`);
        if (el) { el.style.display = 'none'; el.classList.remove('success'); }
    },

    _setSubmitLoading(type, loading) {
        const btn = document.getElementById(`${type}-submit-btn`);
        if (!btn) return;
        const textSpan = btn.querySelector('.btn-text');
        const spinnerSpan = btn.querySelector('.btn-spinner');
        btn.disabled = loading;
        if (textSpan) textSpan.style.display = loading ? 'none' : '';
        if (spinnerSpan) spinnerSpan.style.display = loading ? '' : 'none';
    }
};

const SettingsManager = {
    STORAGE_KEY: 'hwcloud_settings',

    load() {
        try {
            const saved = localStorage.getItem(this.STORAGE_KEY);
            if (saved) {
                const parsed = JSON.parse(saved);
                State.settings = { ...State.settings, ...parsed };
            }
        } catch (e) {
            console.warn('加载设置失败:', e);
        }
        this.applyAll();
    },

    save() {
        try {
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(State.settings));
        } catch (e) {
            console.warn('保存设置失败:', e);
        }
    },

    applyAll() {
        // 粒子背景
        const canvas = document.getElementById('particle-canvas');
        if (canvas) {
            canvas.style.display = State.settings.particles ? '' : 'none';
        }

        // 动画
        if (!State.settings.animations) {
            document.body.style.setProperty('--transition', '0s');
        } else {
            document.body.style.setProperty('--transition', '0.3s ease');
        }

        // 页面过渡动画
        if (!State.settings.animations) {
            document.documentElement.classList.add('page-instant');
        } else {
            document.documentElement.classList.remove('page-instant');
        }
    },

    showSavedToast() {
        const toast = document.createElement('div');
        toast.className = 'settings-saved-toast';
        toast.textContent = '✅ 设置已保存';
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2800);
    },

    init() {
        this.load();

        // 绑定设置页控件
        const animationToggle = document.querySelector('#setting-animation-toggle input');
        const skeletonToggle = document.querySelector('#setting-skeleton-toggle input');
        const particleToggle = document.querySelector('#setting-particle-toggle input');
        const pageSizeSelect = document.getElementById('setting-page-size');
        const autoSaveToggle = document.querySelector('#setting-autosave-toggle input');
        const welcomeToggle = document.querySelector('#setting-welcome-toggle input');

        if (animationToggle) {
            animationToggle.checked = State.settings.animations;
            animationToggle.addEventListener('change', () => {
                State.settings.animations = animationToggle.checked;
            });
        }
        if (skeletonToggle) {
            skeletonToggle.checked = State.settings.skeletons;
            skeletonToggle.addEventListener('change', () => {
                State.settings.skeletons = skeletonToggle.checked;
            });
        }
        if (particleToggle) {
            particleToggle.checked = State.settings.particles;
            particleToggle.addEventListener('change', () => {
                State.settings.particles = particleToggle.checked;
                this.applyAll();
            });
        }
        if (pageSizeSelect) {
            pageSizeSelect.value = String(State.settings.pageSize);
            pageSizeSelect.addEventListener('change', () => {
                State.settings.pageSize = parseInt(pageSizeSelect.value) || 20;
                State.pagination.pageSize = State.settings.pageSize;
            });
        }
        if (autoSaveToggle) {
            autoSaveToggle.checked = State.settings.autoSave;
            autoSaveToggle.addEventListener('change', () => {
                State.settings.autoSave = autoSaveToggle.checked;
            });
        }
        if (welcomeToggle) {
            welcomeToggle.checked = State.settings.showWelcome;
            welcomeToggle.addEventListener('change', () => {
                State.settings.showWelcome = welcomeToggle.checked;
            });
        }

        // 保存按钮
        document.getElementById('settings-save-btn')?.addEventListener('click', () => {
            this.save();
            this.applyAll();
            this.showSavedToast();
        });

        // 重置按钮
        document.getElementById('settings-reset-btn')?.addEventListener('click', () => {
            State.settings = {
                animations: true,
                skeletons: true,
                particles: true,
                pageSize: 20,
                autoSave: true,
                showWelcome: true
            };
            this.applyAll();
            // 更新 UI
            if (animationToggle) animationToggle.checked = true;
            if (skeletonToggle) skeletonToggle.checked = true;
            if (particleToggle) particleToggle.checked = true;
            if (pageSizeSelect) pageSizeSelect.value = '20';
            if (autoSaveToggle) autoSaveToggle.checked = true;
            if (welcomeToggle) welcomeToggle.checked = true;
            this.save();
            this.showSavedToast();
        });

        // API 健康检查更新系统信息
        this.updateSystemInfo();
    },

    async updateSystemInfo() {
        try {
            const resp = await fetch(`${Config.API_BASE_URL}/health`);
            const data = await resp.json();
            const versionEl = document.getElementById('settings-version');
            const updateEl = document.getElementById('settings-last-update');
            const apiStatus = document.getElementById('settings-api-status');
            const apiIndicator = document.getElementById('settings-api-indicator');

            if (versionEl) versionEl.textContent = data.version || 'v1.0.0';
            if (updateEl) updateEl.textContent = `API版本: ${data.version || 'v1.0.0'}`;
            if (apiStatus) apiStatus.textContent = data.status === 'healthy' ? '服务运行正常' : '服务异常';
            if (apiIndicator) {
                if (data.status === 'healthy') {
                    apiIndicator.textContent = '● 在线';
                    apiIndicator.style.color = 'var(--success)';
                } else {
                    apiIndicator.textContent = '● 异常';
                    apiIndicator.style.color = 'var(--error)';
                }
            }
        } catch (e) {
            const apiStatus = document.getElementById('settings-api-status');
            const apiIndicator = document.getElementById('settings-api-indicator');
            if (apiStatus) apiStatus.textContent = '无法连接';
            if (apiIndicator) {
                apiIndicator.textContent = '● 离线';
                apiIndicator.style.color = 'var(--error)';
            }
        }
    }
};

// Chart.js 全局默认配置（确保所有图表字体统一）
if (typeof Chart !== 'undefined') {
    Chart.defaults.color = 'rgba(255, 255, 255, 0.85)';
    Chart.defaults.font = {
        family: "'Inter', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        size: 14,
        weight: '500'
    };
    Chart.defaults.scale.grid.color = 'rgba(255, 255, 255, 0.08)';
}

const State = {
    currentPage: 'solution',
    loadingStates: {
        match: false,
        analyze: false,
        rebuild: false,
        clear: false
    },
    knowledgeStats: null,
    resultCache: {},
    abortControllers: {
        match: null,
        analyze: null
    },
    settings: {
        animations: true,
        skeletons: true,
        particles: true,
        pageSize: 20,
        autoSave: true,
        showWelcome: true
    },
    pagination: {
        currentPage: 1,
        pageSize: 20,
        totalItems: 0,
        totalPages: 0
    },
    globalError: null,
    retryHandler: null,
    user: null,           // 当前登录用户 {id, username, email, role}
    authToken: null,      // JWT access_token
    isQuickDemo: false    // 快速体验标记，绕过登录检查
};

class ParticleSystem {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.particles = [];
        this.animationId = null;
        this.init();
    }

    init() {
        this.resize();
        window.addEventListener('resize', () => this.resize());

        for (let i = 0; i < Config.ANIMATION.PARTICLE_COUNT; i++) {
            this.particles.push({
                x: Math.random() * this.canvas.width,
                y: Math.random() * this.canvas.height,
                vx: (Math.random() - 0.5) * Config.ANIMATION.PARTICLE_SPEED,
                vy: (Math.random() - 0.5) * Config.ANIMATION.PARTICLE_SPEED,
                radius: Math.random() * 2 + 1
            });
        }

        this.animate();
    }

    resize() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
    }

    update() {
        this.particles.forEach(p => {
            p.x += p.vx;
            p.y += p.vy;

            if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
            if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;
        });
    }

    draw() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        this.particles.forEach((p1, i) => {
            this.particles.slice(i + 1).forEach(p2 => {
                const dist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
                if (dist < Config.ANIMATION.CONNECTION_DISTANCE) {
                    this.ctx.beginPath();
                    this.ctx.strokeStyle = `rgba(100, 150, 255, ${1 - dist / Config.ANIMATION.CONNECTION_DISTANCE})`;
                    this.ctx.lineWidth = 0.5;
                    this.ctx.moveTo(p1.x, p1.y);
                    this.ctx.lineTo(p2.x, p2.y);
                    this.ctx.stroke();
                }
            });
        });

        this.particles.forEach(p => {
            this.ctx.beginPath();
            this.ctx.fillStyle = 'rgba(100, 150, 255, 0.6)';
            this.ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
            this.ctx.fill();
        });
    }

    animate() {
        this.update();
        this.draw();
        this.animationId = requestAnimationFrame(() => this.animate());
    }

    destroy() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
        }
    }
}

const ErrorHandler = {
    showBoundary(title, message, detail) {
        const overlay = document.getElementById('global-error-boundary');
        if (!overlay) return;

        document.getElementById('error-boundary-title').textContent = title || '系统遇到了一点问题';
        document.getElementById('error-boundary-message').textContent = message || '请尝试刷新页面或稍后再试';

        const detailEl = document.getElementById('error-boundary-detail');
        if (detail) {
            detailEl.textContent = detail;
            detailEl.style.display = 'block';
        } else {
            detailEl.style.display = 'none';
        }

        overlay.style.display = 'flex';
    },

    hideBoundary() {
        const overlay = document.getElementById('global-error-boundary');
        if (overlay) overlay.style.display = 'none';
    },

    showInline(message, retryHandler) {
        const el = document.getElementById('global-inline-error');
        const textEl = document.getElementById('global-error-text');
        const retryBtn = document.getElementById('global-error-retry');
        if (!el || !textEl) return;

        textEl.textContent = message;
        State.globalError = message;
        State.retryHandler = retryHandler || null;

        if (retryBtn) {
            retryBtn.style.display = retryHandler ? '' : 'none';
        }

        el.style.display = 'flex';
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    },

    hideInline() {
        const el = document.getElementById('global-inline-error');
        if (el) el.style.display = 'none';
        State.globalError = null;
        State.retryHandler = null;
    },

    wrap(fn, fallbackMsg) {
        return async function(...args) {
            try {
                return await fn.apply(this, args);
            } catch (error) {
                console.error(fallbackMsg, error);
                ErrorHandler.showInline(fallbackMsg + ': ' + error.message, () => {
                    ErrorHandler.wrap(fn, fallbackMsg).apply(this, args);
                });
                throw error;
            }
        };
    },

    init() {
        document.getElementById('error-boundary-close')?.addEventListener('click', () => {
            this.hideBoundary();
        });

        document.getElementById('global-error-retry')?.addEventListener('click', () => {
            if (State.retryHandler) {
                this.hideInline();
                State.retryHandler();
            }
        });

        document.getElementById('global-error-close')?.addEventListener('click', () => {
            this.hideInline();
        });

        // 全局 window.onerror 捕获 —— 增强调试信息，方便定位问题来源
        window.addEventListener('error', (event) => {
            if (event.target === window || event.target === document) {
                var errMsg = event.error ? event.error.message : event.message;
                var errStack = event.error ? (event.error.stack || '').substring(0, 500) : '';
                var errSource = '未知';
                if (errStack) {
                    // 提取出错文件和行号
                    var stackLines = errStack.split('\n');
                    if (stackLines.length > 0) errSource = stackLines[0].trim();
                }
                console.error('=== 未捕获错误 ===');
                console.error('消息:', errMsg);
                console.error('来源:', errSource);
                console.error('堆栈:', errStack);
                this.showBoundary(
                    '系统异常', 
                    '发生了未预期的错误：' + (errMsg || '未知错误'),
                    '错误位置：' + errSource + '\n\n请按 Ctrl+Shift+R 强制刷新浏览器（清除缓存）'
                );
            }
        });
    }
};

const PaginationUI = {
    render(container, paginationId, infoId) {
        const { currentPage, pageSize, totalItems, totalPages } = State.pagination;

        if (totalPages <= 1) {
            const pagContainer = document.getElementById(paginationId);
            if (pagContainer) pagContainer.style.display = 'none';
            return;
        }

        // 信息栏
        const infoEl = document.getElementById(infoId);
        if (infoEl) {
            const start = (currentPage - 1) * pageSize + 1;
            const end = Math.min(currentPage * pageSize, totalItems);
            infoEl.textContent = `第 ${start}-${end} 条，共 ${totalItems} 条`;
        }

        // 分页按钮
        const btnsContainer = document.getElementById(paginationId);
        const pagContainer = document.getElementById(container);
        if (!btnsContainer || !pagContainer) return;

        pagContainer.style.display = 'flex';

        // 生成页码
        let pages = [];
        const maxVisible = 5;

        if (totalPages <= maxVisible + 2) {
            for (let i = 1; i <= totalPages; i++) pages.push(i);
        } else {
            pages.push(1);
            if (currentPage > 3) pages.push('...');

            let start = Math.max(2, currentPage - 1);
            let end = Math.min(totalPages - 1, currentPage + 1);

            if (currentPage <= 3) {
                start = 2;
                end = Math.min(maxVisible, totalPages - 1);
            }
            if (currentPage >= totalPages - 2) {
                start = Math.max(2, totalPages - maxVisible + 1);
                end = totalPages - 1;
            }

            for (let i = start; i <= end; i++) pages.push(i);

            if (currentPage < totalPages - 2) pages.push('...');
            pages.push(totalPages);
        }

        let html = '';

        // 上一页
        html += `<button class="pagination-btn" ${currentPage <= 1 ? 'disabled' : ''} data-page="${currentPage - 1}">◀</button>`;

        // 页码
        pages.forEach(p => {
            if (p === '...') {
                html += '<span class="pagination-ellipsis">...</span>';
            } else {
                html += `<button class="pagination-btn ${p === currentPage ? 'active' : ''}" data-page="${p}">${p}</button>`;
            }
        });

        // 下一页
        html += `<button class="pagination-btn" ${currentPage >= totalPages ? 'disabled' : ''} data-page="${currentPage + 1}">▶</button>`;

        // 每页条数选择器
        html += `<select class="pagination-page-size-select" id="pagination-page-size">
            <option value="10" ${pageSize === 10 ? 'selected' : ''}>10条/页</option>
            <option value="20" ${pageSize === 20 ? 'selected' : ''}>20条/页</option>
            <option value="50" ${pageSize === 50 ? 'selected' : ''}>50条/页</option>
        </select>`;

        btnsContainer.innerHTML = html;

        // 绑定事件
        btnsContainer.querySelectorAll('.pagination-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.disabled) return;
                const page = parseInt(btn.dataset.page);
                if (page > 0 && page <= totalPages) {
                    this.goToPage(page);
                }
            });
        });

        // 每页条数
        const pageSizeSelect = document.getElementById('pagination-page-size');
        if (pageSizeSelect) {
            pageSizeSelect.addEventListener('change', () => {
                State.pagination.pageSize = parseInt(pageSizeSelect.value) || 20;
                State.pagination.currentPage = 1;
                State.settings.pageSize = State.pagination.pageSize;
                this.onPageChange();
            });
        }
    },

    goToPage(page) {
        State.pagination.currentPage = page;
        this.onPageChange();
    },

    onPageChange() {
        // 由 HistoryUI 覆盖此方法
        HistoryUI.loadHistory();
    }
};

const API = {
    async match(demand, signal) {
        const headers = { 'Content-Type': 'application/json' };
        // 仅登录用户且非快速体验时发送鉴权
        if (AuthManager.isLoggedIn() && !State.isQuickDemo) {
            headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        }
        const response = await fetch(`${Config.API_BASE_URL}/match`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ demand }),
            signal
        });

        if (!response.ok) {
            throw new Error(`匹配失败: ${response.statusText}`);
        }

        return await response.json();
    },

    async analyze(competitor, industry, signal) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn() && !State.isQuickDemo) {
            headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        }
        const response = await fetch(`${Config.API_BASE_URL}/analyze`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ competitor, industry }),
            signal
        });

        if (!response.ok) {
            throw new Error(`分析失败: ${response.statusText}`);
        }

        return await response.json();
    },

    async getKnowledgeStats() {
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/stats`);
        
        if (!response.ok) {
            throw new Error(`获取统计失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async getDashboardStats() {
        const response = await fetch(`${Config.API_BASE_URL}/dashboard/stats`, {
            headers: AuthManager.isLoggedIn() ? { 'Authorization': `Bearer ${AuthManager.getToken()}` } : {}
        });
        
        if (!response.ok) {
            throw new Error(`获取仪表盘数据失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async rebuildKnowledge() {
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/rebuild`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            throw new Error(`重建失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async clearKnowledge() {
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/clear`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error(`清空失败: ${response.statusText}`);
        }

        return await response.json();
    },

    // ========== 历史记录 API ==========
    async getHistoryList(offset = 0, limit = 20) {
        const response = await fetch(`${Config.API_BASE_URL}/history/list?page=${Math.floor(offset / limit) + 1}&page_size=${limit}`, {
            headers: AuthManager.isLoggedIn() ? { 'Authorization': `Bearer ${AuthManager.getToken()}` } : {}
        });
        if (!response.ok) throw new Error(`获取历史记录失败: ${response.statusText}`);
        return await response.json();
    },

    async getHistoryDetail(id) {
        const response = await fetch(`${Config.API_BASE_URL}/history/${id}`, {
            headers: AuthManager.isLoggedIn() ? { 'Authorization': `Bearer ${AuthManager.getToken()}` } : {}
        });
        if (!response.ok) throw new Error(`获取详情失败: ${response.statusText}`);
        return await response.json();
    },

    async compareHistory(idA, idB) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const response = await fetch(`${Config.API_BASE_URL}/history/compare`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ id_a: idA, id_b: idB })
        });
        if (!response.ok) throw new Error(`对比失败: ${response.statusText}`);
        return await response.json();
    },

    async getCompareAISummary(idA, idB) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const response = await fetch(`${Config.API_BASE_URL}/history/ai-summary`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ id_a: idA, id_b: idB })
        });
        if (!response.ok) throw new Error(`AI总结失败: ${response.statusText}`);
        return await response.json();
    },

    async getCompetitorHistoryList(offset = 0, limit = 20) {
        const response = await fetch(`${Config.API_BASE_URL}/competitor/history/list?page=${Math.floor(offset / limit) + 1}&page_size=${limit}`, {
            headers: AuthManager.isLoggedIn() ? { 'Authorization': `Bearer ${AuthManager.getToken()}` } : {}
        });
        if (!response.ok) throw new Error(`获取竞品分析历史失败: ${response.statusText}`);
        return await response.json();
    },

    async getCompetitorHistoryDetail(id) {
        const response = await fetch(`${Config.API_BASE_URL}/competitor/history/${id}`, {
            headers: AuthManager.isLoggedIn() ? { 'Authorization': `Bearer ${AuthManager.getToken()}` } : {}
        });
        if (!response.ok) throw new Error(`获取详情失败: ${response.statusText}`);
        return await response.json();
    },

    async refineSolution(originalDemand, currentSolution, followUp, conversationHistory) {
        const response = await fetch(`${Config.API_BASE_URL}/solution/refine`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                original_demand: originalDemand,
                current_solution: currentSolution,
                follow_up: followUp,
                conversation_history: conversationHistory || []
            })
        });
        if (!response.ok) throw new Error(`方案优化失败: ${response.statusText}`);
        return await response.json();
    },

    async refineCompetitorAnalysis(originalCompetitor, originalIndustry, currentAnalysis, followUp, conversationHistory) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn() && !State.isQuickDemo) {
            headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        }
        const response = await fetch(`${Config.API_BASE_URL}/competitor/refine`, {
            method: 'POST',
            headers,
            body: JSON.stringify({
                original_competitor: originalCompetitor,
                original_industry: originalIndustry,
                current_analysis: currentAnalysis,
                follow_up: followUp,
                conversation_history: conversationHistory || []
            })
        });
        if (!response.ok) throw new Error(`分析优化失败: ${response.statusText}`);
        return await response.json();
    },

    async updateHistorySolution(historyId, solution) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const response = await fetch(`${Config.API_BASE_URL}/history/${historyId}/solution`, {
            method: 'PATCH',
            headers,
            body: JSON.stringify({ solution })
        });
        if (!response.ok) throw new Error(`更新历史方案失败: ${response.statusText}`);
        return await response.json();
    },

    async updateCompetitorHistorySolution(historyId, analysis) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const response = await fetch(`${Config.API_BASE_URL}/competitor/history/${historyId}/solution`, {
            method: 'PATCH',
            headers,
            body: JSON.stringify({ solution: analysis })
        });
        if (!response.ok) throw new Error(`更新竞品分析历史失败: ${response.statusText}`);
        return await response.json();
    }
};

/* ==================== 进度管理器 ==================== */

class ProgressManager {
    constructor(panelId, barId, stepsId, timeId) {
        this.panel = document.getElementById(panelId);
        this.bar = document.getElementById(barId);
        this.stepsContainer = document.getElementById(stepsId);
        this.timeEl = timeId ? document.getElementById(timeId) : null;
        this.startTime = null;
        this.timer = null;
        this.currentStep = -1;
        this.simulationTimer = null;
    }

    start() {
        if (!this.panel) return this;
        this.panel.style.display = 'block';
        this.panel.classList.remove('success', 'fade-out');
        this.panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        if (this.bar) {
            this.bar.style.width = '0%';
            this.bar.classList.remove('indeterminate');
        }
        this.currentStep = -1;
        this.startTime = Date.now();

        // 重置所有步骤状态
        if (this.stepsContainer) {
            this.stepsContainer.querySelectorAll('.progress-step').forEach(step => {
                step.classList.remove('active', 'done');
                const status = step.querySelector('.step-status');
                if (status) status.className = 'step-status waiting';
            });
        }

        // 启动计时器
        if (this.timeEl) {
            this.timeEl.textContent = '已用时 0.0s';
            this.timer = setInterval(() => this.updateTime(), 100);
        }

        return this;
    }

    setStep(index) {
        if (!this.stepsContainer) return;
        // 标记之前的步骤为完成
        for (let i = 0; i < index; i++) {
            const step = this.stepsContainer.querySelector(`[data-step="${i}"]`);
            if (step) {
                step.classList.remove('active');
                step.classList.add('done');
                const status = step.querySelector('.step-status');
                if (status) status.className = 'step-status completed';
            }
        }
        // 标记当前步骤为进行中
        const currentStep = this.stepsContainer.querySelector(`[data-step="${index}"]`);
        if (currentStep) {
            currentStep.classList.add('active');
            const status = currentStep.querySelector('.step-status');
            if (status) status.className = 'step-status running';
        }
        this.currentStep = index;
    }

    setProgress(percent) {
        if (this.bar) this.bar.style.width = `${percent}%`;
    }

    updateTime() {
        if (!this.startTime || !this.timeEl) return;
        const elapsed = (Date.now() - this.startTime) / 1000;
        this.timeEl.textContent = `已用时 ${elapsed.toFixed(1)}s`;
    }

    // 模拟进度增长（用于非流式后端）
    simulateProgress(steps, totalDuration) {
        if (!this.stepsContainer) return;
        const stepCount = this.stepsContainer.querySelectorAll('.progress-step').length;
        const stepDuration = totalDuration / stepCount;
        let currentStepIndex = 0;

        this.simulationTimer = setInterval(() => {
            if (currentStepIndex < stepCount) {
                this.setStep(currentStepIndex);
                const progress = ((currentStepIndex + 0.5) / stepCount) * 90; // 最多到90%，等API完成后再到100%
                this.setProgress(progress);
                currentStepIndex++;
            }
        }, stepDuration);
    }

    stopSimulation() {
        if (this.simulationTimer) {
            clearInterval(this.simulationTimer);
            this.simulationTimer = null;
        }
    }

    success(message) {
        this.stopSimulation();
        this.setProgress(100);
        if (this.panel) this.panel.classList.add('success');
        
        // 标记所有步骤为完成
        if (this.stepsContainer) {
            this.stepsContainer.querySelectorAll('.progress-step').forEach(step => {
                step.classList.remove('active');
                step.classList.add('done');
                const status = step.querySelector('.step-status');
                if (status) status.className = 'step-status completed';
            });
        }

        const title = this.panel ? this.panel.querySelector('.progress-title') : null;
        if (title) title.textContent = message || '完成！';

        clearInterval(this.timer);

        // 1.5秒后淡出
        setTimeout(() => {
            if (this.panel) this.panel.classList.add('fade-out');
            setTimeout(() => {
                if (this.panel) {
                    this.panel.style.display = 'none';
                    this.panel.classList.remove('success', 'fade-out');
                }
                // 重置进度条颜色
                if (this.bar) this.bar.style.background = '';
            }, 500);
        }, 1500);
    }

    error(message) {
        this.stopSimulation();
        clearInterval(this.timer);
        if (this.panel) this.panel.classList.remove('success');
        const title = this.panel ? this.panel.querySelector('.progress-title') : null;
        if (title) title.textContent = message || '出错了';
        if (this.bar) this.bar.style.background = 'linear-gradient(90deg, var(--error) 0%, #D4191F 100%)';
    }

    cancel() {
        this.stopSimulation();
        clearInterval(this.timer);
        if (this.panel) {
            this.panel.classList.add('fade-out');
            setTimeout(() => {
                this.panel.style.display = 'none';
                this.panel.classList.remove('fade-out');
            }, 500);
        }
        // 重置所有步骤状态
        if (this.stepsContainer) {
            this.stepsContainer.querySelectorAll('.progress-step').forEach(step => {
                step.classList.remove('active', 'done');
                const status = step.querySelector('.step-status');
                if (status) status.className = 'step-status waiting';
            });
        }
        if (this.bar) {
            this.bar.style.width = '0%';
            this.bar.style.background = '';
        }
        const title = this.panel ? this.panel.querySelector('.progress-title') : null;
        if (title) title.textContent = this.panel.id === 'match-progress-panel' ? '正在为您匹配最佳方案...' : '正在生成竞争分析报告...';
    }

    hide() {
        this.stopSimulation();
        clearInterval(this.timer);
        if (this.panel) this.panel.style.display = 'none';
    }
}

// 初始化进度管理器实例
const MatchProgress = new ProgressManager('match-progress-panel', 'match-progress-bar', 'match-progress-steps', 'match-time-elapsed');
const AnalyzeProgress = new ProgressManager('analyze-progress-panel', 'analyze-progress-bar', 'analyze-progress-steps', 'analyze-time-elapsed');
const RebuildProgress = new ProgressManager('rebuild-progress-panel', 'rebuild-progress-bar', null, null);

const UI = {
    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
        }, 3000);
    },

    setButtonLoading(button, loading) {
        if (loading) {
            button.classList.add('loading');
            button.disabled = true;
        } else {
            button.classList.remove('loading');
            button.disabled = false;
        }
    },

    switchPage(pageName) {
        document.querySelectorAll('.page').forEach(page => {
            page.classList.remove('active');
        });
        document.getElementById(`page-${pageName}`).classList.add('active');
        
        document.querySelectorAll('.navbar-item').forEach(item => {
            item.classList.remove('active');
        });
        const navbarItem = document.querySelector(`.navbar-item[data-page="${pageName}"]`);
        if (navbarItem) navbarItem.classList.add('active');
        
        document.querySelectorAll('.mobile-item').forEach(item => {
            item.classList.remove('active');
        });
        const mobileItem = document.querySelector(`.mobile-item[data-page="${pageName}"]`);
        if (mobileItem) mobileItem.classList.add('active');
        
        State.currentPage = pageName;
    },

    simpleMarkdown(text) {
        if (!text || typeof text !== 'string') return '';
        let html = text;
        // 代码块（优先处理）
        const codeBlocks = [];
        html = html.replace(/```[\s\S]*?```/g, function (m) {
            const idx = codeBlocks.length;
            const inner = m.replace(/```[\w]*\n?/, '').replace(/```$/, '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            codeBlocks.push('<pre style="background:rgba(255,255,255,0.08);padding:12px 16px;border-radius:8px;overflow-x:auto;font-size:13px;line-height:1.6;"><code>' + inner + '</code></pre>');
            return '___CODEBLOCK_' + idx + '___';
        });
        // 行内代码
        html = html.replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.12);padding:1px 5px;border-radius:4px;font-size:13px;">$1</code>');
        // 标题
        html = html.replace(/^### (.+)$/gm, '<h4 style="color:rgba(255,255,255,0.95);margin:16px 0 8px;">$1</h4>');
        html = html.replace(/^## (.+)$/gm, '<h3 style="color:rgba(255,255,255,0.95);margin:18px 0 10px;">$1</h3>');
        html = html.replace(/^# (.+)$/gm, '<h2 style="color:rgba(255,255,255,0.95);margin:20px 0 12px;">$1</h2>');
        // 加粗
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        // 斜体
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
        // 链接
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:var(--primary-color);">$1</a>');
        // 无序列表
        html = html.replace(/^[\s]*[-*+] (.+)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>)/s, '<ul style="padding-left:20px;margin:8px 0;">$1</ul>');
        // 有序列表
        html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
        // 横线
        html = html.replace(/^---$/gm, '<hr style="border-color:rgba(255,255,255,0.15);margin:16px 0;">');
        // 段落
        html = html.replace(/\n\n/g, '<br><br>');
        html = html.replace(/\n/g, '<br>');
        // 还原代码块
        codeBlocks.forEach(function (block, idx) {
            html = html.replace('___CODEBLOCK_' + idx + '___', block);
        });
        return html;
    },

    renderMarkdown(content) {
        if (!content || typeof content !== 'string') {
            return '<p style="color: var(--text-secondary);">（无内容）</p>';
        }
        try {
            return this.simpleMarkdown(content);
        } catch (e) {
            console.warn('[UI] Markdown渲染失败:', e);
            const escaped = content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            return '<p style="color: var(--text-secondary); white-space: pre-wrap;">' + escaped.substring(0, 3000) + '</p>';
        }
    },

    renderSources(container, sources) {
        if (!sources || sources.length === 0) {
            container.innerHTML = '<p style="color: var(--text-secondary);">无参考文档</p>';
            return;
        }
        
        container.innerHTML = sources.map((doc, i) => `
            <div class="source-item">
                <p><strong>文档 ${i + 1}:</strong> ${doc.metadata?.source || '未知'}</p>
                <p><strong>行业:</strong> ${doc.metadata?.industry || '未知'}</p>
                <p><strong>内容摘要:</strong> ${doc.page_content?.substring(0, 200) || ''}...</p>
            </div>
        `).join('<hr style="border-color: rgba(255,255,255,0.1); margin: 16px 0;">');
    },

    downloadFile(content, filename) {
        const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }
};

const KnowledgeUI = {
    chart: null,

    async loadStats() {
        try {
            SkeletonUI.showKnowledgeSkeleton();
            console.log('[KnowledgeUI] 正在加载统计数据...');
            const stats = await API.getKnowledgeStats();
            console.log('[KnowledgeUI] 统计数据获取成功:', stats);
            State.knowledgeStats = stats;
            SkeletonUI.clearSkeleton('knowledge-stats');

            const accuracy = stats.accuracy || 50;

            // 安全写入DOM（元素可能不存在，如导航栏无accuracy显示位）
            const safeSet = (id, val) => { var el = document.getElementById(id); if (el) el.textContent = val; };

            safeSet('nav-doc-count', stats.total_documents || 0);
            safeSet('nav-industry-count', stats.supported_industries?.length || 0);
            // nav-accuracy 在导航栏中不存在，已移除引用

            safeSet('kb-total-docs', stats.total_documents || 0);
            safeSet('kb-total-industries', stats.supported_industries?.length || 0);
            safeSet('kb-accuracy', `${accuracy}%`);

            this.renderChart(stats.industry_counts || {});
        } catch (error) {
            console.error('[KnowledgeUI] 加载统计失败:', error.message || error);
            console.error('[KnowledgeUI] 错误堆栈:', error.stack);
            UI.showToast('加载统计数据失败，请检查后端服务（按F12查看详情）', 'warning');
        }
    },

    renderChart(industryCounts) {
        const canvas = document.getElementById('industry-chart');
        if (!canvas) return;
        
        const labels = Object.keys(industryCounts);
        const data = Object.values(industryCounts);
        
        if (this.chart) {
            this.chart.destroy();
        }
        
        this.chart = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: '文档数量',
                    data: data,
                    backgroundColor: 'rgba(255, 0, 0, 0.6)',
                    borderColor: 'rgba(255, 0, 0, 1)',
                    borderWidth: 1,
                    borderRadius: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `文档数量: ${context.raw}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        max: 50,
                        grid: {
                            color: 'rgba(255, 255, 255, 0.1)'
                        },
                        ticks: {
                            color: '#B0B8C8',
                            stepSize: 10,
                            font: {
                                size: 12
                            }
                        },
                        title: {
                            display: true,
                            text: '文档数量',
                            color: '#B0B8C8',
                            font: {
                                size: 14
                            }
                        }
                    },
                    y: {
                        grid: {
                            display: false
                        },
                        ticks: {
                            color: '#FFFFFF',
                            font: {
                                size: 13
                            }
                        }
                    }
                }
            }
        });
    }
};

/* ==================== Dashboard 仪表盘 ==================== */

const DashboardUI = {
    charts: {},
    stats: null,

    async loadStats() {
        try {
            const stats = await API.getDashboardStats();
            this.stats = stats;
            this.renderKPIs(stats);
            this.renderIndustryHeatmap(stats.industry_coverage || {});
            this.renderMatchTrend(stats.match_trends || []);
            this.renderCompetitorFreq(stats.competitor_frequency || {});
            this.renderInfoBar(stats);
        } catch (error) {
            console.error('加载仪表盘数据失败:', error);
            UI.showToast('加载仪表盘数据失败', 'warning');
        }
    },

    renderKPIs(stats) {
        const animateValue = (el, target, suffix = '') => {
            if (!el) return;
            const start = 0;
            const duration = 1000;
            const startTime = performance.now();
            const step = (now) => {
                const progress = Math.min((now - startTime) / duration, 1);
                const easeOut = 1 - Math.pow(1 - progress, 3);
                el.textContent = Math.floor(start + (target - start) * easeOut) + suffix;
                if (progress < 1) requestAnimationFrame(step);
            };
            requestAnimationFrame(step);
        };

        animateValue(document.getElementById('dash-total-matches'), stats.recent_matches || 0);
        animateValue(document.getElementById('dash-total-analyses'), stats.recent_analyses || 0);
        animateValue(document.getElementById('dash-total-docs'), stats.total_documents || 0);

        const accEl = document.getElementById('dash-accuracy');
        if (accEl) accEl.textContent = (stats.accuracy || 87) + '%';

        // 涨幅显示（7日环比）
        const formatTrend = (val) => {
            if (val === null) return { text: '↗ 新增长', cls: '' };
            if (val > 0)   return { text: `↗ +${val}%`,  cls: '' };
            if (val < 0)   return { text: `↘ ${val}%`,  cls: 'trend-down' };
            return              { text: '— 0%',       cls: '' };
        };

        const m = formatTrend(stats.match_growth);
        const matchEl = document.getElementById('dash-match-trend');
        if (matchEl) { matchEl.textContent = m.text; matchEl.className = 'kpi-trend' + (m.cls ? ' ' + m.cls : ''); }

        const a = formatTrend(stats.analyze_growth);
        const analyzeEl = document.getElementById('dash-analyze-trend');
        if (analyzeEl) { analyzeEl.textContent = a.text; analyzeEl.className = 'kpi-trend' + (a.cls ? ' ' + a.cls : ''); }
    },

    renderIndustryHeatmap(coverage) {
        const canvas = document.getElementById('industry-heatmap-chart');
        if (!canvas || typeof Chart === 'undefined') return;
        if (this.charts.heatmap) this.charts.heatmap.destroy();

        const labels = Object.keys(coverage);
        const data = Object.values(coverage);
        
        // 生成热力图颜色
        const maxVal = Math.max(...data, 1);
        const bgColors = data.map(v => {
            const intensity = v / maxVal;
            return `rgba(199, 0, 11, ${0.3 + intensity * 0.7})`;
        });

        this.charts.heatmap = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: '文档覆盖数',
                    data: data,
                    backgroundColor: bgColors,
                    borderColor: 'rgba(199, 0, 11, 0.8)',
                    borderWidth: 1,
                    borderRadius: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `文档数: ${ctx.raw} 篇`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.08)' },
                        ticks: { color: 'rgba(255, 255, 255, 0.7)', font: { size: 13 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: 'rgba(255, 255, 255, 0.85)', font: { size: 13, weight: '500' } }
                    }
                }
            }
        });
    },

    renderMatchTrend(trends) {
        const canvas = document.getElementById('match-trend-chart');
        if (!canvas || typeof Chart === 'undefined') return;
        if (this.charts.trend) this.charts.trend.destroy();

        const labels = trends.map(t => t.date);
        const matchData = trends.map(t => t.matches);
        const analyzeData = trends.map(t => t.analyses);

        this.charts.trend = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: '方案匹配',
                        data: matchData,
                        borderColor: '#C7000B',
                        backgroundColor: 'rgba(199, 0, 11, 0.1)',
                        borderWidth: 3,
                        tension: 0.4,
                        fill: true,
                        pointBackgroundColor: '#C7000B',
                        pointRadius: 4,
                        pointHoverRadius: 6
                    },
                    {
                        label: '竞品分析',
                        data: analyzeData,
                        borderColor: '#4A90E2',
                        backgroundColor: 'rgba(74, 144, 226, 0.1)',
                        borderWidth: 3,
                        tension: 0.4,
                        fill: true,
                        pointBackgroundColor: '#4A90E2',
                        pointRadius: 4,
                        pointHoverRadius: 6
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        labels: { color: 'rgba(255, 255, 255, 0.8)', font: { size: 12 } }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.08)' },
                        ticks: { color: 'rgba(255, 255, 255, 0.7)', font: { size: 13 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { 
                            color: 'rgba(255, 255, 255, 0.75)', 
                            font: { size: 14, weight: '500' },
                            maxRotation: 0
                        }
                    }
                }
            }
        });
    },

    renderCompetitorFreq(freq) {
        const canvas = document.getElementById('competitor-freq-chart');
        if (!canvas || typeof Chart === 'undefined') return;
        if (this.charts.freq) this.charts.freq.destroy();

        // 数据已是百分比，排序取Top12
        const sorted = Object.entries(freq).sort((a, b) => b[1] - a[1]).slice(0, 12);
        const labels = sorted.map(([k]) => k);
        const data = sorted.map(([, v]) => v);

        this.charts.freq = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: '分析占比',
                    data: data,
                    // 彩虹色：暖→冷，从高到低依次对应
                    backgroundColor: [
                        'rgba(255, 59, 48, 0.88)',   // 1. 红 (最暖)
                        'rgba(255, 107, 53, 0.88)',  // 2. 橙红
                        'rgba(255, 149, 0, 0.88)',   // 3. 橙
                        'rgba(255, 204, 2, 0.88)',   // 4. 琥珀/黄
                        'rgba(52, 199, 89, 0.88)',   // 5. 黄绿
                        'rgba(48, 209, 88, 0.88)',   // 6. 翠绿
                        'rgba(0, 199, 190, 0.88)',   // 7. 青
                        'rgba(50, 173, 230, 0.88)',  // 8. 天蓝
                        'rgba(0, 122, 255, 0.88)',   // 9. 蓝
                        'rgba(88, 86, 214, 0.88)',   // 10. 靛
                        'rgba(175, 82, 222, 0.88)',  // 11. 紫
                        'rgba(191, 90, 242, 0.88)'   // 12. 紫罗兰 (最冷)
                    ],
                    borderRadius: 6,
                    borderSkipped: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `占比 ${ctx.raw}%`
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'linear',
                        grid: { color: 'rgba(255, 255, 255, 0.08)' },
                        ticks: {
                            color: 'rgba(255, 255, 255, 0.85)',
                            font: { family: 'Inter, sans-serif', size: 15, weight: '600' },
                            callback: (val) => val + '%',
                            padding: 8
                        },
                        border: { display: false }
                    },
                    y: {
                        grid: { display: false },
                        ticks: {
                            color: 'rgba(255, 255, 255, 0.9)',
                            font: { family: 'Inter, sans-serif', size: 14, weight: '600' },
                            padding: 12
                        },
                        border: { display: false }
                    }
                },
                layout: {
                    padding: { left: 4, right: 80, top: 8, bottom: 8 }
                }
            },
            plugins: [{
                id: 'percentLabels',
                afterDatasetsDraw(chart) {
                    const { ctx, scales: { x, y } } = chart;
                    chart.data.datasets[0].data.forEach((val, i) => {
                        const meta = chart.getDatasetMeta(0);
                        const bar = meta.data[i];
                        if (!bar) return;
                        ctx.save();
                        ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
                        ctx.font = '600 14px Inter, sans-serif';
                        ctx.textAlign = 'left';
                        ctx.textBaseline = 'middle';
                        const xPos = x.getPixelForValue(val) + 8;
                        const yPos = bar.y;
                        ctx.fillText(val + '%', xPos, yPos);
                        ctx.restore();
                    });
                }
            }]
        });
    },

    renderInfoBar(stats) {
        const versionEl = document.getElementById('dash-version');
        const uptimeEl = document.getElementById('dash-uptime');
        const updateEl = document.getElementById('dash-last-update');

        if (versionEl) versionEl.textContent = stats.version || 'v1.0.0';
        if (uptimeEl) uptimeEl.textContent = stats.system_uptime || '--';
        if (updateEl) updateEl.textContent = stats.last_update || '--';
    }
};

const SkeletonUI = {
    showHistorySkeleton() {
        if (!State.settings.skeletons) return;
        const container = document.getElementById('history-list');
        if (!container) return;

        let html = '';
        for (let i = 0; i < 5; i++) {
            html += `<div class="skeleton skeleton-card" style="height: 80px; margin-bottom: 12px;"></div>`;
        }
        container.innerHTML = html;
    },

    showDashboardSkeleton() {
        if (!State.settings.skeletons) return;
        // Dashboard KPI cards
        ['dash-total-matches', 'dash-total-analyses', 'dash-total-docs'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '<span class="skeleton" style="display:inline-block;width:60px;height:28px;"></span>';
        });

        // Charts area
        const chartBodies = document.querySelectorAll('.chart-body');
        chartBodies.forEach(body => {
            const origHeight = body.style.height;
            body.innerHTML = `<div class="skeleton skeleton-chart" style="height: ${origHeight || '300px'};"></div>`;
        });
    },

    showMatchFormSkeleton() {
        if (!State.settings.skeletons) return;
        // 不覆盖整个 container，只放在 solution-content 内，保护子元素不被销毁
        const container = document.getElementById('solution-content');
        if (!container) return;
        container.innerHTML = `
            <div class="skeleton skeleton-result" style="min-height: 200px;">
                <div class="skeleton skeleton-title"></div>
                <div class="skeleton skeleton-text medium"></div>
                <div class="skeleton skeleton-text"></div>
                <div class="skeleton skeleton-text short"></div>
            </div>
        `;
    },

    showCompetitorSkeleton() {
        if (!State.settings.skeletons) return;
        const container = document.getElementById('competitor-content');
        if (!container) return;
        container.innerHTML = `
            <div class="skeleton skeleton-result" style="min-height: 200px;">
                <div class="skeleton skeleton-title"></div>
                <div class="skeleton skeleton-text medium"></div>
                <div class="skeleton skeleton-text"></div>
                <div class="skeleton skeleton-text short"></div>
            </div>
        `;
    },

    showKnowledgeSkeleton() {
        if (!State.settings.skeletons) return;
        const container = document.getElementById('knowledge-stats');
        if (!container) return;
        const statsGrid = container.querySelector('.stats-grid');
        if (statsGrid) {
            statsGrid.innerHTML = Array(4).fill('').map(() => 
                `<div class="skeleton skeleton-card" style="height: 100px;"></div>`
            ).join('');
        }
    },

    clearSkeleton(containerId) {
        const container = document.getElementById(containerId);
        if (container) container.innerHTML = '';
    }
};

const PageTransition = {
    isTransitioning: false,
    duration: 350, // 仅用于防抖锁定时长

    async switchTo(pageName) {
        if (this.isTransitioning) return;
        this.isTransitioning = true;

        const currentPage = document.querySelector('.page.active');
        const targetPage = document.getElementById(`page-${pageName}`);

        if (!targetPage || currentPage === targetPage) {
            this.isTransitioning = false;
            return;
        }

        // 1. 立即交换 active 类（同一帧内完成，无 await 阻塞）
        if (currentPage) currentPage.classList.remove('active');
        targetPage.classList.add('active');
        this._updateNav(pageName);
        State.currentPage = pageName;

        // 2. 动画关闭时无需防抖，直接释放锁
        if (!State.settings.animations) {
            this.isTransitioning = false;
            return;
        }

        // 3. 仅用防抖锁阻止短时间重复点击，不阻塞数据加载
        setTimeout(() => { this.isTransitioning = false; }, this.duration);
    },

    _updateNav(pageName) {
        document.querySelectorAll('.navbar-item').forEach(item => {
            item.classList.toggle('active', item.dataset.page === pageName);
        });
        document.querySelectorAll('.mobile-item').forEach(item => {
            item.classList.toggle('active', item.dataset.page === pageName);
        });
    }
};

/* ==================== 历史记录 ==================== */

const HistoryUI = {
    items: [],
    selectedIds: new Set(),
    isCompareMode: false,
    currentCompareIds: [],
    currentType: 'match',  // 'match' | 'analyze'

    switchTab(type) {
        this.currentType = type;
        this.selectedIds.clear();
        if (this.isCompareMode) this.exitCompareMode();
        
        // 更新 tab 样式
        document.querySelectorAll('.history-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.tab === type);
        });
        
        // 隐藏对比工具（仅方案匹配支持对比）
        const compareSection = document.getElementById('history-compare-section');
        if (compareSection) compareSection.style.display = type === 'match' ? '' : 'none';
        
        this.loadHistory();
    },

    async loadHistory() {
        try {
            SkeletonUI.showHistorySkeleton();
            const { currentPage, pageSize } = State.pagination;
            const offset = (currentPage - 1) * pageSize;

            if (this.currentType === 'match') {
                const data = await API.getHistoryList(offset, pageSize);
                this.items = data.items || [];
                State.pagination.totalItems = data.total || 0;
                State.pagination.totalPages = data.total_pages || 1;
            } else {
                const data = await API.getCompetitorHistoryList(offset, pageSize);
                this.items = data.items || [];
                State.pagination.totalItems = data.total || 0;
                State.pagination.totalPages = data.total_pages || 1;
            }
            this.renderList();
            this.updateCount();
            PaginationUI.render('pagination-container', 'pagination-buttons', 'pagination-info');
        } catch (error) {
            console.error('加载历史记录失败:', error);
            ErrorHandler.showInline('加载历史记录失败: ' + error.message, () => this.loadHistory());
        }
    },

    updateCount() {
        const el = document.getElementById('history-count');
        const label = this.currentType === 'match' ? '方案匹配' : '竞品分析';
        if (el) el.textContent = `共 ${State.pagination.totalItems} 条${label}记录`;
    },

    renderList() {
        const container = document.getElementById('history-list');
        if (!container) return;

        if (this.items.length === 0) {
            const typeLabel = this.currentType === 'match' ? '方案匹配' : '竞品分析';
            const hintText = this.currentType === 'match'
                ? '在「解决方案匹配」页面输入需求并匹配后，方案会自动保存到这里'
                : '在「竞品分析」页面选择竞品和行业并分析后，报告会自动保存到这里';
            container.innerHTML = `
                <div class="history-empty">
                    <div class="empty-icon">📋</div>
                    <p>暂无${typeLabel}历史记录</p>
                    <p class="empty-sub">${hintText}</p>
                </div>
            `;
            return;
        }

        if (this.currentType === 'match') {
            this._renderMatchList(container);
        } else {
            this._renderCompetitorList(container);
        }
    },

    _renderMatchList(container) {
        container.innerHTML = this.items.map(item => {
            const isSelected = this.selectedIds.has(item.id);
            const dateStr = item.created_at ? item.created_at.replace('T', ' ').substring(0, 16) : '--';
            const demandPreview = (item.demand_text || '').substring(0, 200);
            const favName = demandPreview.substring(0, 100);
            const isFav = FavoriteManager.isFavorited(favName);
            return `
                <div class="history-item ${isSelected ? 'selected' : ''}" data-id="${item.id}"
                    data-fav-name="${this.escapeHtml(favName)}"
                    data-fav-content="${this.escapeHtml((item.solution_preview || '').substring(0, 500))}"
                    data-fav-industry="${this.escapeHtml(item.industry || '')}"
                    onclick="HistoryUI.onItemClick(event, ${item.id})">
                    <div class="history-item-checkbox">${isSelected ? '✓' : ''}</div>
                    <div class="history-item-content">
                        <div class="history-item-header">
                            <span class="history-item-date">${dateStr}</span>
                            ${item.industry ? `<span class="history-item-industry">${item.industry}</span>` : ''}
                        </div>
                        <div class="history-item-demand">${this.escapeHtml(demandPreview)}${item.demand_text && item.demand_text.length > 200 ? '...' : ''}</div>
                    </div>
                    <div class="history-item-actions">
                        <button class="btn-favorite fav-action-btn ${isFav ? 'active' : ''}" onclick="event.stopPropagation(); FavoriteManager.toggleFromItem(this.closest('.history-item'))" title="${isFav ? '点击取消收藏' : '点击收藏'}">${isFav ? '⭐ 已收藏' : '☆ 收藏'}</button>
                        <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); HistoryUI.showDetail(${item.id})">查看</button>
                    </div>
                </div>
            `;
        }).join('');
    },

    _renderCompetitorList(container) {
        container.innerHTML = this.items.map(item => {
            const dateStr = item.created_at ? item.created_at.replace('T', ' ').substring(0, 16) : '--';
            const favName = (item.competitor || '未知竞品').substring(0, 100);
            const isFav = FavoriteManager.isFavorited(favName);
            return `
                <div class="history-item" data-id="${item.id}" data-fav-name="${this.escapeHtml(favName)}" data-fav-content="${this.escapeHtml((item.analysis_preview || '').substring(0, 500))}" data-fav-industry="${this.escapeHtml(item.industry || '')}" onclick="HistoryUI.showCompetitorDetail(${item.id})">
                    <div class="history-item-content">
                        <div class="history-item-header">
                            <span class="history-item-date">${dateStr}</span>
                            <span class="history-item-industry competitor-badge">${this.escapeHtml(item.competitor || '未知竞品')}</span>
                            ${item.industry ? `<span class="history-item-industry">${item.industry}</span>` : ''}
                        </div>
                        <div class="history-item-demand" style="color: rgba(255,255,255,0.6);">分析报告已生成 · 点击查看详情</div>
                    </div>
                    <div class="history-item-actions">
                        <button class="btn-favorite fav-action-btn ${isFav ? 'active' : ''}" onclick="event.stopPropagation(); FavoriteManager.toggleFromItem(this.closest('.history-item'))" title="${isFav ? '点击取消收藏' : '点击收藏'}">${isFav ? '⭐ 已收藏' : '☆ 收藏'}</button>
                        <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); HistoryUI.showCompetitorDetail(${item.id})">查看</button>
                    </div>
                </div>
            `;
        }).join('');
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    onItemClick(event, id) {
        if (!this.isCompareMode) {
            this.showDetail(id);
            return;
        }
        // 对比模式：切换选中
        if (this.selectedIds.has(id)) {
            this.selectedIds.delete(id);
        } else {
            if (this.selectedIds.size >= 2) {
                UI.showToast('最多选择两条记录进行对比', 'warning');
                return;
            }
            this.selectedIds.add(id);
        }
        this.renderList();
        this.updateCompareUI();
    },

    updateCompareUI() {
        const hint = document.getElementById('compare-hint');
        const btn = document.getElementById('btn-do-compare');
        if (!hint || !btn) return;

        if (!this.isCompareMode) {
            hint.textContent = '';
            hint.classList.remove('visible');
            btn.textContent = '开始对比';
            btn.disabled = false;
            return;
        }

        const count = this.selectedIds.size;
        btn.textContent = `确认对比 (${count}/2)`;

        if (count === 0) {
            hint.textContent = '请勾选两条记录进行对比';
            hint.classList.add('visible');
            btn.disabled = true;
        } else if (count === 1) {
            hint.textContent = '再勾选一条记录';
            hint.classList.add('visible');
            btn.disabled = true;
        } else {
            hint.textContent = '已选满两条，点击确认对比';
            hint.classList.add('visible');
            btn.disabled = false;
        }
    },

    enterCompareMode() {
        this.isCompareMode = true;
        this.selectedIds.clear();
        this.renderList();
        this.updateCompareUI();
        const btnDo = document.getElementById('btn-do-compare');
        const btnClear = document.getElementById('btn-clear-compare');
        if (btnDo) { btnDo.style.display = ''; btnDo.disabled = true; }
        if (btnClear) btnClear.style.display = '';
        UI.showToast('请勾选两条记录，然后点击「确认对比」', 'info');
    },

    exitCompareMode() {
        this.isCompareMode = false;
        this.selectedIds.clear();
        this.renderList();
        this.updateCompareUI();
        const btnDo = document.getElementById('btn-do-compare');
        const btnClear = document.getElementById('btn-clear-compare');
        if (btnDo) { btnDo.style.display = ''; btnDo.disabled = false; btnDo.textContent = '开始对比'; }
        if (btnClear) btnClear.style.display = 'none';
    },

    async doCompare() {
        if (this.selectedIds.size !== 2) return;
        const [idA, idB] = Array.from(this.selectedIds);
        try {
            const data = await API.compareHistory(idA, idB);
            this.renderCompare(data.item_a, data.item_b);
        } catch (error) {
            console.error('对比失败:', error);
            UI.showToast('对比失败: ' + error.message, 'error');
        }
    },

    renderCompare(itemA, itemB) {
        const panel = document.getElementById('history-compare-panel');
        const body = document.getElementById('compare-body');
        if (!panel || !body) return;

        this.currentCompareIds = [itemA.id, itemB.id];

        // 重置 AI 总结区域
        const aiSummaryBottom = document.getElementById('compare-ai-summary-bottom');
        const aiContent = document.getElementById('ai-summary-content');
        const aiAction = document.getElementById('compare-ai-action');
        const aiBtn = document.getElementById('btn-ai-summary');
        const aiLoading = document.getElementById('ai-summary-loading');
        if (aiSummaryBottom) aiSummaryBottom.style.display = 'none';
        if (aiContent) aiContent.innerHTML = '';
        if (aiAction) aiAction.style.display = 'flex';
        if (aiBtn) aiBtn.style.display = 'flex';
        if (aiLoading) aiLoading.style.display = 'none';

        const renderCol = (item, label) => `
            <div class="compare-column">
                <div class="compare-column-header">${label} · ${item.created_at ? item.created_at.replace('T', ' ').substring(0, 16) : ''}</div>
                <div class="compare-column-demand">
                    <strong>需求：</strong>${this.escapeHtml(item.demand_text || '')}
                </div>
                <div class="compare-column-solution result-content">
                    ${item.solution ? UI.renderMarkdown(item.solution) : '<p style="color: var(--text-muted)">无方案内容</p>'}
                </div>
            </div>
        `;

        body.innerHTML = renderCol(itemA, '方案 A') + renderCol(itemB, '方案 B');
        panel.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    },

    async doAISummary() {
        if (this.currentCompareIds.length !== 2) return;
        const [idA, idB] = this.currentCompareIds;

        const aiBtn = document.getElementById('btn-ai-summary');
        const aiLoading = document.getElementById('ai-summary-loading');
        if (aiBtn) aiBtn.style.display = 'none';
        if (aiLoading) aiLoading.style.display = 'flex';

        try {
            const data = await API.getCompareAISummary(idA, idB);
            const aiSummaryBottom = document.getElementById('compare-ai-summary-bottom');
            const aiContent = document.getElementById('ai-summary-content');
            const aiAction = document.getElementById('compare-ai-action');
            if (aiContent) aiContent.innerHTML = UI.renderMarkdown(data.summary);
            if (aiSummaryBottom) aiSummaryBottom.style.display = '';
            if (aiAction) aiAction.style.display = 'none';
        } catch (error) {
            console.error('AI总结失败:', error);
            UI.showToast('AI总结生成失败: ' + error.message, 'error');
            if (aiBtn) aiBtn.style.display = 'flex';
            if (aiLoading) aiLoading.style.display = 'none';
        }
    },

    closeCompare() {
        const panel = document.getElementById('history-compare-panel');
        const aiSummaryBottom = document.getElementById('compare-ai-summary-bottom');
        if (panel) panel.style.display = 'none';
        if (aiSummaryBottom) aiSummaryBottom.style.display = 'none';
        document.body.style.overflow = '';
        this.currentCompareIds = [];
    },

    async showDetail(id) {
        try {
            if (this.currentType === 'analyze') {
                return this.showCompetitorDetail(id);
            }
            const item = await API.getHistoryDetail(id);
            const modal = document.getElementById('history-detail-modal');
            const body = document.getElementById('detail-body');
            if (!modal || !body) return;

            const dateStr = item.created_at ? item.created_at.replace('T', ' ').substring(0, 16) : '--';
            body.innerHTML = `
                <div class="detail-section">
                    <div class="detail-section-label">创建时间</div>
                    <div style="font-size: var(--font-size-sm); color: var(--text-secondary);">${dateStr}</div>
                </div>
                <div class="detail-section">
                    <div class="detail-section-label">客户需求</div>
                    <div class="detail-demand">${this.escapeHtml(item.demand_text || '')}</div>
                </div>
                <div class="detail-section">
                    <div class="detail-section-label">匹配方案</div>
                    <div class="detail-solution result-content">${item.solution ? UI.renderMarkdown(item.solution) : '<p style="color: var(--text-muted)">无方案内容</p>'}</div>
                </div>
            `;
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        } catch (error) {
            console.error('加载详情失败:', error);
            UI.showToast('加载详情失败', 'warning');
        }
    },

    async showCompetitorDetail(id) {
        try {
            const item = await API.getCompetitorHistoryDetail(id);
            const modal = document.getElementById('history-detail-modal');
            const body = document.getElementById('detail-body');
            if (!modal || !body) return;

            const dateStr = item.created_at ? item.created_at.replace('T', ' ').substring(0, 16) : '--';
            body.innerHTML = `
                <div class="detail-section">
                    <div class="detail-section-label">创建时间</div>
                    <div style="font-size: var(--font-size-sm); color: var(--text-secondary);">${dateStr}</div>
                </div>
                <div class="detail-section">
                    <div class="detail-section-label">竞品名称</div>
                    <div class="detail-demand">${this.escapeHtml(item.competitor || '')}</div>
                </div>
                <div class="detail-section">
                    <div class="detail-section-label">所属行业</div>
                    <div class="detail-demand">${this.escapeHtml(item.industry || '')}</div>
                </div>
                <div class="detail-section">
                    <div class="detail-section-label">分析报告</div>
                    <div class="detail-solution result-content">${item.analysis ? UI.renderMarkdown(item.analysis) : '<p style="color: var(--text-muted)">无分析内容</p>'}</div>
                </div>
            `;
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        } catch (error) {
            console.error('加载竞品详情失败:', error);
            UI.showToast('加载详情失败', 'warning');
        }
    },

    closeDetail() {
        const modal = document.getElementById('history-detail-modal');
        if (modal) modal.style.display = 'none';
        document.body.style.overflow = '';
    },

    init() {
        const btnCompare = document.getElementById('btn-do-compare');
        const btnClear = document.getElementById('btn-clear-compare');
        const btnCloseDetail = document.getElementById('close-detail');
        const btnCloseCompare = document.getElementById('close-compare');

        if (btnCompare) {
            btnCompare.addEventListener('click', () => {
                if (this.isCompareMode) {
                    this.doCompare();
                } else {
                    this.enterCompareMode();
                }
            });
        }
        if (btnClear) btnClear.addEventListener('click', () => this.exitCompareMode());
        if (btnCloseDetail) btnCloseDetail.addEventListener('click', () => this.closeDetail());
        if (btnCloseCompare) btnCloseCompare.addEventListener('click', () => this.closeCompare());

        // AI 总结按钮
        const btnAISummary = document.getElementById('btn-ai-summary');
        if (btnAISummary) btnAISummary.addEventListener('click', () => this.doAISummary());

        // Tab 切换
        document.querySelectorAll('.history-tab').forEach(tab => {
            tab.addEventListener('click', () => this.switchTab(tab.dataset.tab));
        });

        // 点击遮罩关闭
        document.getElementById('history-detail-modal')?.addEventListener('click', (e) => {
            if (e.target === e.currentTarget) this.closeDetail();
        });
        document.getElementById('history-compare-panel')?.addEventListener('click', (e) => {
            if (e.target === e.currentTarget) this.closeCompare();
        });

        // 初始化按钮状态（解除 HTML 中的 disabled）
        this.updateCompareUI();
    }
};

// ===== 收藏管理器 =====
const FavoriteManager = {
    favoriteNames: new Set(),   // Cache of favorited solution names (for quick check)

    // Load current user's favorites to populate the set
    async init() {
        const token = AuthManager.getToken();
        if (!token) return;
        try {
            const resp = await fetch('/api/auth/favorites?page_size=50', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (resp.ok) {
                const data = await resp.json();
                this.favoriteNames = new Set(data.favorites.map(f => f.solution_name));
            }
        } catch(e) {}
    },

    // Check if a solution is already favorited (by name)
    isFavorited(solutionName) {
        return this.favoriteNames.has(solutionName);
    },

    // Toggle favorite from history item element (fetches full content via detail API)
    toggleFromItem(el) {
        const id = parseInt(el.dataset.id);
        const name = el.dataset.favName || '';
        const industry = el.dataset.favIndustry || '';
        console.log('[Fav:ToggleFromItem] 开始收藏操作', { id, name, industry, type: HistoryUI.currentType });
        if (!id) {
            UI.showToast('记录ID无效', 'warning');
            return;
        }

        // Fetch full content from detail API (not truncated preview from DOM)
        const fetchDetail = HistoryUI.currentType === 'analyze'
            ? API.getCompetitorHistoryDetail(id)
            : API.getHistoryDetail(id);

        fetchDetail.then(item => {
            const fullContent = HistoryUI.currentType === 'analyze'
                ? (item.analysis || '')
                : (item.solution || '');
            console.log('[Fav:ToggleFromItem] 获取到详情，调用toggle()', { contentLen: fullContent.length });
            this.toggle(name, fullContent, industry).then(() => {
                console.log('[Fav:ToggleFromItem] toggle()完成，更新按钮', { isFav: this.isFavorited(name) });
                const btn = el.querySelector('.fav-action-btn');
                if (btn) {
                    btn.textContent = this.isFavorited(name) ? '⭐ 已收藏' : '☆ 收藏';
                    btn.className = this.isFavorited(name) ? 'btn-favorite active fav-action-btn' : 'btn-favorite fav-action-btn';
                }
            }).catch(e => {
                console.error('[Fav:ToggleFromItem] toggle()异常', e);
            });
        }).catch((e) => {
            console.error('[Fav:ToggleFromItem] 获取详情失败', e);
            UI.showToast('获取方案详情失败，请重试', 'warning');
        });
    },

    // Toggle favorite: add if not, remove if already
    async toggle(solutionName, solutionContent, industry) {
        const token = AuthManager.getToken();
        console.log('[Fav:Toggle] 进入toggle()', { solutionName, isFav: this.isFavorited(solutionName), hasToken: !!token, favSetSize: this.favoriteNames.size });
        if (!token) { UI.showToast('请先登录', 'warning'); return; }

        if (this.isFavorited(solutionName)) {
            // Find the favorite id to remove
            try {
                const resp = await fetch('/api/auth/favorites?page_size=50', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await resp.json();
                const fav = data.favorites.find(f => f.solution_name === solutionName);
                console.log('[Fav:Toggle] 取消收藏', { found: !!fav, favId: fav?.id });
                if (fav) {
                    await this._remove(fav.id);
                    this.favoriteNames.delete(solutionName);
                    UI.showToast('已取消收藏', 'info');
                    this.loadForProfile();  // 刷新侧边栏收藏列表
                }
            } catch(e) {
                console.error('[Fav:Toggle] 取消收藏失败', e);
                UI.showToast('取消收藏失败', 'warning');
            }
        } else {
            try {
                const resp = await fetch('/api/auth/favorites/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify({
                        solution_name: solutionName,
                        solution_content: solutionContent || '',
                        industry: industry || ''
                    })
                });
                const data = await resp.json();
                console.log('[Fav:Toggle] 添加收藏响应', { ok: resp.ok, status: resp.status, detail: data.detail || data.message });
                if (resp.ok) {
                    this.favoriteNames.add(solutionName);
                    UI.showToast('⭐ 已收藏', 'success');
                    const refreshResult = await this.loadForProfile();  // 刷新侧边栏收藏列表
                    console.log('[Fav:Toggle] loadForProfile结果', { refreshed: refreshResult });
                } else {
                    console.warn('[Fav:Toggle] 添加收藏API返回失败', data);
                    UI.showToast(data.detail || '收藏失败', 'warning');
                }
            } catch(e) {
                console.error('[Fav:Toggle] 添加收藏异常', e);
                UI.showToast('收藏失败', 'warning');
            }
        }
    },

    async _remove(favId) {
        const token = AuthManager.getToken();
        const resp = await fetch(`/api/auth/favorites/${favId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return resp.ok;
    },

    // Load favorites for display in personal center
    async loadForProfile() {
        const token = AuthManager.getToken();
        if (!token) return false;
        try {
            const resp = await fetch('/api/auth/favorites?page_size=50', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!resp.ok) {
                console.error('[Fav:LoadProfile] API请求失败', { status: resp.status });
                return false;
            }
            const data = await resp.json();
            const newNames = new Set(data.favorites.map(f => f.solution_name));
            console.log('[Fav:LoadProfile] 加载完成', {
                count: data.favorites.length,
                names: [...newNames],
                prevNames: [...this.favoriteNames]
            });
            this.favoriteNames = newNames;
            
            const listEl = document.getElementById('fav-list');
            const emptyEl = document.getElementById('fav-list-empty');
            const countEl = document.getElementById('fav-count');
            
            console.log('[Fav:LoadProfile] DOM元素', {
                listEl: !!listEl,
                emptyEl: !!emptyEl,
                countEl: !!countEl
            });
            
            if (!listEl || !emptyEl) {
                // Elements don't exist yet — they will when profile panel opens
                console.log('[Fav:LoadProfile] 侧边栏元素不存在，仅更新内存数据');
                if (countEl) countEl.textContent = data.favorites.length;
                return true;
            }
            
            if (countEl) countEl.textContent = data.favorites.length;
            
            if (data.favorites.length === 0) {
                listEl.style.display = 'none';
                emptyEl.style.display = '';
                return true;
            }
            
            emptyEl.style.display = 'none';
            listEl.style.display = '';
            listEl.innerHTML = data.favorites.map(f => {
                const dateStr = f.created_at ? f.created_at.replace('T', ' ').substring(0, 10) : '';
                const namePreview = f.solution_name.substring(0, 40);
                return `
                    <div class="profile-fav-item">
                        <div class="profile-fav-item-content" onclick="FavoriteManager.viewFavorite(${f.id})" title="${HistoryUI.escapeHtml(f.solution_name)}">
                            <div class="profile-fav-item-name">${HistoryUI.escapeHtml(namePreview)}${f.solution_name.length > 40 ? '...' : ''}</div>
                            <div class="profile-fav-item-meta">${dateStr}${f.industry ? ' · ' + HistoryUI.escapeHtml(f.industry) : ''}</div>
                        </div>
                        <button class="profile-fav-item-delete" onclick="FavoriteManager.deleteFavorite(${f.id}, '${HistoryUI.escapeHtml(f.solution_name).replace(/'/g, "\\'")}')" title="取消收藏">✕</button>
                    </div>
                `;
            }).join('');
            console.log('[Fav:LoadProfile] 侧边栏渲染完成', { count: data.favorites.length });
            return true;
        } catch(e) {
            console.error('[Fav:LoadProfile] 异常', e);
            return false;
        }
    },

    // View favorite content in detail modal
    async viewFavorite(favId) {
        try {
            const token = AuthManager.getToken();
            const resp = await fetch(`/api/auth/favorites?page_size=50`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!resp.ok) return;
            const data = await resp.json();
            const fav = data.favorites.find(f => f.id === favId);
            if (!fav) return;
            
            const modal = document.getElementById('history-detail-modal');
            const body = document.getElementById('detail-body');
            const headerTitle = modal.querySelector('.modal-header h3');
            if (!modal || !body) return;
            
            // Close profile panel first
            document.getElementById('profile-panel').style.display = 'none';
            
            if (headerTitle) headerTitle.textContent = '⭐ 收藏详情';
            body.innerHTML = `
                <div class="detail-section">
                    <div class="detail-section-label">收藏时间</div>
                    <div style="font-size: var(--font-size-sm); color: var(--text-secondary);">${fav.created_at ? fav.created_at.replace('T', ' ').substring(0, 16) : '--'}</div>
                </div>
                <div class="detail-section">
                    <div class="detail-section-label">方案名称</div>
                    <div class="detail-demand">${HistoryUI.escapeHtml(fav.solution_name)}</div>
                </div>
                ${fav.industry ? `
                <div class="detail-section">
                    <div class="detail-section-label">所属行业</div>
                    <div class="detail-demand">${HistoryUI.escapeHtml(fav.industry)}</div>
                </div>` : ''}
                <div class="detail-section">
                    <div class="detail-section-label">方案内容</div>
                    <div class="detail-solution result-content">${fav.solution_content ? UI.renderMarkdown(fav.solution_content) : '<p style="color: var(--text-muted)">无内容</p>'}</div>
                </div>
            `;
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        } catch(e) {
            console.error('View favorite error:', e);
        }
    },

    // Delete a favorite from personal center
    async deleteFavorite(favId, name) {
        if (!confirm(`确定取消收藏「${name}」？`)) return;
        const token = AuthManager.getToken();
        try {
            const resp = await fetch(`/api/auth/favorites/${favId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (resp.ok) {
                this.favoriteNames.delete(name);
                UI.showToast('已取消收藏', 'info');
                this.loadForProfile();  // Refresh list
            } else {
                UI.showToast('删除失败', 'warning');
            }
        } catch(e) {
            UI.showToast('网络错误', 'warning');
        }
    },

    // 更新结果卡片上的收藏按钮外观
    _updateResultBtn(btnId, name) {
        const btn = document.getElementById(btnId);
        if (!btn) return;
        if (this.isFavorited(name)) {
            btn.textContent = '⭐ 已收藏';
            btn.classList.add('active');
        } else {
            btn.textContent = btnId === 'fav-solution-btn' ? '☆ 收藏方案' : '☆ 收藏报告';
            btn.classList.remove('active');
        }
    }
};

function initEventListeners() {
    document.querySelectorAll('.navbar-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            // 登录检查：Dashboard 和历史记录需要登录
            if ((page === 'dashboard' || page === 'history') && !AuthManager.isLoggedIn()) {
                AuthManager._openModal();
                return;
            }
            PageTransition.switchTo(page).then(() => {
                if (page === 'knowledge') KnowledgeUI.loadStats();
                if (page === 'dashboard') DashboardUI.loadStats();
                if (page === 'history') HistoryUI.loadHistory();
                if (page === 'settings') SettingsManager.updateSystemInfo();
                if (page === 'products') { setTimeout(function() { try { ProductGraph._renderGrid(); } catch(e) { console.warn('[PageSwitch] 产品图谱渲染失败:', e); } }, 100); }
            });
        });
    });

    document.querySelectorAll('.mobile-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            const mobileMenu = document.getElementById('mobile-menu');
            mobileMenu?.classList.remove('open');
            // 登录检查：Dashboard 和历史记录需要登录
            if ((page === 'dashboard' || page === 'history') && !AuthManager.isLoggedIn()) {
                AuthManager._openModal();
                return;
            }
            PageTransition.switchTo(page).then(() => {
                if (page === 'knowledge') KnowledgeUI.loadStats();
                if (page === 'dashboard') DashboardUI.loadStats();
                if (page === 'history') HistoryUI.loadHistory();
                if (page === 'settings') SettingsManager.updateSystemInfo();
                if (page === 'products') { setTimeout(function() { try { ProductGraph._renderGrid(); } catch(e) { console.warn('[PageSwitch] 产品图谱渲染失败:', e); } }, 100); }
            });
        });
    });
    
    const navbarToggle = document.getElementById('navbar-toggle');
    const mobileMenu = document.getElementById('mobile-menu');
    
    navbarToggle?.addEventListener('click', () => {
        mobileMenu.classList.toggle('open');
    });

    // 登录按钮
    document.getElementById('nav-login-btn')?.addEventListener('click', () => {
        AuthManager._openModal();
    });

    // 关闭弹窗
    document.getElementById('auth-modal-close')?.addEventListener('click', () => {
        AuthManager._closeModal();
    });
    document.getElementById('auth-modal-overlay')?.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) AuthManager._closeModal();
    });

    // Tab 切换
    document.querySelectorAll('.auth-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            AuthManager._switchTab(tab.dataset.tab);
        });
    });
    document.getElementById('auth-switch-btn')?.addEventListener('click', () => {
        const activeTab = document.querySelector('.auth-tab.active');
        const target = activeTab && activeTab.dataset.tab === 'login' ? 'register' : 'login';
        AuthManager._switchTab(target);
    });

    // 登录表单提交
    document.getElementById('login-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const captchaImg = document.getElementById('login-captcha-img');
        const captchaKey = captchaImg?.dataset.captchaKey || '';
        await AuthManager.login(
            document.getElementById('login-username').value.trim(),
            document.getElementById('login-password').value,
            captchaKey,
            document.getElementById('login-captcha').value.trim()
        );

        // 登录提交时记录实际用户名，便于排查自动填充问题
        const submittedUser = document.getElementById('login-username').value.trim();
        console.log('[Auth] 登录提交: username=' + submittedUser);
    });

    // 检测浏览器自动填充：用户名字段有内容时展示醒目的确认提示
    const _updateAutoFillHint = () => {
        const hint = document.getElementById('login-auto-fill-hint');
        const hintUser = document.getElementById('login-hint-username');
        const userField = document.getElementById('login-username');
        if (!hint || !hintUser || !userField) return;
        const val = userField.value.trim();
        if (val) {
            hintUser.textContent = val;
            hint.style.display = '';
        } else {
            hint.style.display = 'none';
        }
    };
    document.getElementById('login-username')?.addEventListener('input', () => {
        _updateAutoFillHint();
        // 用户手动修改后，清除延迟二次清空的定时器
        if (AuthManager._autoFillGuardTimer) {
            clearTimeout(AuthManager._autoFillGuardTimer);
            AuthManager._autoFillGuardTimer = null;
        }
    });
    // 也监听 change（浏览器自动填充不一定会触发 input）
    document.getElementById('login-username')?.addEventListener('change', _updateAutoFillHint);
    // 密码字段同理：自动填充完成后更新提示
    document.getElementById('login-password')?.addEventListener('change', _updateAutoFillHint);

    // 注册表单提交
    document.getElementById('register-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const pwd = document.getElementById('register-password').value;
        const confirm = document.getElementById('register-password-confirm').value;
        if (pwd !== confirm) {
            AuthManager._showError('register', '两次密码不一致');
            return;
        }
        const captchaImg = document.getElementById('register-captcha-img');
        const captchaKey = captchaImg?.dataset.captchaKey || '';
        await AuthManager.register(
            document.getElementById('register-username').value.trim(),
            document.getElementById('register-email').value.trim(),
            pwd,
            captchaKey,
            document.getElementById('register-captcha').value.trim()
        );
    });

    // 验证码刷新
    document.getElementById('login-captcha-img')?.addEventListener('click', () => AuthManager.loadCaptcha(true));
    document.getElementById('register-captcha-img')?.addEventListener('click', () => AuthManager.loadCaptcha(false));

    // 用户菜单下拉
    document.getElementById('nav-user-avatar-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const dropdown = document.getElementById('user-dropdown');
        const menu = document.getElementById('nav-user-menu');
        const show = dropdown.style.display === 'none';
        dropdown.style.display = show ? '' : 'none';
        menu.classList.toggle('open', show);
    });
    document.addEventListener('click', () => {
        document.getElementById('user-dropdown').style.display = 'none';
        document.getElementById('nav-user-menu')?.classList.remove('open');
    });

    // 退出登录
    document.getElementById('dropdown-logout')?.addEventListener('click', () => {
        AuthManager.logout();
    });

    // ===== 个人中心 =====
    // 打开个人中心
    document.getElementById('dropdown-profile')?.addEventListener('click', () => {
        // Close dropdown
        document.getElementById('user-dropdown').style.display = 'none';
        document.getElementById('nav-user-menu')?.classList.remove('open');
        // Open profile panel
        const panel = document.getElementById('profile-panel');
        panel.style.display = '';
        loadProfileData();
    });

    // 关闭个人中心
    document.getElementById('close-profile')?.addEventListener('click', closeProfilePanel);
    document.getElementById('profile-backdrop')?.addEventListener('click', closeProfilePanel);

    function closeProfilePanel() {
        document.getElementById('profile-panel').style.display = 'none';
    }

    async function loadProfileData() {
        const token = AuthManager.getToken();
        if (!token) return;

        try {
            // Fetch user info
            const meResp = await fetch('/api/auth/me', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!meResp.ok) throw new Error('Failed to load profile');
            const userData = await meResp.json();

            // Update UI
            const initial = (userData.username || 'U')[0].toUpperCase();
            document.getElementById('profile-avatar').textContent = initial;
            document.getElementById('profile-username').textContent = userData.username;
            document.getElementById('profile-role').textContent = userData.role === 'admin' ? '管理员' : '普通用户';
            document.getElementById('info-username').textContent = userData.username;
            document.getElementById('info-email').textContent = userData.email || '未设置';
            // 如果有邮箱则显示邮箱行，否则保持隐藏
            const emailDisplayRow = document.getElementById('email-display-row');
            if (userData.email) {
                if (emailDisplayRow) emailDisplayRow.style.display = '';
            }
            document.getElementById('info-role').textContent = userData.role === 'admin' ? '管理员' : '普通用户';

            // Format dates
            if (userData.created_at) {
                document.getElementById('info-created').textContent = new Date(userData.created_at).toLocaleDateString('zh-CN');
            }
            if (userData.last_login) {
                document.getElementById('info-last-login').textContent = new Date(userData.last_login).toLocaleString('zh-CN');
            }

            // Fetch stats
            try {
                const statsResp = await fetch('/api/auth/stats', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (statsResp.ok) {
                    const stats = await statsResp.json();
                    document.getElementById('stat-match').textContent = stats.match_count || 0;
                    document.getElementById('stat-analyze').textContent = stats.analyze_count || 0;
                    document.getElementById('stat-favorites').textContent = stats.favorites_count || 0;
                    document.getElementById('stat-history').textContent = stats.history_count || 0;
                }
            } catch (e) {
                // Stats are non-critical, fail silently
            }

            // Load favorites list for profile display
            FavoriteManager.loadForProfile();
        } catch (e) {
            console.error('Failed to load profile:', e);
        }
    }

    // 编辑邮箱
    document.getElementById('btn-edit-email')?.addEventListener('click', () => {
        // 隐藏显示行，显示编辑行
        document.getElementById('email-display-row').style.display = 'none';
        document.getElementById('email-edit-row').style.display = '';
        const currentEmail = document.getElementById('info-email').textContent;
        document.getElementById('input-new-email').value = currentEmail !== '未设置' ? currentEmail : '';
        document.getElementById('input-new-email').focus();
    });

    document.getElementById('btn-cancel-email')?.addEventListener('click', () => {
        document.getElementById('email-edit-row').style.display = 'none';
        // 恢复显示行（仅当邮箱已设置时）
        const email = document.getElementById('info-email').textContent;
        const emailDisplayRow = document.getElementById('email-display-row');
        if (email !== '未设置' && emailDisplayRow) {
            emailDisplayRow.style.display = '';
        }
    });

    document.getElementById('btn-save-email')?.addEventListener('click', async () => {
        const email = document.getElementById('input-new-email').value.trim();
        if (!email) {
            alert('请输入邮箱地址');
            return;
        }

        const token = AuthManager.getToken();
        try {
            const resp = await fetch('/api/auth/profile', {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ email })
            });
            const data = await resp.json();
            if (resp.ok) {
                document.getElementById('info-email').textContent = email;
                document.getElementById('email-edit-row').style.display = 'none';
                // 保存成功后显示邮箱行
                document.getElementById('email-display-row').style.display = '';
                alert('邮箱更新成功');
            } else {
                alert(data.detail || '更新失败');
            }
        } catch (e) {
            alert('网络错误，请重试');
        }
    });

    // 修改密码
    document.getElementById('btn-change-password')?.addEventListener('click', () => {
        document.getElementById('password-section-view').style.display = 'none';
        document.getElementById('password-section-edit').style.display = '';
        document.getElementById('input-old-password').value = '';
        document.getElementById('input-new-password').value = '';
        document.getElementById('input-confirm-password').value = '';
        const errEl = document.getElementById('profile-password-error');
        errEl.style.display = 'none';
    });

    document.getElementById('btn-cancel-password')?.addEventListener('click', () => {
        document.getElementById('password-section-view').style.display = '';
        document.getElementById('password-section-edit').style.display = 'none';
    });

    document.getElementById('btn-save-password')?.addEventListener('click', async () => {
        const oldPwd = document.getElementById('input-old-password').value;
        const newPwd = document.getElementById('input-new-password').value;
        const confirmPwd = document.getElementById('input-confirm-password').value;
        const errEl = document.getElementById('profile-password-error');

        if (!oldPwd || !newPwd) {
            errEl.textContent = '请填写完整';
            errEl.style.display = '';
            return;
        }
        if (newPwd.length < 6) {
            errEl.textContent = '新密码至少6位';
            errEl.style.display = '';
            return;
        }
        if (newPwd !== confirmPwd) {
            errEl.textContent = '两次输入的新密码不一致';
            errEl.style.display = '';
            return;
        }

        const token = AuthManager.getToken();
        try {
            const resp = await fetch('/api/auth/change-password', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ old_password: oldPwd, new_password: newPwd })
            });
            const data = await resp.json();
            if (resp.ok) {
                errEl.style.display = 'none';
                alert('密码修改成功');
                document.getElementById('password-section-view').style.display = '';
                document.getElementById('password-section-edit').style.display = 'none';
            } else {
                errEl.textContent = data.detail || '修改失败';
                errEl.style.display = '';
            }
        } catch (e) {
            errEl.textContent = '网络错误，请重试';
            errEl.style.display = '';
        }
    });

    // 退出登录（面板内按钮）
    document.getElementById('btn-profile-logout')?.addEventListener('click', () => {
        closeProfilePanel();
        AuthManager.logout();
    });
    
    const demandInput = document.getElementById('demand-input');
    const charCount = document.getElementById('demand-char-count');
    
    demandInput?.addEventListener('input', () => {
        const length = demandInput.value.length;
        charCount.textContent = length;
        
        if (length > 2000) {
            charCount.style.color = 'var(--error)';
        } else {
            charCount.style.color = 'var(--text-secondary)';
        }
    });
    
    const matchBtn = document.getElementById('match-btn');
    const matchBtnText = matchBtn?.querySelector('.btn-text');

    matchBtn?.addEventListener('click', async () => {
        // --- 取消模式 ---
        if (State.loadingStates.match) {
            if (State.abortControllers.match) {
                State.abortControllers.match.abort();
            }
            MatchProgress.cancel();
            State.loadingStates.match = false;
            if (matchBtnText) matchBtnText.textContent = '开始匹配';
            matchBtn.classList.remove('btn-cancel');
            UI.setButtonLoading(matchBtn, false);
            State.abortControllers.match = null;
            UI.showToast('已取消匹配', 'info');
            return;
        }

        // 登录检查：未登录且非快速体验 → 弹出登录窗口
        if (!AuthManager.isLoggedIn() && !State.isQuickDemo) {
            AuthManager._openModal();
            return;
        }

        const demand = demandInput.value.trim();
        
        if (!demand) {
            UI.showToast('请输入客户需求描述', 'warning');
            return;
        }
        
        if (demand.length > 2000) {
            UI.showToast('需求描述不能超过2000字符', 'warning');
            return;
        }

        // 隐藏之前的结果
        document.getElementById('solution-result').style.display = 'none';
        
        // 创建 AbortController
        const controller = new AbortController();
        State.abortControllers.match = controller;
        State.loadingStates.match = true;
        
        // 切换为取消按钮
        if (matchBtnText) matchBtnText.textContent = '取消匹配';
        matchBtn.classList.add('btn-cancel');
        
        // 启动进度面板
        MatchProgress.start();
        MatchProgress.simulateProgress(3, 6000);
        
        try {
            SkeletonUI.showMatchFormSkeleton();
            const result = await API.match(demand, controller.signal);
            
            // API返回，显示完成
            console.log('[SolutionMatch] API返回结果:', {
                hasAnswer: !!result?.answer,
                answerLength: result?.answer?.length || 0,
                answerPreview: result?.answer?.substring(0, 100) || '(empty)',
                sourceCount: result?.source_documents?.length || 0,
                historyId: result?.history_id
            });
            MatchProgress.success('方案匹配完成！');
            
            const resultContainer = document.getElementById('solution-result');
            const resultContent = document.getElementById('solution-content');
            const sourcesContainer = document.getElementById('solution-sources');
            
            // 防御性检查：如果容器被异常清空导致子元素丢失，尝试重建
            if (!resultContainer || !resultContent) {
                console.warn('[SolutionMatch] 结果容器异常，尝试恢复...', {
                    resultContainer: !!resultContainer,
                    resultContent: !!resultContent
                });
                var existingContainer2 = document.getElementById('solution-result');
                if (existingContainer2 && !document.getElementById('solution-content')) {
                    existingContainer2.innerHTML = `
                        <div class="result-header"><span class="result-badge success">✅ 匹配完成</span></div>
                        <div class="result-content content-card" id="solution-content"></div>
                        <div class="result-actions">
                            <button class="btn btn-primary" id="download-solution-btn">📥 下载方案报告</button>
                            <button class="btn btn-favorite-result" id="fav-solution-btn">☆ 收藏方案</button>
                        </div>
                        <details class="source-documents content-card">
                            <summary class="source-summary">📚 查看参考的解决方案文档</summary>
                            <div id="solution-sources"></div>
                        </details>
                    `;
                    resultContainer = existingContainer2;
                    resultContent = document.getElementById('solution-content');
                    sourcesContainer = document.getElementById('solution-sources');
                    var dlBtn2 = document.getElementById('download-solution-btn');
                    if (dlBtn2) dlBtn2.addEventListener('click', function() {
                        if (State.resultCache.match) {
                            var r = State.resultCache.match;
                            UI.downloadFile(r.answer, '华为云_' + (r.industry || '解决方案') + '_方案匹配报告.md');
                        }
                    });
                }
            }
            
            if (!resultContainer || !resultContent) {
                console.error('[SolutionMatch] 方案结果容器无法恢复', {
                    resultContainer: !!resultContainer,
                    resultContent: !!resultContent,
                    sourcesContainer: !!sourcesContainer
                });
                UI.showToast('匹配完成，但页面结构异常，请刷新后重试', 'warning');
                return;
            }
            
            // 检查 answer 是否有效
            if (!result || !result.answer || (typeof result.answer === 'string' && result.answer.trim() === '')) {
                console.warn('[SolutionMatch] API返回的answer为空', result);
                resultContent.innerHTML = '<div class="result-empty"><p style="color: var(--text-secondary); text-align: center; padding: 40px 20px;">⚠️ 匹配服务返回了空结果，请稍后重试。</p></div>';
                resultContainer.style.display = 'block';
                return;
            }
            
            // 安全渲染 Markdown
            try {
                resultContent.innerHTML = UI.renderMarkdown(result.answer);
            } catch (renderErr) {
                console.error('[SolutionMatch] Markdown渲染失败:', renderErr);
                const escapedText = (result.answer || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                resultContent.innerHTML = '<div class="result-content"><p>方案已生成，但渲染失败。请尝试下载报告查看完整内容。</p><pre style="white-space: pre-wrap; max-height: 300px; overflow-y: auto;">' + escapedText.substring(0, 2000) + '</pre></div>';
            }
            UI.renderSources(sourcesContainer, result.source_documents);
            resultContainer.style.display = 'block';
            resultContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });

            State.resultCache.solution = { ...result, demand };
            // 更新收藏按钮状态
            FavoriteManager._updateResultBtn('fav-solution-btn', demand);
            FollowUpUI.show(demand, result.answer, result.history_id);

            // 高亮功能已按需求移除 —— 用户只需要点击查看产品详情
        } catch (error) {
            if (error.name === 'AbortError') {
                // 用户主动取消，不报错
                console.log('匹配已取消');
                return;
            }
            console.error('匹配失败:', error);
            MatchProgress.error('匹配失败，请重试');
            UI.showToast(error.message || '匹配失败，请重试', 'error');
        } finally {
            State.loadingStates.match = false;
            State.isQuickDemo = false;
            if (matchBtnText) matchBtnText.textContent = '开始匹配';
            matchBtn.classList.remove('btn-cancel');
            State.abortControllers.match = null;
        }
    });
    
    document.getElementById('clear-solution-btn')?.addEventListener('click', () => {
        // 如果正在匹配，先触发取消
        if (State.loadingStates.match && matchBtn) {
            matchBtn.click();
        }
        demandInput.value = '';
        charCount.textContent = '0';
        document.getElementById('solution-result').style.display = 'none';
        MatchProgress.hide();
        State.resultCache.solution = null;
    });
    
    document.getElementById('download-solution-btn')?.addEventListener('click', () => {
        if (State.resultCache.solution) {
            UI.downloadFile(
                State.resultCache.solution.answer,
                '华为云解决方案建议书.md'
            );
        }
    });

    document.getElementById('fav-solution-btn')?.addEventListener('click', () => {
        const cached = State.resultCache.solution;
        if (!cached) return;
        const name = (cached.demand || '方案匹配结果').substring(0, 50);
        FavoriteManager.toggle(name, cached.answer || '', '');
        FavoriteManager._updateResultBtn('fav-solution-btn', name);
    });
    
    const analyzeBtn = document.getElementById('analyze-btn');
    const analyzeBtnText = analyzeBtn?.querySelector('.btn-text');

    analyzeBtn?.addEventListener('click', async () => {
        // --- 取消模式 ---
        if (State.loadingStates.analyze) {
            if (State.abortControllers.analyze) {
                State.abortControllers.analyze.abort();
            }
            AnalyzeProgress.cancel();
            State.loadingStates.analyze = false;
            if (analyzeBtnText) analyzeBtnText.textContent = '开始分析';
            analyzeBtn.classList.remove('btn-cancel');
            UI.setButtonLoading(analyzeBtn, false);
            State.abortControllers.analyze = null;
            UI.showToast('已取消分析', 'info');
            return;
        }

        const competitor = document.getElementById('competitor-select').value;
        const industry = document.getElementById('industry-select').value;
        
        // 隐藏之前的结果
        document.getElementById('competitor-result').style.display = 'none';
        
        // 创建 AbortController
        const controller = new AbortController();
        State.abortControllers.analyze = controller;
        State.loadingStates.analyze = true;
        
        // 切换为取消按钮
        if (analyzeBtnText) analyzeBtnText.textContent = '取消分析';
        analyzeBtn.classList.add('btn-cancel');
        
        // 启动进度面板
        AnalyzeProgress.start();
        AnalyzeProgress.simulateProgress(4, 8000);
        
        try {
            SkeletonUI.showCompetitorSkeleton();
            const result = await API.analyze(competitor, industry, controller.signal);
            
            // API返回，显示完成
            console.log('[CompetitorAnalysis] API返回结果:', {
                hasAnswer: !!result?.answer,
                answerLength: result?.answer?.length || 0,
                answerPreview: result?.answer?.substring(0, 100) || '(empty)',
                sourceCount: result?.source_documents?.length || 0,
                historyId: result?.history_id
            });
            AnalyzeProgress.success('竞争分析完成！');
            
            const resultContainer = document.getElementById('competitor-result');
            const resultContent = document.getElementById('competitor-content');
            const sourcesContainer = document.getElementById('competitor-sources');
            
            // 防御性检查：如果容器被异常清空导致子元素丢失，尝试重建
            if (!resultContainer || !resultContent) {
                console.warn('[CompetitorAnalysis] 结果容器异常，尝试恢复...', {
                    resultContainer: !!resultContainer,
                    resultContent: !!resultContent
                });
                // 如果competitor-result还在但competitor-content丢了，重建content
                var existingContainer = document.getElementById('competitor-result');
                if (existingContainer && !document.getElementById('competitor-content')) {
                    existingContainer.innerHTML = `
                        <div class="result-header"><span class="result-badge success">✅ 分析完成</span></div>
                        <div class="result-content content-card" id="competitor-content"></div>
                        <div class="result-actions">
                            <button class="btn btn-primary" id="download-competitor-btn">📥 下载竞争分析报告</button>
                            <button class="btn btn-favorite-result" id="fav-competitor-btn">☆ 收藏报告</button>
                        </div>
                        <details class="source-documents content-card">
                            <summary class="source-summary">📚 查看参考的解决方案文档</summary>
                            <div id="competitor-sources"></div>
                        </details>
                    `;
                    resultContainer = existingContainer;
                    resultContent = document.getElementById('competitor-content');
                    sourcesContainer = document.getElementById('competitor-sources');
                    // 重新绑定下载按钮
                    var dlBtn = document.getElementById('download-competitor-btn');
                    if (dlBtn) dlBtn.addEventListener('click', function() {
                        if (State.resultCache.competitor) {
                            var r = State.resultCache.competitor;
                            UI.downloadFile(r.answer, '华为云_vs_' + (r.competitor || '竞品') + '_竞争分析报告.md');
                        }
                    });
                }
            }
            
            if (!resultContainer || !resultContent) {
                console.error('[CompetitorAnalysis] 竞品分析结果容器无法恢复', {
                    resultContainer: !!resultContainer,
                    resultContent: !!resultContent,
                    sourcesContainer: !!sourcesContainer
                });
                UI.showToast('分析完成，但页面结构异常，请刷新后重试', 'warning');
                return;
            }
            
            // 检查 answer 是否有效
            if (!result || !result.answer || (typeof result.answer === 'string' && result.answer.trim() === '')) {
                console.warn('[CompetitorAnalysis] API返回的answer为空', result);
                resultContent.innerHTML = '<div class="result-empty"><p style="color: var(--text-secondary); text-align: center; padding: 40px 20px;">⚠️ 分析服务返回了空结果，请稍后重试。</p></div>';
                resultContainer.style.display = 'block';
                return;
            }
            
            // 安全渲染 Markdown，防止 marked.parse() 异常导致空白
            try {
                resultContent.innerHTML = UI.renderMarkdown(result.answer);
            } catch (renderErr) {
                console.error('[CompetitorAnalysis] Markdown渲染失败:', renderErr);
                const escapedText = (result.answer || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                resultContent.innerHTML = '<div class="result-content"><p>分析结果已生成，但渲染失败。请尝试下载报告查看完整内容。</p><pre style="white-space: pre-wrap; max-height: 300px; overflow-y: auto;">' + escapedText.substring(0, 2000) + '</pre></div>';
            }
            UI.renderSources(sourcesContainer, result.source_documents);
            resultContainer.style.display = 'block';
            resultContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
            
            State.resultCache.competitor = { ...result, competitor, industry };
            // 更新收藏按钮状态
            const compFavName = `华为云 vs ${competitor} 竞争分析报告`;
            FavoriteManager._updateResultBtn('fav-competitor-btn', compFavName);
            
            UI.showToast('分析完成！', 'success');
            CompetitorFollowUpUI.show(competitor, industry, result.answer, result.history_id);
        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('分析已取消');
                return;
            }
            console.error('分析失败:', error);
            AnalyzeProgress.error('分析失败，请重试');
            UI.showToast(error.message || '分析失败，请重试', 'error');
        } finally {
            State.loadingStates.analyze = false;
            if (analyzeBtnText) analyzeBtnText.textContent = '开始分析';
            analyzeBtn.classList.remove('btn-cancel');
            State.abortControllers.analyze = null;
        }
    });
    
    document.getElementById('clear-competitor-btn')?.addEventListener('click', () => {
        // 如果正在分析，先触发取消
        if (State.loadingStates.analyze && analyzeBtn) {
            analyzeBtn.click();
        }
        document.getElementById('competitor-result').style.display = 'none';
        AnalyzeProgress.hide();
        State.resultCache.competitor = null;
        CompetitorFollowUpUI.hide();
    });
    
    document.getElementById('download-competitor-btn')?.addEventListener('click', () => {
        if (State.resultCache.competitor) {
            const { competitor, industry, answer } = State.resultCache.competitor;
            UI.downloadFile(
                answer,
                `华为云vs${competitor}_${industry}行业竞争分析报告.md`
            );
        }
    });

    document.getElementById('fav-competitor-btn')?.addEventListener('click', () => {
        const cached = State.resultCache.competitor;
        if (!cached) return;
        const name = `华为云 vs ${cached.competitor} 竞争分析报告`;
        FavoriteManager.toggle(name, cached.answer || '', cached.industry || '');
        FavoriteManager._updateResultBtn('fav-competitor-btn', name);
    });
    
    const rebuildBtn = document.getElementById('rebuild-btn');
    const rebuildProgressPanel = document.getElementById('rebuild-progress-panel');
    const rebuildStatusText = document.getElementById('rebuild-status-text');
    
    rebuildBtn?.addEventListener('click', async () => {
        UI.setButtonLoading(rebuildBtn, true);
        
        // 显示重建进度面板
        if (rebuildProgressPanel) {
            rebuildProgressPanel.style.display = 'block';
            rebuildProgressPanel.classList.remove('success', 'fade-out');
        }
        if (rebuildStatusText) rebuildStatusText.textContent = '正在读取文档目录...';
        
        // 模拟状态更新
        const statusMessages = [
            { delay: 1500, text: '正在加载华为云方案文档...' },
            { delay: 3000, text: '正在加载竞品方案文档...' },
            { delay: 5000, text: '正在分割文档为片段...' },
            { delay: 7000, text: '正在生成向量嵌入（这可能需要一些时间）...' },
            { delay: 10000, text: '正在写入向量数据库...' }
        ];
        
        const statusTimers = statusMessages.map(msg => 
            setTimeout(() => {
                if (rebuildStatusText) rebuildStatusText.textContent = msg.text;
            }, msg.delay)
        );
        
        try {
            const result = await API.rebuildKnowledge();
            
            // 清除所有定时器
            statusTimers.forEach(t => clearTimeout(t));
            
            // 显示成功状态
            if (rebuildProgressPanel) {
                rebuildProgressPanel.classList.add('success');
                const title = rebuildProgressPanel.querySelector('.progress-title');
                if (title) title.textContent = '知识库重建完成！';
            }
            if (rebuildStatusText) {
                rebuildStatusText.textContent = `成功添加 ${result.count || 0} 个文档片段到知识库`;
            }
            
            UI.showToast(`知识库重建完成！共添加 ${result.count || 0} 个文档片段`, 'success');
            await KnowledgeUI.loadStats();
            
            // 3秒后淡出
            setTimeout(() => {
                if (rebuildProgressPanel) {
                    rebuildProgressPanel.classList.add('fade-out');
                    setTimeout(() => {
                        rebuildProgressPanel.style.display = 'none';
                        rebuildProgressPanel.classList.remove('success', 'fade-out');
                    }, 500);
                }
            }, 3000);
        } catch (error) {
            // 清除所有定时器
            statusTimers.forEach(t => clearTimeout(t));
            
            console.error('重建失败:', error);
            if (rebuildProgressPanel) {
                rebuildProgressPanel.classList.remove('success');
                const title = rebuildProgressPanel.querySelector('.progress-title');
                if (title) title.textContent = '重建失败';
            }
            if (rebuildStatusText) rebuildStatusText.textContent = error.message || '重建失败，请重试';
            UI.showToast(error.message || '重建失败，请重试', 'error');
        } finally {
            UI.setButtonLoading(rebuildBtn, false);
        }
    });
    
    const clearKbBtn = document.getElementById('clear-kb-btn');
    const confirmDialog = document.getElementById('confirm-clear');
    const confirmCheckbox = document.getElementById('confirm-checkbox');
    const confirmClearBtn = document.getElementById('confirm-clear-btn');
    
    clearKbBtn?.addEventListener('click', () => {
        confirmDialog.style.display = 'flex';
    });
    
    confirmClearBtn?.addEventListener('click', async () => {
        if (!confirmCheckbox.checked) {
            UI.showToast('请先确认清空知识库', 'warning');
            return;
        }
        
        try {
            await API.clearKnowledge();
            UI.showToast('知识库已清空', 'success');
            confirmDialog.style.display = 'none';
            confirmCheckbox.checked = false;
            await KnowledgeUI.loadStats();
        } catch (error) {
            console.error('清空失败:', error);
            UI.showToast(error.message || '清空失败，请重试', 'error');
        }
    });
}

const FollowUpUI = {
    history: [],
    originalDemand: '',
    currentSolution: '',
    currentHistoryId: null,

    init() {
        const input = document.getElementById('follow-up-input');
        const sendBtn = document.getElementById('send-follow-up-btn');
        const clearBtn = document.getElementById('clear-follow-up-btn');
        if (sendBtn) sendBtn.addEventListener('click', () => this.sendFollowUp());
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendFollowUp();
                }
            });
        }
        if (clearBtn) clearBtn.addEventListener('click', () => this.clearHistory());

        const applyBtn = document.getElementById('apply-refined-btn');
        if (applyBtn) applyBtn.addEventListener('click', () => this.applyRefined());
    },

    show(originalDemand, currentSolution, historyId) {
        this.originalDemand = originalDemand;
        this.currentSolution = currentSolution;
        this.currentHistoryId = historyId || null;
        this.history = [];
        const section = document.getElementById('follow-up-section');
        if (section) section.style.display = 'block';
        this.renderHistory();
    },

    hide() {
        const section = document.getElementById('follow-up-section');
        if (section) section.style.display = 'none';
        this.history = [];
    },

    async sendFollowUp() {
        const input = document.getElementById('follow-up-input');
        const text = input?.value?.trim();
        if (!text) return;
        this.history.push({ role: 'user', content: text });
        this.renderHistory();
        if (input) input.value = '';
        this.showLoading(true);
        try {
            const data = await API.refineSolution(
                this.originalDemand,
                this.currentSolution,
                text,
                this.history.slice(0, -1)
            );
            this.history.push({ role: 'ai', content: data.refined_solution });
            this.currentSolution = data.refined_solution;
            this.renderHistory();
        } catch (error) {
            console.error('方案优化失败:', error);
            UI.showToast('方案优化失败: ' + error.message, 'error');
        } finally {
            this.showLoading(false);
        }
    },

    renderHistory() {
        const container = document.getElementById('follow-up-history');
        if (!container) return;
        container.innerHTML = this.history.map(msg => {
            if (msg.role === 'user') {
                return '<div class="follow-up-msg follow-up-user-msg">' + this.escapeHtml(msg.content) + '</div>';
            } else {
                return '<div class="follow-up-msg follow-up-ai-msg"><div class="result-content">' + UI.renderMarkdown(msg.content) + '</div></div>';
            }
        }).join('');
        container.scrollTop = container.scrollHeight;

        // 显示/隐藏"使用此优化结果"按钮
        const actions = document.getElementById('follow-up-actions');
        if (actions) {
            const hasAiMsg = this.history.some(m => m.role === 'ai');
            actions.style.display = hasAiMsg && this.currentHistoryId ? 'flex' : 'none';
        }
    },

    showLoading(show) {
        const loadingEl = document.getElementById('follow-up-loading');
        const sendBtn = document.getElementById('send-follow-up-btn');
        if (loadingEl) loadingEl.style.display = show ? 'flex' : 'none';
        if (sendBtn) sendBtn.disabled = show;
    },

    clearHistory() {
        this.history = [];
        this.renderHistory();
    },

    async applyRefined() {
        if (!this.currentHistoryId || !this.currentSolution) return;
        const btn = document.getElementById('apply-refined-btn');
        if (btn) btn.disabled = true;
        try {
            await API.updateHistorySolution(this.currentHistoryId, this.currentSolution);
            UI.showToast('方案已更新到历史记录', 'success');
        } catch (error) {
            console.error('更新历史方案失败:', error);
            UI.showToast('更新失败: ' + error.message, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

const CompetitorFollowUpUI = {
    history: [],
    originalCompetitor: '',
    originalIndustry: '',
    currentAnalysis: '',
    currentHistoryId: null,

    init() {
        const input = document.getElementById('competitor-follow-up-input');
        const sendBtn = document.getElementById('send-competitor-follow-up-btn');
        const clearBtn = document.getElementById('clear-competitor-follow-up-btn');
        const applyBtn = document.getElementById('apply-competitor-refined-btn');
        if (sendBtn) sendBtn.addEventListener('click', () => this.sendFollowUp());
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendFollowUp();
                }
            });
        }
        if (clearBtn) clearBtn.addEventListener('click', () => this.clearHistory());
        if (applyBtn) applyBtn.addEventListener('click', () => this.applyRefined());
    },

    show(competitor, industry, currentAnalysis, historyId) {
        this.originalCompetitor = competitor;
        this.originalIndustry = industry;
        this.currentAnalysis = currentAnalysis;
        this.currentHistoryId = historyId || null;
        this.history = [];
        const section = document.getElementById('competitor-follow-up-section');
        if (section) section.style.display = 'block';
        this.renderHistory();
    },

    hide() {
        const section = document.getElementById('competitor-follow-up-section');
        if (section) section.style.display = 'none';
        this.history = [];
        this.currentHistoryId = null;
    },

    async sendFollowUp() {
        const input = document.getElementById('competitor-follow-up-input');
        const text = input?.value?.trim();
        if (!text) return;
        this.history.push({ role: 'user', content: text });
        this.renderHistory();
        if (input) input.value = '';
        this.showLoading(true);
        try {
            const data = await API.refineCompetitorAnalysis(
                this.originalCompetitor,
                this.originalIndustry,
                this.currentAnalysis,
                text,
                this.history.slice(0, -1)
            );
            this.history.push({ role: 'ai', content: data.refined_analysis });
            this.currentAnalysis = data.refined_analysis;
            this.renderHistory();
        } catch (error) {
            console.error('分析优化失败:', error);
            UI.showToast('分析优化失败: ' + error.message, 'error');
        } finally {
            this.showLoading(false);
        }
    },

    renderHistory() {
        const container = document.getElementById('competitor-follow-up-history');
        if (!container) return;
        container.innerHTML = this.history.map(msg => {
            if (msg.role === 'user') {
                return '<div class="follow-up-msg follow-up-user-msg">' + this.escapeHtml(msg.content) + '</div>';
            } else {
                return '<div class="follow-up-msg follow-up-ai-msg"><div class="result-content">' + UI.renderMarkdown(msg.content) + '</div></div>';
            }
        }).join('');
        container.scrollTop = container.scrollHeight;

        // 显示/隐藏"使用此优化结果"按钮
        const actions = document.getElementById('competitor-follow-up-actions');
        if (actions) {
            const hasAiMsg = this.history.some(m => m.role === 'ai');
            actions.style.display = hasAiMsg && this.currentHistoryId ? 'flex' : 'none';
        }
    },

    showLoading(show) {
        const loadingEl = document.getElementById('competitor-follow-up-loading');
        const sendBtn = document.getElementById('send-competitor-follow-up-btn');
        if (loadingEl) loadingEl.style.display = show ? 'flex' : 'none';
        if (sendBtn) sendBtn.disabled = show;
    },

    clearHistory() {
        this.history = [];
        this.renderHistory();
    },

    async applyRefined() {
        if (!this.currentHistoryId || !this.currentAnalysis) return;
        const btn = document.getElementById('apply-competitor-refined-btn');
        if (btn) btn.disabled = true;
        try {
            await API.updateCompetitorHistorySolution(this.currentHistoryId, this.currentAnalysis);
            UI.showToast('分析报告已更新到历史记录', 'success');
            // 不隐藏对话，用户可以继续追问
        } catch (error) {
            console.error('更新竞品分析历史失败:', error);
            UI.showToast('更新失败: ' + error.message, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

function init() {
    try {
        console.log('[Init] 华为云方案匹配系统 v20260531k 正在初始化...');
        const canvas = document.getElementById('particle-canvas');
        if (canvas) {
            new ParticleSystem(canvas);
        }

        initEventListeners();
        HistoryUI.init();
        FollowUpUI.init();
        CompetitorFollowUpUI.init();
        AuthManager.init();
        SettingsManager.init();
        ErrorHandler.init();
        FavoriteManager.init();

        // 初始化产品图谱模块（容错：DOM未就绪时不崩溃）
        try { ProductGraph.init(); } catch (e) {
            console.warn('[Init] ProductGraph初始化延迟，切换到产品页时会重试:', e.message);
        }
        try { ArchTree3D.init(); } catch (e) {
            console.warn('[Init] ArchTree3D初始化失败:', e.message);
        }

        // 隐藏分页容器（无数据时）
        const pagContainer = document.getElementById('pagination-container');
        if (pagContainer) pagContainer.style.display = 'none';

        KnowledgeUI.loadStats();
    } catch (e) {
        console.error('[Init] 初始化失败:', e);
    }
}

document.addEventListener('DOMContentLoaded', init);


/* ==================== 产品图谱模块（网格卡片布局版）==================== */

const ProductGraph = {
    // 状态
    state: {
        selectedNode: null,
        activeFilter: 'all',
        searchQuery: '',
        highlightedProducts: [],
        coreProducts: [],
        nodes: {},
        nodeElements: {},
        groupElements: {}
    },

    // 分类配置
    categories: {
        compute:   { label: '计算',     icon: '☁️', color: '#3B82F6' },
        network:   { label: '网络',     icon: '🌐', color: '#F59E0B' },
        storage:   { label: '存储',     icon: '📂', color: '#22C55E' },
        database:  { label: '数据库',   icon: '📄',  color: '#A855F7' },
        ai:         { label: 'AI/大数据', icon: '🤖',  color: '#EF4444' },
        iot:       { label: 'IoT',      icon: '📡',  color: '#F97316' },
        security:  { label: '安全',     icon: '🛡️',  color: '#EC4899' },
        media:     { label: '音视频/CDN', icon: '🎬',  color: '#06B6D4' },
        enterprise:{ label: '企业应用', icon: '💼',  color: '#84CC16' }
    },

    categoryOrder: ['compute', 'network', 'database', 'storage', 'ai', 'iot', 'security', 'media', 'enterprise'],

    productTree: [
        // 计算
        { id:'ecs', name:'ECS 弹性云服务器', nameEn:'Elastic Cloud Server', category:'compute', desc:'华为云弹性云服务器（ECS）是一款可随时获取、弹性伸缩的云服务器服务。支持多种实例规格族，涵盖通用计算、内存优化、GPU加速、裸金属等多种类型，满足不同业务场景的计算需求。用户可根据业务负载灵活调整资源配置，实现分钟级资源交付和秒级计费，显著降低IT基础设施成本。', capabilities:['分钟级弹性伸缩','通用/计算/内存/GPU多规格族','自定义镜像与快照','SSD云硬盘高速IO','安全组与网络ACL','云监控与告警','裸金属服务器融合','多可用区部署','IPv6双栈支持','弹性公网IP绑定'], scenarios:['Web应用与网站托管','企业ERP/CRM系统','电商大促弹性扩容','AI推理与深度学习','高性能科学计算','游戏服务端部署','视频编解码处理','金融核心交易系统','容器化微服务架构','开发测试环境'] , advantages:['弹性灵活：支持按需扩容缩容，分钟级资源交付','成本优化：按需/包周期多种计费模式，降低CAPEX','安全可靠：多AZ容灾、安全组隔离、数据加密','生态丰富：与OBS/RDS/VPC等200+服务深度集成'], highlights:['99.95%可用性SLA保障','支持Kunpeng/ x86双架构','单实例最高支持208vCPU']},
        { id:'bms', name:'BMS 裸金属服务器', nameEn:'Bare Metal Server', category:'compute', desc:'裸金属服务器（BMS）为用户提供专属物理服务器资源，兼具虚拟机的灵活发放能力和物理机的高性能、高安全性。无虚拟化开销，支持自定义硬件配置，满足对计算性能、数据安全有极致要求的关键业务场景。', capabilities:['专属物理资源独占','零虚拟化性能损耗','支持RAID磁盘阵列','自定义BIOS/固件','与VPC/ELB无缝集成','分钟级自动化发放','带外管理控制台','异构计算加速卡支持'], scenarios:['Oracle/SAP HANA核心数据库','金融高频交易系统','HPC高性能计算集群','大数据分析平台','基因测序与科研计算','视频渲染与后期制作','超融合基础设施底座'] , advantages:['性能极致：无虚拟化层，CPU/内存性能100%释放','安全隔离：物理级资源隔离，满足等保合规要求','灵活扩展：支持在线扩容存储与网络带宽','混合部署：可与ECS共享VPC网络，互联互通'], highlights:['支持NVMe SSD本地盘','单实例最高支持896GB内存','支持GPU/FPGA异构计算']},
        { id:'as', name:'AS 弹性伸缩', nameEn:'Auto Scaling', category:'compute', desc:'弹性伸缩（AS）是华为云提供的自动扩缩容服务，可根据业务负载自动调整ECS或BMS实例数量。支持多种伸缩策略（告警/定时/周期），确保业务在流量高峰时平稳运行，在低谷时自动释放资源，实现成本与性能的最优平衡。', capabilities:['告警触发自动扩缩容','定时/周期伸缩策略','健康检查自动替换','多种冷却时间配置','伸缩组生命周期管理','自定义镜像与脚本','多可用区均衡分布','与ELB自动关联解绑'], scenarios:['电商大促弹性扩容','视频直播突发流量','在线教育高峰期','游戏新区开服','批处理任务弹性调度','微服务自动伸缩','DevOps持续集成环境'] , advantages:['全自动化：无需人工干预，24x7自动响应业务变化','成本节省：低谷期自动缩容，降低闲置资源成本','高可用性：健康检查自动替换异常实例','灵活策略：支持告警/定时/周期多种触发方式'], highlights:['秒级监控数据采集','支持预测性伸缩','与云监控深度联动']},
        { id:'cci', name:'CCI 云容器实例', nameEn:'Cloud Container Instance', category:'compute', desc:'云容器实例（CCI）是Serverless容器引擎服务，用户无需管理服务器或Kubernetes集群，只需提供容器镜像即可运行容器化应用。按实际使用的vCPU和内存资源秒级计费，特别适合事件驱动、突发流量和CI/CD流水线等场景。', capabilities:['Serverless无服务器架构','秒级容器启动','按秒计费精确到0.01核','支持GPU容器实例','事件触发自动执行','兼容Kubernetes API','私有镜像仓库集成','多可用区调度'], scenarios:['CI/CD持续集成流水线','批量数据处理任务','事件驱动微服务','AI推理快速部署','定时任务与批处理','突发流量弹性承载','函数计算替代方案'] , advantages:['零运维：无需管理集群节点，专注业务逻辑','极低成本：按秒计费，任务结束即停止计费','极速启动：容器秒级冷启动，快速响应请求','GPU支持：支持NVIDIA GPU容器，AI推理利器'], highlights:['兼容K8s原生API','支持VPC网络直通','与SWR镜像仓库集成']},
        { id:'cce', name:'CCE 云容器引擎', nameEn:'Cloud Container Engine', category:'compute', desc:'云容器引擎（CCE）是基于Kubernetes的企业级容器管理平台，提供高可用、安全、易用的容器编排能力。支持多集群统一管理、混合云部署、服务网格治理，帮助企业快速构建云原生应用，实现微服务架构转型。', capabilities:['K8s原生托管服务','多集群统一纳管','混合云/多云部署','Istio服务网格治理','Serverless容器节点','DevOps流水线集成','GPU/裸金属容器','安全容器运行时','灰度发布与回滚','自定义资源CRD'], scenarios:['微服务架构改造','DevOps平台搭建','多租户SaaS平台','边缘计算应用','AI/ML训练推理','电商秒杀系统','金融云原生转型','物联网设备管理'] , advantages:['企业级高可用：控制面三节点高可用，99.95% SLA','全托管运维：自动升级、自动修复、自动扩缩容','混合云统一：本地数据中心与云上集群统一管理','安全合规：等保三级、国密算法、安全容器'], highlights:['支持K8s 1.28+最新版本','单集群最大10000节点','与ASM服务网格深度集成']},
        { id:'fgs', name:'FGS 函数工作流', nameEn:'FunctionGraph', category:'compute', desc:'函数工作流（FGS）是Serverless事件驱动计算服务，用户只需编写业务代码并设置运行条件，无需预置或管理任何服务器。支持多种触发器（API网关、OBS、定时器等），按调用次数和执行时间计费，真正实现按需付费。', capabilities:['事件触发自动执行','多语言运行时(Python/Node/Java/Go)','API网关一键暴露','OBS对象事件触发','定时触发器(Cron)','异步消息队列触发','函数编排工作流','版本与别名管理','并发与配额控制'], scenarios:['API后端服务','图片/视频处理管道','日志分析与清洗','IoT数据实时处理','定时数据同步','Webhook回调处理','Chatbot对话机器人','文件格式转换'] , advantages:['零服务器管理：无需关心服务器配置、补丁、扩容','极致成本：按调用次数+执行时间计费，无请求不收费','极速开发：分钟级部署，专注业务逻辑','高可用自动扩展：自动应对流量峰值'], highlights:['毫秒级冷启动优化','支持自定义运行时','与OBS/RocketMQ深度集成']},
        // 网络
        { id:'vpc', name:'VPC 虚拟私有云', nameEn:'Virtual Private Cloud', category:'network', desc:'虚拟私有云（VPC）是用户在华为云上构建的隔离、私密的虚拟网络环境。用户可以完全掌控自己的虚拟网络，包括自定义IP地址段、划分子网、配置路由表和安全组等。VPC提供与本地数据中心一致的私网体验，同时享受云的弹性与便捷。', capabilities:['自定义私有网段(10/172/192)','多子网灵活划分','安全组与网络ACL双重防护','自定义路由表策略','VPC对等连接互通','与本地IDC VPN/专线互通','IPv4/IPv6双栈支持','私网NAT网关','流量镜像分析'], scenarios:['企业多层级网络隔离','混合云组网互联','开发/测试/生产环境隔离','多地域VPC互联互通','金融级网络隔离合规','容器网络Overlay底座','大规模微服务网络'] , advantages:['完全掌控：用户对虚拟网络有完全控制权','安全隔离：L2逻辑隔离，不同VPC网络互不可见','灵活扩展：支持跨AZ部署，子网大小灵活调整','混合互联：VPN/专线/云连接多种方式连通本地'], highlights:['支持超大网段(/8-/29)','网络ACL规则数达200+','与云防火墙联动防护']},
        { id:'elb', name:'ELB 弹性负载均衡', nameEn:'Elastic Load Balance', category:'network', desc:'弹性负载均衡（ELB）将访问流量自动分发到多台后端云服务器，消除单点故障，提升应用可用性。支持四层（TCP/UDP）和七层（HTTP/HTTPS）负载均衡，提供健康检查、会话保持、SSL卸载等企业级功能。', capabilities:['四层/七层负载均衡','自动健康检查与剔除','会话保持(Sticky Session)','SSL/TLS证书卸载','加权轮询/最少连接/源IP算法','跨可用区容灾部署','HTTP/2与WebSocket支持','访问日志与监控','自定义转发策略'], scenarios:['高可用Web应用入口','电商大促流量分发','API网关流量调度','音视频直播负载均衡','游戏服区组负载','金融交易网关','微服务入口网关','SSL证书集中管理'] , advantages:['高可用保障：跨AZ部署，单点故障自动切换','性能卓越：单实例支持千万级并发连接','灵活调度：多种负载算法适配不同业务','安全增强：SSL卸载，后端服务专注业务逻辑'], highlights:['单实例吞吐量达10Gbps','支持QUIC协议','与WAF联动防护']},
        { id:'eip', name:'EIP 弹性公网IP', nameEn:'Elastic IP', category:'network', desc:'弹性公网IP（EIP）提供独立的公网IP地址资源，支持与ECS、BMS、ELB、NAT网关等云资源灵活绑定和解绑。带宽可按需调整，支持独享带宽和共享带宽两种模式，满足不同业务的公网访问需求。', capabilities:['独立公网IP资源','灵活绑定/解绑/转移','带宽按需升降配','共享带宽成本优化','IPv4/IPv6双栈支持','BGP多线接入','按带宽/按流量计费','DDoS基础防护'], scenarios:['云服务器公网访问','对外提供Web/API服务','NAT网关出口IP','ELB公网入口','堡垒机跳板访问','游戏服务器公网暴露','邮件服务器公网收发'] , advantages:['灵活绑定：IP与实例解耦，实例变更IP不变','成本优化：共享带宽降低多实例公网成本','快速调整：带宽分钟级升降，适应业务变化','高可用：BGP多线接入，自动路由优选'], highlights:['支持1Mbps-1000Mbps带宽','共享带宽最高支持5Gbps','支持IPv6公网地址']},
        { id:'dns', name:'DNS 云解析服务', nameEn:'Domain Name Service', category:'network', desc:'云解析服务（DNS）提供高可用、高扩展的权威域名解析服务，在全球部署大量解析节点，确保用户访问快速、稳定。支持智能解析、负载均衡、私有Zone等企业级功能，满足内外网统一域名管理需求。', capabilities:['公网权威域名解析','智能分线路/分地域解析','权重轮询负载均衡','私有Zone内网解析','DNSSEC安全扩展','全球Anycast节点','API自动化管理','解析记录批量导入','DNS高防抗攻击'], scenarios:['网站域名解析管理','CDN智能调度','多活数据中心流量切换','内网域名统一管理','混合云DNS统一','高防DNS防劫持','全球用户就近访问'] , advantages:['全球加速：Anycast网络，全球用户就近解析','智能调度：按地域/运营商/权重智能分配流量','高防安全：T级DDoS防护，防DNS劫持','简单易用：可视化控制台，API全自动化管理'], highlights:['解析延迟<10ms','支持亿级QPS解析','SLA可用性99.99%']},
        // 存储
        { id:'obs', name:'OBS 对象存储', nameEn:'Object Storage Service', category:'storage', desc:'对象存储服务（OBS）是华为云提供的海量、安全、高可靠、低成本的数据存储服务。支持标准/低频/归档三级存储类型，数据持久性高达99.9999999999%（12个9）。通过HTTP/HTTPS协议即可访问，与华为云大数据、AI、CDN等服务深度集成。', capabilities:['海量对象存储(EB级)','标准/低频/归档三级类型','多AZ冗余存储(12个9持久性)','跨区域复制容灾','生命周期自动转换','WORM防篡改合规','静态网站托管','S3兼容API','图片/视频在线处理','事件通知触发'], scenarios:['视频/图片/文档存储','数据归档与长期备份','大数据分析数据源','静态网站/前端托管','日志集中存储','医疗影像存档','视频监控存储','备份容灾异地复制'] , advantages:['极致可靠：12个9数据持久性，多AZ冗余','成本分层：热/温/冷数据自动分层，降低70%成本','全球部署：50+区域，就近存储就近访问','生态集成：与ModelArts/MRS/CDN等无缝集成'], highlights:['单桶支持万亿对象','上传下载不限速','支持S3兼容API']},
        { id:'evs', name:'EVS 云硬盘', nameEn:'Elastic Volume Service', category:'storage', desc:'云硬盘（EVS）为ECS/BMS等计算实例提供持久化的块级存储服务。支持SSD、SAS、SATA多种磁盘类型，满足不同性能需求。提供快照备份、在线扩容、共享卷等企业级功能，数据可靠性达99.9999999%。', capabilities:['SSD超高性能(百万IOPS)','SAS/SATA多种类型','快照备份与回滚','在线扩容不中断','共享卷多实例挂载','加密磁盘(国密算法)','自动备份策略','跨AZ复制','SCSI/virtio双模式'], scenarios:['数据库高性能存储','企业应用系统盘','大数据计算存储','日志文件持久化','容器持久化存储','视频编辑工作站','开发测试数据盘','虚拟机模板镜像'] , advantages:['性能卓越：SSD云盘最高支持百万IOPS','灵活扩展：在线扩容不中断业务','数据安全：快照备份+加密，多重保护','高可靠：9个9数据可靠性，自动冗余'], highlights:['单盘最大支持32TB','延迟低至0.5ms','支持SCSI透传']},
        { id:'sfs', name:'SFS 弹性文件服务', nameEn:'Scalable File Service', category:'storage', desc:'弹性文件服务（SFS）提供完全托管的共享文件存储，支持NFS和CIFS协议，可为多台ECS/BMS提供共享访问。具备高吞吐、低时延的特点，容量可按需扩展，无需预分配，特别适合需要共享文件访问的企业应用和HPC场景。', capabilities:['NFS v3/v4协议支持','CIFS/SMB协议支持','容量弹性扩展(不预分配)','高吞吐低时延','多可用区高可用','快照备份','配额管理','AD域集成认证','POSIX权限控制'], scenarios:['企业文件共享服务器','HPC高性能计算共享存储','媒体编辑团队协作','内容管理系统(CMS)','容器共享存储(PVC)','Windows应用共享目录','DevOps构建缓存共享'] , advantages:['完全托管：无需维护文件服务器，开箱即用','共享访问：多台ECS同时读写，协作高效','弹性扩展：容量自动增长，无需预规划','协议兼容：同时支持Linux/Windows文件协议'], highlights:['单实例最高吞吐20GB/s','支持百万级OPS','与HPC集群深度优化']},
        { id:'cbr', name:'CBR 云备份', nameEn:'Cloud Backup and Recovery', category:'storage', desc:'云备份（CBR）是针对华为云资源的统一备份服务，支持对ECS、EVS、SFS Turbo等资源进行崩溃一致性或应用一致性备份。提供增量备份、即时恢复、跨区域复制等功能，帮助用户构建全面的数据保护体系。', capabilities:['崩溃一致性备份','应用一致性备份(数据库)','永久增量备份','即时恢复(RTO分钟级)','跨区域复制容灾','备份策略自动化','文件级细粒度恢复','加密传输与存储','合规保留策略'], scenarios:['企业核心数据备份','数据库定期备份','虚拟机整机备份','文件系统增量备份','灾难恢复演练','合规数据归档','勒索病毒防护','跨地域容灾'] , advantages:['统一平台：一个控制台管理所有云资源备份','高效增量：首次全备后永久增量，节省存储','快速恢复：分钟级RTO，减少业务中断时间','安全可靠：传输/存储双重加密，防勒索'], highlights:['支持SAP HANA应用一致性','跨区域复制RPO<1小时','保留策略最长35年']},
        // 数据库
        { id:'rds', name:'RDS 云数据库', nameEn:'Relational Database Service', category:'database', desc:'云数据库（RDS）是华为云提供的专业级托管关系型数据库服务，支持MySQL、PostgreSQL和SQL Server三大主流引擎。提供自动备份、故障自动切换、读写分离等企业级功能，让用户专注于业务开发，无需关心数据库运维。', capabilities:['MySQL 8.0/5.7 全托管','PostgreSQL 13/14 全托管','SQL Server 2019 全托管','主备架构自动切换','读写分离Proxy代理','自动备份与时间点恢复','参数模板与性能调优','监控告警与慢SQL分析','SSL加密传输','只读副本横向扩展'], scenarios:['Web应用与移动App后端','企业ERP/CRM/HR系统','电商平台订单与库存','金融核心账务系统','游戏玩家数据存储','SaaS多租户应用','政务信息系统','教育管理平台'] , advantages:['完全托管：自动补丁、自动备份、自动故障恢复','高可用：主备秒级切换，RPO=0','性能优化：慢SQL分析、索引建议、参数调优','安全合规：SSL加密、审计日志、等保合规'], highlights:['支持最大16TB存储','只读副本最多10个','与DAS智能自治联动']},
        { id:'dds', name:'DDS 文档数据库', nameEn:'Document Database Service', category:'database', desc:'文档数据库服务（DDS）是兼容MongoDB协议的全托管文档数据库，支持副本集和分片集群架构。具备灵活的Schema设计、高并发读写和水平扩展能力，特别适合需要快速迭代、数据结构多变的互联网应用。', capabilities:['MongoDB 4.4/5.0兼容','副本集高可用架构','分片集群水平扩展','灵活Schema-less设计','全文检索与聚合管道','地理空间索引','变更流(Change Stream)','自动备份与恢复','SSL加密与审计','性能诊断与优化'], scenarios:['内容管理系统(CMS)','物联网时序数据存储','社交网络用户数据','游戏装备/道具/日志','电商商品目录','移动应用后端','实时分析与报表','地理位置服务'] , advantages:['灵活数据模型：无需预定义Schema，快速迭代','水平扩展：分片集群轻松应对TB级数据','高性能：内存映射存储，读写性能卓越','全托管：自动备份、自动升级、自动扩缩容'], highlights:['单分片支持3TB数据','副本集秒级切换','兼容MongoDB原生驱动']},
        { id:'gaussdb', name:'GaussDB', nameEn:'GaussDB', category:'database', desc:'GaussDB是华为自研的企业级分布式数据库，采用存算分离架构，具备金融级高可用和数据强一致性。支持MySQL和openGauss双引擎，提供HTAP混合负载处理能力，满足大规模OLTP和实时OLAP分析需求。', capabilities:['分布式水平扩展','金融级强一致性','异地双活多活架构','HTAP混合负载处理','AI自治调优','列存引擎分析加速','在线扩容缩容','全密态数据库','闪回查询与回收站','逻辑复制与数据订阅'], scenarios:['金融核心交易与支付','电信计费与CRM系统','政企关键业务系统','大规模OLTP业务','实时OLAP报表分析','分布式电商订单','智慧城市数据中台','国产替代迁移'] , advantages:['自研可控：完全自主可控，满足信创要求','金融级可靠：RPO=0，异地双活保障业务连续性','HTAP融合：一套数据同时支持交易和分析','AI智能：自动索引推荐、参数调优、异常检测'], highlights:['支持PB级数据量','TPC-C性能业界领先','通过央行金融认证']},
        { id:'dws', name:'DWS 数据仓库', nameEn:'Data Warehouse Service', category:'database', desc:'数据仓库服务（DWS）是华为云提供的PB级企业级数据仓库，基于MPP大规模并行处理架构。兼容标准SQL和主流BI工具，支持实时数据写入和即席查询，帮助企业构建统一的数据分析平台，驱动数据驱动决策。', capabilities:['PB级数据分析能力','MPP大规模并行处理','标准SQL兼容','实时数据流式写入','即席查询秒级响应','兼容Hive SQL语法','冷热数据分层存储','行存/列存混合引擎','与BI工具深度集成','数据共享跨集群访问'], scenarios:['企业BI报表与分析','用户行为深度分析','经营决策数据驾驶舱','海量日志聚合分析','电信数据集市','金融风控数据分析','IoT数据实时分析','数据湖仓一体架构'] , advantages:['海量分析：PB级数据秒级查询，轻松应对大数据量','实时写入：流式数据实时入库，分析零延迟','生态兼容：兼容标准SQL和主流BI工具，零学习成本','弹性扩展：计算存储分离，按需独立扩缩容'], highlights:['查询性能比开源快5倍','支持10000+并发查询','冷热数据自动分层降本50%']},
        { id:'dcs', name:'DCS 分布式缓存', nameEn:'Distributed Cache Service', category:'database', desc:'分布式缓存服务（DCS）是兼容Redis和Memcached协议的高性能内存数据库服务。提供主备、集群、Proxy多种部署模式，支持数据持久化和读写分离，为应用提供毫秒级响应的数据缓存能力。', capabilities:['Redis 6.2/7.0全兼容','主备/集群/Proxy多架构','数据持久化(AOF/RDB)','读写分离自动代理','大Key热Key分析','慢查询诊断','数据迁移与同步','自动故障切换','SSL加密连接','实例规格弹性变更'], scenarios:['用户会话状态缓存','实时排行榜与计数器','消息队列与发布订阅','API接口限流熔断','数据库查询结果缓存','实时推荐系统','购物车与库存缓存','分布式锁协调'] , advantages:['极速响应：内存级访问，平均延迟<1ms','多种架构：主备/集群/Proxy满足不同规模','数据安全：持久化+备份，防止数据丢失','智能诊断：大Key分析、慢查询、性能监控'], highlights:['单集群支持千万级QPS','支持最大4TB内存','与DDM分布式数据库联动']},
        { id:'geminidb', name:'GeminiDB', nameEn:'GeminiDB NoSQL', category:'database', desc:'GeminiDB是华为云推出的云原生多模数据库，兼容Cassandra、DynamoDB、Redis、InfluxDB等多种NoSQL协议。采用存算分离架构，具备强一致性和无限扩展能力，一套平台满足键值、宽表、时序等多种数据模型需求。', capabilities:['Cassandra/DynamoDB兼容','Redis协议兼容','InfluxDB时序兼容','存算分离架构','强一致性读写','自动分片扩容','备份恢复与迁移','多AZ高可用','数据压缩与降冷','监控告警与诊断'], scenarios:['IoT时序数据存储','海量宽表数据存储','键值高速缓存','日志与监控数据','社交网络图数据','电商商品属性存储','游戏排行榜与计数','车联网轨迹数据'] , advantages:['多模统一：一套数据库满足多种NoSQL场景','无限扩展：存算分离，存储和计算独立扩缩容','强一致性：跨AZ强一致读写，数据零丢失','成本优化：数据自动压缩，冷数据分层存储'], highlights:['兼容4种NoSQL协议','存储自动无限扩展','时序数据压缩比10:1']},
        // AI/大数据
        { id:'modelarts', name:'ModelArts AI开发平台', nameEn:'ModelArts', category:'ai', desc:'ModelArts是华为云面向AI开发者的一站式开发平台，覆盖数据处理、算法开发、模型训练、模型管理到模型部署的全流程。内置大量预置算法和模型市场，支持Notebook交互式开发和分布式大规模训练，降低AI开发门槛。', capabilities:['可视化数据标注','Jupyter Notebook开发','分布式大规模训练','自动模型调优(AutoML)','模型管理版本控制','一键模型部署推理','AI Gallery模型市场','预置100+算法模板','模型压缩与量化','AIGC大模型微调'], scenarios:['图像分类与目标检测','自然语言处理模型','推荐系统算法开发','语音合成与识别','大模型微调与部署','医学影像AI诊断','工业质检视觉检测','自动驾驶感知模型'] , advantages:['全链路覆盖：从数据到部署一站式完成','零代码训练：自动调参，降低AI开发门槛','算力弹性：按需GPU集群，训练完即释放','生态丰富：AI Gallery海量预训练模型'], highlights:['支持千卡分布式训练','内置盘古大模型','与昇腾AI芯片深度优化']},
        { id:'mrs', name:'MRS 大数据', nameEn:'MapReduce Service', category:'ai', desc:'MapReduce服务（MRS）是华为云基于Apache开源生态的企业级大数据分析平台，提供Hadoop、Spark、Flink、Hive等一站式大数据组件。支持存算分离架构和混合负载调度，帮助企业快速构建数据湖，实现海量数据的存储和分析。', capabilities:['Hadoop/Spark/Flink全栈','存算分离架构','混合负载统一调度','数据湖格式支持(Delta/Iceberg)','一键集群创建与扩缩容','自动化运维监控','跨集群数据共享','与OBS数据湖集成','Kerberos安全认证','冷热数据自动分层'], scenarios:['离线批处理ETL','实时流计算分析','数据湖统一存储','日志分析与挖掘','用户行为分析','电信数据处理','金融风控建模','IoT数据聚合分析'] , advantages:['开源兼容：100%兼容Apache生态，无缝迁移','存算分离：存储和计算独立扩展，成本降低40%','混合负载：批处理+流计算+交互查询统一平台','全托管：一键部署，自动化运维，降低人力成本'], highlights:['支持Spark 3.3+','单集群支持3000+节点','与DLI数据湖探索联动']},
        { id:'dli', name:'DLI 数据湖探索', nameEn:'Data Lake Insight', category:'ai', desc:'数据湖探索（DLI）是华为云提供的Serverless大数据交互分析服务，支持SQL查询、流处理和批处理的融合处理。无需预置集群，按实际扫描数据量计费，可无缝对接OBS、RDS、Kafka等多种数据源，实现数据湖的即席查询和分析。', capabilities:['标准SQL交互查询','流批一体处理','Serverless免运维','与OBS数据湖直连','多数据源联邦查询','Spark作业提交','Python UDF扩展','数据权限精细管控','查询结果可视化','REST API集成'], scenarios:['数据湖即席查询','实时流数据处理','异构数据源联邦分析','交互式数据探索','日志实时分析','BI报表数据准备','数据科学家探索分析','IoT数据实时洞察'] , advantages:['Serverless：无需集群，即开即用，按量付费','流批一体：一套SQL同时处理流数据和批数据','联邦查询：跨OBS/RDS/Kafka等数据源联合分析','极致弹性：自动扩展计算资源，应对查询峰值'], highlights:['查询延迟秒级','支持PB级数据扫描','与DWS数仓数据共享']},
        { id:'ei', name:'EI 企业智能', nameEn:'Enterprise Intelligence', category:'ai', desc:'企业智能（EI）是华为云提供的开箱即用AI服务套件，涵盖视觉、语音、语言、知识图谱等多个领域。用户无需AI expertise即可通过API调用强大的AI能力，快速实现智能化升级，包括OCR识别、人脸识别、语音合成、自然语言理解等。', capabilities:['OCR文字与证件识别','人脸检测与身份核验','语音合成(TTS)','语音识别(ASR)','自然语言理解(NLU)','知识图谱构建','内容审核与鉴黄','智能客服机器人','文本翻译与摘要','图像内容理解'], scenarios:['智能客服与对话机器人','身份证/发票自动识别','人脸门禁与考勤','视频内容审核','舆情监控与分析','智能招聘简历解析','医疗单据自动录入','合同文本智能审查'] , advantages:['开箱即用：API调用即可获得业界领先AI能力','持续进化：模型持续迭代优化，能力不断提升','多模融合：视觉+语音+语言多模态AI协同','安全可靠：数据隐私保护，符合等保要求'], highlights:['人脸识别准确率99.8%+','OCR支持100+种证件','支持多语种实时翻译']},
        // IoT
        { id:'iotda', name:'IoTDA 设备接入', nameEn:'IoT Device Access', category:'iot', desc:'IoT设备接入（IoTDA）是华为云提供的海量设备连接管理服务，支持MQTT、CoAP、LwM2M等多种工业协议。提供设备全生命周期管理、设备影子、规则引擎、OTA升级等能力，帮助企业快速构建物联网应用。', capabilities:['MQTT/CoAP/LwM2M多协议','亿级设备并发接入','设备影子与状态同步','规则引擎数据流转','设备OTA固件升级','设备分组与批量管理','数字孪生可视化','设备安全认证(X.509)','边云协同IoT Edge','时序数据存储分析'], scenarios:['智慧城市路灯/井盖管理','工业设备预测性维护','智能家居全屋互联','车联网V2X数据采集','能源管理智能电表','智慧农业环境监测','资产追踪与定位','智慧园区安防联动'] , advantages:['海量接入：单实例支持亿级设备同时在线','协议丰富：支持主流物联网协议，兼容性强','全生命周期：从注册到退役全流程管理','边云协同：边缘计算与云端协同，低时延响应'], highlights:['MQTT连接延时<50ms','支持设备影子秒级同步','与IoT数据分析联动']},
        // 安全
        { id:'waf', name:'WAF Web应用防火墙', nameEn:'Web Application Firewall', category:'security', desc:'Web应用防火墙（WAF）保护Web应用和API免受常见Web攻击，包括SQL注入、XSS跨站脚本、CC攻击、恶意爬虫等。通过AI智能防御引擎，可自动识别0day漏洞攻击和高级威胁，确保Web业务安全运行。', capabilities:['OWASP Top10攻击防护','SQL注入/XSS/命令注入防护','CC攻击智能清洗','Bot管理与恶意爬虫识别','精准访问控制(IP/URL/Geo)','API安全防护','0day漏洞虚拟补丁','自定义防护规则','全量访问日志审计','与态势感知联动'], scenarios:['企业官网安全防护','电商平台防爬虫/刷单','API接口安全加固','政府门户网站防护','金融在线业务防护','SaaS应用安全防护','游戏防外挂/刷量','移动App后端防护'] , advantages:['AI智能防御：机器学习自动识别新型攻击','精准防护：基于业务语义的精细化防护规则','合规保障：满足等保2.0三级Web安全要求','零部署：DNS/CDN方式接入，无需改动业务'], highlights:['攻击检出率99.9%+','CC清洗能力Tbps级','支持gRPC/WebSocket防护']},
        { id:'aad', name:'AAD DDoS防护', nameEn:'Anti-DDoS Protection', category:'security', desc:'DDoS防护（AAD）提供Tbps级DDoS攻击防护能力，全面保护网络层、传输层和应用层免受各类DDoS攻击。采用AI智能检测+全球清洗中心架构，可在攻击流量到达用户业务前完成清洗，确保业务连续性。', capabilities:['Tbps级攻击清洗能力','网络层/传输层/应用层全栈防护','AI智能攻击检测','全球近源清洗中心','攻击流量实时可视','自动防护策略调优','高防IP代理接入','CC攻击精准识别','攻击溯源与分析报告','与WAF联合防护'], scenarios:['金融行业防DDoS勒索','游戏服务器防攻击','电商平台大促保障','政府网站防攻击瘫痪','在线教育直播防护','企业官网防恶意竞争','DNS防DDoS劫持','视频直播防流量攻击'] , advantages:['T级防护：单用户Tbps级防护能力，无惧大流量攻击','AI智能：自动识别攻击模式，秒级响应','全球清洗：全球近源清洗，降低网络延迟','联合防护：与WAF联动，七层四层全面防护'], highlights:['攻击检测延迟<10秒','清洗成功率99.99%+','支持Anycast全球近源清洗']},
        { id:'hss', name:'HSS 主机安全', nameEn:'Host Security Service', category:'security', desc:'主机安全服务（HSS）提供服务器资产管理、漏洞管理、入侵检测和安全运营的一体化主机安全解决方案。基于轻量化Agent部署，实时监测服务器安全状态，自动发现和修复漏洞，防御勒索病毒和恶意入侵。', capabilities:['服务器资产自动发现','漏洞扫描与一键修复','基线配置合规检查','入侵检测与告警','勒索病毒专项防护','恶意文件实时查杀','登录行为审计','进程/端口/账号监控','容器镜像安全扫描','安全事件自动化响应'], scenarios:['服务器安全加固','等保合规检查','勒索病毒防护','安全运营中心(SOC)','容器安全治理','漏洞生命周期管理','异常登录检测','合规审计报告生成'] , advantages:['轻量部署：Agent资源占用低，不影响业务性能','全栈防护：从漏洞到入侵的全链路安全覆盖','自动修复：高危漏洞一键修复，降低人工投入','勒索专项：专项防护勒索病毒，数据安全保障'], highlights:['支持Windows/Linux双平台','Agent内存占用<50MB','与SecMaster安全运营联动']},
        // 音视频/CDN
        { id:'live', name:'Live 视频直播', nameEn:'Live Video Streaming', category:'media', desc:'视频直播（Live）是华为云提供的超低延时、高清流畅的视频直播服务，支持RTMP/HLS/DASH/WebRTC等多种协议，可承载千万级并发观看。提供实时录制、截图鉴黄、连麦互动、内容审核等丰富功能，满足各类直播场景需求。', capabilities:['4K/8K超高清直播','超低延时直播(<1s)','RTMP/HLS/WebRTC多协议','实时录制与时移回放','智能截图与鉴黄审核','连麦互动与PK','直播间弹幕/礼物','CDN全球分发加速','自适应码率推流','直播数据统计分析'], scenarios:['体育赛事直播','电商带货直播','在线教育直播课','互动娱乐直播','企业年会/发布会直播','远程医疗手术直播','游戏赛事直播','政务公开直播'] , advantages:['超低延时：WebRTC协议支持亚秒级延时','超大规模：单直播间支持千万级并发观看','智能审核：AI自动鉴黄、鉴暴、鉴政，降低审核成本','全球分发：全球CDN节点，就近接入低卡顿'], highlights:['端到端延时<500ms','支持HDR10高动态','与RTC实时音视频联动']},
        { id:'vod', name:'VOD 视频点播', nameEn:'Video on Demand', category:'media', desc:'视频点播（VOD）是集视频上传、存储、转码、加密、分发、播放于一体的全栈点播服务平台。支持多格式自适应码率、DRM内容保护、AI智能审核剪辑，帮助用户快速构建稳定、安全、智能的视频点播应用。', capabilities:['多格式上传与存储','智能多码率转码','DRM数字版权加密','CDN全球加速分发','AI智能审核与剪辑','视频水印与封面','播放器SDK多端支持','播放数据统计分析','视频内容搜索','HLS/DASH自适应播放'], scenarios:['短视频/长视频平台','在线教育课程点播','企业培训视频库','IPTV/OTT视频平台','媒体资讯视频发布','视频 surveillance回放','电商商品视频展示','直播录制回放存储'] , advantages:['一站式：上传-转码-加密-分发-播放全流程','智能转码：AI识别内容场景，自动优化转码参数','版权保护：DRM+水印+防盗链，全方位版权保护','全球加速：CDN节点覆盖，播放流畅不卡顿'], highlights:['支持8K视频转码','转码速度提升3倍','AI智能拆条与封面生成']},
        { id:'rtc', name:'RTC 实时音视频', nameEn:'Real-Time Communication', category:'media', desc:'实时音视频（RTC）基于WebRTC标准构建，提供超低延时、高质量的实时音视频通信能力。支持万人超大房间、屏幕共享、互动白板、美颜滤镜等功能，满足视频会议、在线教育、远程医疗、游戏语音等实时互动场景。', capabilities:['超低延时音视频(<200ms)','万人超大房间','智能美颜与滤镜','屏幕共享与标注','互动电子白板','云端录制与回放','噪音抑制与回声消除','网络自适应抗弱网','多路混流与布局','信令与媒体分离'], scenarios:['视频会议与远程办公','在线教育互动课堂','远程医疗会诊','游戏实时语音','金融远程面签','社交视频通话','客服视频坐席','远程技术支持'] , advantages:['超低延时：全球端到端平均延时<200ms','超强抗弱网：70%丢包下仍保持流畅','超大房间：单房间支持万人同时在线','全平台：iOS/Android/Web/小程序/PC全端覆盖'], highlights:['支持1080P高清视频','AI智能降噪','与Live直播无缝连麦']},
        { id:'cdn', name:'CDN 内容分发网络', nameEn:'Content Delivery Network', category:'media', desc:'内容分发网络（CDN）通过在全球部署大量边缘节点，将网站、视频、应用等内容缓存到离用户最近的节点，显著提升用户访问速度和体验。支持静态加速、下载加速、视频点播加速、全站加速等多种场景。', capabilities:['全球2800+边缘节点','智能DNS调度','静态内容缓存加速','HTTPS/TLS加速','大文件下载加速','视频点播加速','全站动态加速(DCDN)','缓存刷新与预热','访问日志与实时分析','WAF/DDoS联动防护'], scenarios:['网站静态资源加速','APP安装包下载加速','视频点播流畅播放','电商大促峰值加速','游戏资源包更新','API接口全球加速','软件分发与补丁更新','全站动静混合加速'] , advantages:['全球覆盖：2800+节点覆盖全球主要区域','智能调度：实时网络探测，最优节点调度','极速体验：静态资源缓存命中率达95%+','安全加速：HTTPS加速+WAF+DDoS三位一体'], highlights:['支持QUIC协议','单节点带宽40Gbps+','命中率行业领先']},
        // 企业应用
        { id:'meeting', name:'Meeting 华为云会议', nameEn:'Huawei Cloud Meeting', category:'enterprise', desc:'华为云会议（Meeting）提供全场景端云协同视频会议解决方案，支持高清音视频、屏幕共享、会议纪要、实时字幕等功能。具备电信级安全性和稳定性，支持千人大型会议和会议室硬件终端接入，满足企业远程协作需求。', capabilities:['1080P高清视频会议','1080P高清云录制','屏幕共享与远程标注','智能会议纪要','实时字幕与翻译','千人大型会议','会议室硬件终端接入','日历与会议预约集成','API/SDK二次开发','会议数据加密传输'], scenarios:['企业日常远程会议','跨地域团队协作','在线培训与研讨','远程招聘面试','客户远程演示','医疗远程会诊','政务视频会议','应急指挥调度'] , advantages:['高清稳定：华为音视频技术积累，弱网环境下依然清晰','安全合规：端到端加密，满足政企安全合规要求','全场景：PC/手机/平板/会议室硬件全端覆盖','智能体验：AI会议纪要、实时字幕，提升会议效率'], highlights:['支持1000方视频会议','端到端加密传输','与WeLink深度集成']},
        { id:'welink', name:'WeLink 智能协同', nameEn:'WeLink', category:'enterprise', desc:'WeLink是华为云推出的安全、智能、数字化协同办公平台，整合即时消息、视频会议、智能邮箱、考勤审批、知识库等功能于一体。基于华为云安全架构，提供企业级的数据安全保障和开放API能力，助力企业数字化转型。', capabilities:['IM即时消息与群聊','1000方高清视频会议','智能邮箱与日程管理','考勤打卡与审批流程','企业知识库与文档','任务与项目管理','企业应用市场','开放API与低代码','多端同步(PC/手机/平板)','企业通讯录管理'], scenarios:['企业远程办公协同','跨部门项目协作','客户沟通与商务对接','员工培训与知识分享','审批流程数字化','企业信息发布','供应商协同管理','移动办公外勤管理'] , advantages:['安全可信：华为云安全架构，数据主权可控','全场景协同：消息+会议+邮件+审批一站式','智能高效：AI翻译、智能助手提升办公效率','开放集成：开放API，与企业现有系统无缝集成'], highlights:['通过等保三级认证','支持国密算法加密','与华为云200+服务集成']},
        { id:'codehub', name:'CodeHub 代码托管', nameEn:'CodeHub', category:'enterprise', desc:'CodeHub是基于Git的云端代码托管与DevOps协作平台，提供代码仓库管理、合并请求（MR）代码审查、CI/CD流水线、代码质量扫描等能力。支持私有部署和多云管理，帮助开发团队实现高效协作和持续交付。', capabilities:['Git代码仓库托管','合并请求(MR)与代码审查','分支策略与保护规则','CI/CD流水线编排','代码质量静态扫描','安全漏洞自动检测','代码规范自动检查','制品仓库管理','Wiki与文档协作','多租户权限管理'], scenarios:['软件开发团队协作','开源项目管理','DevOps持续交付','微服务代码管理','代码安全审计','多项目统一管理','跨地域团队开发','代码评审规范化'] , advantages:['企业级安全：代码加密存储，细粒度权限控制','DevOps一体：代码+构建+测试+部署全流程','质量内建：代码扫描+安全检测，问题早发现','高效协作：MR代码审查，保证代码质量'], highlights:['支持Git LFS大文件','与CCE容器服务联动','兼容GitHub/GitLab导入']}
    ],

    links: [
        // 计算 ↔ 网络
        {s:'ecs',t:'vpc'}, {s:'ecs',t:'elb'}, {s:'elb',t:'ecs'},
        // 计算 ↔ 存储
        {s:'ecs',t:'obs'}, {s:'ecs',t:'evs'}, {s:'obs',t:'sfs'},
        // 计算 ↔ 数据库
        {s:'ecs',t:'rds'}, {s:'ecs',t:'dcs'}, {s:'rds',t:'dws'},
        // 存储 ↔ 数据库/AI
        {s:'obs',t:'dws'}, {s:'obs',t:'modelarts'}, {s:'evs',t:'cbr'},
        // AI ↔ 数据库
        {s:'modelarts',t:'dws'}, {s:'modelarts',t:'ei'}, {s:'mrs',t:'dws'},
        // IoT ↔ 存储
        {s:'iotda',t:'obs'},
        // 安全
        {s:'waf',t:'aad'}, {s:'ecs',t:'waf'}, {s:'hss',t:'ecs'},
        // 音视频
        {s:'live',t:'vod'}, {s:'vod',t:'obs'}, {s:'rtc',t:'live'}, {s:'live',t:'cdn'},
        // 企业应用
        {s:'welink',t:'meeting'}, {s:'meeting',t:'live'}, {s:'codehub',t:'ecs'}
    ],

    init() {
        try {
            // 确保 state 已初始化（防御性守卫）
            if (!this.state) { this.state = { selectedNode: null, activeFilter: 'all', searchQuery: '', highlightedProducts: [], coreProducts: [], nodes: {}, nodeElements: {}, groupElements: {} }; }
            this._buildIndex();
            this._renderGrid();
            this._bindEvents();
        } catch (e) {
            console.error('[ProductGraph] 初始化失败:', e);
        }
    },

    _buildIndex() {
        if (!this.state) return;
        if (!this.productTree || !this.productTree.length) return;
        this.state.nodes = {};
        for (var i = 0; i < this.productTree.length; i++) { this.state.nodes[this.productTree[i].id] = this.productTree[i]; }
    },

    _renderGrid() {
        if (!this.state) return;
        var container = document.getElementById('products-graph');
        if (!container) return;
        container.innerHTML = '';
        this.state.nodeElements = {};
        this.state.groupElements = {};

        var groups = {};
        for (var g = 0; g < this.categoryOrder.length; g++) groups[this.categoryOrder[g]] = [];
        for (var j = 0; j < this.productTree.length; j++) {
            var p = this.productTree[j];
            if (groups[p.category]) groups[p.category].push(p);
        }

        var self = this;
        this.categoryOrder.forEach(function(cat) {
            var products = groups[cat];
            if (!products || products.length === 0) return;
            var catConfig = self.categories[cat] || {};

            var groupEl = document.createElement('div');
            groupEl.className = 'product-category-group';
            groupEl.setAttribute('data-cat', cat);
            groupEl.innerHTML =
                '<div class="category-group-header">' +
                    '<span class="category-group-icon">' + (catConfig.icon || '') + '</span>' +
                    '<span class="category-group-title">' + (catConfig.label || cat) + '</span>' +
                    '<span class="category-group-count">' + products.length + ' 款产品</span>' +
                '</div><div class="category-nodes-grid"></div>';
            container.appendChild(groupEl);
            self.state.groupElements[cat] = groupEl;

            var gridEl = groupEl.querySelector('.category-nodes-grid');
            products.forEach(function(product, idx) {
                var node = document.createElement('div');
                node.className = 'product-node fade-in';
                node.id = 'product-node-' + product.id;
                node.setAttribute('data-product-id', product.id);
                node.setAttribute('data-category', product.category);
                node.style.animationDelay = (idx * 50) + 'ms';

                if (self._isRootProduct(product.id)) node.classList.add('node-root');
                else if (self._isBranchProduct(product.id)) node.classList.add('node-branch');

                node.innerHTML = '<span class="node-category-dot"></span><span class="node-label">' + product.name + '</span>';
                node.addEventListener('click', function() { self._onNodeClick(product); });
                gridEl.appendChild(node);
                self.state.nodeElements[product.id] = node;
            });
        });
    },

    _onNodeClick(product) {
        if (!product || !this.state) return;
        document.querySelectorAll('.product-node.selected').forEach(function(n) { n.classList.remove('selected'); });
        var el = this.state.nodeElements[product.id];
        if (el) el.classList.add('selected');
        this.state.selectedNode = product.id;
        this._showDetail(product);
    },

    _showDetail(product) {
        if (!product || !this.state) return;
        var self = this; // 修复：确保 self 指向 ProductGraph，而非 window
        var empty = document.getElementById('detail-empty-state');
        var content = document.getElementById('detail-content-area');
        if (empty) empty.style.display = 'none';
        if (!content) return;
        content.style.display = '';
        var cat = this.categories[product.category] || {};
        var caps = product.capabilities || [];
        var sces = product.scenarios || [];
        var advs = product.advantages || [];
        var hlts = product.highlights || [];
        var capHtml = caps.map(function(c){return '<li>'+c+'</li>';}).join('');
        var sceHtml = sces.map(function(s){return '<li>'+s+'</li>';}).join('');
        var advHtml = advs.map(function(a){return '<li>'+a+'</li>';}).join('');
        var hltHtml = hlts.map(function(h){return '<li>'+h+'</li>';}).join('');
        var relIds = this._getRelatedProducts(product.id);
        var relHtml = relIds.map(function(rId){var rn=self.state.nodes[rId];return '<li onclick="ProductGraph._jumpToNode(\''+rId+'\')">'+(rn?rn.name:rId)+'</li>';}).join('');
        content.innerHTML =
            '<div class="product-detail-content"><div class="product-detail-header">'+
                '<span class="detail-category-badge" style="background:'+cat.color+'"></span>'+
                '<div><h3>'+product.name+'</h3><div class="detail-name-en">'+product.nameEn+'</div></div>'+
                '</div><div class="product-detail-body">'+
                '<div class="detail-section"><div class="detail-section-title">简介</div>'+
                '<div class="detail-section-content">'+product.desc+'</div></div>'+
                '<div class="detail-section"><div class="detail-section-title">核心能力</div>'+
                '<ul class="detail-scenario-list">'+capHtml+'</ul></div>'+
                '<div class="detail-section"><div class="detail-section-title">典型场景</div>'+
                '<ul class="detail-scenario-list">'+sceHtml+'</ul></div>'+
                (advHtml?'<div class="detail-section"><div class="detail-section-title">产品优势</div>'+
                '<ul class="detail-advantage-list">'+advHtml+'</ul></div>':'')+
                (hltHtml?'<div class="detail-section"><div class="detail-section-title">技术亮点</div>'+
                '<ul class="detail-highlight-list">'+hltHtml+'</ul></div>':'')+
                '<div class="detail-section"><div class="detail-section-title">关联产品</div>'+
                '<ul class="detail-related-list" id="detail-related-products">'+relHtml+'</ul></div>'+
                '</div></div>';
        var panel = document.getElementById('product-detail-panel');
        if (panel) panel.scrollTop = 0;
    },

    _getRelatedProducts(productId) {
        var r = new Set();
        this.links.forEach(function(l){if(l.s===productId)r.add(l.t);if(l.t===productId)r.add(l.s);});
        return Array.from(r).slice(0,8);
    },

    _jumpToNode(nodeId) {
        if (!this.state) return;
        var el=this.state.nodeElements[nodeId],p=this.state.nodes[nodeId];
        if(el&&p){this._onNodeClick(p);var g=el.closest('.product-category-group');if(g&&g.classList.contains('group-hidden'))g.classList.remove('group-hidden');el.scrollIntoView({behavior:'smooth',block:'center'});}
    },

    _isRootProduct(id){return['ecs','obs','modelarts'].indexOf(id)!==-1;},
    _isBranchProduct(id){return['rds','dws','iotda','waf','live','welink','mrs','gaussdb','cce'].indexOf(id)!==-1;},

    _bindEvents(){
        var self=this;
        document.querySelectorAll('.product-filter-btn').forEach(function(b){
            b.addEventListener('click',function(){
                document.querySelectorAll('.product-filter-btn').forEach(function(x){x.classList.remove('active');});
                b.classList.add('active');
                self.setFilter(b.getAttribute('data-category'));
            });
        });
        var si=document.getElementById('product-search-input');
        if(si){var t=null;si.addEventListener('input',function(e){clearTimeout(t);t=setTimeout(function(){self.setSearch(e.target.value.trim().toLowerCase());},250)});}
        document.addEventListener('click',function(e){
            if(e.target.closest('#btn-clear-highlight')||e.target.classList.contains('btn-clear-highlight'))self.clearHighlights();
        });
    },

    setFilter(cat){
        if (!this.state) return;
        this.state.activeFilter=cat;
        var self=this;
        Object.keys(this.state.groupElements).forEach(function(c){
            self.state.groupElements[c].classList.toggle('group-hidden',(cat!=='all')&&(c!==cat));
        });
        this._applySearchVisibility();
    },

    setSearch(q){if(!this.state)return;this.state.searchQuery=q;this._applySearchVisibility();},

    _applySearchVisibility(){
        if(!this.state)return;
        var q=this.state.searchQuery,self=this;
        Object.keys(this.state.nodeElements).forEach(function(id){
            var el=self.state.nodeElements[id],p=self.state.nodes[id];
            if(!p)return;
            var cm=(self.state.activeFilter==='all'||(p.category===self.state.activeFilter));
            var sm=!q||self._matchesSearch(p,q);
            el.style.display=(cm&&sm)?'':'none';
        });
    },

    _matchesSearch(p,q){
        var lq=q.toLowerCase();
        return p.name.toLowerCase().indexOf(lq)!==-1||p.nameEn.toLowerCase().indexOf(lq)!==-1||p.desc.toLowerCase().indexOf(lq)!==-1||
            p.capabilities.some(function(c){return c.toLowerCase().indexOf(lq)!==-1;})||
            p.scenarios.some(function(s){return s.toLowerCase().indexOf(lq)!==-1;});
    },

    highlightProducts(names,cores){
        // 高亮功能已按需求移除 —— 用户只需要点击查看产品详情
        return;
    },

    _findProductIdByName(name){
        if(!name||!this.productTree)return null;
        var n=name.trim().toLowerCase(),i,p,j,p2;
        for(i=0;i<this.productTree.length;i++){p=this.productTree[i];if(p.name.toLowerCase()===n||p.nameEn.toLowerCase()===n||p.id.toLowerCase()===n)return p.id;}
        for(j=0;j<this.productTree.length;j++){p2=this.productTree[j];if(n.indexOf(p2.id.toLowerCase())!==-1||p2.name.toLowerCase().indexOf(n)!==-1||p2.nameEn.toLowerCase().indexOf(n)!==-1)return p2.id;}
        var m={'\u5f39\u6027\u4e91\u6705\u52a1\u5668':'ecs','\u4e91\u6705\u52a1\u5668':'ecs','\u88f8\u91d1\u5c5e':'bms','\u5f39\u6027\u4f38\u7f29':'as','\u5bf9\u8c61\u558a\u50a8':'obs','\u4e91\u786c\u76d8':'evs','\u6587\u4ef6\u670d\u52a1':'sfs','\u4e91\u5907\u4efd':'cbr','\u5173\u7cfb\u578b\u6570\u636e\u5e93':'rds','mysql':'rds','postgresql':'rds','\u6587\u6863\u6570\u636e\u5e93':'dds','mongodb':'dds','\u6570\u636e\u4ed3\u5e93':'dws','\u6570\u4ed3':'dws','\u5206\u5e03\u5f0f\u7f13\u5b58':'dcs','redis':'dcs','gaussdb':'gaussdb','modelarts':'modelarts','ma':'modelarts','ai\u5f00\u53d1\u5e73\u53f0':'modelarts','\u5927\u6570\u636e':'mrs','mapreduce':'mrs','\u4f01\u4e1a\u667a\u80fd':'ei','\u4eba\u5de5\u667a\u80fd':'ei','\u7269\u8054\u7f51':'iotda','iot':'iotda','\u8bbe\u5907\u63a5\u5165':'iotda','waf':'waf','web\u9632\u706b\u5899':'waf','web\u5e94\u7528\u9632\u706b\u5899':'waf','ddos':'ddos','anti-ddos':'ddos','\u4e3b\u673a\u5b89\u5168':'hss','\u5b89\u5168\u670d\u52a1':'hss','\u76f4\u64ad':'live','\u89c6\u9891\u76f4\u64ad':'live','\u70b9\u64ad':'vod','\u89c6\u9891\u70b9\u64ad':'vod','\u5b9e\u65f6\u97f3\u89c6\u9891':'rtc','\u97f3\u89c6\u9891\u901a\u8bdd':'rtc','welink':'welink','\u534e\u4e3a\u4e91\u4f1a\u8bae':'welink','\u4e91\u4f1a\u8bae':'welink','\u4ee3\u7801\u6258\u7ba1':'codehub'};
        var ks=Object.keys(m);
        for(var k=0;k<ks.length;k++){if(n.indexOf(ks[k])!==-1||ks[k].indexOf(n)!==-1)return m[ks[k]];}
        return null;
    },

    clearHighlightStyles(){
        if(!this.state)return;
        var v=Object.values(this.state.nodeElements);
        for(var x=0;x<v.length;x++){try{v[x].classList.remove('matched','core-matched');}catch(e){}}
    },

    clearHighlights(){if(!this.state)return;this.clearHighlightStyles();this.state.highlightedProducts=[];this.state.coreProducts=[];this._updateHighlightBar(0,0);},

    _updateHighlightBar(mc,cc){
        if(!this.state)return;
        var b=document.getElementById('products-highlight-bar');
        if(!b)return;
        if(mc===0){
            b.style.background='linear-gradient(90deg,rgba(199,0,11,.04)0%,rgba(139,92,246,.03)100%)';
            b.style.borderColor='rgba(255,255,255,.06)';
            b.innerHTML='<span class="highlight-icon">\ud83d\udca1</span><span class="highlight-default-text">\u70b9\u51fb\u5de6\u4fa7\u4ea7\u54c1\u8282\u70b9\uff0c\u53ef\u67e5\u770b\u8be5\u4ea7\u54c1\u7684\u8be6\u7ec6\u4ecb\u7ecd\u3001\u6838\u5fc3\u80fd\u529b\u548c\u5e94\u7528\u573a\u666f</span>';
        }else{
            b.style.background='linear-gradient(90deg,rgba(245,158,11,.08)0%,rgba(199,0,11,.05)100%)';
            b.style.borderColor='rgba(245,158,11,.12)';
            var ch=cc>0?' \u00b7<span class="highlight-core-count">'+cc+'</span> \u4e2a\u6838\u5fc3\u4ea7\u54c1':'';
            b.innerHTML='<span class="highlight-icon">\u2728</span>\u65b9\u6848\u5339\u914d\u7ed3\u679c\u6d89\u53ca <span class="highlight-count">'+mc+'</span> \u4e2a\u534e\u4e3a\u4e91\u4ea7\u54c1'+ch+' \uff08\u91d1\u8272=\u6d89\u53ca\u4ea7\u54c1\uff0c\u7ea2\u8272=\u6838\u5fc3\u4ea7\u54c1\uff09<button class="btn-clear-highlight" id="btn-clear-highlight">\u6e05\u9664\u9ad8\u4eae</button>';
        }
    },

    _extractProductsFromText(text){
        // 高亮功能已按需求移除，不再执行产品名称提取
        return{matched:[],core:[]};
    },
};

/* ===== 3D产品架构树形图 ===== */

var ArchTree3D = {
    canvas: null,
    ctx: null,
    width: 0,
    height: 0,
    nodes: [],
    links: [],
    cam: { rx: -0.4, ry: 0.6, zoom: 1.35, tx: 0, ty: -55 },
    drag: { active: false, sx: 0, sy: 0, srx: 0, sry: 0 },
    hovered: null,
    selected: null,
    autoRotate: true,
    animId: null,
    categoryColors: {
        compute: '#3B82F6', network: '#F59E0B', storage: '#22C55E',
        database: '#A855F7', ai: '#EC4899', iot: '#06B6D4',
        security: '#EF4444', media: '#8B5CF6', enterprise: '#14B8A6'
    },

    init: function() {
        var btn = document.getElementById('arch-tree-btn');
        var modal = document.getElementById('arch-modal');
        var closeBtn = document.getElementById('arch-close-btn');
        var autoBtn = document.getElementById('arch-auto-rotate-btn');
        var resetBtn = document.getElementById('arch-reset-btn');
        if (!btn || !modal) return;

        btn.addEventListener('click', function() {
            modal.classList.add('active');
            ArchTree3D._start();
        });
        closeBtn.addEventListener('click', function() {
            modal.classList.remove('active');
            ArchTree3D._stop();
        });
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                modal.classList.remove('active');
                ArchTree3D._stop();
            }
        });
        autoBtn.addEventListener('click', function() {
            ArchTree3D.autoRotate = !ArchTree3D.autoRotate;
            autoBtn.classList.toggle('active', ArchTree3D.autoRotate);
        });
        resetBtn.addEventListener('click', function() {
            ArchTree3D.cam.rx = -0.4;
            ArchTree3D.cam.ry = 0.6;
            ArchTree3D.cam.zoom = 1.0;
            ArchTree3D.cam.tx = 0;
            ArchTree3D.cam.ty = 0;
            ArchTree3D.selected = null;
        });
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && modal.classList.contains('active')) {
                modal.classList.remove('active');
                ArchTree3D._stop();
            }
        });
    },

    _buildScene: function() {
        var products = ProductGraph.productTree || [];
        var rawLinks = ProductGraph.links || [];
        var catOrder = ProductGraph.categoryOrder || [];
        var cats = ProductGraph.categories || {};
        var self = this;

        // Group products by category
        var byCat = {};
        for (var i = 0; i < products.length; i++) {
            var p = products[i];
            if (!byCat[p.category]) byCat[p.category] = [];
            byCat[p.category].push(p);
        }

        // Create nodes: center hub + categories + products
        var nodes = [];
        var nodeMap = {};

        // Center hub
        nodes.push({ id: 'root', name: '华为云', type: 'root', color: '#C7000B', x: 0, y: 0, z: 0, r: 28 });
        nodeMap['root'] = 0;

        // Category nodes arranged in a circle on XY plane
        var catCount = catOrder.length;
        var catRadius = 210;
        for (var c = 0; c < catCount; c++) {
            var cat = catOrder[c];
            var angle = (2 * Math.PI * c) / catCount - Math.PI / 2;
            var cx = Math.cos(angle) * catRadius;
            var cy = Math.sin(angle) * catRadius;
            var cz = 0;
            var catColor = self.categoryColors[cat] || '#888';
            nodes.push({ id: 'cat_' + cat, name: (cats[cat] && cats[cat].name) || cat, type: 'category', category: cat, color: catColor, x: cx, y: cy, z: cz, r: 20 });
            nodeMap['cat_' + cat] = nodes.length - 1;
            // Link category to root
            self.links.push({ from: 0, to: nodes.length - 1, color: catColor, width: 2 });
        }

        // Product nodes orbit around their category
        var prodRadius = 125;
        for (var ci = 0; ci < catOrder.length; ci++) {
            var catKey = catOrder[ci];
            var catProds = byCat[catKey] || [];
            var catNodeIdx = nodeMap['cat_' + catKey];
            var catNode = nodes[catNodeIdx];
            var catColor = self.categoryColors[catKey] || '#888';
            for (var pi = 0; pi < catProds.length; pi++) {
                var prod = catProds[pi];
                var pAngle = (2 * Math.PI * pi) / Math.max(catProds.length, 1) + ci * 0.3;
                var tilt = (pi % 2 === 0 ? 1 : -1) * 55;
                var px = catNode.x + Math.cos(pAngle) * prodRadius;
                var py = catNode.y + Math.sin(pAngle) * prodRadius;
                var pz = catNode.z + tilt;
                nodes.push({ id: prod.id, name: prod.name, type: 'product', category: catKey, color: catColor, x: px, y: py, z: pz, r: 12, desc: prod.desc });
                var prodIdx = nodes.length - 1;
                nodeMap[prod.id] = prodIdx;
                // Link product to category
                self.links.push({ from: catNodeIdx, to: prodIdx, color: catColor, width: 1.2 });
            }
        }

        // Inter-product links
        for (var li = 0; li < rawLinks.length; li++) {
            var l = rawLinks[li];
            var fi = nodeMap[l.source];
            var ti = nodeMap[l.target];
            if (fi !== undefined && ti !== undefined) {
                var fromNode = nodes[fi];
                self.links.push({ from: fi, to: ti, color: 'rgba(255,255,255,0.12)', width: 0.8, dashed: true });
            }
        }

        // Add some extra flow connections (ECS->OBS->DWS->ModelArts style)
        var flows = [
            ['ecs','obs'],['obs','dws'],['dws','modelarts'],
            ['vpc','ecs'],['elb','vpc'],['eip','elb'],
            ['rds','ecs'],['dds','rds'],['gaussdb','dws'],
            ['cce','ecs'],['cci','cce'],['fgs','cce'],
            ['iotda','dli'],['dli','mrs'],['mrs','modelarts'],
            ['hss','waf'],['waf','elb'],['aad','waf'],
            ['cdn','obs'],['live','cdn'],['vod','live'],
            ['meeting','webrtc'],['weLink','meeting']
        ];
        for (var fi2 = 0; fi2 < flows.length; fi2++) {
            var f = flows[fi2];
            var fIdx = nodeMap[f[0]];
            var tIdx = nodeMap[f[1]];
            if (fIdx !== undefined && tIdx !== undefined) {
                var exists = false;
                for (var ei = 0; ei < self.links.length; ei++) {
                    var el = self.links[ei];
                    if ((el.from === fIdx && el.to === tIdx) || (el.from === tIdx && el.to === fIdx)) {
                        exists = true; break;
                    }
                }
                if (!exists) {
                    self.links.push({ from: fIdx, to: tIdx, color: 'rgba(255,255,255,0.08)', width: 0.6, dashed: true });
                }
            }
        }

        self.nodes = nodes;
    },

    _start: function() {
        var self = this;
        self.canvas = document.getElementById('arch-canvas');
        if (!self.canvas) return;
        self.ctx = self.canvas.getContext('2d');
        self._resize();
        window.addEventListener('resize', self._resize);

        if (self.nodes.length === 0) self._buildScene();

        // Mouse events
        self.canvas.addEventListener('mousedown', function(e) { self._onMouseDown(e); });
        self.canvas.addEventListener('mousemove', function(e) { self._onMouseMove(e); });
        self.canvas.addEventListener('mouseup', function(e) { self._onMouseUp(e); });
        self.canvas.addEventListener('mouseleave', function(e) { self._onMouseUp(e); });
        self.canvas.addEventListener('wheel', function(e) { self._onWheel(e); }, { passive: false });
        self.canvas.addEventListener('click', function(e) { self._onClick(e); });
        self.canvas.addEventListener('dblclick', function(e) { self._onDblClick(e); });

        self.autoRotate = true;
        self._loop();
    },

    _stop: function() {
        if (this.animId) cancelAnimationFrame(this.animId);
        this.animId = null;
    },

    _resize: function() {
        var wrapper = ArchTree3D.canvas && ArchTree3D.canvas.parentElement;
        if (!wrapper) return;
        var rect = wrapper.getBoundingClientRect();
        ArchTree3D.width = rect.width;
        ArchTree3D.height = rect.height;
        ArchTree3D.canvas.width = rect.width * (window.devicePixelRatio || 1);
        ArchTree3D.canvas.height = rect.height * (window.devicePixelRatio || 1);
        ArchTree3D.ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
    },

    _project: function(x, y, z) {
        var c = this.cam;
        // Rotate around Y
        var cosY = Math.cos(c.ry), sinY = Math.sin(c.ry);
        var x1 = x * cosY - z * sinY;
        var z1 = x * sinY + z * cosY;
        // Rotate around X
        var cosX = Math.cos(c.rx), sinX = Math.sin(c.rx);
        var y2 = y * cosX - z1 * sinX;
        var z2 = y * sinX + z1 * cosX;
        // Perspective
        var fov = 750 * c.zoom;
        var scale = fov / (fov + z2 + 400);
        return {
            x: this.width / 2 + (x1 + c.tx) * scale,
            y: this.height / 2 + (y2 + c.ty) * scale,
            z: z2,
            scale: scale,
            visible: z2 > -fov + 50
        };
    },

    _loop: function() {
        var self = ArchTree3D;
        self.animId = requestAnimationFrame(self._loop);

        if (self.autoRotate && !self.drag.active) {
            self.cam.ry += 0.0015;
        }

        var ctx = self.ctx;
        var w = self.width;
        var h = self.height;

        // Clear
        ctx.clearRect(0, 0, w, h);

        // Background subtle grid
        ctx.strokeStyle = 'rgba(255,255,255,0.015)';
        ctx.lineWidth = 1;
        for (var gx = 0; gx < w; gx += 60) {
            ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, h); ctx.stroke();
        }
        for (var gy = 0; gy < h; gy += 60) {
            ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke();
        }

        // Project all nodes
        var projected = [];
        for (var i = 0; i < self.nodes.length; i++) {
            projected.push(self._project(self.nodes[i].x, self.nodes[i].y, self.nodes[i].z));
        }

        // Draw links (sorted by depth, back to front)
        var linkData = [];
        for (var li = 0; li < self.links.length; li++) {
            var l = self.links[li];
            var p1 = projected[l.from];
            var p2 = projected[l.to];
            if (!p1.visible || !p2.visible) continue;
            var depth = (p1.z + p2.z) / 2;
            linkData.push({ l: l, p1: p1, p2: p2, depth: depth });
        }
        linkData.sort(function(a, b) { return a.depth - b.depth; });

        for (var lj = 0; lj < linkData.length; lj++) {
            var ld = linkData[lj];
            var isHighlight = self.selected !== null && (ld.l.from === self.selected || ld.l.to === self.selected);
            ctx.beginPath();
            ctx.moveTo(ld.p1.x, ld.p1.y);
            ctx.lineTo(ld.p2.x, ld.p2.y);
            ctx.strokeStyle = isHighlight ? ld.l.color : ld.l.color;
            ctx.lineWidth = isHighlight ? ld.l.width * 2.5 : ld.l.width;
            ctx.globalAlpha = isHighlight ? 0.9 : 0.25;
            if (ld.l.dashed && !isHighlight) {
                ctx.setLineDash([4, 6]);
            } else {
                ctx.setLineDash([]);
            }
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.globalAlpha = 1;
        }

        // Draw nodes (sorted by depth)
        var nodeData = [];
        for (var ni = 0; ni < self.nodes.length; ni++) {
            nodeData.push({ idx: ni, node: self.nodes[ni], p: projected[ni] });
        }
        nodeData.sort(function(a, b) { return a.p.z - b.p.z; });

        for (var nj = 0; nj < nodeData.length; nj++) {
            var nd = nodeData[nj];
            if (!nd.p.visible) continue;
            var n = nd.node;
            var isSel = self.selected === nd.idx;
            var isHov = self.hovered === nd.idx;
            var r = n.r * nd.p.scale * (isSel ? 1.3 : 1) * (isHov ? 1.15 : 1);
            var alpha = Math.min(1, nd.p.scale * 1.2);

            // Glow
            if (isSel || isHov || n.type === 'root') {
                var grad = ctx.createRadialGradient(nd.p.x, nd.p.y, r * 0.3, nd.p.x, nd.p.y, r * 3);
                grad.addColorStop(0, n.color);
                grad.addColorStop(1, 'transparent');
                ctx.fillStyle = grad;
                ctx.globalAlpha = (isSel ? 0.25 : 0.12) * alpha;
                ctx.beginPath();
                ctx.arc(nd.p.x, nd.p.y, r * 3, 0, Math.PI * 2);
                ctx.fill();
            }

            // Node body
            ctx.globalAlpha = alpha;
            var nodeGrad = ctx.createRadialGradient(nd.p.x - r * 0.3, nd.p.y - r * 0.3, 0, nd.p.x, nd.p.y, r);
            nodeGrad.addColorStop(0, self._lighten(n.color, 40));
            nodeGrad.addColorStop(1, n.color);
            ctx.fillStyle = nodeGrad;
            ctx.beginPath();
            ctx.arc(nd.p.x, nd.p.y, r, 0, Math.PI * 2);
            ctx.fill();

            // Border
            ctx.strokeStyle = isSel ? '#FFFFFF' : self._lighten(n.color, 20);
            ctx.lineWidth = isSel ? 2.5 : 1;
            ctx.globalAlpha = alpha * (isSel ? 0.9 : 0.4);
            ctx.beginPath();
            ctx.arc(nd.p.x, nd.p.y, r, 0, Math.PI * 2);
            ctx.stroke();

            // Label
            ctx.globalAlpha = alpha;
            ctx.fillStyle = '#FFFFFF';
            ctx.font = (n.type === 'root' ? 'bold 14px' : n.type === 'category' ? 'bold 12px' : '11px') + ' system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            var labelY = nd.p.y + r + (n.type === 'root' ? 18 : 14);
            // Label background
            var metrics = ctx.measureText(n.name);
            var lbw = metrics.width + 12;
            var lbh = 18;
            ctx.fillStyle = 'rgba(0,0,0,0.6)';
            ctx.beginPath();
            var rx = nd.p.x - lbw / 2, ry = labelY - lbh / 2, rw = lbw, rh = lbh, rr = 4;
            ctx.moveTo(rx + rr, ry);
            ctx.lineTo(rx + rw - rr, ry);
            ctx.quadraticCurveTo(rx + rw, ry, rx + rw, ry + rr);
            ctx.lineTo(rx + rw, ry + rh - rr);
            ctx.quadraticCurveTo(rx + rw, ry + rh, rx + rw - rr, ry + rh);
            ctx.lineTo(rx + rr, ry + rh);
            ctx.quadraticCurveTo(rx, ry + rh, rx, ry + rh - rr);
            ctx.lineTo(rx, ry + rr);
            ctx.quadraticCurveTo(rx, ry, rx + rr, ry);
            ctx.closePath();
            ctx.fill();
            ctx.fillStyle = isSel ? '#FFFFFF' : 'rgba(255,255,255,0.85)';
            ctx.fillText(n.name, nd.p.x, labelY);
            ctx.globalAlpha = 1;
        }
    },

    _lighten: function(hex, amt) {
        var num = parseInt(hex.replace('#', ''), 16);
        var r = Math.min(255, (num >> 16) + amt);
        var g = Math.min(255, ((num >> 8) & 0x00FF) + amt);
        var b = Math.min(255, (num & 0x0000FF) + amt);
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    },

    _onMouseDown: function(e) {
        this.drag.active = true;
        this.drag.sx = e.clientX;
        this.drag.sy = e.clientY;
        this.drag.srx = this.cam.rx;
        this.drag.sry = this.cam.ry;
        this.autoRotate = false;
        var btn = document.getElementById('arch-auto-rotate-btn');
        if (btn) btn.classList.remove('active');
    },

    _onMouseMove: function(e) {
        var rect = this.canvas.getBoundingClientRect();
        var mx = e.clientX - rect.left;
        var my = e.clientY - rect.top;

        if (this.drag.active) {
            var dx = e.clientX - this.drag.sx;
            var dy = e.clientY - this.drag.sy;
            this.cam.ry = this.drag.sry + dx * 0.005;
            this.cam.rx = this.drag.srx - dy * 0.005;
            this.cam.rx = Math.max(-1.2, Math.min(1.2, this.cam.rx));
            return;
        }

        // Hit test
        var closest = null;
        var closestDist = 9999;
        for (var i = 0; i < this.nodes.length; i++) {
            var p = this._project(this.nodes[i].x, this.nodes[i].y, this.nodes[i].z);
            if (!p.visible) continue;
            var dx2 = mx - p.x;
            var dy2 = my - p.y;
            var dist = Math.sqrt(dx2 * dx2 + dy2 * dy2);
            var hitR = this.nodes[i].r * p.scale * 1.5;
            if (dist < hitR && dist < closestDist) {
                closestDist = dist;
                closest = i;
            }
        }
        this.hovered = closest;
        this.canvas.style.cursor = closest !== null ? 'pointer' : 'grab';

        // Tooltip
        var tooltip = document.getElementById('arch-tooltip');
        if (tooltip) {
            if (closest !== null) {
                var n = this.nodes[closest];
                tooltip.innerHTML = '<b>' + n.name + '</b>' + (n.desc ? '<br><span style="font-size:11px;color:rgba(255,255,255,0.6)">' + (n.desc.length > 40 ? n.desc.substring(0, 40) + '...' : n.desc) + '</span>' : '');
                tooltip.style.left = (mx + 16) + 'px';
                tooltip.style.top = (my - 10) + 'px';
                tooltip.classList.add('visible');
            } else {
                tooltip.classList.remove('visible');
            }
        }
    },

    _onMouseUp: function(e) {
        this.drag.active = false;
    },

    _onWheel: function(e) {
        e.preventDefault();
        var delta = e.deltaY > 0 ? 0.9 : 1.1;
        this.cam.zoom = Math.max(0.3, Math.min(3.0, this.cam.zoom * delta));
    },

    _onClick: function(e) {
        if (this.hovered !== null) {
            this.selected = this.selected === this.hovered ? null : this.hovered;
        } else {
            this.selected = null;
        }
    },

    _onDblClick: function(e) {
        this.cam.zoom = 1.0;
        this.cam.tx = 0;
        this.cam.ty = 0;
    }
};