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
        const ids = [
            'solution-result', 'competitor-result',
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
                    // 只清空内容，不隐藏元素（页面可见性由 PageTransition 管理）
                    el.innerHTML = '';
                }
            }
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

        // 全局 window.onerror 捕获
        window.addEventListener('error', (event) => {
            if (event.target === window || event.target === document) {
                console.error('未捕获错误:', event.error);
                this.showBoundary('系统异常', '发生了未预期的错误，请刷新页面', event.error?.message);
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

    renderMarkdown(content) {
        let html;
        if (typeof marked !== 'undefined') {
            html = marked.parse(content);
        } else {
            html = content.replace(/\n/g, '<br>');
        }
        // 确保渲染内容在深色背景下可见：去除内联深色样式，用CSS控制颜色
        html = html.replace(/style="[^"]*color\s*:\s*#[0-9a-fA-F]{1,6}[^"]*"/gi, '');
        html = html.replace(/color\s*:\s*#[0-3][0-9a-fA-F]{5}/gi, 'color: rgba(255,255,255,0.88)');
        return html;
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
            const stats = await API.getKnowledgeStats();
            State.knowledgeStats = stats;
            SkeletonUI.clearSkeleton('knowledge-stats');
            
            const accuracy = stats.accuracy || 50;
            
            document.getElementById('nav-doc-count').textContent = stats.total_documents || 0;
            document.getElementById('nav-industry-count').textContent = stats.supported_industries?.length || 0;
            document.getElementById('nav-accuracy').textContent = `${accuracy}%`;
            
            document.getElementById('kb-total-docs').textContent = stats.total_documents || 0;
            document.getElementById('kb-total-industries').textContent = stats.supported_industries?.length || 0;
            document.getElementById('kb-accuracy').textContent = `${accuracy}%`;
            
            this.renderChart(stats.industry_counts || {});
        } catch (error) {
            console.error('加载统计失败:', error);
            UI.showToast('加载统计数据失败，请检查后端服务', 'warning');
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
                    backgroundColor: [
                        'rgba(199, 0, 11, 0.85)',
                        'rgba(199, 0, 11, 0.75)',
                        'rgba(199, 0, 11, 0.65)',
                        'rgba(74, 144, 226, 0.7)',
                        'rgba(74, 144, 226, 0.6)',
                        'rgba(74, 144, 226, 0.5)',
                        'rgba(82, 196, 26, 0.6)',
                        'rgba(82, 196, 26, 0.5)',
                        'rgba(250, 173, 20, 0.6)',
                        'rgba(250, 173, 20, 0.5)',
                        'rgba(199, 0, 11, 0.55)',
                        'rgba(74, 144, 226, 0.4)'
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
            this.toggle(name, fullContent, industry).then(() => {
                const btn = el.querySelector('.fav-action-btn');
                if (btn) {
                    btn.textContent = this.isFavorited(name) ? '⭐ 已收藏' : '☆ 收藏';
                    btn.className = this.isFavorited(name) ? 'btn-favorite active fav-action-btn' : 'btn-favorite fav-action-btn';
                }
            });
        }).catch(() => {
            UI.showToast('获取方案详情失败', 'warning');
        });
    },

    // Toggle favorite: add if not, remove if already
    async toggle(solutionName, solutionContent, industry) {
        const token = AuthManager.getToken();
        if (!token) { UI.showToast('请先登录', 'warning'); return; }

        if (this.isFavorited(solutionName)) {
            // Find the favorite id to remove
            try {
                const resp = await fetch('/api/auth/favorites?page_size=50', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await resp.json();
                const fav = data.favorites.find(f => f.solution_name === solutionName);
                if (fav) {
                    await this._remove(fav.id);
                    this.favoriteNames.delete(solutionName);
                    UI.showToast('已取消收藏', 'info');
                }
            } catch(e) {
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
                if (resp.ok) {
                    this.favoriteNames.add(solutionName);
                    UI.showToast('⭐ 已收藏', 'success');
                } else {
                    UI.showToast(data.detail || '收藏失败', 'warning');
                }
            } catch(e) {
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
        if (!token) return;
        try {
            const resp = await fetch('/api/auth/favorites?page_size=50', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!resp.ok) return;
            const data = await resp.json();
            this.favoriteNames = new Set(data.favorites.map(f => f.solution_name));
            
            const listEl = document.getElementById('fav-list');
            const emptyEl = document.getElementById('fav-list-empty');
            const countEl = document.getElementById('fav-count');
            
            if (countEl) countEl.textContent = data.favorites.length;
            
            if (data.favorites.length === 0) {
                listEl.style.display = 'none';
                emptyEl.style.display = '';
                return;
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
        } catch(e) {
            console.error('Load favorites error:', e);
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
            MatchProgress.success('方案匹配完成！');
            
            const resultContainer = document.getElementById('solution-result');
            const resultContent = document.getElementById('solution-content');
            const sourcesContainer = document.getElementById('solution-sources');
            
            if (!resultContainer || !resultContent) {
                console.warn('方案结果容器未找到，可能页面已切换');
                return;
            }
            
            resultContent.innerHTML = UI.renderMarkdown(result.answer);
            UI.renderSources(sourcesContainer, result.source_documents);
            resultContainer.style.display = 'block';
            resultContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
            
            State.resultCache.solution = { ...result, demand };
            // 更新收藏按钮状态
            FavoriteManager._updateResultBtn('fav-solution-btn', demand);
            FollowUpUI.show(demand, result.answer, result.history_id);
            
            UI.showToast('匹配完成！', 'success');
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
            AnalyzeProgress.success('竞争分析完成！');
            
            const resultContainer = document.getElementById('competitor-result');
            const resultContent = document.getElementById('competitor-content');
            const sourcesContainer = document.getElementById('competitor-sources');
            
            if (!resultContainer || !resultContent) {
                console.warn('竞品分析结果容器未找到，可能页面已切换');
                return;
            }
            
            resultContent.innerHTML = UI.renderMarkdown(result.answer);
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

    // 隐藏分页容器（无数据时）
    const pagContainer = document.getElementById('pagination-container');
    if (pagContainer) pagContainer.style.display = 'none';

    KnowledgeUI.loadStats();
}

document.addEventListener('DOMContentLoaded', init);
