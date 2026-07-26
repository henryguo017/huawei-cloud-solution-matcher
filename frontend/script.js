// [版本] 20260531w — 移除3D产品架构弹窗(ArchTree3D)功能，保留产品图谱页面(ProductGraph)
const Config = {
    API_BASE_URL: '/api',
    ANIMATION: {
        PARTICLE_COUNT: 80,
        CONNECTION_DISTANCE: 150,
        PARTICLE_SPEED: 0.5
    },
    INDUSTRIES: [
        '智慧农业', '工业互联网', '智慧园区', '智慧城市', '智慧医疗',
        '智慧金融', '智慧能源', '智慧交通', '智慧教育', '智慧文旅',
        '制造', '政务', '零售', '汽车', '矿山',
        '钢铁冶金', '化工', '智慧物流', '传媒文娱', '应急管理',
        '智慧水利', '国资云', '互联网', '游戏', '生物医药'
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
            // 登录成功后刷新当前页面，让 auth 状态自然初始化所有 UI 组件
            // 成就通知暂存到 sessionStorage，刷新后由 _checkPendingAchievements() 显示
            if (data.newly_unlocked && data.newly_unlocked.length > 0) {
                try { sessionStorage.setItem('pending_achievements', JSON.stringify(data.newly_unlocked)); } catch(_) {}
            }
            // 登录成功后，检查是否需要提示绑定邮箱
            if (data.user && !data.user.email) {
                const hideUntil = localStorage.getItem('hide_email_prompt_until');
                if (!hideUntil || Date.now() > parseInt(hideUntil)) {
                    AuthManager._showEmailBindingPrompt();
                    return true;
                }
            }
            location.reload();
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

    // 检查是否登录（含过期时间校验，避免"前端认为已登录但后端token已失效"的矛盾）
    isLoggedIn() {
        if (!State.authToken || !State.user) return false;
        try {
            const saved = localStorage.getItem(this.STORAGE_KEY);
            if (saved) {
                const data = JSON.parse(saved);
                // expiresAt 存在且已过期 → 判为未登录
                if (data.expiresAt && Date.now() >= data.expiresAt) return false;
            }
        } catch(e) { /* 解析失败按已登录处理，让后端最终裁决 */ }
        return true;
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

    _showEmailBindingPrompt() {
        const overlay = document.createElement('div');
        overlay.id = 'email-binding-overlay';
        overlay.className = 'auth-modal-overlay';
        overlay.innerHTML = `
            <div class="auth-modal">
                <button class="auth-modal-close" id="email-binding-close"><svg class="icon" aria-hidden="true"><use href="#i-x"></use></svg></button>
                <h2 style="text-align:center; margin-bottom:20px; color:#333;">建议绑定邮箱 <svg class="icon" aria-hidden="true"><use href="#i-mail"></use></svg></h2>
                <p style="text-align:center; color:#666; margin-bottom:25px; font-size:14px;">绑定邮箱后可通过邮件找回密码，提升账户安全</p>
                <form id="email-binding-form" class="auth-form">
                    <div class="form-group">
                        <label class="form-label">邮箱</label>
                        <input type="email" class="form-input" id="email-binding-input" placeholder="请输入邮箱" required autocomplete="email">
                    </div>
                    <div id="email-binding-error" class="auth-error" style="display:none;"></div>
                    <button type="submit" class="auth-submit-btn">
                        <span class="btn-text">绑定并保存</span>
                    </button>
                </form>
                <div class="auth-footer">
                    <button type="button" id="email-binding-skip" class="auth-switch-link">暂不绑定</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        overlay.style.display = '';
        const input = document.getElementById('email-binding-input');
        if (input) input.focus();

        const closePrompt = () => {
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
            location.reload();
        };

        document.getElementById('email-binding-close')?.addEventListener('click', closePrompt);
        document.getElementById('email-binding-form')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const email = document.getElementById('email-binding-input').value.trim();
            if (!email) {
                document.getElementById('email-binding-error').textContent = '请输入邮箱';
                document.getElementById('email-binding-error').style.display = '';
                return;
            }
            const token = AuthManager.getToken();
            try {
                const resp = await fetch(`${Config.API_BASE_URL}/auth/profile`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` }
                });
                if (!resp.ok) {
                    const data = await resp.json();
                    throw new Error(data.detail || '绑定失败');
                }
                const user = JSON.parse(localStorage.getItem('user') || '{}');
                user.email = email;
                localStorage.setItem('user', JSON.stringify(user));
                closePrompt();
            } catch (err) {
                document.getElementById('email-binding-error').textContent = err.message || '绑定失败，请重试';
                document.getElementById('email-binding-error').style.display = '';
            }
        });
        document.getElementById('email-binding-skip')?.addEventListener('click', () => {
            localStorage.setItem('hide_email_prompt_until', Date.now() + 7 * 24 * 60 * 60 * 1000);
            closePrompt();
        });
    },

    _clearAuth() {
        State.authToken = null;
        State.user = null;
        localStorage.removeItem(this.STORAGE_KEY);
    },

    _updateUI() {
        const loginBtn = document.getElementById('nav-login-btn');
        const mobileLoginBtn = document.getElementById('mobile-login-btn');
        const userMenu = document.getElementById('nav-user-menu');
        const userName = document.getElementById('nav-user-name');
        if (State.user) {
            if (loginBtn) loginBtn.style.display = 'none';
            if (mobileLoginBtn) mobileLoginBtn.style.display = 'none';
            if (userMenu) userMenu.style.display = '';
            if (userName) userName.textContent = State.user.username;
        } else {
            if (loginBtn) loginBtn.style.display = '';
            if (mobileLoginBtn) mobileLoginBtn.style.display = '';
            if (userMenu) userMenu.style.display = 'none';
        }
        // 同步"我的"聚合页用户卡片
        this._updateMineCard();
    },

    _updateMineCard() {
        const guest = document.getElementById('mine-user-guest');
        const logged = document.getElementById('mine-user-logged');
        const nameEl = document.getElementById('mine-user-name');
        const emailEl = document.getElementById('mine-user-email');
        if (!guest || !logged) return;
        if (State.user) {
            guest.style.display = 'none';
            logged.style.display = 'flex';
            if (nameEl) nameEl.textContent = State.user.username || '用户';
            if (emailEl) emailEl.textContent = State.user.email || '未绑定邮箱';
        } else {
            guest.style.display = 'flex';
            logged.style.display = 'none';
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
            // ★ 关键修复：从 localStorage（持久化真相来源）读 token，而非易失的 State.authToken
            const saved = localStorage.getItem(this.STORAGE_KEY);
            const token = saved ? JSON.parse(saved).token : null;
            if (!token) return;  // 无 token 时直接返回，不做任何清除

            const resp = await fetch(`${Config.API_BASE_URL}/auth/me`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!resp.ok) {
                // ★ 不再调用 _clearAuth() 清空 localStorage！
                // 旧逻辑：/auth/me 一旦 401（可能因网络抖动/竞态）就清空 localStorage，
                //   导致后续匹配请求从 localStorage 读 token 得到 null → 不发 header → 后端 401。
                // 新逻辑：验证失败仅记录，保留 localStorage 中的 token。
                //   token 是否真失效，由具体操作的「预验证」逻辑（匹配前 /auth/me）判定并兜底。
                console.warn('[Auth] _verifyToken 验证失败(HTTP ' + resp.status + ')，保留 localStorage 待后续操作预验证处理');
                this._updateUI();  // 仅刷新 UI 状态，不动 localStorage
            }
        } catch (e) {
            // 网络异常同样不清空 localStorage（避免误杀有效 token）
            console.warn('[Auth] _verifyToken 网络异常，保留 localStorage:', e);
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
        toast.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-circle-check"></use></svg> 设置已保存';
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
                particles: false,
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
    matchMode: 'agent',  // 'normal' | 'agent' | 'wizard'（默认主推 Agent 模式，与 index.html 默认 active 一致）
    currentClientId: null,  // 当前选中的客户档案 ID（Agent 记忆隔离维度）；null = 全局记忆
    wizardData: {          // 向导模式收集的数据
        industry: null,
        scale: null,
        pains: [],
        extra: ''
    },
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
        particles: false,
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
        document.getElementById('error-boundary-message').innerHTML = message || '请尝试刷新页面或稍后再试';

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

        textEl.innerHTML = message;
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

        // 全局未处理 Promise 拒绝捕获 —— 避免静默失败（如网络抖动时个别 fetch 未 catch）
        window.addEventListener('unhandledrejection', (event) => {
            const reason = event.reason;
            const msg = (reason && reason.message) ? reason.message : String(reason);
            console.error('=== 未处理的 Promise 拒绝 ===', reason);
            ErrorHandler.showInline('操作未能完成：' + msg + '（如持续出现请按 Ctrl+Shift+R 强制刷新）');
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
    async match(demand, signal, mode = "standard", customerFiles = []) {
        const headers = { 'Content-Type': 'application/json' };
        // 仅登录用户且非快速体验时发送鉴权
        if (AuthManager.isLoggedIn() && !State.isQuickDemo) {
            headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        }
        const response = await fetch(`${Config.API_BASE_URL}/match`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ demand, mode, customer_files: customerFiles, is_quick_demo: State.isQuickDemo }),
            signal
        });

        if (!response.ok) {
            throw new Error(`匹配失败: ${response.statusText}`);
        }

        return await response.json();
    },

    // 标准/向导模式 SSE 流式匹配（P0-2）：镜像 agentMatchStream 的 reader 框架
    async matchStream(demand, signal, mode = "standard", customerFiles = [], onEvent) {
        const headers = { 'Content-Type': 'application/json' };
        // 直读 localStorage token（与 agentMatchStream 一致的暴力修复，避免中间层吞掉 Authorization）
        let token = null;
        try {
            const raw = localStorage.getItem('hwcloud_auth');
            if (raw) {
                const d = JSON.parse(raw);
                token = d.token || d.access_token || null;
            }
        } catch (e) { token = null; }
        if (token) {
            headers['Authorization'] = 'Bearer ' + token;
        }

        const response = await fetch(`${Config.API_BASE_URL}/match/stream`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ demand, mode, customer_files: customerFiles, is_quick_demo: State.isQuickDemo }),
            signal
        });

        if (!response.ok) {
            const errBody = await response.json().catch(() => ({}));
            const detail = errBody.detail || `HTTP ${response.status}`;
            throw new Error(detail);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const parts = buffer.split('\n\n');
            buffer = parts.pop() || '';

            for (const part of parts) {
                if (!part.trim()) continue;
                const lines = part.split('\n');
                let eventType = '';
                let dataStr = '';
                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        eventType = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        dataStr = line.slice(6);
                    }
                }
                if (dataStr) {
                    try {
                        const data = JSON.parse(dataStr);
                        onEvent(data);
                    } catch (e) {
                        console.warn('[SSE match] JSON 解析失败:', dataStr);
                    }
                }
            }
        }
    },

    async agentMatchStream(demand, signal, onEvent, customerFiles = [], clientId = null) {
        const headers = { 'Content-Type': 'application/json' };

        // ★★ 暴力修复（2026-07-19 根治版）★★
        // 不经过任何中间层(State/AuthManager/isLoggedIn/isQuickDemo)，直接读 localStorage。
        // 之前所有 401 的根因都是某个中间层返回了 null 或 false，导致跳过 Authorization。
        let token = null;
        try {
            const raw = localStorage.getItem('hwcloud_auth');
            if (raw) {
                const d = JSON.parse(raw);
                token = d.token || d.access_token || null;
            }
        } catch(e) { token = null; }

        // 有 token 就无条件设置 Authorization —— 不再检查任何 flag
        if (token) {
            headers['Authorization'] = 'Bearer ' + token;
            console.log('[AgentMatch] ✓ Bearer已设 length=' + token.length + ' prefix=' + token.substring(0, 12));
        }
        // 即使 token 为空也继续发请求 —— 让服务端返回明确错误而不是前端静默失败
        console.log('[AgentMatch] hwcloud_auth原始值:', localStorage.getItem('hwcloud_auth')?.substring(0, 80));

        const response = await fetch(`${Config.API_BASE_URL}/agent/match/stream`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ demand, customer_files: customerFiles, client_id: clientId, is_quick_demo: State.isQuickDemo }),
            signal
        });

        if (!response.ok) {
            const errBody = await response.json().catch(() => ({}));
            const detail = errBody.detail || `HTTP ${response.status}`;
            console.error('[AgentMatch] ✗ 失败 —', response.status, detail,
                '| 发送时token:', token ? `${token.slice(0,10)}...${token.slice(-6)}` : '(无)');
            throw new Error(detail);
        }

        // 用 ReadableStream 读取 SSE
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            // 按 \n\n 分割 SSE 事件块
            const parts = buffer.split('\n\n');
            buffer = parts.pop() || '';

            for (const part of parts) {
                if (!part.trim()) continue;
                const lines = part.split('\n');
                let eventType = '';
                let dataStr = '';
                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        eventType = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        dataStr = line.slice(6);
                    }
                }
                if (dataStr) {
                    try {
                        const data = JSON.parse(dataStr);
                        onEvent(data);
                    } catch (e) {
                        console.warn('[SSE] JSON 解析失败:', dataStr);
                    }
                }
            }
        }
    },

    // 阶段 2.5：澄清续跑 —— 用户回答后带 clarify_id 续跑，SSE 流式返回（与 agentMatchStream 同构）
    async agentClarify(clarifyId, answers, clientId = null, signal, onEvent) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn() && !State.isQuickDemo) {
            headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        }
        const response = await fetch(`${Config.API_BASE_URL}/agent/clarify`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ clarify_id: clarifyId, answers: answers, client_id: clientId }),
            signal
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `澄清续跑失败: ${response.statusText}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const parts = buffer.split('\n\n');
            buffer = parts.pop() || '';

            for (const part of parts) {
                if (!part.trim()) continue;
                const lines = part.split('\n');
                let eventType = '';
                let dataStr = '';
                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        eventType = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        dataStr = line.slice(6);
                    }
                }
                if (dataStr) {
                    try {
                        const data = JSON.parse(dataStr);
                        onEvent(data);
                    } catch (e) {
                        console.warn('[SSE clarify] JSON 解析失败:', dataStr);
                    }
                }
            }
        }
    },

    async analyze(competitor, industry, signal) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn() && !State.isQuickDemo) {
            headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        }
        const response = await fetch(`${Config.API_BASE_URL}/analyze`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ competitor, industry, is_quick_demo: State.isQuickDemo }),
            signal
        });

        if (!response.ok) {
            throw new Error(`分析失败: ${response.statusText}`);
        }

        return await response.json();
    },

    async exportReport(request) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn() && !State.isQuickDemo) {
            headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        }
        const response = await fetch(`${Config.API_BASE_URL}/export/report`, {
            method: 'POST',
            headers,
            body: JSON.stringify(request)
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `导出失败: ${response.statusText}`);
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

    async getPricingReference(industry) {
        const url = industry
            ? `${Config.API_BASE_URL}/pricing/reference?industry=${encodeURIComponent(industry)}`
            : `${Config.API_BASE_URL}/pricing/reference`;
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`获取价目失败: ${response.statusText}`);
        }
        return await response.json();
    },

    async getAchievements() {
        const response = await fetch(`${Config.API_BASE_URL}/achievements`, {
            headers: AuthManager.isLoggedIn() ? { 'Authorization': `Bearer ${AuthManager.getToken()}` } : {}
        });
        if (!response.ok) throw new Error(`获取成就失败: ${response.statusText}`);
        return await response.json();
    },

    async checkPageView(page) {
        try {
            const response = await fetch(`${Config.API_BASE_URL}/achievements/page-view`, {
                method: 'POST',
                headers: AuthManager.isLoggedIn() ? {
                    'Authorization': `Bearer ${AuthManager.getToken()}`,
                    'Content-Type': 'application/json',
                } : { 'Content-Type': 'application/json' },
                body: JSON.stringify({ page }),
            });
            if (!response.ok) return null;
            const data = await response.json();
            if (data.newly_unlocked && data.newly_unlocked.length > 0 && window.AchievementUI && AchievementUI.showUnlockToast) {
                setTimeout(() => AchievementUI.showUnlockToast(data.newly_unlocked), 500);
            }
            return data;
        } catch (err) {
            console.warn('[Achievement] page-view check failed:', err.message);
            return null;
        }
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
        const headers = {};
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/rebuild`, {
            method: 'POST',
            headers
        });
        
        if (!response.ok) {
            throw new Error(`重建失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async clearKnowledge() {
        const headers = {};
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/clear`, {
            method: 'POST',
            headers
        });

        if (!response.ok) {
            throw new Error(`清空失败: ${response.statusText}`);
        }

        return await response.json();
    },

    async syncMyKnowledge() {
        const headers = {};
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/sync-mine`, {
            method: 'POST',
            headers
        });

        if (!response.ok) {
            let msg = `同步失败: ${response.statusText}`;
            try {
                const err = await response.json();
                if (err && err.detail) msg = err.detail;
            } catch (e) { /* ignore */ }
            throw new Error(msg);
        }

        return await response.json();
    },

    async getTaskStatus(taskId) {
        const headers = {};
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const resp = await fetch(`${Config.API_BASE_URL}/knowledge/task/${encodeURIComponent(taskId)}`, { headers });
        if (!resp.ok) {
            let msg = `查询失败: ${resp.statusText}`;
            try { const e = await resp.json(); if (e && e.detail) msg = e.detail; } catch (e) { /* ignore */ }
            throw new Error(msg);
        }
        return await resp.json();
    },

    // 通用 HTTP 方法
    async get(url) {
        const headers = {};
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const resp = await fetch(`${Config.API_BASE_URL}${url}`, { headers });
        if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || resp.statusText);
        return resp.json();
    },
    async post(url, body) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const resp = await fetch(`${Config.API_BASE_URL}${url}`, {
            method: 'POST',
            headers,
            body: JSON.stringify(body)
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `操作失败: ${resp.statusText}`);
        }
        return resp.json();
    },
    async put(url, body) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const resp = await fetch(`${Config.API_BASE_URL}${url}`, {
            method: 'PUT',
            headers,
            body: JSON.stringify(body)
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `更新失败: ${resp.statusText}`);
        }
        return resp.json();
    },
    async delete(url) {
        const headers = {};
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const resp = await fetch(`${Config.API_BASE_URL}${url}`, { method: 'DELETE', headers });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `删除失败: ${resp.statusText}`);
        }
        return resp.json();
    },

    // ========== 历史记录 API ==========
    async getHistoryList(offset = 0, limit = 20) {
        const response = await fetch(`${Config.API_BASE_URL}/history/list?page=${Math.floor(offset / limit) + 1}&page_size=${limit}`, {
            headers: AuthManager.isLoggedIn() ? { 'Authorization': `Bearer ${AuthManager.getToken()}` } : {}
        });
        if (!response.ok) throw new Error(`获取历史记录失败: ${response.statusText}`);
        return await response.json();
    },

    // 方案版本化：获取同一分组的全部版本（v1/v2/v3...）
    async getHistoryGroup(groupId) {
        return await this.get(`/history/group/${groupId}`);
    },

    // 方案版本化：将某版本标记为「定稿」（同组仅一个定稿）
    async finalizeHistory(id) {
        return await this.post(`/history/${id}/finalize`, {});
    },

    // 方案版本化：回滚（非破坏性复制为新版本）
    async rollbackHistory(id) {
        return await this.post(`/history/${id}/rollback`, {});
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
    },

    // 归档 / 取消归档 / 下载 / 追问（历史方案增强）
    async archiveHistory(historyId) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const response = await fetch(`${Config.API_BASE_URL}/history/${historyId}/archive`, {
            method: 'POST', headers
        });
        if (!response.ok) throw new Error(`归档失败: ${response.statusText}`);
        return await response.json();
    },

    async unarchiveHistory(historyId) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const response = await fetch(`${Config.API_BASE_URL}/history/${historyId}/unarchive`, {
            method: 'POST', headers
        });
        if (!response.ok) throw new Error(`取消归档失败: ${response.statusText}`);
        return await response.json();
    },

    async downloadHistoryFile(historyId) {
        const headers = {};
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const response = await fetch(`${Config.API_BASE_URL}/history/${historyId}/download`, {
            method: 'POST', headers
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `下载失败: ${response.statusText}`);
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        let fname = '华为云方案报告.docx';
        const cd = response.headers.get('Content-Disposition');
        if (cd) {
            const m = cd.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)/i);
            if (m) fname = decodeURIComponent(m[1]);
        }
        a.download = fname;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        return true;
    },

    async saveHistoryFollowup(historyId, followUp, refinedSolution, conversationHistory) {
        const headers = { 'Content-Type': 'application/json' };
        if (AuthManager.isLoggedIn()) headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
        const body = { follow_up: followUp, refined_solution: refinedSolution };
        if (conversationHistory) body.conversation_history = conversationHistory;
        const response = await fetch(`${Config.API_BASE_URL}/history/${historyId}/followup`, {
            method: 'POST', headers, body: JSON.stringify(body)
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `追问保存失败: ${response.statusText}`);
        }
        return await response.json();
    },
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

    setSteps(steps) {
        if (!this.stepsContainer) return;
        const stepEls = this.stepsContainer.querySelectorAll('.progress-step');
        steps.forEach((step, i) => {
            const el = stepEls[i];
            if (!el) return;
            const iconEl = el.querySelector('.step-icon');
            const labelEl = el.querySelector('.step-label');
            const descEl = el.querySelector('.step-desc');
            if (iconEl) iconEl.innerHTML = step.icon;
            if (labelEl) labelEl.textContent = step.label;
            if (descEl) descEl.textContent = step.desc;
        });
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
        if (title) title.innerHTML = message || '完成！';

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
        if (title) title.innerHTML = message || '出错了';
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

// 轮询后台知识库任务（重建/同步）直到完成或失败
// 每 1.5s 查询一次 /knowledge/task/{task_id}，回调 onTick(status) 用于更新进度条与文案
// 返回最终 TaskStatusResponse（success）；失败时 reject（含 404=服务重启导致任务丢失）
function pollKbTask(taskId, onTick) {
    return new Promise((resolve, reject) => {
        const timer = setInterval(async () => {
            try {
                const st = await API.getTaskStatus(taskId);
                if (onTick) onTick(st);
                if (st.status === 'success') {
                    clearInterval(timer);
                    resolve(st);
                } else if (st.status === 'failed') {
                    clearInterval(timer);
                    reject(new Error(st.message || '任务失败'));
                }
            } catch (e) {
                clearInterval(timer);
                reject(new Error(e.message || '无法获取任务状态（可能服务已重启，请重试）'));
            }
        }, 1500);
    });
}

// 对话式需求引导向导
const DemandWizard = {
    currentStep: 0,
    totalSteps: 4,
    _transitioning: false,   // 防止自动跳转期间的重复触发

    // 行业列表（每个行业使用独立图标，无重复）
    industries: [
        { name: '智慧农业', icon: '<svg class="icon" aria-hidden="true"><use href="#i-wheat"></use></svg>' },
        { name: '工业互联网', icon: '<svg class="icon" aria-hidden="true"><use href="#i-settings"></use></svg>' },
        { name: '智慧园区', icon: '<svg class="icon" aria-hidden="true"><use href="#i-building-2"></use></svg>' },
        { name: '智慧城市', icon: '<svg class="icon" aria-hidden="true"><use href="#i-city"></use></svg>' },
        { name: '智慧医疗', icon: '<svg class="icon" aria-hidden="true"><use href="#i-stethoscope"></use></svg>' },
        { name: '智慧金融', icon: '<svg class="icon" aria-hidden="true"><use href="#i-banknote"></use></svg>' },
        { name: '智慧能源', icon: '<svg class="icon" aria-hidden="true"><use href="#i-zap"></use></svg>' },
        { name: '智慧交通', icon: '<svg class="icon" aria-hidden="true"><use href="#i-car"></use></svg>' },
        { name: '智慧教育', icon: '<svg class="icon" aria-hidden="true"><use href="#i-book-open"></use></svg>' },
        { name: '智慧文旅', icon: '<svg class="icon" aria-hidden="true"><use href="#i-landmark"></use></svg>' },
        { name: '制造', icon: '<svg class="icon" aria-hidden="true"><use href="#i-factory"></use></svg>' },
        { name: '政务', icon: '<svg class="icon" aria-hidden="true"><use href="#i-shield"></use></svg>' },
        { name: '零售', icon: '<svg class="icon" aria-hidden="true"><use href="#i-shopping-cart"></use></svg>' },
        { name: '汽车', icon: '<svg class="icon" aria-hidden="true"><use href="#i-route"></use></svg>' },
        { name: '矿山', icon: '<svg class="icon" aria-hidden="true"><use href="#i-hard-hat"></use></svg>' },
        { name: '钢铁冶金', icon: '<svg class="icon" aria-hidden="true"><use href="#i-flame"></use></svg>' },
        { name: '化工', icon: '<svg class="icon" aria-hidden="true"><use href="#i-flask-conical"></use></svg>' },
        { name: '智慧物流', icon: '<svg class="icon" aria-hidden="true"><use href="#i-truck"></use></svg>' },
        { name: '传媒文娱', icon: '<svg class="icon" aria-hidden="true"><use href="#i-tv"></use></svg>' },
        { name: '应急管理', icon: '<svg class="icon" aria-hidden="true"><use href="#i-alert-triangle"></use></svg>' },
        { name: '智慧水利', icon: '<svg class="icon" aria-hidden="true"><use href="#i-droplets"></use></svg>' },
        { name: '国资云', icon: '<svg class="icon" aria-hidden="true"><use href="#i-cloud"></use></svg>' },
        { name: '互联网', icon: '<svg class="icon" aria-hidden="true"><use href="#i-globe"></use></svg>' },
        { name: '游戏', icon: '<svg class="icon" aria-hidden="true"><use href="#i-gamepad-2"></use></svg>' },
        { name: '生物医药', icon: '<svg class="icon" aria-hidden="true"><use href="#i-heart-pulse"></use></svg>' },
    ],

    // 痛点标签
    painTags: [
        '降本增效', '数字化转型', '设备预测性维护',
        '数据孤岛打通', '智能化升级', '安全合规',
        '客户体验提升', '供应链优化', '远程协作',
        '节能减排', '自动化运维', '精准营销',
    ],

    init() {
        this.renderIndustries();
        this.renderPainTags();
        this._bindEvents();
        // 初始隐藏（默认标准模式）
        this.container.style.display = 'none';
    },

    get container() {
        return document.getElementById('demand-wizard');
    },

    show() {
        this.container.style.display = 'block';
        this.goToStep(0);
        // 隐藏 textarea 和原来的按钮组
        const demandInput = document.getElementById('demand-input');
        if (demandInput) demandInput.parentElement.style.display = 'none';
        const btnGroup = document.querySelector('#page-solution .button-group');
        if (btnGroup) btnGroup.style.display = 'none';
    },

    hide() {
        this.container.style.display = 'none';
        const demandInput = document.getElementById('demand-input');
        if (demandInput) demandInput.parentElement.style.display = '';
        const btnGroup = document.querySelector('#page-solution .button-group');
        if (btnGroup) btnGroup.style.display = '';
    },

    goToStep(step) {
        // 防重入：动画期间禁止重复跳转
        if (this._transitioning && step !== this.currentStep) return;
        this._transitioning = true;
        this.currentStep = step;
        // 面板切换 — 用 data-wp 属性精确匹配，不依赖 querySelectorAll 的 DOM 索引
        this.container.querySelectorAll('.wizard-panel').forEach(p => {
            const wp = parseInt(p.getAttribute('data-wp'));
            p.classList.toggle('active', wp === step);
        });
        // 步骤指示器 — 用 data-ws 属性精确匹配
        this.container.querySelectorAll('.wizard-step-dot').forEach(dot => {
            const ws = parseInt(dot.getAttribute('data-ws'));
            dot.classList.remove('active', 'done');
            if (ws === step) dot.classList.add('active');
            else if (ws < step) dot.classList.add('done');
        });
        // 步骤连线 — 用 data-wl 属性精确匹配
        this.container.querySelectorAll('.wizard-step-line').forEach(line => {
            const wl = parseInt(line.getAttribute('data-wl'));
            line.classList.toggle('done', wl < step);
        });
        // 按钮状态
        const prevBtn = document.getElementById('wizard-prev-btn');
        const nextBtn = document.getElementById('wizard-next-btn');
        const submitBtn = document.getElementById('wizard-submit-btn');
        if (prevBtn) prevBtn.disabled = (step === 0);
        if (nextBtn) nextBtn.style.display = (step < this.totalSteps - 1) ? '' : 'none';
        if (submitBtn) submitBtn.style.display = (step === this.totalSteps - 1) ? '' : 'none';
        // Step 3 时更新摘要
        if (step === this.totalSteps - 1) {
            this.renderSummary();
        }
        // 动画完成后解锁（匹配 CSS 0.3s + 余量）
        setTimeout(() => { this._transitioning = false; }, 350);
    },

    next() {
        if (this.currentStep < this.totalSteps - 1) {
            this.goToStep(this.currentStep + 1);
        }
    },

    prev() {
        if (this.currentStep > 0) {
            this.goToStep(this.currentStep - 1);
        }
    },

    // ===== Step 0: 渲染行业卡片 =====
    renderIndustries() {
        const grid = document.getElementById('wizard-industry-grid');
        if (!grid) return;
        grid.innerHTML = this.industries.map(ind => 
            `<div class="wizard-industry-card" data-industry="${ind.name}">
                <span class="wic-icon">${ind.icon}</span>
                <span class="wic-name">${ind.name}</span>
            </div>`
        ).join('');
    },

    // ===== Step 2: 渲染痛点标签 =====
    renderPainTags() {
        const container = document.getElementById('wizard-pain-tags');
        if (!container) return;
        container.innerHTML = this.painTags.map(tag =>
            `<span class="wizard-pain-tag" data-pain="${tag}">${tag}</span>`
        ).join('');
    },

    // ===== Step 3: 渲染确认摘要 =====
    renderSummary() {
        const container = document.getElementById('wizard-summary');
        if (!container) return;
        const d = State.wizardData;
        const scaleLabels = { startup: '初创团队', sme: '中小企业', large: '大型企业', group: '集团/跨国' };
        container.innerHTML = `
            <div class="wizard-summary-item">
                <span class="wsi-label"><svg class="icon" aria-hidden="true"><use href="#i-pin"></use></svg> 行业</span>
                <span class="wsi-value">${d.industry || '未选择'}</span>
            </div>
            <div class="wizard-summary-item">
                <span class="wsi-label"><svg class="icon" aria-hidden="true"><use href="#i-building-2"></use></svg> 规模</span>
                <span class="wsi-value">${scaleLabels[d.scale] || '未选择'}</span>
            </div>
            <div class="wizard-summary-item">
                <span class="wsi-label"><svg class="icon" aria-hidden="true"><use href="#i-target"></use></svg> 关注点</span>
                <span class="wsi-tags">${d.pains.length > 0 
                    ? d.pains.map(p => `<span class="wsi-tag">${p}</span>`).join('') 
                    : '<span style="color:rgba(255,255,255,0.3)">未选择</span>'}</span>
            </div>
        `;
    },

    // ===== 合成需求描述 =====
    synthesizeDemand() {
        const d = State.wizardData;
        const scaleLabels = { startup: '初创团队（1-50人）', sme: '中小企业（50-500人）', large: '大型企业（500-5000人）', group: '集团企业（5000人以上）' };
        let demand = '';
        if (d.industry) demand += `我们是一家${d.industry}领域的${scaleLabels[d.scale] || '企业'}。`;
        if (d.pains.length > 0) {
            demand += `目前面临的主要痛点和需求是：${d.pains.join('、')}。`;
        }
        if (d.extra) demand += ` 补充信息：${d.extra}`;
        demand += ` 请推荐最适合的华为云行业解决方案。`;
        return demand;
    },

    _bindEvents() {
        // 行业选择
        document.getElementById('wizard-industry-grid')?.addEventListener('click', (e) => {
            const card = e.target.closest('.wizard-industry-card');
            if (!card) return;
            document.querySelectorAll('.wizard-industry-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            State.wizardData.industry = card.dataset.industry;
            setTimeout(() => this.next(), 200);
        });

        // 规模选择
        document.getElementById('wizard-scale-options')?.addEventListener('click', (e) => {
            const card = e.target.closest('.wizard-radio-card');
            if (!card) return;
            document.querySelectorAll('.wizard-radio-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            State.wizardData.scale = card.dataset.value;
            setTimeout(() => this.next(), 200);
        });

        // 痛点选择
        document.getElementById('wizard-pain-tags')?.addEventListener('click', (e) => {
            const tag = e.target.closest('.wizard-pain-tag');
            if (!tag) return;
            tag.classList.toggle('selected');
            const pain = tag.dataset.pain;
            if (tag.classList.contains('selected')) {
                if (!State.wizardData.pains.includes(pain)) State.wizardData.pains.push(pain);
            } else {
                State.wizardData.pains = State.wizardData.pains.filter(p => p !== pain);
            }
        });

        // 自定义痛点输入
        const customInput = document.getElementById('wizard-custom-pain');
        customInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && customInput.value.trim()) {
                const val = customInput.value.trim();
                if (!State.wizardData.pains.includes(val)) {
                    State.wizardData.pains.push(val);
                    // 动态添加标签
                    const tagsContainer = document.getElementById('wizard-pain-tags');
                    const span = document.createElement('span');
                    span.className = 'wizard-pain-tag selected';
                    span.dataset.pain = val;
                    span.textContent = val;
                    span.addEventListener('click', function() {
                        this.classList.remove('selected');
                        State.wizardData.pains = State.wizardData.pains.filter(p => p !== val);
                    });
                    tagsContainer?.appendChild(span);
                }
                customInput.value = '';
            }
        });

        // 补充信息
        document.getElementById('wizard-extra')?.addEventListener('input', (e) => {
            State.wizardData.extra = e.target.value;
        });

        // 导航按钮
        document.getElementById('wizard-prev-btn')?.addEventListener('click', () => this.prev());
        document.getElementById('wizard-next-btn')?.addEventListener('click', () => this.next());
        document.getElementById('wizard-submit-btn')?.addEventListener('click', () => {
            // 点击匹配按钮
            document.getElementById('match-btn')?.click();
        });
        document.getElementById('wizard-skip-btn')?.addEventListener('click', () => {
            // 切换到标准模式
            State.matchMode = 'normal';
            const modeToggle = document.getElementById('mode-toggle');
            modeToggle?.querySelectorAll('.mode-option').forEach(el => el.classList.remove('active'));
            modeToggle?.querySelector('[data-mode="normal"]')?.classList.add('active');
            const hint = document.getElementById('mode-hint');
            if (hint) hint.textContent = '精准搜索 + LLM 生成';
            this.hide();
        });
    },
};

// 初始化进度管理器实例
const MatchProgress = new ProgressManager('match-progress-panel', 'match-progress-bar', 'match-progress-steps', 'match-time-elapsed');
const AnalyzeProgress = new ProgressManager('analyze-progress-panel', 'analyze-progress-bar', 'analyze-progress-steps', 'analyze-time-elapsed');
const RebuildProgress = new ProgressManager('rebuild-progress-panel', 'rebuild-progress-bar', null, null);

const UI = {
    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = message;
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

        document.querySelectorAll('.sidebar-item').forEach(item => {
            item.classList.remove('active');
        });
        const sidebarItem = document.querySelector(`.sidebar-item[data-page="${pageName}"]`);
        if (sidebarItem) sidebarItem.classList.add('active');
        
        document.querySelectorAll('.mobile-nav-item').forEach(item => {
            item.classList.remove('active');
        });
        const mobileItem = document.querySelector(`.mobile-nav-item[data-page="${pageName}"]`);
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
            codeBlocks.push('<pre style="background:var(--neutral-300,#F7F8FA);border:1px solid var(--neutral-400,#F2F3F5);color:var(--neutral-900,#1D2129);padding:12px 16px;border-radius:8px;overflow-x:auto;font-size:13px;line-height:1.6;"><code>' + inner + '</code></pre>');
            return '___CODEBLOCK_' + idx + '___';
        });
        // 行内代码
        html = html.replace(/`([^`]+)`/g, '<code style="background:var(--neutral-300,#F7F8FA);color:var(--primary-color,#C7000B);border:1px solid var(--neutral-400,#F2F3F5);padding:1px 5px;border-radius:4px;font-size:13px;">$1</code>');
        // 标题（颜色用 token，字号交给 .result-content 的 token 规则以保留响应式缩放）
        html = html.replace(/^### (.+)$/gm, '<h4 style="color:var(--text-primary,#1D2129);margin:16px 0 8px;">$1</h4>');
        html = html.replace(/^## (.+)$/gm, '<h3 style="color:var(--text-primary,#1D2129);margin:18px 0 10px;">$1</h3>');
        html = html.replace(/^# (.+)$/gm, '<h2 style="color:var(--text-primary,#1D2129);margin:20px 0 12px;">$1</h2>');
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
        // 表格（在横线之前处理）— 增强版：跳过空行/宽松分隔/兜底管道符
        html = (function () {
            const lines = html.split('\n');
            const parseCells = (line) => {
                return line.split('|').slice(1, -1).map(function (c) { return c.trim(); });
            };
            const buildTable = (headerLine, dataLines) => {
                const headers = parseCells(headerLine);
                let tbl = '<table class="markdown-table" style="width:100%;border-collapse:collapse;margin:12px 0;font-size:var(--font-size-sm,14px);border:1px solid #d9d9d9;">';
                tbl += '<thead><tr>';
                headers.forEach(function (h) {
                    tbl += '<th style="border:1px solid #d9d9d9;border-bottom:2px solid rgba(199,0,11,0.15);padding:10px 14px;text-align:left;background:rgba(199,0,11,0.06);color:#1f2329;font-weight:600;">' + h + '</th>';
                });
                tbl += '</tr></thead><tbody>';
                dataLines.forEach(function (row) {
                    const cells = parseCells(row);
                    // 跳过全为 - : | 空格 的分隔行（防御性过滤）
                    if (cells.every(c => /^[\s\-:|]+$/.test(c) || c === '')) return;
                    tbl += '<tr>';
                    cells.forEach(function (c) {
                        tbl += '<td style="border:1px solid #e8e8e8;padding:10px 14px;color:#333;">' + c + '</td>';
                    });
                    tbl += '</tr>';
                });
                tbl += '</tbody></table>';
                return tbl;
            };
            // 判断是否为分隔行（宽松匹配：允许 |---| | :--- | | :--: | 等各种格式）
            const isSeparator = (line) => /^\|[\s\-:|]{3,}\|$/.test(line.trim());
            // 判断是否为表格数据行（以 | 开头和结尾，至少含一个 | 分隔的单元格）
            const isTableRow = (line) => /^\s*\|.+\|$/.test(line);

            let i = 0;
            while (i < lines.length) {
                if (isTableRow(lines[i])) {
                    const headerLine = lines[i].trim();
                    let sepIdx = -1;
                    // 向后查找分隔行（跳过空行，最多看 3 行）
                    for (let look = i + 1; look <= Math.min(i + 3, lines.length - 1); look++) {
                        if (isSeparator(lines[look])) { sepIdx = look; break; }
                        if (lines[look].trim() !== '' && !isTableRow(lines[look])) break; // 非空非表行→停止
                    }

                    if (sepIdx !== -1) {
                        // 找到分隔行，收集后续数据行（跳过空行）
                        let j = sepIdx + 1;
                        while (j < lines.length) {
                            if (isTableRow(lines[j])) { j++; }
                            else if (lines[j].trim() === '') { j++; } // 跳过表内空行
                            else { break; }
                        }
                        lines.splice(i, j - i, buildTable(headerLine, lines.slice(sepIdx + 1, j).filter(l => isTableRow(l))));
                    } else {
                        // 无显式分隔行：检测连续管道行是否构成无分隔符表格（≥2行且列数一致）
                        let j = i + 1;
                        while (j < lines.length) {
                            if (isTableRow(lines[j])) { j++; }
                            else if (lines[j].trim() === '') { j++; }
                            else { break; }
                        }
                        const rowLines = lines.slice(i, j).filter(l => isTableRow(l));
                        if (rowLines >= 2) {
                            const colCount = parseCells(rowLines[0]).length;
                            const allSameCols = rowLines.every(r => parseCells(r).length === colCount);
                            if (allSameCols && colCount >= 2) {
                                // 视为无分隔符表格：第一行当表头
                                lines.splice(i, j - i, buildTable(rowLines[0], rowLines.slice(1)));
                            } else {
                                i++;
                            }
                        } else {
                            i++;
                        }
                    }
                } else {
                    i++;
                }
            }

            // 兜底：将剩余孤立管道行转为可读文本（防止单行 |...| 泄漏）
            html = lines.join('\n');
            html = html.replace(/^(?:\s*\|.+\|)+$/gm, function (pipeBlock) {
                const pipeLines = pipeBlock.trim().split('\n').filter(l => /^\s*\|/.test(l));
                if (pipeLines.length <= 0) return pipeBlock;
                // 尝试构建简单文本表格
                const maxCols = Math.max.apply(null, pipeLines.map(l => l.split('|').length - 2));
                if (maxCols >= 2 && pipeLines.length >= 2) {
                    return buildTable(pipeLines[0].trim(), pipeLines.slice(1).map(l => l.trim()));
                }
                // 单行或单列：直接显示，去掉首尾 |
                return pipeLines.map(function (l) {
                    return l.replace(/^\s*\|/, '').replace(/\|\s*$/, '').replace(/\|/g, ' | ');
                }).join('<br>');
            });

            return html;
        })();
        // 横线
        html = html.replace(/^---$/gm, '<hr style="border:none;border-top:1px solid var(--neutral-500,#DCE0E6);margin:16px 0;">');
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
        // 未登录时静默跳过（/knowledge/stats 需要认证，避免 401 toast 干扰）
        if (!AuthManager.isLoggedIn()) { return; }
        try {
            SkeletonUI.showKnowledgeSkeleton();
            console.log('[KnowledgeUI] 正在加载统计数据...');
            const stats = await API.getKnowledgeStats();
            console.log('[KnowledgeUI] 统计数据获取成功:', stats);
            State.knowledgeStats = stats;
            SkeletonUI.clearSkeleton('knowledge-stats');

            // 安全写入DOM（元素可能不存在，如导航栏无accuracy显示位）
            const safeSet = (id, val) => { var el = document.getElementById(id); if (el) el.textContent = val; };

            safeSet('nav-doc-count', stats.total_documents || 0);
            safeSet('nav-industry-count', stats.supported_industries?.length || 0);
            // nav-accuracy 在导航栏中不存在，已移除引用

            safeSet('kb-total-docs', stats.total_documents || 0);
            safeSet('kb-total-industries', stats.supported_industries?.length || 0);
            safeSet('kb-competitors', stats.competitor_companies?.length || 0);

            // 动态更新标准模式进度面板的文档片段数
            const fragEl = document.getElementById('kb-fragment-count');
            if (fragEl && stats.total_documents) {
                fragEl.textContent = `从 ${stats.total_documents} 个文档片段中匹配相关方案`;
            }

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
                        position: 'nearest',
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
                            color: 'rgba(0, 0, 0, 0.06)'
                        },
                        ticks: {
                            color: '#555D6A',
                            stepSize: 10,
                            font: {
                                size: 12
                            }
                        },
                        title: {
                            display: true,
                            text: '文档数量',
                            color: '#555D6A',
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
                            color: '#333',
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

// ===== 知识库文档管理（扩展 KnowledgeUI） =====
Object.assign(KnowledgeUI, {
    docList: [],
    docFilter: 'all',
    editingDocId: null,

    async loadDocList() {
        const listEl = document.getElementById('kb-doc-list');
        const countEl = document.getElementById('kb-doc-count');
        if (!AuthManager.isLoggedIn()) {
            if (listEl) listEl.innerHTML = '<div class="kb-doc-skeleton">请登录后查看知识库文档</div>';
            if (countEl) countEl.textContent = '';
            this.docList = [];
            return;
        }
        try {
            if (listEl) listEl.innerHTML = '<div class="kb-doc-skeleton">加载中...</div>';
            const data = await API.get('/knowledge/documents');
            this.docList = data.documents || [];
            this.renderDocList();
        } catch (e) {
            console.error('[KnowledgeUI] 加载文档列表失败:', e);
            UI.showToast('加载文档列表失败', 'warning');
        }
    },

    renderDocList() {
        const listEl = document.getElementById('kb-doc-list');
        const countEl = document.getElementById('kb-doc-count');
        if (!listEl) return;

        // 根据登录状态控制「新增文档」按钮显示
        const addBtn = document.getElementById('kb-doc-add-btn');
        if (addBtn) addBtn.style.display = AuthManager.isLoggedIn() ? '' : 'none';

        let docs = this.docList;
        // 搜索过滤
        const searchTerm = (document.getElementById('kb-doc-search')?.value || '').toLowerCase();
        if (searchTerm) {
            docs = docs.filter(d => d.title.toLowerCase().includes(searchTerm) || d.industry.toLowerCase().includes(searchTerm));
        }
        // 分类过滤
        if (this.docFilter !== 'all') {
            docs = docs.filter(d => d.category === this.docFilter);
        }

        if (countEl) countEl.textContent = `共 ${docs.length} 个文档`;

        if (docs.length === 0) {
            listEl.innerHTML = '<div class="kb-doc-skeleton">暂无文档，点击"+ 新增文档"开始添加</div>';
            return;
        }

        const catIcons = { huawei: '<span class="cat-dot huawei"></span>', competitor: '<span class="cat-dot competitor"></span>' };
        const isLoggedIn = AuthManager.isLoggedIn();
        listEl.innerHTML = docs.map(d => `
            <div class="kb-doc-item" data-id="${d.id}">
                <span class="kb-doc-item-icon">${catIcons[d.category] || '<svg class="icon" aria-hidden="true"><use href="#i-file"></use></svg>'}</span>
                <div class="kb-doc-item-info">
                    <div class="kb-doc-item-title">${d.title}</div>
                    <div class="kb-doc-item-meta">
                        <span>${d.industry}</span>
                        <span>${d.category === 'huawei' ? '华为方案' : '竞品'}</span>
                        <span>${d.size_kb}KB</span>
                    </div>
                </div>
                ${isLoggedIn ? `
                <div class="kb-doc-item-actions">
                    <button class="kb-doc-action-btn" data-action="edit" data-id="${d.id}"><svg class="icon" aria-hidden="true"><use href="#i-pencil"></use></svg> 编辑</button>
                    <button class="kb-doc-action-btn" data-action="reindex" data-id="${d.id}"><svg class="icon" aria-hidden="true"><use href="#i-refresh-cw"></use></svg> 重索引</button>
                    <button class="kb-doc-action-btn danger" data-action="delete" data-id="${d.id}"><svg class="icon" aria-hidden="true"><use href="#i-trash-2"></use></svg></button>
                </div>
                ` : ''}
            </div>
        `).join('');

        // 绑定操作按钮事件
        listEl.querySelectorAll('.kb-doc-action-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const action = btn.dataset.action;
                const docId = btn.dataset.id;
                if (action === 'edit') this._openEditorForEdit(docId);
                else if (action === 'reindex') this._reindexDoc(docId);
                else if (action === 'delete') this._deleteDoc(docId);
            });
        });
    },

    async _openEditorForEdit(docId) {
        if (!AuthManager.isLoggedIn()) {
            UI.showToast('请先登录后再编辑文档', 'warning');
            AuthManager._openModal();
            return;
        }
        try {
            const doc = await API.get(`/knowledge/documents/${encodeURIComponent(docId)}`);
            this.editingDocId = docId;
            // 打开编辑弹窗
            document.getElementById('kb-editor-title-text').textContent = '编辑文档';
            document.getElementById('kb-editor-category').value = doc.category;
            document.getElementById('kb-editor-category').disabled = true;
            document.getElementById('kb-editor-industry').value = doc.industry;
            document.getElementById('kb-editor-industry').disabled = true;
            document.getElementById('kb-editor-doc-title').value = doc.filename.replace('.txt', '');
            document.getElementById('kb-editor-doc-title').disabled = true;
            document.getElementById('kb-editor-content').value = doc.content;
            document.getElementById('kb-editor-save-btn').querySelector('.btn-text').textContent = '更新';
            this._showEditor();
        } catch (e) {
            UI.showToast('加载文档失败: ' + e.message, 'error');
        }
    },

    async _reindexDoc(docId) {
        if (!AuthManager.isLoggedIn()) {
            UI.showToast('请先登录后再操作', 'warning');
            AuthManager._openModal();
            return;
        }
        try {
            UI.showToast('正在重新索引...', 'info');
            await API.post(`/knowledge/documents/${encodeURIComponent(docId)}/reindex`);
            UI.showToast('重新索引完成', 'success');
        } catch (e) {
            UI.showToast('重新索引失败: ' + e.message, 'error');
        }
    },

    async _deleteDoc(docId) {
        if (!AuthManager.isLoggedIn()) {
            UI.showToast('请先登录后再删除文档', 'warning');
            AuthManager._openModal();
            return;
        }
        const doc = this.docList.find(d => d.id === docId);
        if (!confirm(`确定要删除「${doc?.title || docId}」吗？此操作不可撤销。`)) return;
        try {
            await API.delete(`/knowledge/documents/${encodeURIComponent(docId)}`);
            UI.showToast('文档已删除', 'success');
            await this.loadDocList();
            await this.loadStats();
        } catch (e) {
            UI.showToast('删除失败: ' + e.message, 'error');
        }
    },

    _showEditor() {
        document.getElementById('kb-editor-overlay').style.display = '';
    },

    _hideEditor() {
        document.getElementById('kb-editor-overlay').style.display = 'none';
        this.editingDocId = null;
    },

    _resetEditor() {
        document.getElementById('kb-editor-title-text').textContent = '新增文档';
        document.getElementById('kb-editor-category').disabled = false;
        document.getElementById('kb-editor-category').value = 'huawei';
        document.getElementById('kb-editor-industry').disabled = false;
        document.getElementById('kb-editor-industry').value = '智慧农业';
        document.getElementById('kb-editor-doc-title').disabled = false;
        document.getElementById('kb-editor-doc-title').value = '';
        document.getElementById('kb-editor-content').value = '';
        document.getElementById('kb-editor-save-btn').querySelector('.btn-text').textContent = '保存';
        document.getElementById('kb-editor-status').textContent = '';
    },

    async _saveDocument() {
        if (!AuthManager.isLoggedIn()) {
            UI.showToast('请先登录后再保存文档', 'warning');
            AuthManager._openModal();
            return;
        }
        const statusEl = document.getElementById('kb-editor-status');
        const category = document.getElementById('kb-editor-category').value;
        const industry = document.getElementById('kb-editor-industry').value;
        const title = document.getElementById('kb-editor-doc-title').value.trim();
        const content = document.getElementById('kb-editor-content').value.trim();

        if (!title) { statusEl.textContent = '请输入文档标题'; return; }
        if (!content) { statusEl.textContent = '请输入文档内容'; return; }

        try {
            statusEl.textContent = '保存中...';
            if (this.editingDocId) {
                // 更新
                await API.put(`/knowledge/documents/${encodeURIComponent(this.editingDocId)}`, { content });
                UI.showToast('文档已更新', 'success');
            } else {
                // 新建
                await API.post('/knowledge/documents', { category, industry, title, content });
                UI.showToast('文档已创建', 'success');
            }
            this._hideEditor();
            await this.loadDocList();
            await this.loadStats();
        } catch (e) {
            statusEl.textContent = '保存失败: ' + e.message;
        }
    },

    _bindDocEvents() {
        // 新增按钮（需要登录）
        document.getElementById('kb-doc-add-btn')?.addEventListener('click', () => {
            if (!AuthManager.isLoggedIn()) {
                UI.showToast('请先登录后再管理知识库', 'warning');
                AuthManager._openModal();
                return;
            }
            this._resetEditor();
            this._showEditor();
        });
        // 关闭弹窗
        document.getElementById('kb-editor-close')?.addEventListener('click', () => this._hideEditor());
        document.getElementById('kb-editor-cancel-btn')?.addEventListener('click', () => this._hideEditor());
        // 保存按钮
        document.getElementById('kb-editor-save-btn')?.addEventListener('click', () => this._saveDocument());
        // 分类切换时更新行业列表
        document.getElementById('kb-editor-category')?.addEventListener('change', (e) => {
            const sel = document.getElementById('kb-editor-industry');
            if (e.target.value === 'competitor') {
                sel.innerHTML = `
                    <option value="AWS">AWS</option>
                    <option value="Google Cloud">Google Cloud</option>
                    <option value="Oracle Cloud">Oracle Cloud</option>
                    <option value="天翼云">天翼云</option>
                    <option value="火山引擎">火山引擎</option>
                    <option value="微软Azure">微软Azure</option>
                    <option value="施耐德电气">施耐德电气</option>
                    <option value="移动云">移动云</option>
                    <option value="联通云">联通云</option>
                    <option value="腾讯云">腾讯云</option>
                    <option value="西门子">西门子</option>
                    <option value="阿里云">阿里云</option>
                `;
            } else {
                sel.innerHTML = `
                    <option value="智慧农业">智慧农业</option>
                    <option value="工业互联网">工业互联网</option>
                    <option value="智慧园区">智慧园区</option>
                    <option value="智慧城市">智慧城市</option>
                    <option value="智慧医疗">智慧医疗</option>
                    <option value="智慧金融">智慧金融</option>
                    <option value="智慧能源">智慧能源</option>
                    <option value="智慧交通">智慧交通</option>
                    <option value="智慧教育">智慧教育</option>
                    <option value="智慧文旅">智慧文旅</option>
                    <option value="制造">制造</option>
                    <option value="政务">政务</option>
                    <option value="零售">零售</option>
                    <option value="汽车">汽车</option>
                    <option value="矿山">矿山</option>
                    <option value="钢铁冶金">钢铁冶金</option>
                    <option value="化工">化工</option>
                    <option value="智慧物流">智慧物流</option>
                    <option value="传媒文娱">传媒文娱</option>
                    <option value="应急管理">应急管理</option>
                    <option value="智慧水利">智慧水利</option>
                    <option value="国资云">国资云</option>
                    <option value="互联网">互联网</option>
                    <option value="游戏">游戏</option>
                    <option value="生物医药">生物医药</option>
                `;
            }
        });
        // 搜索
        document.getElementById('kb-doc-search')?.addEventListener('input', () => this.renderDocList());
        // 分类过滤
        document.querySelectorAll('.kb-filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.kb-filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.docFilter = btn.dataset.filter;
                this.renderDocList();
            });
        });
        // 点击弹窗遮罩关闭
        document.getElementById('kb-editor-overlay')?.addEventListener('click', (e) => {
            if (e.target === document.getElementById('kb-editor-overlay')) this._hideEditor();
        });
        // ESC关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && document.getElementById('kb-editor-overlay')?.style.display !== 'none') {
                this._hideEditor();
            }
        });
    },
});

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

        const accEl = document.getElementById('dash-competitors');
        if (accEl) accEl.textContent = stats.competitor_companies?.length || 0;

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
        if (!canvas || typeof Chart === 'undefined') {
            console.warn('[Dashboard] 图表渲染跳过:', {
                canvasFound: !!canvas,
                chartGlobal: typeof Chart !== 'undefined',
                chartFailed: window.__chartFailed || false
            });
            return;
        }
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
                        position: 'nearest',
                        callbacks: {
                            label: (ctx) => `文档数: ${ctx.raw} 篇`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(0, 0, 0, 0.06)' },
                        ticks: { color: '#555D6A', font: { size: 13 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#666', font: { size: 13, weight: '500' } }
                    }
                }
            }
        });
    },

    renderMatchTrend(trends) {
        const canvas = document.getElementById('match-trend-chart');
        if (!canvas || typeof Chart === 'undefined') {
            console.warn('[Dashboard] 图表渲染跳过:', {
                canvasFound: !!canvas,
                chartGlobal: typeof Chart !== 'undefined',
                chartFailed: window.__chartFailed || false
            });
            return;
        }
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
                        position: 'top',
                        align: 'end',
                        labels: { color: '#555D6A', font: { size: 12 }, usePointStyle: true, padding: 16 }
                    },
                    tooltip: {
                        position: 'nearest',
                        mode: 'index',
                        intersect: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(0, 0, 0, 0.06)' },
                        ticks: { color: '#555D6A', font: { size: 13 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { 
                            color: '#666', 
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
        if (!canvas || typeof Chart === 'undefined') {
            console.warn('[Dashboard] 图表渲染跳过:', {
                canvasFound: !!canvas,
                chartGlobal: typeof Chart !== 'undefined',
                chartFailed: window.__chartFailed || false
            });
            return;
        }
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
                        position: 'nearest',
                        callbacks: {
                            label: (ctx) => `占比 ${ctx.raw}%`
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'linear',
                        grid: { color: 'rgba(0, 0, 0, 0.06)' },
                        ticks: {
                            color: '#555D6A',
                            font: { family: 'Inter, sans-serif', size: 15, weight: '600' },
                            callback: (val) => val + '%',
                            padding: 8
                        },
                        border: { display: false }
                    },
                    y: {
                        grid: { display: false },
                        ticks: {
                            color: '#333',
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
                        ctx.fillStyle = '#555D6A';
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
        document.querySelectorAll('.sidebar-item').forEach(item => {
            item.classList.toggle('active', item.dataset.page === pageName);
        });
        // 移动端底部导航：子页面（历史/成就/设置）归属"我的"Tab
        const mineSubPages = ['mine', 'history', 'achievement', 'settings'];
        const mobileActive = mineSubPages.includes(pageName) ? 'mine' : pageName;
        document.querySelectorAll('.mobile-nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.page === mobileActive);
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
            document.getElementById('history-list').innerHTML = '';
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
                    <div class="empty-icon"><svg class="icon" aria-hidden="true"><use href="#i-clipboard-list"></use></svg></div>
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

    _statusBadges(item) {
        let html = '';
        if (item.downloaded) html += '<span class="history-badge badge-downloaded"><svg class="icon" aria-hidden="true"><use href="#i-circle-check"></use></svg> 已下载</span>';
        if (item.archived) html += '<span class="history-badge badge-archived"><svg class="icon" aria-hidden="true"><use href="#i-lock"></use></svg> 已归档</span>';
        return html;
    },

    // 方案版本化徽标：v1/v2/v3 + 定稿
    _versionBadge(item) {
        let html = '';
        if (item.version && item.version >= 1) {
            html += `<span class="history-badge badge-version">v${item.version}</span>`;
        }
        if (item.is_final) {
            html += '<span class="history-badge badge-final"><svg class="icon" aria-hidden="true"><use href="#i-circle-check"></use></svg> 定稿</span>';
        }
        return html;
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
                    <div class="history-item-checkbox">${isSelected ? '<svg class="icon" aria-hidden="true"><use href="#i-check"></use></svg>' : ''}</div>
                    <div class="history-item-content">
                        <div class="history-item-header">
                            <span class="history-item-date">${dateStr}</span>
                            <span class="history-item-tags">
                                ${item.industry ? `<span class="history-item-industry">${item.industry}</span>` : ''}
                                ${this._versionBadge(item)}
                                ${this._statusBadges(item)}
                            </span>
                        </div>
                        <div class="history-item-demand">${this.escapeHtml(demandPreview)}${item.demand_text && item.demand_text.length > 200 ? '...' : ''}</div>
                    </div>
                    <div class="history-item-actions">
                        <button class="btn-icon" title="下载方案报告" onclick="event.stopPropagation(); HistoryUI.downloadItem(${item.id})"><svg class="icon" aria-hidden="true"><use href="#i-download"></use></svg></button>
                        <button class="btn-icon ${item.archived ? 'active' : ''}" title="${item.archived ? '取消归档' : '归档'}" onclick="event.stopPropagation(); HistoryUI.toggleArchive(${item.id})"><svg class="icon" aria-hidden="true"><use href="#i-lock"></use></svg></button>
                        <button class="btn-favorite fav-action-btn ${isFav ? 'active' : ''}" onclick="event.stopPropagation(); FavoriteManager.toggleFromItem(this.closest('.history-item'))" title="${isFav ? '点击取消收藏' : '点击收藏'}">${isFav ? '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg>' : '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg>'}</button>
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
                            <span class="history-item-tags">
                                <span class="history-item-industry competitor-badge">${this.escapeHtml(item.competitor || '未知竞品')}</span>
                                ${item.industry ? `<span class="history-item-industry">${item.industry}</span>` : ''}
                                ${this._statusBadges(item)}
                            </span>
                        </div>
                        <div class="history-item-demand">${item.competitor ? '华为云 vs ' + this.escapeHtml(item.competitor) + (item.industry ? ' · ' + this.escapeHtml(item.industry) : '') + ' 对比分析' : '竞品分析报告 · 点击查看详情'}</div>
                    </div>
                    <div class="history-item-actions">
                        <button class="btn-icon" title="下载分析报告" onclick="event.stopPropagation(); HistoryUI.downloadItem(${item.id})"><svg class="icon" aria-hidden="true"><use href="#i-download"></use></svg></button>
                        <button class="btn-icon ${item.archived ? 'active' : ''}" title="${item.archived ? '取消归档' : '归档'}" onclick="event.stopPropagation(); HistoryUI.toggleArchive(${item.id})"><svg class="icon" aria-hidden="true"><use href="#i-lock"></use></svg></button>
                        <button class="btn-favorite fav-action-btn ${isFav ? 'active' : ''}" onclick="event.stopPropagation(); FavoriteManager.toggleFromItem(this.closest('.history-item'))" title="${isFav ? '点击取消收藏' : '点击收藏'}">${isFav ? '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg>' : '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg>'}</button>
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
            this._openDetailModal(item, 'match');
        } catch (error) {
            console.error('加载详情失败:', error);
            UI.showToast('加载详情失败', 'warning');
        }
    },

    async showCompetitorDetail(id) {
        try {
            const item = await API.getCompetitorHistoryDetail(id);
            this._openDetailModal(item, 'analyze');
        } catch (error) {
            console.error('加载竞品详情失败:', error);
            UI.showToast('加载详情失败', 'warning');
        }
    },

    _openDetailModal(item, type) {
        const modal = document.getElementById('history-detail-modal');
        const body = document.getElementById('detail-body');
        if (!modal || !body) return;
        this.currentDetail = item;
        this.currentDetailType = type;
        this._pendingRefined = null;
        body.innerHTML = this.renderDetailBody(item, type);
        this.bindDetailEvents(item, type);
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        // 历史方案匹配详情：补渲染成本参考卡片（只读，不绑定编辑/导出，独立 id 避免冲突）
        if (type === 'match') {
            try { renderCostReferenceReadOnly(item); } catch (e) { console.warn('历史成本卡片渲染失败', e); }
        }
    },

    renderDetailBody(item, type) {
        const dateStr = item.created_at ? item.created_at.replace('T', ' ').substring(0, 16) : '--';
        const contentLabel = type === 'analyze' ? '分析报告' : '匹配方案';
        const contentHtml = type === 'analyze'
            ? (item.analysis ? UI.renderMarkdown(item.analysis) : '<p style="color: var(--text-muted)">无分析内容</p>')
            : (item.solution ? UI.renderMarkdown(item.solution) : '<p style="color: var(--text-muted)">无方案内容</p>');
        const demandBlock = type === 'analyze'
            ? `<div class="detail-section"><div class="detail-section-label">竞品名称</div><div class="detail-demand">${this.escapeHtml(item.competitor || '')}</div></div>
               <div class="detail-section"><div class="detail-section-label">所属行业</div><div class="detail-demand">${this.escapeHtml(item.industry || '')}</div></div>`
            : `<div class="detail-section"><div class="detail-section-label">客户需求</div><div class="detail-demand">${this.escapeHtml(item.demand_text || '')}</div></div>`;
        const statusLine = this._statusBadges(item) ? `<div class="detail-status">${this._statusBadges(item)}</div>` : '';
        const archiveBtn = item.archived
            ? `<button class="btn btn-secondary btn-sm" id="detail-unarchive-btn"><svg class="icon" aria-hidden="true"><use href="#i-lock"></use></svg> 取消归档</button>`
            : `<button class="btn btn-secondary btn-sm" id="detail-archive-btn"><svg class="icon" aria-hidden="true"><use href="#i-lock"></use></svg> 归档</button>`;
        const followupBtn = item.archived ? '' : `<button class="btn btn-primary btn-sm" id="detail-followup-toggle">追问优化</button>`;
        // 方案版本化：版本徽标 + 定稿/回滚/查看版本按钮（仅方案匹配 & 未归档）
        const versionLine = (type === 'match' && (item.version || item.is_final))
            ? `<div class="detail-status">${this._versionBadge(item)}</div>` : '';
        const finalizeBtn = (type === 'match' && !item.is_final && !item.archived)
            ? `<button class="btn btn-success btn-sm" id="detail-finalize-btn"><svg class="icon" aria-hidden="true"><use href="#i-circle-check"></use></svg> 定稿</button>` : '';
        const rollbackBtn = (type === 'match' && !item.archived)
            ? `<button class="btn btn-secondary btn-sm" id="detail-rollback-btn"><svg class="icon" aria-hidden="true"><use href="#i-refresh-cw"></use></svg> 回滚为新版本</button>` : '';
        const versionsBtn = (type === 'match' && item.group_id)
            ? `<button class="btn btn-ghost btn-sm" id="detail-versions-btn"><svg class="icon" aria-hidden="true"><use href="#i-layers"></use></svg> 查看版本</button>` : '';
        const versionsSection = (type === 'match' && item.group_id)
            ? `<div class="detail-section" id="detail-versions-section" style="display:none;">
                   <div class="detail-section-label">方案版本（v1/v2/v3）</div>
                   <div id="detail-versions-list" class="versions-list"></div>
               </div>` : '';
        const costRefSection = (type === 'match') ? `
            <div class="detail-section">
                <div class="detail-section-label">成本参考估算</div>
                <div class="cost-reference-card detail-cr-card" id="detail-cost-reference-card" style="display:none; margin-top:8px;">
                    <div class="cr-header">
                        <div><span class="cr-title">方案成本区间参考</span> <span class="cr-badge" id="detail-cr-industry-badge">通用</span></div>
                        <div class="cr-sub" id="detail-cr-sub">基于公开价目表策展的区间参考</div>
                    </div>
                    <div class="cr-disclaimer" id="detail-cr-disclaimer"></div>
                    <div class="cr-table" id="detail-cr-table"></div>
                    <div class="cr-total">
                        <span class="cr-total-label" id="detail-cr-total-label">预估月费合计（参考）</span>
                        <strong class="cr-total-value" id="detail-cr-total">¥0</strong>
                    </div>
                </div>
            </div>` : '';
        return `
            <div class="detail-section">
                <div class="detail-section-label">创建时间</div>
                <div style="font-size: var(--font-size-sm); color: var(--text-secondary);">${dateStr}</div>
            </div>
            ${demandBlock}
            ${versionLine}
            <div class="detail-section">
                <div class="detail-section-label">${contentLabel}</div>
                <div class="detail-solution result-content" id="detail-solution-content">${contentHtml}</div>
            </div>
            <div class="detail-actions">
                ${statusLine}
                <div class="detail-action-btns">
                    <button class="btn btn-secondary btn-sm" id="detail-download-btn"><svg class="icon" aria-hidden="true"><use href="#i-download"></use></svg> 下载报告</button>
                    ${archiveBtn}
                    ${followupBtn}
                    ${finalizeBtn}
                    ${rollbackBtn}
                    ${versionsBtn}
                </div>
            </div>
            ${versionsSection}
            ${costRefSection}
            <div class="followup-section" id="followup-section" style="display:none;">
                <div class="followup-title">追问优化（基于当前方案继续对话，优化后自动保存）</div>
                <div class="followup-conversation" id="followup-conversation">${this.renderConversation(item.conversation || [])}</div>
                <div class="followup-input-row">
                    <textarea id="followup-input" class="followup-input" placeholder="例如：补充预算控制在 50 万以内的实施路径，并突出华为云差异化优势"></textarea>
                    <button class="btn btn-primary btn-sm" id="followup-send">发送</button>
                </div>
                <div class="followup-preview" id="followup-preview" style="display:none;"></div>
                <div class="followup-preview-actions" id="followup-preview-actions" style="display:none;">
                    <button class="btn btn-success btn-sm" id="followup-apply">应用并保存</button>
                    <button class="btn btn-ghost btn-sm" id="followup-discard">放弃</button>
                </div>
            </div>
        `;
    },

    renderConversation(conv) {
        if (!conv || !conv.length) {
            return '<div class="followup-empty">暂无追问记录。输入你的问题，AI 会基于当前方案继续优化并保存到本记录。</div>';
        }
        return conv.map(m => {
            if (m.role === 'user') {
                return `<div class="followup-msg user"><div class="followup-role">你</div><div class="followup-text">${this.escapeHtml(m.content || '')}</div></div>`;
            }
            return `<div class="followup-msg assistant"><div class="followup-role">AI</div><div class="followup-text followup-ai-summary">已根据上方追问优化方案（更新于上方方案正文）</div></div>`;
        }).join('');
    },

    bindDetailEvents(item, type) {
        const dl = document.getElementById('detail-download-btn');
        if (dl) dl.addEventListener('click', async () => {
            try {
                UI.showToast('正在生成并下载文件...', 'info');
                await API.downloadHistoryFile(item.id);
                item.downloaded = true;
                this.renderList();
                UI.showToast('已下载到本地', 'success');
            } catch (e) {
                UI.showToast(e.message || '下载失败', 'error');
            }
        });
        const ab = document.getElementById('detail-archive-btn');
        if (ab) ab.addEventListener('click', async () => {
            try {
                await API.archiveHistory(item.id);
                item.archived = true;
                this.renderList();
                this._openDetailModal(item, type);
                UI.showToast('已归档，记录已锁定不可修改', 'success');
            } catch (e) {
                UI.showToast(e.message || '归档失败', 'error');
            }
        });
        const ub = document.getElementById('detail-unarchive-btn');
        if (ub) ub.addEventListener('click', async () => {
            try {
                await API.unarchiveHistory(item.id);
                item.archived = false;
                this.renderList();
                this._openDetailModal(item, type);
                UI.showToast('已取消归档', 'info');
            } catch (e) {
                UI.showToast(e.message || '操作失败', 'error');
            }
        });
        const ft = document.getElementById('detail-followup-toggle');
        if (ft) ft.addEventListener('click', () => {
            const sec = document.getElementById('followup-section');
            if (sec) sec.style.display = sec.style.display === 'none' ? 'block' : 'none';
        });
        const send = document.getElementById('followup-send');
        if (send) send.addEventListener('click', () => this.sendFollowup(item, type));
        const apply = document.getElementById('followup-apply');
        if (apply) apply.addEventListener('click', () => this.applyFollowup(item, type));
        const discard = document.getElementById('followup-discard');
        if (discard) discard.addEventListener('click', () => {
            const p = document.getElementById('followup-preview');
            const pa = document.getElementById('followup-preview-actions');
            if (p) p.style.display = 'none';
            if (pa) pa.style.display = 'none';
            this._pendingRefined = null;
        });
        // 方案版本化：定稿 / 回滚 / 查看版本
        const fb = document.getElementById('detail-finalize-btn');
        if (fb) fb.addEventListener('click', async () => {
            try {
                const resp = await API.finalizeHistory(item.id);
                item.is_final = true;
                this.renderList();
                this._openDetailModal(item, type);
                UI.showToast(resp.message || '已定稿', 'success');
            } catch (e) {
                UI.showToast(e.message || '定稿失败', 'error');
            }
        });
        const rb = document.getElementById('detail-rollback-btn');
        if (rb) rb.addEventListener('click', async () => {
            try {
                const resp = await API.rollbackHistory(item.id);
                this.renderList();
                UI.showToast(resp.message || '已回滚生成新版本', 'success');
                const sec = document.getElementById('detail-versions-section');
                if (sec && sec.style.display !== 'none' && item.group_id) {
                    this._loadVersions(item.group_id, item.id);
                }
            } catch (e) {
                UI.showToast(e.message || '回滚失败', 'error');
            }
        });
        const vb = document.getElementById('detail-versions-btn');
        if (vb) vb.addEventListener('click', () => {
            const sec = document.getElementById('detail-versions-section');
            if (!sec) return;
            if (sec.style.display === 'none') {
                sec.style.display = 'block';
                this._loadVersions(item.group_id, item.id);
            } else {
                sec.style.display = 'none';
            }
        });
    },

    // 加载并渲染同一分组的全部版本（v1/v2/v3）
    async _loadVersions(groupId, currentId) {
        const listEl = document.getElementById('detail-versions-list');
        if (!listEl) return;
        listEl.innerHTML = '<div class="versions-loading">加载中...</div>';
        try {
            const group = await API.getHistoryGroup(groupId);
            const versions = group.versions || [];
            if (versions.length === 0) {
                listEl.innerHTML = '<div class="versions-empty">暂无其他版本</div>';
                return;
            }
            listEl.innerHTML = versions.map(v => {
                const cur = v.id === currentId ? ' current' : '';
                const fin = v.is_final ? '<span class="history-badge badge-final"><svg class="icon" aria-hidden="true"><use href="#i-circle-check"></use></svg> 定稿</span>' : '';
                const dt = v.created_at ? v.created_at.replace('T', ' ').substring(0, 16) : '';
                return `
                    <div class="version-item${cur}">
                        <div class="version-item-head">
                            <span class="version-tag">v${v.version}</span>
                            ${fin}
                            <span class="version-date">${dt}</span>
                        </div>
                        <div class="version-preview">${this.escapeHtml((v.solution_preview || '').substring(0, 120))}</div>
                        <button class="btn btn-ghost btn-sm version-view-btn" onclick="event.stopPropagation(); HistoryUI.showDetail(${v.id})">查看此版本</button>
                    </div>`;
            }).join('');
        } catch (e) {
            listEl.innerHTML = '<div class="versions-empty">版本加载失败</div>';
        }
    },

    async sendFollowup(item, type) {
        const input = document.getElementById('followup-input');
        const followUp = (input && input.value || '').trim();
        if (!followUp) { UI.showToast('请输入追问内容', 'warning'); return; }
        const preview = document.getElementById('followup-preview');
        const previewActions = document.getElementById('followup-preview-actions');
        const sendBtn = document.getElementById('followup-send');
        try {
            sendBtn.disabled = true;
            sendBtn.textContent = '生成中...';
            const history = (item.conversation || []).filter(m => m.role === 'user' || m.role === 'assistant');
            let data;
            if (type === 'analyze') {
                data = await API.refineCompetitorAnalysis(item.competitor || '', item.industry || '', item.analysis || '', followUp, history);
            } else {
                data = await API.refineSolution(item.demand_text || '', item.solution || '', followUp, history);
            }
            this._pendingRefined = data.refined_solution;
            preview.innerHTML = `<div class="detail-section-label">AI 优化结果预览</div><div class="detail-solution result-content">${UI.renderMarkdown(data.refined_solution)}</div>`;
            preview.style.display = 'block';
            previewActions.style.display = 'flex';
        } catch (e) {
            UI.showToast(e.message || '优化失败', 'error');
        } finally {
            sendBtn.disabled = false;
            sendBtn.textContent = '发送';
        }
    },

    async applyFollowup(item, type) {
        const input = document.getElementById('followup-input');
        const followUp = (input && input.value || '').trim();
        if (!this._pendingRefined) return;
        try {
            const resp = await API.saveHistoryFollowup(item.id, followUp, this._pendingRefined);
            item.conversation = resp.conversation || (item.conversation || []).concat([
                { role: 'user', content: followUp },
                { role: 'assistant', content: this._pendingRefined }
            ]);
            if (type === 'analyze') { item.analysis = this._pendingRefined; } else { item.solution = this._pendingRefined; }
            const li = this.items.find(it => it.id === item.id);
            if (li) {
                if (type === 'analyze') li.analysis_preview = (this._pendingRefined || '').substring(0, 500);
                else li.solution_preview = (this._pendingRefined || '').substring(0, 500);
            }
            const solEl = document.getElementById('detail-solution-content');
            if (solEl) solEl.innerHTML = UI.renderMarkdown(this._pendingRefined);
            const convEl = document.getElementById('followup-conversation');
            if (convEl) convEl.innerHTML = this.renderConversation(item.conversation);
            const p = document.getElementById('followup-preview');
            const pa = document.getElementById('followup-preview-actions');
            if (p) p.style.display = 'none';
            if (pa) pa.style.display = 'none';
            if (input) input.value = '';
            this._pendingRefined = null;
            this.renderList();
            UI.showToast('优化结果已保存', 'success');
        } catch (e) {
            UI.showToast(e.message || '保存失败', 'error');
        }
    },

    closeDetail() {
        const modal = document.getElementById('history-detail-modal');
        if (modal) modal.style.display = 'none';
        document.body.style.overflow = '';
    },

    // 列表项：下载方案/报告（重新生成 docx 并标记已下载）
    async downloadItem(id) {
        const item = this.items.find(it => it.id === id);
        try {
            UI.showToast('正在生成并下载文件...', 'info');
            await API.downloadHistoryFile(id);
            if (item) item.downloaded = true;
            this.renderList();
            UI.showToast('已下载到本地', 'success');
        } catch (e) {
            console.error('下载失败:', e);
            UI.showToast(e.message || '下载失败', 'error');
        }
    },

    // 列表项：归档 / 取消归档
    async toggleArchive(id) {
        const item = this.items.find(it => it.id === id);
        if (!item) return;
        try {
            if (item.archived) {
                await API.unarchiveHistory(id);
                item.archived = false;
                UI.showToast('已取消归档', 'info');
            } else {
                await API.archiveHistory(id);
                item.archived = true;
                UI.showToast('已归档，记录将被锁定不可修改', 'success');
            }
            this.renderList();
        } catch (e) {
            console.error('归档操作失败:', e);
            UI.showToast(e.message || '操作失败', 'error');
        }
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
                    btn.innerHTML = this.isFavorited(name) ? '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg> 已收藏' : '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg> 收藏';
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
                    UI.showToast('<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg> 已收藏', 'success');
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
                        <button class="profile-fav-item-delete" onclick="FavoriteManager.deleteFavorite(${f.id}, '${HistoryUI.escapeHtml(f.solution_name).replace(/'/g, "\\'")}')" title="取消收藏"><svg class="icon" aria-hidden="true"><use href="#i-x"></use></svg></button>
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
            
            if (headerTitle) headerTitle.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg> 收藏详情';
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
            btn.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg> 已收藏';
            btn.classList.add('active');
        } else {
            btn.innerHTML = btnId === 'fav-solution-btn' ? '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg> 收藏方案' : '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg> 收藏报告';
            btn.classList.remove('active');
        }
    }
};

function initEventListeners() {
    // 防止浏览器自动填充顶栏搜索框（Edge/Chrome 忽略 autocomplete=off）
    (function clearSearchAutofill() {
        const si = document.getElementById('topbar-search-input');
        if (!si) return;
        const doClear = () => { if (si.value) si.value = ''; };
        doClear();
        setTimeout(doClear, 100);
        setTimeout(doClear, 500);
    })();

    document.querySelectorAll('.navbar-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            // 登录检查：Dashboard 和历史记录需要登录
            if ((page === 'dashboard' || page === 'history') && !AuthManager.isLoggedIn()) {
                AuthManager._openModal();
                return;
            }
            PageTransition.switchTo(page).then(() => {
                if (page === 'knowledge') { KnowledgeUI.loadStats(); KnowledgeUI.loadDocList(); }
                if (page === 'dashboard') DashboardUI.loadStats();
                if (page === 'history') HistoryUI.loadHistory();
                if (page === 'settings') SettingsManager.updateSystemInfo();
                if (page === 'products') { setTimeout(function() { try { ProductGraph._renderGrid(); } catch(e) { console.warn('[PageSwitch] 产品图谱渲染失败:', e); } }, 100); }
            }).catch(err => console.warn('[PageSwitch] 页面切换失败:', err));
        });
    });

    document.querySelectorAll('.mobile-nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            // 登录检查：Dashboard 和历史记录需要登录
            if ((page === 'dashboard' || page === 'history') && !AuthManager.isLoggedIn()) {
                AuthManager._openModal();
                return;
            }
            PageTransition.switchTo(page).then(() => {
                if (page === 'knowledge') { KnowledgeUI.loadStats(); KnowledgeUI.loadDocList(); }
                if (page === 'dashboard') DashboardUI.loadStats();
                if (page === 'history') HistoryUI.loadHistory();
                if (page === 'settings') SettingsManager.updateSystemInfo();
                if (page === 'mine') { try { AuthManager._updateMineCard(); MineUI.syncCounts(); } catch(e) {} }
                if (page === 'products') { setTimeout(function() { try { ProductGraph._renderGrid(); } catch(e) { console.warn('[PageSwitch] 产品图谱渲染失败:', e); } }, 100); }
            }).catch(err => console.warn('[PageSwitch] 页面切换失败:', err));
        });
    });

    // ===== "我的"聚合页交互 =====
    const MineUI = {
        init() {
            // 登录按钮
            document.getElementById('mine-login-btn')?.addEventListener('click', () => AuthManager._openModal());
            // 退出登录
            document.getElementById('mine-logout-btn')?.addEventListener('click', () => {
                if (typeof AuthManager.logout === 'function') AuthManager.logout();
                else if (typeof AuthManager._logout === 'function') AuthManager._logout();
            });
            // 功能入口跳转
            document.querySelectorAll('.mine-menu-item').forEach(btn => {
                btn.addEventListener('click', () => {
                    const target = btn.dataset.goto;
                    if ((target === 'dashboard' || target === 'history') && !AuthManager.isLoggedIn()) {
                        AuthManager._openModal();
                        return;
                    }
                    PageTransition.switchTo(target).then(() => {
                        if (target === 'dashboard') DashboardUI.loadStats();
                        if (target === 'history') HistoryUI.loadHistory();
                        if (target === 'settings') SettingsManager.updateSystemInfo();
                    }).catch(() => {});
                });
            });
            // 主题切换（移动端）
            document.getElementById('mine-theme-row')?.addEventListener('click', (e) => {
                const dot = e.target.closest('.mine-theme-dot');
                if (!dot) return;
                const skin = dot.dataset.skin;
                document.body.setAttribute('data-skin', skin);
                try { localStorage.setItem('skin', skin); } catch(_) {}
                document.querySelectorAll('.mine-theme-dot').forEach(d => d.classList.toggle('active', d.dataset.skin === skin));
                document.querySelectorAll('.theme-color').forEach(d => d.classList.toggle('active', d.dataset.skin === skin));
            });
        },
        syncCounts() {
            // 同步侧栏底部的文档/行业统计到"我的"页脚
            const doc = document.getElementById('nav-doc-count')?.textContent || '--';
            const ind = document.getElementById('nav-industry-count')?.textContent || '--';
            const md = document.getElementById('mine-doc-count');
            const mi = document.getElementById('mine-industry-count');
            if (md) md.textContent = doc;
            if (mi) mi.textContent = ind;
            // 同步主题选中态
            let skin = 'classic-blue';
            try { skin = localStorage.getItem('skin') || 'classic-blue'; } catch(_) {}
            if (!['classic-blue','teal','summer-yellow','peach-pink'].includes(skin)) skin = 'classic-blue';
            document.querySelectorAll('.mine-theme-dot').forEach(d => d.classList.toggle('active', d.dataset.skin === skin));
        }
    };
    MineUI.init();
    
    document.querySelectorAll('.sidebar-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            if ((page === 'dashboard' || page === 'history') && !AuthManager.isLoggedIn()) {
                AuthManager._openModal();
                return;
            }
            PageTransition.switchTo(page).then(() => {
                if (page === 'knowledge') { KnowledgeUI.loadStats(); KnowledgeUI.loadDocList(); }
                if (page === 'dashboard') DashboardUI.loadStats();
                if (page === 'history') HistoryUI.loadHistory();
                if (page === 'settings') SettingsManager.updateSystemInfo();
                if (page === 'products') { setTimeout(function() { try { ProductGraph._renderGrid(); } catch(e) { console.warn('[PageSwitch] 产品图谱渲染失败:', e); } }, 100); }
            }).catch(err => console.warn('[PageSwitch] 页面切换失败:', err));
        });
    });

    const navbarToggle = document.getElementById('navbar-toggle');
    const mobileLoginBtn = document.getElementById('mobile-login-btn');
    
    // 移动端登录按钮
    mobileLoginBtn?.addEventListener('click', () => {
        AuthManager._openModal();
    });
    
    // 汉堡菜单：已登录显示用户菜单，未登录弹出登录框
    navbarToggle?.addEventListener('click', (e) => {
        e.stopPropagation();
        if (AuthManager.isLoggedIn()) {
            const dropdown = document.getElementById('user-dropdown');
            if (dropdown) {
                const show = dropdown.style.display === 'none';
                dropdown.style.display = show ? '' : 'none';
                document.getElementById('nav-user-menu')?.classList.toggle('open', show);
            }
        } else {
            AuthManager._openModal();
        }
    });

    // 侧边栏收起 / 展开（默认展开，状态持久化）
    const sidebarToggle = document.getElementById('sidebar-toggle');
    function _updateSidebarToggleUI(isCollapsed) {
        if (!sidebarToggle) return;
        sidebarToggle.title = isCollapsed ? '展开侧边栏' : '收起侧边栏';
    }
    sidebarToggle?.addEventListener('click', () => {
        const shell = document.getElementById('app-shell');
        if (!shell) return;
        const isCollapsed = shell.classList.toggle('collapsed');
        try {
            localStorage.setItem('sidebar-collapsed', isCollapsed ? '1' : '0');
        } catch (_) {}
        _updateSidebarToggleUI(isCollapsed);
    });
    try {
        if (localStorage.getItem('sidebar-collapsed') === '1') {
            document.getElementById('app-shell')?.classList.add('collapsed');
            _updateSidebarToggleUI(true);
        }
    } catch (_) {}

    // ===== 主题切换器 =====
    (function initThemeSwitcher() {
        const body = document.body;
        const palette = document.getElementById('theme-palette');

        let currentSkin = 'classic-blue';
        try { currentSkin = localStorage.getItem('skin') || 'classic-blue'; } catch(_) {}
        if (!['classic-blue','teal','summer-yellow','peach-pink'].includes(currentSkin)) currentSkin = 'classic-blue';

        function applySkin(skin) {
            body.setAttribute('data-skin', skin);
            currentSkin = skin;
            if (palette) {
                palette.querySelectorAll('.theme-color').forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.skin === skin);
                });
            }
            try { localStorage.setItem('skin', skin); } catch(_) {}
        }

        applySkin(currentSkin);

        if (palette) {
            palette.addEventListener('click', (e) => {
                const btn = e.target.closest('.theme-color');
                if (!btn || btn.dataset.skin === currentSkin) return;
                applySkin(btn.dataset.skin);
            });
        }
    })();

    // 产品详情弹窗关闭
    document.getElementById('product-modal-close')?.addEventListener('click', () => {
        var overlay = document.getElementById('product-modal-overlay');
        if (overlay) {
            overlay.style.display = 'none';
            document.body.style.overflow = '';
        }
    });
    document.getElementById('product-modal-overlay')?.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) {
            e.target.style.display = 'none';
            document.body.style.overflow = '';
        }
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

    // ===== 忘记密码弹窗 =====
    document.getElementById('forgot-password-link')?.addEventListener('click', () => {
        document.getElementById('auth-modal-overlay').style.display = 'none';
        document.getElementById('forgot-password-modal-overlay').style.display = '';
        document.getElementById('forgot-password-email').value = '';
        document.getElementById('forgot-password-error').style.display = 'none';
        document.getElementById('forgot-password-success').style.display = 'none';
    });

    document.getElementById('forgot-password-modal-close')?.addEventListener('click', () => {
        document.getElementById('forgot-password-modal-overlay').style.display = 'none';
    });

    document.getElementById('back-to-login-btn')?.addEventListener('click', () => {
        document.getElementById('forgot-password-modal-overlay').style.display = 'none';
        document.getElementById('auth-modal-overlay').style.display = '';
        AuthManager._switchTab('login');
    });

    document.getElementById('forgot-password-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('forgot-password-email').value.trim();
        if (!email) {
            document.getElementById('forgot-password-error').textContent = '请输入邮箱';
            document.getElementById('forgot-password-error').style.display = '';
            return;
        }
        const btn = document.getElementById('forgot-password-submit-btn');
        btn.querySelector('.btn-text').style.display = 'none';
        btn.querySelector('.btn-spinner').style.display = '';
        try {
            const resp = await fetch(`${Config.API_BASE_URL}/auth/forgot-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });
            const data = await resp.json();
            btn.querySelector('.btn-text').style.display = '';
            btn.querySelector('.btn-spinner').style.display = 'none';
            document.getElementById('forgot-password-error').style.display = 'none';
            document.getElementById('forgot-password-success').textContent = '重置链接已发送到邮箱，请查收（有效期30分钟）';
            document.getElementById('forgot-password-success').style.display = '';
        } catch (err) {
            btn.querySelector('.btn-text').style.display = '';
            btn.querySelector('.btn-spinner').style.display = 'none';
            document.getElementById('forgot-password-error').textContent = '发送失败，请稍后重试';
            document.getElementById('forgot-password-error').style.display = '';
        }
    });

    // ===== 重置密码弹窗 =====
    document.getElementById('reset-password-modal-close')?.addEventListener('click', () => {
        document.getElementById('reset-password-modal-overlay').style.display = 'none';
    });

    document.getElementById('reset-password-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        // 优先从全局变量读取 token（URL 中的 token 会被清理）
        const token = window._resetToken || new URLSearchParams(window.location.search).get('token');
        const newPwd = document.getElementById('reset-password-new').value;
        const confirmPwd = document.getElementById('reset-password-confirm').value;
        if (newPwd.length < 6) {
            document.getElementById('reset-password-error').textContent = '密码至少6位';
            document.getElementById('reset-password-error').style.display = '';
            return;
        }
        if (newPwd !== confirmPwd) {
            document.getElementById('reset-password-error').textContent = '两次密码不一致';
            document.getElementById('reset-password-error').style.display = '';
            return;
        }
        const btn = document.getElementById('reset-password-submit-btn');
        btn.querySelector('.btn-text').style.display = 'none';
        btn.querySelector('.btn-spinner').style.display = '';
        try {
            const resp = await fetch(`${Config.API_BASE_URL}/auth/reset-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token, new_password: newPwd })
            });
            const data = await resp.json();
            btn.querySelector('.btn-text').style.display = '';
            btn.querySelector('.btn-spinner').style.display = 'none';
            if (!resp.ok) {
                document.getElementById('reset-password-error').textContent = data.detail || '重置失败';
                document.getElementById('reset-password-error').style.display = '';
                return;
            }
            document.getElementById('reset-password-error').style.display = 'none';
            document.getElementById('reset-password-success').textContent = '密码已重置！正在跳转到登录...';
            document.getElementById('reset-password-success').style.display = '';
            setTimeout(() => { window.location.href = '/'; }, 2000);
        } catch (err) {
            btn.querySelector('.btn-text').style.display = '';
            btn.querySelector('.btn-spinner').style.display = 'none';
            document.getElementById('reset-password-error').textContent = '重置失败，请稍后重试';
            document.getElementById('reset-password-error').style.display = '';
        }
    });

    // 页面加载时检查 URL 是否有重置 token
    (() => {
        const urlParams = new URLSearchParams(window.location.search);
        const resetToken = urlParams.get('token');
        if (resetToken) {
            document.getElementById('reset-password-modal-overlay').style.display = '';
        }
    })();

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

    // 数字从 0 滚动到目标值（带 easeOut 缓动），用于个人档案统计卡 count-up 动画
    // 支持重入：再次触发时取消上一次未完成的动画，避免关闭后重开时数字错乱
    function animateStatCountUp(el, end, duration, delay) {
        if (!el) return;
        const endVal = Math.max(0, parseInt(end, 10) || 0);
        el.textContent = 0;
        if (el._countUpRAF) cancelAnimationFrame(el._countUpRAF);
        setTimeout(function () {
            const startTime = performance.now();
            function tick(now) {
                const elapsed = now - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const easeOut = 1 - Math.pow(1 - progress, 3);
                el.textContent = Math.floor(endVal * easeOut);
                if (progress < 1) {
                    el._countUpRAF = requestAnimationFrame(tick);
                } else {
                    el.textContent = endVal;
                    el._countUpRAF = null;
                }
            }
            el._countUpRAF = requestAnimationFrame(tick);
        }, delay || 0);
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
                    // 统计数字 count-up 动画（从 0 滚动到真实值，依次错开更有节奏感）
                    animateStatCountUp(document.getElementById('stat-match'), stats.match_count || 0, 1200, 0);
                    animateStatCountUp(document.getElementById('stat-analyze'), stats.analyze_count || 0, 1200, 100);
                    animateStatCountUp(document.getElementById('stat-favorites'), stats.favorites_count || 0, 1200, 200);
                    animateStatCountUp(document.getElementById('stat-history'), stats.history_count || 0, 1200, 300);
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
    
    // ========== 客户资料上传（阶段1：标准/智能/向导三模式通用） ==========
    const CustomerFileUploader = {
        MAX_FILES: 10,
        MAX_FILE_MB: 100,
        ALLOWED_EXTS: ['.docx', '.xlsx', '.pdf', '.pptx', '.txt', '.csv', '.md', '.png', '.jpg', '.jpeg'],
        files: [],   // {id, file, path, status: 'uploading'|'done'|'error', error}
        seq: 0,
        _lockedTimer: null,
        dropzoneEl: null,
        inputEl: null,
        listEl: null,
        lockedHintEl: null,

        init() {
            this.dropzoneEl = document.getElementById('cf-dropzone');
            this.inputEl = document.getElementById('cf-file-input');
            this.listEl = document.getElementById('cf-file-list');
            this.lockedHintEl = document.getElementById('cf-locked-hint');
            if (!this.dropzoneEl || !this.inputEl) return;

            // 默认隐藏锁定提示（登录态可能还没初始化，延迟刷新）
            if (this.lockedHintEl) this.lockedHintEl.style.display = 'none';

            this.dropzoneEl.addEventListener('click', () => this._onActivate());
            this.dropzoneEl.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this._onActivate(); }
            });

            this.inputEl.addEventListener('change', (e) => {
                this._handleFiles(e.target.files);
                e.target.value = '';  // 允许重复选择同一文件
            });

            ['dragenter', 'dragover'].forEach(ev =>
                this.dropzoneEl.addEventListener(ev, (e) => {
                    e.preventDefault(); e.stopPropagation();
                    this.dropzoneEl.classList.add('dragover');
                }));
            ['dragleave', 'drop'].forEach(ev =>
                this.dropzoneEl.addEventListener(ev, (e) => {
                    e.preventDefault(); e.stopPropagation();
                    if (ev === 'dragleave' && this.dropzoneEl.contains(e.relatedTarget)) return;
                    this.dropzoneEl.classList.remove('dragover');
                }));
            this.dropzoneEl.addEventListener('drop', (e) => {
                if (e.dataTransfer && e.dataTransfer.files) this._handleFiles(e.dataTransfer.files);
            });

            // 延迟刷新：等 AuthManager.init() 完成后再判一次登录态
            setTimeout(() => this._refreshLockState(), 500);
        },

        _refreshLockState() {
            const loggedIn = typeof AuthManager !== 'undefined' && AuthManager.isLoggedIn && AuthManager.isLoggedIn();
            if (!loggedIn) {
                this.dropzoneEl.classList.add('is-locked');
            } else {
                this.dropzoneEl.classList.remove('is-locked');
                // 登录后始终隐藏锁定提示
                if (this.lockedHintEl) this.lockedHintEl.style.display = 'none';
            }
        },

        _onActivate() {
            // 动态重判登录态（登录后不需刷新页面）
            if (typeof AuthManager !== 'undefined' && AuthManager.isLoggedIn && !AuthManager.isLoggedIn()) {
                UI.showToast('请先登录后再上传客户资料', 'info');
                // 闪现锁定提示条，3 秒后自动消失
                if (this.lockedHintEl) {
                    this.lockedHintEl.style.display = 'flex';
                    clearTimeout(this._lockedTimer);
                    this._lockedTimer = setTimeout(() => {
                        if (this.lockedHintEl) this.lockedHintEl.style.display = 'none';
                    }, 3000);
                }
                return;
            }
            this.inputEl.click();
        },

        _handleFiles(fileList) {
            if (typeof AuthManager !== 'undefined' && AuthManager.isLoggedIn && !AuthManager.isLoggedIn()) {
                UI.showToast('请先登录后再上传客户资料', 'info');
                return;
            }
            const incoming = Array.from(fileList || []);
            if (!incoming.length) return;

            let remaining = this.MAX_FILES - this.files.length;
            if (remaining <= 0) {
                UI.showToast(`最多同时上传 ${this.MAX_FILES} 个文件，请先移除部分`, 'warning');
                return;
            }

            const accepted = [];
            for (const f of incoming) {
                if (remaining <= 0) {
                    UI.showToast(`最多同时上传 ${this.MAX_FILES} 个文件，多余的已忽略`, 'warning');
                    break;
                }
                const ext = (f.name.indexOf('.') >= 0 ? f.name.slice(f.name.lastIndexOf('.')).toLowerCase() : '');
                if (!this.ALLOWED_EXTS.includes(ext)) {
                    UI.showToast(`不支持的格式：${f.name}`, 'warning');
                    continue;
                }
                if (f.size > this.MAX_FILE_MB * 1024 * 1024) {
                    UI.showToast(`超过 ${this.MAX_FILE_MB}MB 上限：${f.name}`, 'warning');
                    continue;
                }
                if (this.files.some(x => x.file.name === f.name && x.file.size === f.size)) {
                    continue;  // 去重（同名同大小）
                }
                accepted.push(f);
                remaining--;
            }

            for (const f of accepted) {
                const id = ++this.seq;
                const item = { id, file: f, path: null, status: 'uploading', error: null };
                this.files.push(item);
                this._renderItem(item);
                this._uploadOne(item);
            }
        },

        async _uploadOne(item) {
            try {
                const form = new FormData();
                form.append('file', item.file);
                const headers = {};
                if (AuthManager.isLoggedIn() && !State.isQuickDemo) {
                    headers['Authorization'] = `Bearer ${AuthManager.getToken()}`;
                }
                const resp = await fetch(`${Config.API_BASE_URL}/upload/customer-file`, {
                    method: 'POST',
                    headers,
                    body: form
                });
                if (!resp.ok) {
                    let msg = `上传失败 (${resp.status})`;
                    try { const j = await resp.json(); if (j.detail) msg = j.detail; } catch (e) {}
                    throw new Error(msg);
                }
                const data = await resp.json();
                item.path = data.path;
                item.status = 'done';
            } catch (err) {
                item.status = 'error';
                item.error = (err && err.message) || '上传失败';
            }
            this._renderItem(item);
        },

        _renderItem(item) {
            if (!this.listEl) return;
            let li = this.listEl.querySelector(`[data-id="${item.id}"]`);
            if (!li) {
                li = document.createElement('li');
                li.className = 'upload-file-item';
                li.dataset.id = item.id;
                this.listEl.appendChild(li);
            }
            const sizeKB = item.file.size / 1024;
            const sizeStr = sizeKB >= 1024 ? `${(sizeKB / 1024).toFixed(1)} MB` : `${Math.round(sizeKB)} KB`;
            let statusHtml = '';
            if (item.status === 'uploading') {
                statusHtml = `<span class="upload-file-status uploading">上传中…</span>`;
            } else if (item.status === 'done') {
                statusHtml = `<span class="upload-file-status done"><svg class="icon" aria-hidden="true"><use href="#i-circle-check"></use></svg> 已就绪</span>`;
            } else {
                statusHtml = `<span class="upload-file-status error" title="${(item.error || '').replace(/"/g, '&quot;')}"><svg class="icon" aria-hidden="true"><use href="#i-triangle-alert"></use></svg> ${(item.error || '失败').replace(/</g, '&lt;')}</span>`;
            }
            li.innerHTML = `
                <svg class="icon upload-file-icon" aria-hidden="true"><use href="#i-file"></use></svg>
                <div class="upload-file-meta">
                    <div class="upload-file-name" title="${item.file.name.replace(/"/g, '&quot;')}">${item.file.name.replace(/</g, '&lt;')}</div>
                    <div class="upload-file-sub"><span>${sizeStr}</span> · ${statusHtml}</div>
                </div>
                <button class="upload-file-remove" type="button" title="移除" aria-label="移除文件">
                    <svg class="icon" aria-hidden="true"><use href="#i-trash-2"></use></svg>
                </button>`;
            li.querySelector('.upload-file-remove').addEventListener('click', (e) => {
                e.stopPropagation();
                this._remove(item.id);
            });
        },

        _remove(id) {
            this.files = this.files.filter(x => x.id !== id);
            const li = this.listEl ? this.listEl.querySelector(`[data-id="${id}"]`) : null;
            if (li) li.remove();
        },

        getServerPaths() {
            return this.files.filter(x => x.status === 'done').map(x => x.path);
        },

        hasPending() {
            return this.files.some(x => x.status === 'uploading');
        },

        clear() {
            this.files = [];
            this.seq = 0;
            if (this.listEl) this.listEl.innerHTML = '';
            if (this.inputEl) this.inputEl.value = '';
        }
    };
    CustomerFileUploader.init();
    
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

    // ===== 客户档案（方案B：Agent 记忆按客户隔离） =====
    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
    }
    function loadClients() {
        const sel = document.getElementById('client-select');
        if (!sel || !AuthManager.isLoggedIn()) return;  // 未登录不加载
        const prev = State.currentClientId;
        fetch(`${Config.API_BASE_URL}/clients`, {
            headers: { 'Authorization': `Bearer ${AuthManager.getToken()}` }
        })
            .then(r => r.ok ? r.json() : { clients: [] })
            .then(data => {
                const clients = (data.clients || []);
                sel.innerHTML = '<option value="">（全局记忆 · 不限定客户）</option>' +
                    clients.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
                if (prev) sel.value = String(prev);
                State.currentClientId = sel.value ? Number(sel.value) : null;
            })
            .catch(() => {});
    }
    document.getElementById('client-new-btn')?.addEventListener('click', () => {
        const name = prompt('请输入客户名称（如：某某制造企业）：');
        if (!name || !name.trim()) return;
        const note = prompt('客户备注（可选，可留空）：') || '';
        fetch(`${Config.API_BASE_URL}/clients`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${AuthManager.getToken()}` },
            body: JSON.stringify({ name: name.trim(), note })
        }).then(r => r.ok ? r.json() : Promise.reject(r))
          .then(c => { UI.showToast(`已新建客户「${c.name}」`, 'success'); State.currentClientId = c.id; loadClients(); })
          .catch(err => { err.json?.().then?.(e => UI.showToast(e.detail || '新建客户失败', 'error')); });
    });
    document.getElementById('client-del-btn')?.addEventListener('click', () => {
        if (!State.currentClientId) { UI.showToast('当前为全局记忆，无需删除', 'info'); return; }
        const sel = document.getElementById('client-select');
        const name = sel?.selectedOptions?.[0]?.textContent || '该客户';
        if (!confirm(`确定删除客户「${name}」？其 Agent 记忆将一并清除。`)) return;
        fetch(`${Config.API_BASE_URL}/clients/${State.currentClientId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${AuthManager.getToken()}` }
        }).then(r => {
            if (r.ok) { UI.showToast(`已删除客户「${name}」`, 'success'); State.currentClientId = null; loadClients(); }
            else UI.showToast('删除失败', 'error');
        }).catch(() => UI.showToast('删除失败', 'error'));
    });
    document.getElementById('client-select')?.addEventListener('change', (e) => {
        State.currentClientId = e.target.value ? Number(e.target.value) : null;
    });
    // 初始化：默认 Agent 模式 → 显示客户栏
    if (State.matchMode === 'agent') {
        const cb = document.getElementById('client-bar');
        if (cb) cb.style.display = '';
        // 登录态可能尚未就绪：本块在脚本顶层执行，早于 init() 中的 AuthManager.init()，
        // 此时 isLoggedIn() 仍为 false，直接 loadClients() 会被跳过导致下拉永远为空。
        // 延迟到登录态（含服务端校验）确认后再加载，参考 CustomerFileUploader 模式（行4449）。
        setTimeout(() => { if (AuthManager.isLoggedIn()) loadClients(); }, 300);
    }

    // ===== 匹配模式切换 =====
    const modeToggle = document.getElementById('mode-toggle');
    const modeHint = document.getElementById('mode-hint');
    modeToggle?.addEventListener('click', (e) => {
        const option = e.target.closest('.mode-option');
        if (!option) return;
        const newMode = option.dataset.mode;
        if (State.matchMode === newMode) return;
        const prevMode = State.matchMode;   // 记录切换前的模式，用于判断布局是否变化
        State.matchMode = newMode;
        // 更新 UI
        modeToggle.querySelectorAll('.mode-option').forEach(el => el.classList.remove('active'));
        option.classList.add('active');
        // 更新提示文字
        if (modeHint) {
            const hints = {
                normal: '精准搜索 + LLM 生成',
                agent: 'AI 记忆上下文 → 精准检索 → 为你定制方案',
                wizard: '像 BD 顾问一样，一步步挖掘客户需求'
            };
            modeHint.textContent = hints[newMode] || '';
        }

        // 客户档案栏：仅 Agent 模式显示并加载
        const clientBar = document.getElementById('client-bar');
        if (clientBar) {
            if (newMode === 'agent') {
                clientBar.style.display = '';
                loadClients();
            } else {
                clientBar.style.display = 'none';
            }
        }

        // 向导模式的显示/隐藏
        const demandInput = document.getElementById('demand-input');
        if (newMode === 'wizard') {
            DemandWizard.show();
        } else {
            DemandWizard.hide();
            if (demandInput) demandInput.parentElement.style.display = '';
        }

        // 只有涉及向导模式的切换才会改变输入区高度（向导模式隐藏 textarea 并显示向导面板）。
        // 文档高度骤变时浏览器会把 scrollY clamp 到新的最大值——在高视口下会被归 0，
        // 表现为“切到 Agent 时页面弹到最顶端”。锚点补偿无法解决（目标滚动位置常超出可滚动范围），
        // 故改为：切换后平滑滚动到新模式的主输入元素，给用户一个确定、自然的落点。
        // Agent ↔ 标准 之间切换布局完全相同，无需滚动，保持当前视口。
        const layoutChanged = newMode === 'wizard' || prevMode === 'wizard';
        if (layoutChanged) {
            requestAnimationFrame(() => {
                const target = newMode === 'wizard'
                    ? document.getElementById('demand-wizard')
                    : document.getElementById('demand-input');
                if (!target) return;
                const headerOffset = 72;  // 顶部固定栏(56px) + 呼吸留白
                const top = target.getBoundingClientRect().top + window.scrollY - headerOffset;
                window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
            });
        }
    });

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

        // 向导模式：用收集的数据合成需求
        const isWizardMode = State.matchMode === 'wizard';
        const demand = isWizardMode 
            ? DemandWizard.synthesizeDemand()
            : demandInput.value.trim();
        
        // 阶段1：收集已上传就绪的客户资料文件路径
        const customerFiles = CustomerFileUploader.getServerPaths();
        if (CustomerFileUploader.hasPending()) {
            UI.showToast('部分客户资料仍在上传中，将仅使用已就绪的文件', 'info');
        } else if (CustomerFileUploader.files.some(f => f.status === 'error')) {
            UI.showToast('有客户资料上传失败，已忽略失败文件', 'warning');
        }
        
        // 空输入：允许提交，后端会检测 easter_empty_search 成就
        if (!demand && !isWizardMode) {
            // 非向导模式且输入为空，提示用户确认（对应"无声胜有声"隐藏成就）
            if (!confirm('输入为空，确定要直接匹配吗？')) return;
        }
        
        // 向导模式：至少需要选择行业
        if (isWizardMode && !State.wizardData.industry) {
            UI.showToast('请至少选择客户所在的行业', 'warning');
            DemandWizard.goToStep(0);
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
        const isAgentMode = State.matchMode === 'agent';
        MatchProgress.start();
        if (!isAgentMode) {
            MatchProgress.simulateProgress(3, 6000);
        }
        
        try {
            // 智能匹配要求登录：匿名用户直接拦截并弹登录框，
            // 既避免 401 报错，也彻底杜绝写入 user_id=0 的共享记忆池
            if (isAgentMode && !AuthManager.isLoggedIn()) {
                UI.showToast('请先登录后再使用智能匹配', 'warning');
                AuthManager._openModal();
                MatchProgress.hide();
                return;
            }
            SkeletonUI.showMatchFormSkeleton();
            // 新匹配开始：隐藏上一轮成本参考卡片
            const _cr = document.getElementById('cost-reference-card');
            if (_cr) _cr.style.display = 'none';
            if (isAgentMode) MatchProgress.setSteps([
                { icon: '<svg class="icon" aria-hidden="true"><use href="#i-brain"></use></svg>', label: '分析需求意图', desc: 'AI 理解模糊需求，提取关键信息' },
                { icon: '<svg class="icon" aria-hidden="true"><use href="#i-search"></use></svg>', label: '智能搜索知识库', desc: '用结构化关键词精准检索' },
                { icon: '<svg class="icon" aria-hidden="true"><use href="#i-sparkles"></use></svg>', label: '综合生成方案', desc: '基于知识库 + AI 生成完整方案' }
            ]);

            // ★ 轻量预验证（不阻断，仅日志）
            //   之前版本预验证失败会 _clearAuth()+弹登录框，可能误杀有效token。
            //   改为 fire-and-forget 日志记录，让实际请求结果决定后续行为。
            try {
                const _raw = localStorage.getItem('hwcloud_auth');
                const _t = _raw ? JSON.parse(_raw).token : null;
                if (_t) {
                    fetch(`${Config.API_BASE_URL}/auth/me`, { headers: { 'Authorization': 'Bearer ' + _t } })
                        .then(r => console.log('[MatchPreAuth] /auth/me →', r.status))
                        .catch(e => console.warn('[MatchPreAuth] 网络异常(非致命):', e));
                }
            } catch(_) {}

            let result;
            if (isAgentMode) {
                // SSE 流式模式：监听事件更新进度面板 + 实时思考流
                const toolStepMap = { analyze_demand: 0, search_kb: 1, search_competitor: 1, generate_report: 2 };
                const tsContainer = document.getElementById('thinking-stream');
                const tsEntries = document.getElementById('thinking-entries');
                const tsBadge = document.getElementById('thinking-step-badge');

                // 显示思考流面板
                if (tsContainer) {
                    tsEntries.innerHTML = '';
                    tsContainer.style.display = 'block';
                    tsContainer.classList.remove('done');
                }

                // 思考流渲染辅助函数
                const addThinkEntry = (type, labelClass, icon, labelText, text) => {
                    if (!tsEntries) return;
                    const div = document.createElement('div');
                    div.className = 'think-entry';
                    div.innerHTML = `<div class="think-icon ${type}">${icon}</div><div class="think-body"><div class="think-label ${labelClass}-label">${labelText}</div><div class="think-text">${text}</div></div>`;
                    tsEntries.appendChild(div);
                    tsEntries.scrollTop = tsEntries.scrollHeight;
                };

                const resultContainer = document.getElementById('solution-result');
                const resultContent = document.getElementById('solution-content');

                State.lastAgentDemand = demand;
                await API.agentMatchStream(demand, controller.signal, (event) => {
                    applyAgentProgressEvents(event);
                    if (event.type === 'result') {
                        result = event.data;
                    } else if (event.type === 'error') {
                        throw new Error(event.message);
                    }
                }, customerFiles, State.currentClientId);
            } else {
                // 标准/向导模式：SSE 流式消费（P0-2）—— 逐字渲染答案，终态调 renderAgentResult 做完整渲染
                const streamContent = document.getElementById('solution-content');
                const streamContainer = document.getElementById('solution-result');
                let streamedAnswer = '';
                let _lastRender = 0;
                await API.matchStream(demand, controller.signal, State.matchMode, customerFiles, (event) => {
                    if (event.type === 'token') {
                        streamedAnswer += (event.text || '');
                        const now = Date.now();
                        // 轻量节流：约每 180ms 或遇换行时重渲染，避免长文逐 token 重排卡顿
                        if (streamContent && (now - _lastRender > 180 || (event.text || '').indexOf('\n') >= 0)) {
                            _lastRender = now;
                            streamContent.innerHTML = UI.renderMarkdown(streamedAnswer);
                            if (streamContainer) streamContainer.style.display = 'block';
                        }
                    } else if (event.type === 'result') {
                        result = event.data;
                    } else if (event.type === 'error') {
                        throw new Error(event.message);
                    }
                });
            }
            
            // 统一渲染结果（首轮与澄清续跑共用；含暂停/过期守卫）
            renderAgentResult(result, demand);
        } catch (error) {
            if (error.name === 'AbortError') {
                // 用户主动取消，不报错
                console.log('匹配已取消');
                const ts = document.getElementById('thinking-stream');
                if (ts) ts.style.display = 'none';
                return;
            }
            // 匹配失败 — 直接显示服务端错误，不再做任何鉴权判断/清登录态/弹框
            // （2026-07-19 根治版：之前所有"清登录态+弹登录框"的逻辑都会误杀有效token）
            const msg = error.message || '';
            console.error('[Match] 失败:', msg, '| localStorage有token:', !!localStorage.getItem('hwcloud_auth'));
            MatchProgress.hide();
            UI.showToast(msg || '匹配失败，请重试', 'error');
        } finally {
            State.loadingStates.match = false;
            State.isQuickDemo = false;
            if (matchBtnText) matchBtnText.textContent = '开始匹配';
            matchBtn.classList.remove('btn-cancel');
            State.abortControllers.match = null;
        }
    });

    // ==================== Agent 流式事件处理 + 结果渲染（首轮与澄清续跑共用） ====================

    // 将工具名映射到进度面板语义步骤（analyze=0, search=1, generate=2）
    function _toolStepIndex(tool) {
        if (tool === 'analyze_demand') return 0;
        if (tool === 'search_kb' || tool === 'search_competitor') return 1;
        return 2;
    }

    // 处理 SSE 进度事件：更新思考流面板 + 进度条（首轮与澄清续跑共用）
    function applyAgentProgressEvents(event) {
        if (!event || !event.type) return;
        const tsEntries = document.getElementById('thinking-entries');
        const tsBadge = document.getElementById('thinking-step-badge');

        const addThinkEntry = (type, labelClass, icon, labelText, text) => {
            if (!tsEntries) return;
            const div = document.createElement('div');
            div.className = 'think-entry';
            div.innerHTML = `<div class="think-icon ${type}">${icon}</div><div class="think-body"><div class="think-label ${labelClass}-label">${labelText}</div><div class="think-text">${text}</div></div>`;
            tsEntries.appendChild(div);
            tsEntries.scrollTop = tsEntries.scrollHeight;
        };

        switch (event.type) {
            case 'step':
                if (tsBadge) tsBadge.textContent = `Step ${event.step}`;
                break;
            case 'thought':
                addThinkEntry('thought', 'think', '<svg class="icon" aria-hidden="true"><use href="#i-lightbulb"></use></svg>', '思考', event.text || '');
                break;
            case 'tool_start':
                MatchProgress.setStep(_toolStepIndex(event.tool));
                addThinkEntry('tool', 'tool', '<svg class="icon" aria-hidden="true"><use href="#i-search"></use></svg>', '调用工具', `正在执行：${event.tool}`);
                break;
            case 'tool_end':
                addThinkEntry('tool', 'tool', '<svg class="icon" aria-hidden="true"><use href="#i-circle-check"></use></svg>', '工具完成', `${event.tool} 执行完成`);
                break;
            case 'final':
                MatchProgress.setStep(2);
                addThinkEntry('final', 'final', '<svg class="icon" aria-hidden="true"><use href="#i-sparkles"></use></svg>', '完成', '方案生成完成');
                break;
            default:
                break;
        }
    }

    // 统一渲染匹配结果（标准模式 / Agent 首轮 / 澄清续跑共用）；含 paused/expired/空答案守卫
    function renderAgentResult(result, demand) {
        if (!result) {
            UI.showToast('匹配未返回结果', 'error');
            return;
        }
        // 阶段 2.5：澄清暂停 —— 展示提问卡，等待用户作答后续跑
        if (result.paused) {
            MatchProgress.hide();
            showClarifyCard({ clarify_id: result.clarify_id, questions: result.questions || [] });
            return;
        }
        // 澄清会话过期
        if (result.expired) {
            clearClarifyCard();
            MatchProgress.hide();
            UI.showToast('澄清会话已过期，请重新发起匹配', 'warning');
            return;
        }
        // 空答案守卫
        if (!result.answer || (typeof result.answer === 'string' && result.answer.trim() === '')) {
            MatchProgress.error('未生成方案内容');
            UI.showToast('未生成方案内容，请重试', 'warning');
            return;
        }

        const resultContainer = document.getElementById('solution-result');
        const resultContent = document.getElementById('solution-content');
        if (!resultContainer || !resultContent) return;

        try {
            resultContent.innerHTML = UI.renderMarkdown(result.answer);
        } catch (e) {
            resultContent.innerHTML = '<div class="result-content"><p>方案已生成，但渲染失败，请尝试下载方案文档查看。</p></div>';
        }
        UI.renderSources(document.getElementById('solution-sources'), result.source_documents);
        resultContainer.style.display = 'block';
        resultContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });

        // 快速体验引导条：仅「匿名 + 体验」时展示（把游客转化为注册用户）
        // 已登录用户用体验时不显示——他们本就拥有保存/历史/向导/Agent 全部能力，无需再推荐登录
        const qdBanner = document.getElementById('quick-demo-banner');
        if (qdBanner) {
            if (State.isQuickDemo && !AuthManager.isLoggedIn()) {
                qdBanner.style.display = 'flex';
                const qdLoginBtn = document.getElementById('qd-login-btn');
                if (qdLoginBtn) qdLoginBtn.onclick = () => {
                    AuthManager._openModal();
                };
            } else {
                qdBanner.style.display = 'none';
            }
        }

        // 隐藏思考流面板
        const ts = document.getElementById('thinking-stream');
        if (ts) ts.style.display = 'none';

        // 缓存 + 收藏按钮 + FollowUp + 成就（含版本元信息回填）
        State.resultCache.solution = {
            answer: result.answer,
            solution_json: result.solution_json || null,
            source_documents: result.source_documents || [],
            demand: demand,
            history_id: result.history_id,
            group_id: result.group_id,
            version: result.version,
            is_final: result.is_final,
            title: result.title,
        };
        const favName = (demand || '方案匹配结果').substring(0, 50);
        FavoriteManager._updateResultBtn('fav-solution-btn', favName);

        // 成本参考卡片：按行业拉公开价目骨架，渲染可编辑 BOM
        renderCostReference(result);

        MatchProgress.success('匹配完成！');
        UI.showToast('匹配完成！', 'success');

        if (result.history_id) {
            FollowUpUI.show(demand, result.answer, result.history_id);
        }

        if (result.newly_unlocked && result.newly_unlocked.length > 0 && window.AchievementUI && AchievementUI.showUnlockToast) {
            setTimeout(() => AchievementUI.showUnlockToast(result.newly_unlocked), 500);
        }
    }

    // ==================== 成本参考卡片（方案成本估算器） ====================
    // 状态挂在 window.__crState，避免与文件其它作用域的 const 冲突
    if (!window.__crState) window.__crState = { rows: [], tier: 'mid', view: 'month', annual_discount: 0.85, bound: false, viewBound: false, addBound: false };

    // 工具函数挂到 window，确保所有作用域（含 ProductGraph 对象方法）都能访问
    window._crEsc = function _crEsc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    };
    window._crMoney = function _crMoney(n) {
        const v = Math.round((Number(n) || 0) * 100) / 100;
        return v.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    };
    function _crUpdateTierButtons() {
        document.querySelectorAll('#cr-tier-tabs .cr-tier-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.tier === window.__crState.tier);
        });
    }
    function _crUpdateViewButtons() {
        document.querySelectorAll('#cr-view-tabs .cr-view-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.view === (window.__crState.view || 'month'));
        });
    }
    // 周期换算系数：按年 = 月 × 12 × 折扣系数（默认 0.85）
    function _crFactor() {
        if (window.__crState.view === 'year') {
            const d = Number(window.__crState.annual_discount) || 0.85;
            return 12 * d;
        }
        return 1;
    }
    function _crRound(n) { return Math.round((Number(n) || 0) * 100) / 100; }
    function _crRenderTable() {
        const table = document.getElementById('cr-table');
        if (!table) return;
        const factor = _crFactor();
        const isYear = window.__crState.view === 'year';
        const priceLabel = isYear ? '单价(年)' : '单价(月)';
        let html = '<div class="cr-row cr-row-head">'
            + '<span class="cr-c-product">产品 / 规格</span>'
            + '<span class="cr-c-qty">数量</span>'
            + '<span class="cr-c-price">' + priceLabel + '</span>'
            + '<span class="cr-c-sub">小计</span></div>';
        window.__crState.rows.forEach((row, idx) => {
            if (row.business_only || row.no_price) {
                const label = row.business_only ? '商务定价' : '参考价待补充';
                const cls = row.business_only ? 'cr-row-biz' : 'cr-row-noprice';
                html += `<div class="cr-row ${cls}">`
                    + `<span class="cr-c-product"><b>${_crEsc(row.product)}</b><br><small>${_crEsc(row.spec || '')}</small></span>`
                    + `<span class="cr-c-biz-note">${_crEsc(label)}：${_crEsc(row.note || '')}</span></div>`;
                return;
            }
            const dispUnit = _crRound(row.unit_price * factor);
            const dispSub = _crRound(row.qty * row.unit_price * factor);
            const customTag = row.custom ? '<span class="cr-tag-custom">自定义</span>' : '';
            const billInner = _crEsc(row.billing || '') + (row.unit_label ? ((row.billing ? ' · ' : '') + _crEsc(row.unit_label)) : '');
            const billText = (row.billing || row.unit_label) ? `<span class="cr-bill">${billInner}</span>` : '';
            const warn = (!row.custom && row.verified === false) ? ' <span class="cr-warn" title="待官网复核">⚠</span>' : '';
            const delBtn = row.custom ? `<button class="cr-del" data-del="${idx}" title="删除该行" type="button">×</button>` : '';
            html += `<div class="cr-row" data-idx="${idx}">`
                + `<span class="cr-c-product"><b>${_crEsc(row.product)}</b>${customTag}<br><small>${_crEsc(row.spec || '')}</small>`
                + `${billText}${warn}</span>`
                + `<span class="cr-c-qty"><input type="number" min="0" class="cr-input cr-qty" data-idx="${idx}" value="${row.qty}"></span>`
                + `<span class="cr-c-price"><input type="number" min="0" step="0.01" class="cr-input cr-price" data-idx="${idx}" value="${dispUnit}"><span class="cr-unit">元</span></span>`
                + `<span class="cr-c-sub"><span class="cr-sub-amt" id="cr-sub-${idx}">¥${_crMoney(dispSub)}</span>${delBtn}</span></div>`;
        });
        table.innerHTML = html;
        table.querySelectorAll('.cr-qty, .cr-price').forEach(inp => {
            inp.addEventListener('input', (e) => {
                const i = parseInt(e.target.dataset.idx, 10);
                const val = parseFloat(e.target.value) || 0;
                const f = _crFactor();
                if (e.target.classList.contains('cr-qty')) window.__crState.rows[i].qty = val;
                else window.__crState.rows[i].unit_price = f ? (val / f) : val; // 单价按当前周期口径输入，存回月度基准
                const r = window.__crState.rows[i];
                const subEl = document.getElementById('cr-sub-' + i);
                if (subEl) subEl.textContent = '¥' + _crMoney(_crRound(r.qty * r.unit_price * f));
                window.__crState.tier = null;
                _crUpdateTierButtons();
                _crComputeTotal();
            });
        });
        table.querySelectorAll('.cr-del').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const i = parseInt(e.currentTarget.dataset.del, 10);
                if (!isNaN(i)) {
                    window.__crState.rows.splice(i, 1);
                    _crRenderTable();
                    _crComputeTotal();
                }
            });
        });
    }
    function _crComputeTotal() {
        const factor = _crFactor();
        let total = 0;
        window.__crState.rows.forEach(r => {
            if (!r.business_only && !r.no_price) total += (Number(r.qty) || 0) * (Number(r.unit_price) || 0);
        });
        total = _crRound(total * factor);
        const el = document.getElementById('cr-total');
        if (el) el.textContent = '¥' + _crMoney(total);
        const lbl = document.getElementById('cr-total-label');
        if (lbl) lbl.textContent = window.__crState.view === 'year' ? '预估年费合计（参考）' : '预估月费合计（参考）';
        const hint = document.getElementById('cr-view-hint');
        if (hint) hint.textContent = window.__crState.view === 'year'
            ? `年费 = 月 × 12 × ${(Number(window.__crState.annual_discount) || 0.85)}` : '';
    }
    function _crBindViewTabs() {
        if (window.__crState.viewBound) return;
        const tabs = document.getElementById('cr-view-tabs');
        if (!tabs) return;
        tabs.querySelectorAll('.cr-view-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                window.__crState.view = btn.dataset.view || 'month';
                _crUpdateViewButtons();
                _crRenderTable();
                _crComputeTotal();
            });
        });
        window.__crState.viewBound = true;
    }
    function _crBindCustomAdd() {
        if (window.__crState.addBound) return;
        const addBtn = document.getElementById('cr-add-btn');
        const form = document.getElementById('cr-add-form');
        if (!addBtn || !form) return;
        const nameI = document.getElementById('cr-add-name');
        const specI = document.getElementById('cr-add-spec');
        const priceI = document.getElementById('cr-add-price');
        const qtyI = document.getElementById('cr-add-qty');
        const confirmBtn = document.getElementById('cr-add-confirm');
        const cancelBtn = document.getElementById('cr-add-cancel');
        const resetForm = () => { nameI.value = ''; specI.value = ''; priceI.value = ''; qtyI.value = '1'; };
        addBtn.addEventListener('click', () => {
            const show = form.style.display === 'none' || !form.style.display;
            form.style.display = show ? 'flex' : 'none';
            if (show && nameI) nameI.focus();
        });
        cancelBtn?.addEventListener('click', () => { form.style.display = 'none'; resetForm(); });
        confirmBtn?.addEventListener('click', () => {
            const name = (nameI.value || '').trim();
            if (!name) { UI.showToast('请填写产品名称', 'warning'); nameI.focus(); return; }
            const price = parseFloat(priceI.value) || 0;   // 表单统一按「元/月」录入
            let qty = parseFloat(qtyI.value);
            if (isNaN(qty) || qty < 0) qty = 1;
            window.__crState.rows.push({
                product: name,
                spec: (specI.value || '').trim(),
                billing: '自定义', unit_label: '',
                qty: qty, unit_price: price,
                custom: true, verified: true, note: '',
                business_only: false, no_price: false
            });
            window.__crState.tier = null;
            _crUpdateTierButtons();
            form.style.display = 'none';
            resetForm();
            _crRenderTable();
            _crComputeTotal();
        });
        window.__crState.addBound = true;
    }
    function _crBindTierTabs() {
        if (window.__crState.bound) return;
        const tabs = document.getElementById('cr-tier-tabs');
        if (!tabs) return;
        tabs.querySelectorAll('.cr-tier-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tier = btn.dataset.tier;
                window.__crState.tier = tier;
                window.__crState.rows.forEach(row => {
                    if (row.business_only || !row.tier) return;
                    const t = row.tier[tier];
                    if (t) { row.qty = t.qty; row.unit_price = t.unit_price; }
                });
                _crUpdateTierButtons();
                _crRenderTable();
                _crComputeTotal();
            });
        });
        window.__crState.bound = true;
    }
    function renderCostReference(result) {
        const card = document.getElementById('cost-reference-card');
        if (!card) return;
        let industry = '';
        try {
            const src = (result.source_documents || [])[0];
            industry = src && src.metadata ? (src.metadata.industry || '') : '';
        } catch (e) {}
        if (State.resultCache.solution) State.resultCache.solution.industry = industry;

        API.getPricingReference(industry).then(data => {
            if (!data || !data.items || data.items.length === 0) {
                card.style.display = 'none';
                return;
            }
            card.style.display = 'block';
            const badge = document.getElementById('cr-industry-badge');
            if (badge) badge.textContent = data.industry + (data.is_default ? '（通用）' : '');
            const sub = document.getElementById('cr-sub');
            if (sub) sub.textContent = data.description || '基于公开价目表策展的区间参考';
            const disc = document.getElementById('cr-disclaimer');
            if (disc) disc.textContent = (data.disclaimer || '') + `（数据采集：${data.collected_at || ''} · ${data.region || ''}）`;

            // 缓存行业/免责等元信息，供导出成本表使用
            window.__crState.industry = data.industry || '';
            window.__crState.is_default = !!data.is_default;
            window.__crState.description = data.description || '';
            window.__crState.disclaimer = (data.disclaimer || '') + (data.collected_at ? `（数据采集：${data.collected_at} · ${data.region || ''}）` : '');
            window.__crState.collected_at = data.collected_at || '';
            window.__crState.region = data.region || '';
            window.__crState.annual_discount = (typeof data.annual_discount === 'number' && data.annual_discount > 0) ? data.annual_discount : 0.85;

            window.__crState.rows = data.items.map(it => {
                if (it.business_only) {
                    return { product: it.product, spec: it.spec || '', business_only: true, note: it.note || '商务报价，请咨询华为云销售' };
                }
                if (it.no_price) {
                    return { product: it.product, spec: it.spec || '', no_price: true, note: it.note || '参考价待补充' };
                }
                const mid = (it.tier && it.tier.mid) || { qty: it.qty || 1, unit_price: it.ref_price || 0 };
                return {
                    product: it.product, spec: it.spec || '', billing: it.billing || '',
                    unit_label: it.unit_label || '', ref_price: it.ref_price,
                    qty: mid.qty, unit_price: mid.unit_price, tier: it.tier || null,
                    source_url: it.source_url || '', verified: it.verified !== false, note: it.note || ''
                };
            });
            window.__crState.tier = 'mid';
            window.__crState.view = 'month';
            _crBindTierTabs();
            _crBindViewTabs();
            _crBindCustomAdd();
            _crUpdateTierButtons();
            _crUpdateViewButtons();
            _crRenderTable();
            _crComputeTotal();
        }).catch(err => {
            console.warn('成本参考加载失败:', err);
            card.style.display = 'none';
        });
    }

    // 历史/只读场景的成本参考卡片渲染（无编辑/导出绑定，detail-cr- 独立 id 避免与主页卡片冲突）
    function renderCostReferenceReadOnly(item) {
        const card = document.getElementById('detail-cost-reference-card');
        if (!card) return;
        let industry = (item && item.industry) || '';
        try {
            const src = (item && item.source_documents && item.source_documents[0]);
            if (!industry && src && src.metadata) industry = src.metadata.industry || '';
        } catch (e) {}
        API.getPricingReference(industry).then(data => {
            if (!data || !data.items || data.items.length === 0) {
                card.style.display = 'none';
                return;
            }
            card.style.display = 'block';
            const badge = document.getElementById('detail-cr-industry-badge');
            if (badge) badge.textContent = data.industry + (data.is_default ? '（通用）' : '');
            const sub = document.getElementById('detail-cr-sub');
            if (sub) sub.textContent = data.description || '基于公开价目表策展的区间参考';
            const disc = document.getElementById('detail-cr-disclaimer');
            if (disc) disc.textContent = (data.disclaimer || '') + (data.collected_at ? `（数据采集：${data.collected_at} · ${data.region || ''}）` : '');
            const rows = data.items.map(it => {
                if (it.business_only) return { kind: 'biz', product: it.product, spec: it.spec || '', note: it.note || '商务报价，请咨询华为云销售' };
                if (it.no_price) return { kind: 'noprice', product: it.product, spec: it.spec || '', note: it.note || '参考价待补充' };
                if (it.free) return { kind: 'free', product: it.product, spec: it.spec || '', note: it.note || '按实际创建的资源计费' };
                const mid = (it.tier && it.tier.mid) || { qty: it.qty || 1, unit_price: it.ref_price || 0 };
                return { kind: 'price', product: it.product, spec: it.spec || '', billing: it.billing || '', unit_label: it.unit_label || '', qty: mid.qty, unit_price: mid.unit_price, verified: it.verified !== false, note: it.note || '' };
            });
            const table = document.getElementById('detail-cr-table');
            if (table) {
                let html = '<div class="cr-row cr-row-head"><span class="cr-c-product">产品 / 规格</span><span class="cr-c-qty">数量</span><span class="cr-c-price">单价(月)</span><span class="cr-c-sub">小计</span></div>';
                let total = 0;
                rows.forEach(r => {
                    if (r.kind === 'biz' || r.kind === 'noprice' || r.kind === 'free') {
                        const label = r.kind === 'biz' ? '商务定价' : (r.kind === 'free' ? '基础免费' : '参考价待补充');
                        const cls = r.kind === 'biz' ? 'cr-row-biz' : (r.kind === 'free' ? 'cr-row-free' : 'cr-row-noprice');
                        html += `<div class="cr-row ${cls}"><span class="cr-c-product"><b>${_crEsc(r.product)}</b><br><small>${_crEsc(r.spec)}</small></span><span class="cr-c-biz-note">${label}：${_crEsc(r.note)}</span></div>`;
                        return;
                    }
                    const subAmt = (Number(r.qty) || 0) * (Number(r.unit_price) || 0);
                    total += subAmt;
                    const bill = _crEsc(r.billing) + (r.unit_label ? ((r.billing ? ' · ' : '') + _crEsc(r.unit_label)) : '');
                    const warn = (!r.verified) ? ' <span class="cr-warn" title="待官网复核">⚠</span>' : '';
                    html += `<div class="cr-row"><span class="cr-c-product"><b>${_crEsc(r.product)}</b><br><small>${_crEsc(r.spec)}</small>${bill ? `<span class="cr-bill">${bill}</span>` : ''}${warn}</span><span class="cr-c-qty">${r.qty}</span><span class="cr-c-price">¥${_crMoney(r.unit_price)}</span><span class="cr-c-sub">¥${_crMoney(subAmt)}</span></div>`;
                });
                table.innerHTML = html;
                const el = document.getElementById('detail-cr-total');
                if (el) el.textContent = '¥' + _crMoney(Math.round(total * 100) / 100);
                const lbl = document.getElementById('detail-cr-total-label');
                if (lbl) lbl.textContent = '预估月费合计（参考）';
            }
        }).catch(err => {
            console.warn('历史成本参考加载失败:', err);
            card.style.display = 'none';
        });
    }

    // 展示澄清提问卡（阶段 2.5）
    function showClarifyCard(event) {
        clearClarifyCard();
        const clarifyId = event.clarify_id;
        const questions = event.questions || [];
        if (!clarifyId || questions.length === 0) {
            UI.showToast('AI 需要补充信息，但未提供具体问题', 'warning');
            return;
        }

        const ts = document.getElementById('thinking-stream');
        if (ts) ts.style.display = 'none';

        const card = document.createElement('div');
        card.className = 'clarify-card content-card';
        card.id = 'clarify-card';

        const qHtml = questions.map((q, i) => {
            const opts = (q.options || []).map(o =>
                `<button type="button" class="clarify-opt-btn" data-qindex="${i}">${HistoryUI.escapeHtml(o)}</button>`
            ).join('');
            return `
                <div class="clarify-q">
                    <div class="clarify-q-text">${i + 1}. ${HistoryUI.escapeHtml(q.question)}</div>
                    ${opts ? `<div class="clarify-opts">${opts}</div>` : ''}
                    <input type="text" class="clarify-input" id="clarify-input-${i}" placeholder="输入你的补充（也可点选上方选项）" />
                </div>`;
        }).join('');

        card.innerHTML = `
            <div class="clarify-header">
                <span class="clarify-title"><svg class="icon" aria-hidden="true"><use href="#i-message-circle"></use></svg> AI 需要你补充一点信息</span>
            </div>
            <div class="clarify-body">${qHtml}</div>
            <div class="clarify-actions">
                <button class="btn btn-primary btn-sm" id="clarify-submit-btn">提交并继续</button>
                <button class="btn btn-ghost btn-sm" id="clarify-skip-btn">跳过，直接生成</button>
            </div>
        `;

        // 插入到思考流之后（思考流已隐藏），位置稳定且符合现有布局
        if (ts && ts.parentNode) {
            ts.parentNode.insertBefore(card, ts.nextSibling);
        } else {
            const wrap = document.getElementById('solution-result');
            if (wrap && wrap.parentNode) wrap.parentNode.insertBefore(card, wrap);
            else document.body.appendChild(card);
        }

        card.querySelectorAll('.clarify-opt-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = btn.dataset.qindex;
                const input = document.getElementById(`clarify-input-${idx}`);
                if (input) input.value = btn.textContent.trim();
                card.querySelectorAll(`.clarify-opt-btn[data-qindex="${idx}"]`).forEach(b => b.classList.remove('selected'));
                btn.classList.add('selected');
            });
        });

        const submit = () => {
            const answers = questions.map((q, i) => {
                const input = document.getElementById(`clarify-input-${i}`);
                return { question: q.question, answer: input ? input.value.trim() : '' };
            });
            if (!answers.some(a => a.answer)) {
                UI.showToast('请至少补充一项，或点「跳过」', 'warning');
                return;
            }
            agentClarifyResume(clarifyId, answers);
        };
        card.querySelector('#clarify-submit-btn').addEventListener('click', submit);
        card.querySelector('#clarify-skip-btn').addEventListener('click', () => agentClarifyResume(clarifyId, []));

        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    // 清除澄清提问卡
    function clearClarifyCard() {
        const card = document.getElementById('clarify-card');
        if (card) card.remove();
    }

    // 用户作答后续跑 Agent（阶段 2.5）
    async function agentClarifyResume(clarifyId, answers) {
        clearClarifyCard();
        const controller = new AbortController();
        State.abortControllers.match = controller;
        State.loadingStates.match = true;

        const matchBtn = document.getElementById('match-btn');
        const matchBtnText = matchBtn ? matchBtn.querySelector('.btn-text') : null;
        if (matchBtn) {
            if (matchBtnText) matchBtnText.textContent = '取消匹配';
            matchBtn.classList.add('btn-cancel');
        }

        MatchProgress.start();
        MatchProgress.setSteps([
            { icon: '<svg class="icon" aria-hidden="true"><use href="#i-brain"></use></svg>', label: '分析需求意图', desc: 'AI 理解补充信息，提取关键要点' },
            { icon: '<svg class="icon" aria-hidden="true"><use href="#i-search"></use></svg>', label: '智能搜索知识库', desc: '用结构化关键词精准检索' },
            { icon: '<svg class="icon" aria-hidden="true"><use href="#i-sparkles"></use></svg>', label: '综合生成方案', desc: '基于知识库 + AI 生成完整方案' }
        ]);

        const tsContainer = document.getElementById('thinking-stream');
        const tsEntries = document.getElementById('thinking-entries');
        if (tsContainer) {
            if (tsEntries) tsEntries.innerHTML = '';
            tsContainer.style.display = 'block';
            tsContainer.classList.remove('done');
        }

        try {
            let result;
            let eventCount = 0;
            let lastEventType = '';
            console.log('[Clarify Resume] 开始续跑 clarify_id=', clarifyId, 'answers=', answers);
            await API.agentClarify(clarifyId, answers, State.currentClientId, controller.signal, (event) => {
                eventCount++;
                lastEventType = event.type || '(no type)';
                applyAgentProgressEvents(event);
                if (event.type === 'result') {
                    result = event.data;
                    console.log('[Clarify Resume] 收到 result 事件 paused=', result?.paused, 'expired=', result?.expired);
                } else if (event.type === 'error') {
                    throw new Error(event.message);
                }
            });
            console.log('[Clarify Resume] SSE 流结束 eventCount=', eventCount, 'lastEvent=', lastEventType, 'result=', !!result);

            // 兜底：流正常关闭但没收到 result → 后端未发出事件
            if (!result) {
                if (eventCount === 0) {
                    throw new Error('服务器无响应（可能重启中或网络中断），请重试');
                }
                throw new Error('匹配过程异常结束，未返回结果（已收到 ' + eventCount + ' 个事件）');
            }

            renderAgentResult(result, State.lastAgentDemand);
        } catch (error) {
            if (error.name === 'AbortError') {
                const ts = document.getElementById('thinking-stream');
                if (ts) ts.style.display = 'none';
                return;
            }
            console.error('[Clarify Resume] 续跑失败:', error);
            MatchProgress.error('生成失败，请重试');
            UI.showToast(error.message || '生成失败，请重试', 'error');
        } finally {
            State.loadingStates.match = false;
            State.isQuickDemo = false;
            if (matchBtnText) matchBtnText.textContent = '开始匹配';
            if (matchBtn) matchBtn.classList.remove('btn-cancel');
            if (State.abortControllers.match === controller) State.abortControllers.match = null;
        }
    }
    
    document.getElementById('clear-solution-btn')?.addEventListener('click', () => {
        // 如果正在匹配，先触发取消
        if (State.loadingStates.match && matchBtn) {
            matchBtn.click();
        }
        demandInput.value = '';
        charCount.textContent = '0';
        CustomerFileUploader.clear();
        document.getElementById('solution-result').style.display = 'none';
        MatchProgress.hide();
        State.resultCache.solution = null;
    });
    
    // 导出方案书（Word）：优先用结构化 solution_json，后端自动回退 Markdown
    async function triggerExportSolutionBook() {
        const cached = State.resultCache.solution;
        if (!cached || !cached.answer) {
            UI.showToast('请先生成方案再导出', 'warning');
            return;
        }
        const btn = document.getElementById('export-docx-btn');
        const origHtml = btn ? btn.innerHTML : '<svg class="icon" aria-hidden="true"><use href="#i-file-text"></use></svg> 导出方案书';
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-loader"></use></svg> 生成中...';
        }
        UI.showToast('正在生成方案书...', 'info');
        try {
            // 构造成本参考附表（使用用户在卡片中修改确认过的编辑态）
            let cost_reference = null;
            const cr = window.__crState;
            if (cr && cr.rows && cr.rows.length) {
                cost_reference = {
                    industry: cr.industry || (cached.industry || ''),
                    is_default: !!cr.is_default,
                    description: cr.description || '',
                    disclaimer: cr.disclaimer || '',
                    collected_at: cr.collected_at || '',
                    region: cr.region || '',
                    tier: cr.tier || null,
                    view_mode: cr.view || 'month',
                    annual_discount: (typeof cr.annual_discount === 'number' && cr.annual_discount > 0) ? cr.annual_discount : 0.85,
                    rows: cr.rows.map(r => ({
                        product: r.product,
                        spec: r.spec || '',
                        billing: r.billing || '',
                        unit_label: r.unit_label || '',
                        qty: r.qty,
                        unit_price: r.unit_price,
                        verified: r.verified !== false,
                        note: r.note || '',
                        custom: !!r.custom,
                        business_only: !!r.business_only,
                        no_price: !!r.no_price
                    }))
                };
            }
            const resp = await API.exportReport({
                report_type: 'solution',
                format: 'word',
                title: '华为云解决方案建议书',
                content: cached.answer,
                solution_json: cached.solution_json || null,
                source_documents: cached.source_documents || [],
                metadata: { customer: '', title: '华为云解决方案建议书' },
                cost_reference
            });
            const status = (resp.status || '').toUpperCase();
            if (status !== 'COMPLETED') {
                throw new Error(resp.error_message || '方案书生成失败');
            }
            // 下载生成的文件（download_url 已含 /api，需去掉避免与 API_BASE_URL 拼接成 /api/api/...）
            const dlPath = (resp.download_url || '').replace(/^\/api/, '');
            const dlUrl = `${Config.API_BASE_URL}${dlPath}`;
            const fileResp = await fetch(dlUrl);
            if (!fileResp.ok) throw new Error('文件下载失败');
            const blob = await fileResp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = resp.file_name || 'solution_report.docx';
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            UI.showToast('方案书已生成并下载', 'success');
        } catch (e) {
            console.error('[导出方案书] 失败:', e);
            UI.showToast(e.message || '导出失败，请重试', 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = origHtml;
            }
        }
    }

    document.getElementById('download-solution-btn')?.addEventListener('click', () => {
        if (State.resultCache.solution) {
            let md = State.resultCache.solution.answer || '';
            // 追加成本参考附表（合法 Markdown 表格，供纯文本查看）
            const cr = window.__crState;
            if (cr && cr.rows && cr.rows.length) {
                const isYear = cr.view === 'year';
                const factor = isYear ? 12 * ((Number(cr.annual_discount) || 0.85)) : 1;
                const unitTxt = isYear ? '元/年' : '元/月';
                const lines = ['', '---', '', '## 成本参考估算（区间参考，非精确报价）', ''];
                lines.push(`| 产品 | 规格 | 计费方式 | 数量 | 单价(${unitTxt}) | 小计(${unitTxt}) |`);
                lines.push('| :--- | :--- | :--- | :--- | :--- | :--- |');
                let total = 0;
                cr.rows.forEach(r => {
                    const product = (r.product || '') + (r.custom ? '（自定义）' : '');
                    const spec = r.spec || '';
                    if (r.business_only) {
                        lines.push(`| **${product}** | ${spec} | — | — | — | 商务定价：${r.note || '请咨询华为云销售'} |`);
                        return;
                    }
                    if (r.no_price) {
                        lines.push(`| **${product}** | ${spec} | — | — | — | 参考价待补充：${r.note || ''} |`);
                        return;
                    }
                    const qty = Number(r.qty) || 0;
                    const up = Math.round((Number(r.unit_price) || 0) * factor * 100) / 100;
                    const sub = Math.round(qty * up * 100) / 100;
                    total += sub;
                    const billing = (r.billing || '') + (r.unit_label ? ('·' + r.unit_label) : '');
                    lines.push(`| **${product}** | ${spec} | ${billing} | ${qty} | ${up} | ${sub} |`);
                });
                lines.push('', `**合计（估算，不含商务定价与待补充项）：¥${total.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${unitTxt}**`);
                if (cr.disclaimer) lines.push('', `免责声明：${cr.disclaimer}`);
                md += lines.join('\n');
            }
            UI.downloadFile(md, '华为云解决方案建议书.md');
        }
    });

    document.getElementById('export-docx-btn')?.addEventListener('click', triggerExportSolutionBook);

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
                        <div class="result-header"><span class="result-badge success"><svg class="icon" aria-hidden="true"><use href="#i-circle-check"></use></svg> 分析完成</span></div>
                        <div class="result-content content-card" id="competitor-content"></div>
                        <div class="result-actions">
                            <button class="btn btn-primary" id="download-competitor-btn"><svg class="icon" aria-hidden="true"><use href="#i-download"></use></svg> 下载竞争分析报告</button>
                            <button class="btn btn-favorite-result" id="fav-competitor-btn"><svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg> 收藏报告</button>
                        </div>
                        <details class="source-documents content-card">
                            <summary class="source-summary"><svg class="icon" aria-hidden="true"><use href="#i-book-open"></use></svg> 查看参考的解决方案文档</summary>
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
                resultContent.innerHTML = '<div class="result-empty"><p style="color: var(--text-secondary); text-align: center; padding: 40px 20px;"><svg class="icon" aria-hidden="true"><use href="#i-triangle-alert"></use></svg> 分析服务返回了空结果，请稍后重试。</p></div>';
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

            // ★ 匹配完成：隐藏思考流面板（释放占用的空间，尤其移动端）
            const tsDone = document.getElementById('thinking-stream');
            if (tsDone) { tsDone.style.display = 'none'; }
            
            State.resultCache.competitor = { ...result, competitor, industry };
            // 更新收藏按钮状态
            const compFavName = `华为云 vs ${competitor} 竞争分析报告`;
            FavoriteManager._updateResultBtn('fav-competitor-btn', compFavName);
            
            UI.showToast('分析完成！', 'success');
            CompetitorFollowUpUI.show(competitor, industry, result.answer, result.history_id);

            // 成就通知（竞品分析）
            console.log('[Achievement] analyze newly_unlocked:', result.newly_unlocked);
            if (result.newly_unlocked && result.newly_unlocked.length > 0 && window.AchievementUI && AchievementUI.showUnlockToast) {
                setTimeout(() => AchievementUI.showUnlockToast(result.newly_unlocked), 500);
            }
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
        if (!AuthManager.isLoggedIn()) {
            UI.showToast('请先登录后再操作', 'warning');
            AuthManager._openModal();
            return;
        }
        UI.setButtonLoading(rebuildBtn, true);
        UI.setButtonLoading(syncMineBtn, true); // 同一进度面板，禁用同步避免冲突

        // 显示重建进度面板
        if (rebuildProgressPanel) {
            rebuildProgressPanel.style.display = 'block';
            rebuildProgressPanel.classList.remove('success', 'fade-out');
        }
        const titleEl = rebuildProgressPanel?.querySelector('.progress-title');
        if (titleEl) titleEl.textContent = '正在重建知识库（后台运行）...';
        if (rebuildStatusText) rebuildStatusText.textContent = '任务已提交，正在排队...';
        RebuildProgress.start();

        try {
            const task = await API.rebuildKnowledge(); // { task_id, status, message }
            if (rebuildStatusText) rebuildStatusText.textContent = task.message || '任务已提交，正在排队...';

            // 轮询后台任务进度，直到 success / failed
            const final = await pollKbTask(task.task_id, (st) => {
                RebuildProgress.setProgress(st.progress);
                if (rebuildStatusText && st.message) rebuildStatusText.textContent = st.message;
            });

            RebuildProgress.success('知识库重建完成！');
            const count = (final.result && final.result.count) || 0;
            if (rebuildStatusText) rebuildStatusText.textContent = `成功添加 ${count} 个文档片段到知识库`;
            UI.showToast(`知识库重建完成！共添加 ${count} 个文档片段`, 'success');
            await KnowledgeUI.loadStats();
            await KnowledgeUI.loadDocList();
        } catch (error) {
            console.error('重建失败:', error);
            RebuildProgress.error('重建失败');
            if (rebuildStatusText) rebuildStatusText.textContent = error.message || '重建失败，请重试';
            UI.showToast(error.message || '重建失败，请重试', 'error');
        } finally {
            UI.setButtonLoading(rebuildBtn, false);
            UI.setButtonLoading(syncMineBtn, false);
        }
    });
    
    const clearKbBtn = document.getElementById('clear-kb-btn');
    const confirmOverlay = document.getElementById('confirm-clear-overlay');
    const confirmClearBtn = document.getElementById('confirm-clear-btn');
    const cancelCloseBtn = document.getElementById('cancel-clear-btn');
    const cancelCancelBtn = document.getElementById('confirm-cancel-btn');

    const closeConfirm = () => { confirmOverlay.style.display = 'none'; };

    clearKbBtn?.addEventListener('click', () => {
        if (!AuthManager.isLoggedIn()) {
            UI.showToast('请先登录后再操作', 'warning');
            AuthManager._openModal();
            return;
        }
        confirmOverlay.style.display = 'flex';
    });
    confirmOverlay?.addEventListener('click', (e) => { if (e.target === confirmOverlay) closeConfirm(); });
    cancelCancelBtn?.addEventListener('click', closeConfirm);
    cancelCloseBtn?.addEventListener('click', closeConfirm);

    confirmClearBtn?.addEventListener('click', async () => {
        try {
            await API.clearKnowledge();
            UI.showToast('知识库已清空', 'success');
            closeConfirm();
            await KnowledgeUI.loadStats();
            await KnowledgeUI.loadDocList();
        } catch (error) {
            console.error('清空失败:', error);
            UI.showToast(error.message || '清空失败，请重试', 'error');
        }
    });

    // ===== 同步最新官方方案（方案B：保留用户自定义内容）=====
    const syncMineBtn = document.getElementById('sync-mine-btn');
    syncMineBtn?.addEventListener('click', async () => {
        if (!AuthManager.isLoggedIn()) {
            UI.showToast('请先登录后再操作', 'warning');
            AuthManager._openModal();
            return;
        }
        if (!confirm('将把管理员最新扩充的官方方案合并进你的知识库，你自己的文档会保留。确定同步吗？')) return;

        UI.setButtonLoading(syncMineBtn, true);
        UI.setButtonLoading(rebuildBtn, true); // 同一进度面板，禁用重建避免冲突

        // 显示进度面板（复用重建面板）
        if (rebuildProgressPanel) {
            rebuildProgressPanel.style.display = 'block';
            rebuildProgressPanel.classList.remove('success', 'fade-out');
        }
        const titleEl = rebuildProgressPanel?.querySelector('.progress-title');
        if (titleEl) titleEl.textContent = '正在同步你的知识库（后台运行）...';
        if (rebuildStatusText) rebuildStatusText.textContent = '任务已提交，正在排队...';
        RebuildProgress.start();

        try {
            const task = await API.syncMyKnowledge(); // { task_id, status, message }
            if (rebuildStatusText) rebuildStatusText.textContent = task.message || '任务已提交，正在排队...';

            const final = await pollKbTask(task.task_id, (st) => {
                RebuildProgress.setProgress(st.progress);
                if (rebuildStatusText && st.message) rebuildStatusText.textContent = st.message;
            });

            RebuildProgress.success('知识库同步完成！');
            const total = (final.result && final.result.total_documents) || 0;
            if (rebuildStatusText) rebuildStatusText.textContent = `已同步最新官方方案，共 ${total} 个文档片段（你的自定义内容已保留）`;
            UI.showToast(`已同步最新官方方案，共 ${total} 个文档片段`, 'success');
            await KnowledgeUI.loadStats();
            await KnowledgeUI.loadDocList();
        } catch (error) {
            console.error('同步失败:', error);
            RebuildProgress.error('同步失败');
            if (rebuildStatusText) rebuildStatusText.textContent = error.message || '同步失败，请重试';
            UI.showToast(error.message || '同步失败，请重试', 'error');
        } finally {
            UI.setButtonLoading(syncMineBtn, false);
            UI.setButtonLoading(rebuildBtn, false);
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
        console.log('[Init] 华为云方案匹配系统 v20260531n 正在初始化...');
        const canvas = document.getElementById('particle-canvas');
        if (canvas) {
            new ParticleSystem(canvas);
        }

        initEventListeners();
        DemandWizard.init();
        HistoryUI.init();
        FollowUpUI.init();
        CompetitorFollowUpUI.init();
        AuthManager.init();
        SettingsManager.init();
        ErrorHandler.init();
        FavoriteManager.init();
        AchievementUI.init();

        // 初始化产品图谱模块（容错：DOM未就绪时不崩溃）
        try { ProductGraph.init(); } catch (e) {
            console.warn('[Init] ProductGraph初始化延迟，切换到产品页时会重试:', e.message);
        }
        // 初始化 AI 智能助手
        try { AIAssistant.init(); } catch (e) {
            console.warn('[Init] AI助手初始化失败:', e.message);
        }
        // ArchTree3D 已移除（v20260531w — 3D产品架构弹窗功能废弃）

        // 隐藏分页容器（无数据时）
        const pagContainer = document.getElementById('pagination-container');
        if (pagContainer) pagContainer.style.display = 'none';

        KnowledgeUI.loadStats();
        KnowledgeUI._bindDocEvents();
        KnowledgeUI.loadDocList();

        // 登录刷新后显示待处理的成就通知
        try {
            const pending = sessionStorage.getItem('pending_achievements');
            if (pending && window.AchievementUI && AchievementUI.showUnlockToast) {
                sessionStorage.removeItem('pending_achievements');
                const achievements = JSON.parse(pending);
                if (achievements.length > 0) {
                    setTimeout(() => AchievementUI.showUnlockToast(achievements), 1000);
                }
            }
        } catch (_) {}

        // 检测 URL 中的 reset-password?token 参数（邮件重置链接）
        try {
            const urlParams = new URLSearchParams(window.location.search);
            const resetToken = urlParams.get('token');
            if (resetToken) {
                console.log('[Init] 检测到密码重置链接，打开重置弹窗...');
                // 保存 token 到全局变量（提交表单时使用）
                window._resetToken = resetToken;
                // 清理 URL（去掉 token 参数，避免刷新时重复触发）
                window.history.replaceState({}, document.title, window.location.pathname);
                // 延迟一点等 DOM 完全就绪
                setTimeout(() => {
                    const overlay = document.getElementById('reset-password-modal-overlay');
                    if (overlay) {
                        overlay.style.display = '';
                        const errEl = document.getElementById('reset-password-error');
                        const succEl = document.getElementById('reset-password-success');
                        if (errEl) errEl.style.display = 'none';
                        if (succEl) succEl.style.display = 'none';
                        console.log('[Init] 重置密码弹窗已打开');
                    }
                }, 500);
            }
        } catch (_) {}
    } catch (e) {
        console.error('[Init] 初始化失败:', e);
    }
}

document.addEventListener('DOMContentLoaded', init);


/* ==================== AI 智能助手模块 ==================== */
const AIAssistant = {
    isOpen: false,
    isTyping: false,
    history: [],   // 对话上下文 [{role: 'user'|'ai', text: '...'}]

    init() {
        // 打开按钮
        var aiBtn = document.getElementById('topbar-ai-btn');
        if (aiBtn) aiBtn.addEventListener('click', () => this.open());

        // 关闭按钮 + 遮罩点击
        var closeBtn = document.getElementById('ai-panel-close');
        if (closeBtn) closeBtn.addEventListener('click', () => this.close());
        // 新对话按钮（清空上下文，保留面板打开）
        var newChatBtn = document.getElementById('ai-new-chat-btn');
        if (newChatBtn) newChatBtn.addEventListener('click', () => this.newChat());
        var overlay = document.getElementById('ai-assistant-overlay');
        if (overlay) overlay.addEventListener('click', (e) => { if (e.target === overlay) this.close(); });

        // 快捷建议卡片
        document.querySelectorAll('.ai-quick-card').forEach(card => {
            card.addEventListener('click', () => {
                var q = card.getAttribute('data-q');
                if (q) this.sendQuestion(q);
            });
        });

        // 输入框
        var input = document.getElementById('ai-input');
        if (input) {
            input.addEventListener('input', () => this._updateSendBtn());
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._doSend(); }
            });

            // 自动高度
            input.addEventListener('input', function() {
                this.style.height = 'auto';
                this.style.height = Math.min(this.scrollHeight, 120) + 'px';
            });
        }

        // 发送按钮
        var sendBtn = document.getElementById('ai-send-btn');
        if (sendBtn) sendBtn.addEventListener('click', () => this._doSend());

        // ESC 关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) this.close();
        });
    },

    open() {
        this.isOpen = true;
        var overlay = document.getElementById('ai-assistant-overlay');
        if (overlay) overlay.style.display = 'flex';
        document.body.style.overflow = 'hidden';

        // 聚焦输入
        setTimeout(() => {
            var input = document.getElementById('ai-input');
            if (input) input.focus();
        }, 300);
    },

    close() {
        this.isOpen = false;
        var overlay = document.getElementById('ai-assistant-overlay');
        if (overlay) overlay.style.display = 'none';
        document.body.style.overflow = '';
        // 关闭时清空对话历史和消息（新会话），并恢复快捷建议
        this.history = [];
        this.isTyping = false;
        var container = document.getElementById('ai-chat-messages');
        if (container) container.innerHTML = '';
        var qa = document.getElementById('ai-quick-actions');
        if (qa) qa.style.display = '';
    },

    newChat() {
        // 开始新对话：清空上下文（保留面板打开），恢复快捷建议与输入态
        this.history = [];
        this.isTyping = false;
        var container = document.getElementById('ai-chat-messages');
        if (container) container.innerHTML = '';
        var qa = document.getElementById('ai-quick-actions');
        if (qa) qa.style.display = '';
        var input = document.getElementById('ai-input');
        if (input) { input.value = ''; input.style.height = 'auto'; }
        this._updateSendBtn();
    },

    toggle() {
        this.isOpen ? this.close() : this.open();
    },

    sendQuestion(q) {
        var input = document.getElementById('ai-input');
        if (input) { input.value = q; this._doSend(); }
    },

    _updateSendBtn() {
        var btn = document.getElementById('ai-send-btn');
        var input = document.getElementById('ai-input');
        if (btn && input) btn.disabled = !input.value.trim();
    },

    _doSend() {
        var input = document.getElementById('ai-input');
        if (!input || this.isTyping) return;
        var text = input.value.trim();
        if (!text) return;

        // 隐藏快捷建议
        var qa = document.getElementById('ai-quick-actions');
        if (qa) qa.style.display = 'none';

        // 显示用户消息
        this._addMsg(text, 'user');

        // 清空输入
        input.value = '';
        input.style.height = 'auto';
        this._updateSendBtn();

        // 记录到历史
        this.history.push({ role: 'user', text: text });

        // 发送请求
        this._askAI(text);
    },

    _addMsg(text, role) {
        var container = document.getElementById('ai-chat-messages');
        if (!container) return;

        var div = document.createElement('div');
        div.className = 'ai-msg ai-msg-' + role;
        div.innerHTML = '<div class="ai-msg-bubble">' + this._renderTablesOnly(this._escapeHtml(text)).replace(/\n/g, '<br>') + '</div>';
        container.appendChild(div);

        // 自动滚动到底部
        container.scrollTop = container.scrollHeight;

        return div;
    },

    _showThinking() {
        var container = document.getElementById('ai-chat-messages');
        if (!container) return null;

        var div = document.createElement('div');
        div.className = 'ai-msg ai-msg-ai';
        div.id = 'ai-thinking-msg';
        div.innerHTML = '<div class="ai-msg-thinking"><span></span><span></span><span></span></div>';
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
        return div;
    },

    _removeThinking() {
        var el = document.getElementById('ai-thinking-msg');
        if (el) el.remove();
    },

    async _askAI(question) {
        this.isTyping = true;
        this._showThinking();

        try {
            // 带上登录 token，后端才能识别 user → 命中 personal 路由（"我的客户档案"等个人知识类问题）
            var _headers = { 'Content-Type': 'application/json' };
            try {
                if (AuthManager.isLoggedIn()) {
                    _headers['Authorization'] = 'Bearer ' + AuthManager.getToken();
                }
            } catch (e) { /* 未登录则匿名请求，走 cloud/general 路由 */ }
            var resp = await fetch('/api/ai/chat', {
                method: 'POST',
                headers: _headers,
                body: JSON.stringify({ question: question, history: this.history })
            });

            var data = await resp.json();

            this._removeThinking();

            if (data.answer) {
                // 记录 AI 回复到历史
                this.history.push({ role: 'ai', text: data.answer });
                this._addMsg(data.answer, 'ai');
            } else if (data.error) {
                this._addMsg('抱歉，处理时出现错误：' + data.error, 'ai');
            } else {
                this._addMsg('抱歉，暂时无法回答这个问题。请稍后再试。', 'ai');
            }
        } catch (err) {
            this._removeThinking();
            this._addMsg('网络连接失败，请检查网络后重试。', 'ai');
        } finally {
            this.isTyping = false;
        }
    },

    // 仅渲染 Markdown 表格（AI 聊天用：保持纯文本输出，但表格转为可读 HTML）
    _renderTablesOnly(text) {
        if (!text || !text.includes('|')) return text;
        var lines = text.split('\n');
        var parseCells = function(line) {
            return line.split('|').slice(1, -1).map(function(c) { return c.trim(); });
        };
        var buildTable = function(headerLine, dataLines) {
            var headers = parseCells(headerLine);
            var tbl = '<table class="markdown-table" style="width:100%;border-collapse:collapse;margin:8px 0;font-size:13px;border:1px solid #d9d9d9;">';
            tbl += '<thead><tr>';
            headers.forEach(function(h) {
                tbl += '<th style="border:1px solid #d9d9d9;border-bottom:2px solid rgba(199,0,11,0.15);padding:6px 10px;text-align:left;background:rgba(199,0,11,0.06);color:#1f2329;font-weight:600;white-space:nowrap;">' + h + '</th>';
            });
            tbl += '</tr></thead><tbody>';
            dataLines.forEach(function(row) {
                var cells = parseCells(row);
                // 跳过分隔行（防御性过滤）
                if (cells.every(function(c) { return /^[\s\-:|]+$/.test(c) || c === ''; })) return;
                tbl += '<tr>';
                cells.forEach(function(c) {
                    tbl += '<td style="border:1px solid #e8e8e8;padding:6px 10px;color:#333;">' + c + '</td>';
                });
                tbl += '</tr>';
            });
            tbl += '</tbody></table>';
            return tbl;
        };
        var isSep = function(l) { return /^\|[\s\-:|]{3,}\|$/.test(l.trim()); };
        var isRow = function(l) { return /^\s*\|.+\|$/.test(l); };

        var i = 0;
        while (i < lines.length) {
            if (isRow(lines[i])) {
                var headerLine = lines[i].trim();
                var sepIdx = -1;
                for (var look = i + 1; look <= Math.min(i + 3, lines.length - 1); look++) {
                    if (isSep(lines[look])) { sepIdx = look; break; }
                    if (lines[look].trim() !== '' && !isRow(lines[look])) break;
                }
                if (sepIdx !== -1) {
                    var j = sepIdx + 1;
                    while (j < lines.length && (isRow(lines[j]) || lines[j].trim() === '')) j++;
                    var dataRows = lines.slice(sepIdx + 1, j).filter(isRow);
                    lines.splice(i, j - i, buildTable(headerLine, dataRows));
                } else {
                    // 无分隔符：连续 ≥2 行管道且列数一致 → 当表格
                    var j2 = i + 1;
                    while (j2 < lines.length && (isRow(lines[j2]) || lines[j2].trim() === '')) j2++;
                    var rLines = lines.slice(i, j2).filter(isRow);
                    if (rLines.length >= 2) {
                        var cc = parseCells(rLines[0]).length;
                        if (cc >= 2 && rLines.every(function(r) { return parseCells(r).length === cc; })) {
                            lines.splice(i, j2 - i, buildTable(rLines[0], rLines.slice(1)));
                        } else { i++; }
                    } else { i++; }
                }
            } else { i++; }
        }
        return lines.join('\n');
    },

    _escapeHtml(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(s));
        return d.innerHTML;
    }
};

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
        compute:   { label: '计算',     icon: '<svg class="icon" aria-hidden="true"><use href="#i-cloud"></use></svg>', color: '#3B82F6' },
        network:   { label: '网络',     icon: '<svg class="icon" aria-hidden="true"><use href="#i-globe"></use></svg>', color: '#F59E0B' },
        storage:   { label: '存储',     icon: '<svg class="icon" aria-hidden="true"><use href="#i-folder"></use></svg>', color: '#22C55E' },
        database:  { label: '数据库',   icon: '<svg class="icon" aria-hidden="true"><use href="#i-file"></use></svg>',  color: '#A855F7' },
        ai:         { label: 'AI/大数据', icon: '<svg class="icon" aria-hidden="true"><use href="#i-bot"></use></svg>',  color: '#EF4444' },
        iot:       { label: 'IoT',      icon: '<svg class="icon" aria-hidden="true"><use href="#i-radio"></use></svg>',  color: '#F97316' },
        security:  { label: '安全',     icon: '<svg class="icon" aria-hidden="true"><use href="#i-shield"></use></svg>',  color: '#EC4899' },
        media:     { label: '音视频/CDN', icon: '<svg class="icon" aria-hidden="true"><use href="#i-film"></use></svg>',  color: '#06B6D4' },
        enterprise:{ label: '企业应用', icon: '<svg class="icon" aria-hidden="true"><use href="#i-briefcase"></use></svg>',  color: '#84CC16' }
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
        { id:'codehub', name:'CodeHub 代码托管', nameEn:'CodeHub', category:'enterprise', desc:'CodeHub是基于Git的云端代码托管与DevOps协作平台，提供代码仓库管理、合并请求（MR）代码审查、CI/CD流水线、代码质量扫描等能力。支持私有部署和多云管理，帮助开发团队实现高效协作和持续交付。', capabilities:['Git代码仓库托管','合并请求(MR)与代码审查','分支策略与保护规则','CI/CD流水线编排','代码质量静态扫描','安全漏洞自动检测','代码规范自动检查','制品仓库管理','Wiki与文档协作','多租户权限管理'], scenarios:['软件开发团队协作','开源项目管理','DevOps持续交付','微服务代码管理','代码安全审计','多项目统一管理','跨地域团队开发','代码评审规范化'] , advantages:['企业级安全：代码加密存储，细粒度权限控制','DevOps一体：代码+构建+测试+部署全流程','质量内建：代码扫描+安全检测，问题早发现','高效协作：MR代码审查，保证代码质量'], highlights:['支持Git LFS大文件','与CCE容器服务联动','兼容GitHub/GitLab导入']},
        // 网络（补充）
        { id:'nat', name:'NAT 网关', nameEn:'NAT Gateway', category:'network', desc:'NAT网关（NAT Gateway）为云下VPC内的实例提供访问公网的能力，同时支持端口级SNAT/DNAT规则。多台ECS可共享一个或多个弹性公网IP访问互联网，大幅降低公网成本。支持高达5Gbps带宽和千万级并发连接。', capabilities:['SNAT源地址转换(共享EIP)','DNAT目标地址转换(端口映射)','多EIP共享与自动故障切换','端口级粒度规则配置','SNAT规则按子网/网段划分','跨可用区高可用部署','出入方向流量监控','与ELB/ECS无缝集成','支持IPv4/IPv6双栈'], scenarios:['多台ECS共享公网出口','数据库只读副本公网同步','微服务统一公网出口','容器集群出站流量','混合云数据同步通道','批量任务下载/上传出口'] , advantages:['成本优化：多实例共享EIP，降低70%公网成本','高吞吐：单网关最高5Gbps，支持千万级并发','灵活规则：端口级SNAT/DNAT精细控制','高可用：跨AZ部署，自动故障切换'], highlights:['最大支持20个绑定EIP','并发连接数达千万级','支持SNAT规则按子网划分']},
        { id:'vpn', name:'VPN 网关', nameEn:'VPN Gateway', category:'network', desc:'VPN网关（VPN）基于IPsec-VPN协议，在企业本地数据中心（IDC）与华为云VPC之间建立加密隧道，实现安全可靠的混合云组网。支持主备双链路冗余、BGP动态路由和IKEv2协议，满足金融、政务等行业的高安全合规要求。', capabilities:['IPsec-VPN加密隧道','IKEv1/IKEv2密钥协商','主备双链路冗余热备','BGP动态路由自动学习','预共享密钥/证书认证','DPD死信体检测','多站点Hub-Spoke组网','QoS带宽保障','日志审计与监控'], scenarios:['IDC上云混合云互联','异地容灾备份链路','分支机构接入总部VPC','SAP HANA系统容灾','政务外网安全接入','跨国企业跨境组网'] , advantages:['安全合规：国密算法支持，满足等保要求','高可靠：主备双链路自动切换，RPO接近0','灵活组网：支持Hub-Spoke多点互联','低成本：相比专线，VPN成本降低80%+'], highlights:['加密算法支持AES-256-GCM','单链路带宽最高1Gbps','支持国密SM2/SM3/SM4']},
        // 计算/PaaS（补充）
        { id:'swr', name:'SWR 容器镜像服务', nameEn:'Software Repository for Container', category:'compute', desc:'SWR是华为云提供的容器镜像全生命周期托管服务，支持镜像存储、分发、安全扫描和企业级镜像市场。与CCE/CCI深度集成，提供镜像加速、跨区域复制、漏洞扫描等能力，帮助企业构建安全的容器 DevOps 流水线。', capabilities:['Docker/OCI镜像托管','镜像安全漏洞扫描','企业级 Harbor 镜像仓库','镜像全球加速分发','跨区域镜像同步复制','镜像签名与验签','P2P镜像加速拉取','镜像生命周期策略','组织与多租户隔离','API/CLI全功能操作'], scenarios:['K8s集群镜像分发','CI/CD流水线镜像构建','多地域容器部署','企业内部镜像市场','镜像安全合规扫描','微服务版本化管理'] , advantages:['安全可信：镜像漏洞自动扫描，阻断风险镜像入库','极速分发：全球加速节点，镜像拉取速度提升10倍','企业治理：组织隔离+镜像签名，满足合规要求','生态集成：与CCE/CCI零配置对接，开箱即用'], highlights:['单租户最大100TB存储','支持10000+镜像标签','Harbor开源兼容']},
        { id:'apig', name:'APIG API网关', nameEn:'API Gateway', category:'compute', desc:'APIG是企业级高性能API网关服务，提供API的全生命周期管理——从设计、发布、运维到下线。支持RESTful/gRPC/WebSocket等多种协议，具备流量控制、签名验证、访问控制、监控告警等企业级能力，是微服务和开放平台的统一入口。', capabilities:['RESTful/gRPC/WebSocket协议','API全生命周期管理','流量控制与限流熔断','请求签名验证(HMAC/AKSK)','OAuth2.0授权与访问控制','自定义插件与扩展','API版本管理与灰度发布','请求/响应转换与Mock','调用链追踪与日志分析','多环境(开发/测试/生产)隔离'], scenarios:['微服务统一API入口','开放平台API对外开放','移动App后端网关','IoT设备API代理','第三方系统集成接口','B2B API产品化运营'] , advantages:['高性能：单实例支持万级QPS，毫秒级延迟','安全防护：签名验证+流控+WAF联动全方位防护','运维友好：可视化调试、自动文档生成、调用分析','灵活扩展：自定义插件机制，满足个性化需求'], highlights:['支持gRPC协议透传','自定义插件支持Python/Node.js','与IAM深度集成鉴权']},
        { id:'cse', name:'CSE 微服务引擎', nameEn:'Cloud Service Engine', category:'compute', desc:'CSE是基于Apache ServiceComb的开源微服务框架，提供服务注册发现、配置管理、分布式事务、限流降级等微服务基础设施能力。支持Spring Cloud/Dubbo/Go/mesh等多语言生态，帮助企业快速构建和管理云原生微服务应用。', capabilities:['服务注册与发现(Nacos/Eureka)','分布式配置中心','限流熔断与降级(Sentinel)','分布式事务(Seata)','服务网格(Service Mesh)','多语言SDK(Java/Go/Python/Dubbo)','灰度发布与蓝绿部署','全链路追踪与监控','证书管理与mTLS通信','多数据中心容灾'], scenarios:['Spring Cloud微服务迁移','Dubbo传统微服务升级','Service Mesh渐进式演进','多语言异构微服务治理','金融核心系统微服务改造','大规模微服务集群管理'] , advantages:['开源兼容：100%兼容Spring Cloud/Dubbo生态，零改造成本','生产级可靠性：多AZ高可用，99.95% SLA保障','渐进式演进：支持Sidecar模式平滑过渡到Mesh','全栈治理：注册+配置+事务+限流一站式解决'], highlights:['支持百万级服务实例','与CCE/K8s原生集成','开源社区活跃度Top3']},
        { id:'s2', name:'ServiceStage 应用管理', nameEn:'ServiceStage', category:'compute', desc:'ServiceStage是一站式应用管理与运维平台，提供应用全托管部署、灰度发布、自动化运维、性能管理等能力。支持容器应用和无服务器应用的统一管理，与CCE/CCI/CodeHub深度集成，让开发者专注于业务代码而无需关心底层基础设施。', capabilities:['应用全托管部署','滚动/灰度/蓝绿发布','自动化扩缩容策略','健康检查与自愈','APM应用性能监控','日志集中采集与分析','CI/CD流水线一键部署','多环境管理(Dev/Test/Prod)','应用模板与快速创建','成本分析与资源优化'], scenarios:['Web应用托管与运维','微服务统一管理平台','无服务器应用(FaaS)管理','DevOps持续交付落地','多团队应用隔离管理','应用性能瓶颈诊断'] , advantages:['零运维：应用全托管，无需管理底层K8s集群','一键发布：从代码提交到生产上线全自动流水线','可观测性：内置APM+日志+告警一体化监控','成本透明：资源使用可视化，自动推荐降本方案'], highlights:['支持5000+应用并发管理','与CodeHub/CCE零配置联动','内置Prometheus+Grafana监控面板']},
        // 安全（补充）
        { id:'iam', name:'IAM 统一身份认证', nameEn:'Identity and Access Management', category:'security', desc:'IAM是华为云统一的身份与权限管理服务，提供用户身份管理、细粒度权限控制和身份联邦能力。支持基于策略的权限模型（类似RBAC）、多因素认证(MFA)、SSO单点登录和LDAP/AD外部身份源集成，满足企业复杂的身份治理需求。', capabilities:['用户/用户组管理','基于策略的权限控制(RBAC)','多因素认证(MFA)','SSO单点登录(SAML/OIDC)','LDAP/AD身份联邦','委托临时安全凭证','访问密钥(AK/SK)管理','账号密码策略与审计','组织与项目多层级隔离','API权限精细化管控'], scenarios:['企业员工云资源权限管控','SSO统一登录华为云控制台','多租户SaaS权限隔离','等保合规身份审计','外部合作伙伴临时授权','DevOps自动化凭证管理'] , advantages:['细粒度权限：支持资源级操作级精确控制','安全合规：MFA+SSO+审计日志满足等保要求','统一治理：一套IAM覆盖所有华为云服务','灵活集成：支持LDAP/AD/OIDC多种身份源'], highlights:['支持25000+IAM策略数','MFA支持TOTP/U2F硬件密钥','审计日志保留最长7年']},
        { id:'dew', name:'DEW 密钥管理', nameEn:'Data Encryption Workshop', category:'security', desc:'DEW是华为云提供的专业密钥管理服务(KMS)，支持密钥的全生命周期管理和硬件安全模块(HSM)保护。提供数据加密、签名验签、密钥轮换等密码学能力，帮助用户轻松满足等保/GDPR/PCI-DSS等合规场景的数据加密需求。', capabilities:['HSM硬件安全模块保护','对称/非对称密钥管理','密钥自动轮换策略','信封加密(Envelope)','数据加密SDK/API','数字签名与验签','凭据管理(数据库密码等)','跨区域密钥复制','密钥使用审计日志','BYOK自带密钥导入'], scenarios:['数据库TDE透明加密','对象存储(OBS)服务端加密','磁盘(EVS)数据加密','API通信TLS证书管理','支付系统PIN码保护',' GDPR个人数据脱敏'] , advantages:['合规认证：通过FIPS 140-2 Level3和国密认证','硬件级安全：专用HSM集群，密钥永不离明文','简单易用：一行代码完成加解密，零密码学门槛','全面覆盖：支持对称/非对称/信封/签名全场景'], highlights:['HSM通过FIPS 140-2 L3认证','支持国密SM2/SM3/SM4算法','密钥可用性99.99%']},
        // 数据库/数据（补充）
        { id:'das', name:'DAS 数据管理服务', nameEn:'Data Admin Service', category:'database', desc:'DAS是面向数据库的一站式管理运维平台，提供实例管理、SQL窗口、慢SQL分析、性能诊断、容量预估、SQL审核等功能。支持MySQL/PostgreSQL/SQL Server/GaussDB等多引擎，DBA可通过Web控制台完成日常运维工作，显著提升数据库管理效率。', capabilities:['多引擎统一管理(MySQL/PG/SQLServer/GaussDB)','实时性能监控与诊断','慢SQL分析与优化建议','SQL智能审核与规约','在线DDL变更(无锁结构变更)','实例会话管理(Kill/锁等待)','容量预估与扩容建议','备份恢复管理','参数对比与调优','权限与账号管理'], scenarios:['DBA日常运维工作台','SQL开发与审核流程','数据库性能问题排查','数据库容量规划','多实例统一监控大盘','开发测试环境自助查询'] , advantages:['免安装：纯Web控制台，无需安装客户端','智能诊断：AI驱动的根因分析和优化建议','安全可控：SQL审核+权限审批防误操作','多引擎统一：一个平台管所有数据库类型'], highlights:['支持1000+实例纳管','SQL审核规则200+条','慢SQL分析精度达语句级']},
        { id:'cloudtable', name:'CloudTable 表格存储', nameEn:'CloudTable', category:'database', desc:'CloudTable是基于Apache HBase/OpenTSDB等开源生态构建的分布式NoSQL数据库服务，提供海量结构化/半结构化数据的存储与查询能力。支持PB级数据规模、毫秒级延迟和自动水平扩展，适用于时序数据、日志、社交图谱、推荐画像等大数据场景。', capabilities:['HBase兼容宽表模型','OpenTSDB时序数据模型','PB级数据自动水平扩展','毫秒级读写延迟','多版本与TTL自动过期','冷热数据分层存储','二级索引加速查询','RegionServer自动均衡','快照备份与跨AZ容灾','REST API与多语言SDK'], scenarios:['IoT设备时序数据存储','用户行为轨迹与画像','社交网络关系图谱','监控指标与时序数据','电商商品属性宽表','日志与点击流存储'] , advantages:['极致扩展：存算分离架构，存储计算独立线性扩展','超低延迟：分布式索引优化，P99<5ms','开源兼容：100%兼容HBase/OpenTSDB生态，零迁移成本','成本低廉：Serverless计费，按实际读写量付费'], highlights:['单表支持万亿行数据','写入TPS达百万级','与DLI/MRS/HDFS无缝互通']},
        { id:'roma', name:'ROMA 应用与数据集成', nameEn:'ROMA Connect', category:'enterprise', desc:'ROMA Connect是华为云的企业级应用与数据集成平台，提供API编排、数据集成、消息集成和能力开放等核心能力。支持300+预置连接器（ERP/CRM/数据库/消息队列/SaaS），帮助企业打通IT系统孤岛，实现数据自由流动和资产复用。', capabilities:['API全生命周期管理','数据集成(实时/批量/增量)','消息队列集成(MQTT/Kafka/RabbitMQ)','300+预置连接器适配器','低代码/零代码集成编排','数据转换与映射(ETL)','API安全与流量控制','API资产市场与能力开放','定时调度与事件触发','多租户与权限隔离'], scenarios:['ERP/CRM/OA系统间数据同步','遗留系统API化改造','SaaS应用与企业系统集成','数据湖入湖管道搭建','开放银行/开放政府API平台','供应链上下游数据协同'] , advantages:['广泛连接：300+连接器覆盖主流企业软件','低代码拖拽：业务人员也能完成集成编排','企业级可靠：断点续传、异常重试、数据一致性保障','资产沉淀：API资产化管理，一次开发多次复用'], highlights:['支持300+异构系统连接器','数据集成吞吐量达GB/s级','API调用SLA 99.95%']},
        { id:'dataarts', name:'DataArts 数据治理', nameEn:'DataArts Studio', category:'ai', desc:'DataArts Studio是华为云的一站式数据治理中心，涵盖数据开发、数据质量、数据目录、数据安全和数据服务等全链路能力。提供可视化的数据建模、ETL编排、元数据管理和数据血缘追踪，帮助企业构建可信赖的企业级数据中台。', capabilities:['数据建模(维度/事实/汇总)','可视化ETL编排(DAG)','数据质量规则与检核','元数据管理与数据目录','数据血缘自动追踪','数据安全分级分类','数据服务API自动生成','数据标准管理','工作空间多租户隔离','与DWS/DLI/GaussDB深度集成'], scenarios:['企业数据中台建设','数据仓库建模与ETL开发','数据质量治理专项','元数据资产管理','数据资产目录与地图','监管报送数据治理'] , advantages:['一站式：从建模→开发→质量→服务全链路闭环','智能化：AI辅助数据标准推荐和质量规则生成','企业级：支持PB级数据处理和多租户隔离','开放性：与Hadoop/Spark/Flink等开源生态兼容'], highlights:['支持10000+任务并发调度','数据血缘自动追踪全链路','数据质量规则200+内置模板']},
        // 运维/可观测性
        { id:'ces', name:'CES 云监控', nameEn:'Cloud Eye Service', category:'enterprise', desc:'CES是华为云统一的资源监控与告警服务，提供对云服务器、数据库、网络、存储等40+种云资源的实时监控能力。支持自定义Dashboard、阈值告警、通知推送和API导出，帮助企业掌握云资源运行状态，及时发现和处理异常。', capabilities:['40+云产品监控指标采集','自定义监控Dashboard','阈值/趋势/事件多类告警','邮件/短信/HTTP多渠道通知','Agentless无侵入采集','自定义上报指标(PutMetric)','告警抑制与静默规则','历史数据存储与趋势分析','API全量数据导出','与SMN/LTS联动'], scenarios:['云资源运行状态大盘','业务系统性能基线监控','容量规划与趋势预测','告警通知与值班响应','SLA达标率统计','成本与用量关联分析'] , advantages:['全面覆盖：40+云产品开箱即用，无需额外部署','灵活告警：多级别告警+抑制+升级策略，避免告警风暴','可视化：拖拽式Dashboard，分钟级搭建监控大屏','开放集成：API完整开放，可与自有监控系统对接'], highlights:['指标采集频率最短1秒','告警响应时间<1分钟','支持15天免费数据存储']},
        { id:'lts', name:'LTS 日志服务', nameEn:'Log Tank Service', category:'enterprise', desc:'LTS是华为云提供的日志采集、存储、检索和分析服务。支持ICAgent主机采集、云服务日志接入和API直传三种方式，提供全文检索、SQL分析、可视化图表和告警规则等功能，帮助企业实现日志数据的统一管理和价值挖掘。', capabilities:['ICAgent主机日志采集','云服务日志一键接入','API/SDK直传日志','全文检索与SQL分析','日志结构化提取','可视化仪表盘与图表','日志转储至OBS长期保存','日志告警规则','多租户日志隔离','与CES/SMN联动'], scenarios:['应用日志集中管理与分析','访问日志与安全审计','错误日志定位与排查','业务日志统计分析','合规日志长期留存(等保)','容器日志采集(Fluentd/Fluent Bit)'] , advantages:['一站式：采集→存储→检索→分析→告警全流程','高性能：亿级日志秒级检索，SQL分析毫秒返回','低成本：冷热分层存储，较自建ELK降低50%成本','易集成：支持主流日志框架(Log4j/Logback/Nginx)开箱即用'], highlights:['单日志流支持日增10TB','检索响应时间<1秒','支持ICAgent自动升级']},
        { id:'smn', name:'SMN 消息通知', nameEn:'Simple Message Notification', category:'enterprise', desc:'SMN是华为云的消息通知服务，提供可靠的消息传递能力，支持短信、邮件、HTTP/HTTPS、FunctionGraph等多种消息推送渠道。可作为云服务的告警通知通道，也可作为业务系统的消息中间件，支撑告警通知、营销触达、状态同步等场景。', capabilities:['短信通知(国内/国际)','邮件通知(HTML/文本)','HTTP/HTTPS Webhook回调','FunctionGraph函数触发','消息主题(Topic)订阅发布','消息模板与变量替换','消息队列死信处理','发送记录与统计','跨区域消息可达','与CES/CloudTrigger联动'], scenarios:['云资源告警短信/邮件通知','业务系统异常告警触达','用户营销短信/邮件推送','CI/CD流水线状态通知','IoT设备告警上行通知','异步任务完成回调'] , advantages:['多渠道：短信/邮件/HTTP/函数多路并行触达','高可靠：消息持久化和重试机制，到达率99.9%','简单易用：Topic订阅模型，一行代码发消息','成本透明：按量计费，无最低消费'], highlights:['短信到达率99.9%+','支持国际短信发送','消息模板支持变量占位']}
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
        // 网络（补充）
        ,{s:'nat',t:'vpc'}, {s:'nat',t:'eip'}, {s:'vpc',t:'nat'}
        ,{s:'vpn',t:'vpc'}, {s:'vpc',t:'vpn'}
        // 计算/PaaS（补充）
        ,{s:'swr',t:'cce'}, {s:'swr',t:'cci'}, {s:'cce',t:'swr'}
        ,{s:'apig',t:'ecs'}, {s:'apig',t:'cce'}, {s:'ecs',t:'apig'}
        ,{s:'cse',t:'cce'}, {s:'cce',t:'cse'}
        ,{s:'s2',t:'cce'}, {s:'s2',t:'codehub'}, {s:'codehub',t:'s2'}
        // 安全（补充）
        ,{s:'iam',t:'hss'}, {s:'iam',t:'waf'}, {s:'hss',t:'iam'}
        ,{s:'dew',t:'obs'}, {s:'dew',t:'rds'}, {s:'obs',t:'dew'}
        // 数据库/数据（补充）
        ,{s:'das',t:'rds'}, {s:'das',t:'gaussdb'}, {s:'rds',t:'das'}
        ,{s:'cloudtable',t:'dws'}, {s:'cloudtable',t:'mrs'}, {s:'dws',t:'cloudtable'}
        ,{s:'roma',t:'rds'}, {s:'roma',t:'obs'}, {s:'obs',t:'roma'}
        ,{s:'dataarts',t:'dws'}, {s:'dataarts',t:'obs'}, {s:'obs',t:'dataarts'}
        // 运维/可观测性
        ,{s:'ces',t:'ecs'}, {s:'ces',t:'rds'}, {s:'ecs',t:'ces'}
        ,{s:'lts',t:'ecs'}, {s:'lts',t:'cce'}, {s:'ecs',t:'lts'}
        ,{s:'smn',t:'ces'}, {s:'smn',t:'hss'}, {s:'ces',t:'smn'}
    ],

    init() {
        try {
            // 确保 state 已初始化（防御性守卫）
            if (!this.state) { this.state = { selectedNode: null, activeFilter: 'all', searchQuery: '', highlightedProducts: [], coreProducts: [], nodes: {}, nodeElements: {}, groupElements: {} }; }
            this._buildIndex();
            this._renderGrid();
            this._renderStats();
            this._bindEvents();
            this._initHotProducts(); // 初始化右侧面板热门产品
            this._ensurePriceMap();  // 预热产品→参考价 lookup（异步，命中后产品介绍展示价格）
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
                node.addEventListener('mouseenter', function() { self._onNodeHover(product); });
                node.addEventListener('mouseleave', function() { self._onNodeLeave(); });
                gridEl.appendChild(node);
                self.state.nodeElements[product.id] = node;
            });
        });
    },

    _renderStats() {
        if (!this.productTree) return;
        var productsCount = this.productTree.length;
        var categoriesCount = (this.categoryOrder || []).length;
        var linksCount = (this.links || []).length;
        var map = {
            'pg-stat-products': productsCount,
            'pg-stat-categories': categoriesCount,
            'pg-stat-links': linksCount,
            'pg-nav-products': productsCount,
            'pg-nav-categories': categoriesCount
        };
        Object.keys(map).forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.textContent = map[id];
        });
    },

    _onNodeClick(product) {
        if (!product || !this.state) return;
        document.querySelectorAll('.product-node.selected').forEach(function(n) { n.classList.remove('selected'); });
        var el = this.state.nodeElements[product.id];
        if (el) el.classList.add('selected');
        this.state.selectedNode = product.id;
        // 同时更新右侧面板 + 弹窗
        this._showPanelDetail(product);
        this._showDetail(product);
    },

    /* ---- 悬停预览（态2） ---- */
    _onNodeHover(product) {
        if (!product || !this.state || this.state.selectedNode === product.id) return; // 已选中不覆盖
        var panel = document.getElementById('panel-hover-state');
        var card = document.getElementById('hover-preview-card');
        if (!panel || !card) return;

        var cat = this.categories[product.category] || {};
        var caps = (product.capabilities || []).slice(0, 4);
        var catColorMap = {
            compute: '#D97706', network: '#2563EB', storage: '#059669',
            database: '#7C3AED', ai: '#DB2777', iot: '#0D9488',
            security: '#DC2626', media: '#4F46E5', enterprise: '#4B5563'
        };
        var catColor = catColorMap[product.category] || '#666';

        var catLabel = (typeof cat === 'object' ? (cat.label || product.category) : String(cat));
        var capTags = caps.map(function(c) {
            return '<span class="pv-tag pv-cap">' + c + '</span>';
        }).join('');

        card.setAttribute('data-pv-cat', product.category);
        card.innerHTML =
            '<div class="pv-category-row"><span class="pv-cat-badge">' + catLabel + '</span></div>' +
            '<h4 class="pv-name">' + product.name + '</h4>' +
            '<div class="pv-name-en">' + (product.nameEn || '') + '</div>' +
            (product.desc ? '<div class="pv-desc">' + product.desc + '</div>' : '') +
            (caps.length > 0 ?
                '<div><div class="pv-section-title" style="color:' + catColor + ';">核心能力</div>' +
                '<div class="pv-tag-list">' + capTags + '</div></div>' : '') +
            '<div class="pv-hint"><svg class="icon" aria-hidden="true"><use href="#i-click"></use></svg> 点击查看完整详情</div>';

        document.getElementById('panel-default-state').style.display = 'none';
        document.getElementById('panel-selected-state').style.display = 'none';
        panel.style.display = '';
    },

    _onNodeLeave() {
        if (!this.state || !this.state.selectedNode) {
            // 没有选中任何产品 → 回到默认态
            var panel = document.getElementById('panel-hover-state');
            if (panel) panel.style.display = 'none';
            document.getElementById('panel-default-state').style.display = '';
        }
        // 有选中产品 → 保持选中态不变
    },

    /* ---- 面板选中详情（态3） ---- */
    _showPanelDetail(product) {
        if (!product) return;
        var container = document.getElementById('selected-detail-content');
        if (!container) return;

        var cat = this.categories[product.category] || {};
        var catColorMap = {
            compute: '#D97706', network: '#2563EB', storage: '#059669',
            database: '#7C3AED', ai: '#DB2777', iot: '#0D9488',
            security: '#DC2626', media: '#4F46E5', enterprise: '#4B5563'
        };
        var catColor = catColorMap[product.category] || '#666';

        var catLabel = (typeof cat === 'object' ? (cat.label || product.category) : String(cat));

        var caps = (product.capabilities || []).slice(0, 6);
        var sces = (product.scenarios || []).slice(0, 5);
        var advs = (product.advantages || []).slice(0, 4);
        var hlts = (product.highlights || []).slice(0, 4);

        var capHtml = caps.map(function(c){return '<span class="sd-chip sd-cap">'+c+'</span>';}).join('');
        var sceHtml = sces.map(function(s){return '<span class="sd-chip sd-sce">'+s+'</span>';}).join('');
        var advHtml = advs.map(function(a){return '<li>'+a+'</li>';}).join('');
        var hltHtml = hlts.map(function(h){return '<span class="sd-chip sd-hlt">'+h+'</span>';}).join('');

        var self = this;
        var relIds = this._getRelatedProducts(product.id);
        var relNames = [];
        relIds.forEach(function(rId){
            var rn = self.state.nodes[rId];
            if (rn) relNames.push(rn.name);
        });

        container.parentElement.setAttribute('data-sd-cat', product.category);
        container.innerHTML =
            '<div class="sd-header">'+
                '<span class="sd-cat-pill">'+catLabel+'</span>'+
                '<h4>'+product.name+'</h4>'+
                '<div class="sd-name-en">'+(product.nameEn||'')+'</div>'+
            '</div>'+
            (product.desc ?
                '<div class="sd-section"><div class="sd-section-title" style="color:#555D6A">简介</div>'+
                '<div style="font-size:0.82rem;line-height:1.65;color:var(--text-primary);padding:10px 12px;background:linear-gradient(135deg,#FAFAF7,#F7F5F1);border-radius:9px;border:1px solid rgba(0,0,0,0.04);">'+product.desc+'</div></div>'
                : '')+
            (caps.length > 0 ?
                '<div class="sd-section"><div class="sd-section-title" style="color:'+catColor+'">核心能力</div>'+
                '<div class="sd-chip-list">'+capHtml+'</div></div>' : '')+
            (sces.length > 0 ?
                '<div class="sd-section"><div class="sd-section-title" style="color:#0876A6">典型场景</div>'+
                '<div class="sd-chip-list">'+sceHtml+'</div></div>' : '')+
            (advs.length > 0 ?
                '<div class="sd-section"><div class="sd-section-title" style="color:#05854B">产品优势</div>'+
                '<ul class="sd-adv-list">'+advHtml+'</ul></div>' : '')+
            (hlts.length > 0 ?
                '<div class="sd-section"><div class="sd-section-title" style="color:#9333EA">技术亮点</div>'+
                '<div class="sd-chip-list">'+hltHtml+'</div></div>' : '')+
            (relNames.length > 0 ?
                '<div class="sd-section"><div class="sd-section-title" style="color:var(--text-secondary)">关联产品</div>'+
                '<div class="sd-chip-list" style="flex-wrap:wrap;gap:5px">'+relNames.map(function(n){return '<span class="sd-chip" style="background:rgba(199,0,11,0.07);color:#C7000B;font-size:0.72rem;padding:4px 9px;border-radius:7px">'+n+'</span>';}).join('')+'</div></div>' : '')+
            '<div class="sd-action-bar">'+
                '<button class="sd-btn sd-btn-primary" onclick="ProductGraph._openFullDetail(\''+product.id+'\')">完整详情</button>'+
                '<button class="sd-btn sd-btn-outline" onclick="ProductGraph._resetPanel()">关闭面板</button>'+
            '</div>';

        // 切换三态：隐藏默认和预览，显示选中
        document.getElementById('panel-default-state').style.display = 'none';
        document.getElementById('panel-hover-state').style.display = 'none';
        document.getElementById('panel-selected-state').style.display = '';
        this._attachPanelPrice(product); // 异步追加参考价格区块
    },

    /* 打开完整详情弹窗（从面板按钮触发） */
    _openFullDetail(productId) {
        var p = this.state.nodes[productId];
        if (p) this._showDetail(p);
    },

    /* ---- 热门产品初始化 ---- */
    _initHotProducts() {
        var hotIds = ['ecs','obs','rds','modelarts','waf','iotda','cce','gaussdb'];
        var self = this;
        var listEl = document.getElementById('panel-hot-products');
        if (!listEl) return;
        var html = '';
        hotIds.forEach(function(id) {
            var p = self.state.nodes[id];
            if (p) {
                html += '<button class="panel-hot-item" data-pid="'+id+'" title="查看 '+p.name+' 详情">'+p.name+'</button>';
            }
        });
        listEl.innerHTML = html;
        // 绑定点击事件
        listEl.querySelectorAll('.panel-hot-item').forEach(function(btn){
            btn.addEventListener('click', function(){
                var pid = btn.getAttribute('data-pid');
                var prod = self.state.nodes[pid];
                if (prod) self._onNodeClick(prod);
            });
        });
    },

    /* 重置面板到默认态 */
    _resetPanel() {
        if (!this.state) return;
        this.state.selectedNode = null;
        document.querySelectorAll('.product-node.selected').forEach(function(n) { n.classList.remove('selected'); });
        document.getElementById('panel-default-state').style.display = '';
        document.getElementById('panel-hover-state').style.display = 'none';
        document.getElementById('panel-selected-state').style.display = 'none';
        var overlay = document.getElementById('product-modal-overlay');
        if (overlay) { overlay.style.display = 'none'; document.body.style.overflow = ''; }
    },

    _showDetail(product) {
        if (!product || !this.state) return;
        var cat = this.categories[product.category] || {};
        var caps = product.capabilities || [];
        var sces = product.scenarios || [];
        var advs = product.advantages || [];
        var hlts = product.highlights || [];
        var capHtml = caps.map(function(c){return '<li>'+c+'</li>';}).join('');
        var sceHtml = sces.map(function(s){return '<li>'+s+'</li>';}).join('');
        var advHtml = advs.map(function(a){return '<li>'+a+'</li>';}).join('');
        var hltHtml = hlts.map(function(h){return '<li>'+h+'</li>';}).join('');
        var self = this;
        var relIds = this._getRelatedProducts(product.id);
        var relHtml = relIds.map(function(rId){var rn=self.state.nodes[rId];return '<li onclick="ProductGraph._jumpToNode(\''+rId+'\')">'+(rn?rn.name:rId)+'</li>';}).join('');
        
        // v3 premium modal: section classes for chip/card styling
        var html =
            '<div class="product-detail-header">'+
                '<span class="detail-category-badge">'+(cat.label||cat)+'</span>'+
                '<div class="detail-header-titles"><h3>'+product.name+'</h3><div class="detail-name-en">'+product.nameEn+'</div></div>'+
            '</div><div class="product-detail-body">'+
            // 简介：暖灰卡片
            '<div class="detail-section section-intro"><div class="detail-section-title title-intro">简介</div>'+
            '<div class="detail-section-content">'+product.desc+'</div></div>'+
            // 核心能力：红色 chip
            '<div class="detail-section detail-capability"><div class="detail-section-title title-capability">核心能力</div>'+
            '<ul class="detail-chip-list">'+capHtml+'</ul></div>'+
            // 典型场景：蓝色 chip
            '<div class="detail-section detail-scenario"><div class="detail-section-title title-scenario">典型场景</div>'+
            '<ul class="detail-chip-list">'+sceHtml+'</ul></div>'+
            // 产品优势：绿色卡片行
            (advHtml?'<div class="detail-section detail-advantage"><div class="detail-section-title title-advantage">产品优势</div>'+
            '<ul class="detail-advantage-list">'+advHtml+'</ul></div>':'')+
            // 技术亮点：紫色 chip
            (hltHtml?'<div class="detail-section detail-highlight"><div class="detail-section-title title-highlight">技术亮点</div>'+
            '<ul class="detail-chip-list">'+hltHtml+'</ul></div>':'')+
            // 关联产品：品牌红 pill
            '<div class="detail-section detail-related"><div class="detail-section-title">关联产品</div>'+
            '<ul class="detail-related-list" id="detail-related-products">'+relHtml+'</ul></div>'+
            '</div>';
        
        // 弹窗展示
        var modalBody = document.getElementById('product-modal-body');
        var overlay = document.getElementById('product-modal-overlay');
        if (modalBody && overlay) {
            modalBody.innerHTML = html;
            overlay.style.display = 'flex';
            document.body.style.overflow = 'hidden';
            self._attachPrice(product); // 异步追加参考价格区块
        }
    },

    /* ---- 参考价格联动：产品介绍 = 成本参考价目表里「有价格」的产品 ---- */
    _ensurePriceMap() {
        if (this._priceMapPromise) return this._priceMapPromise;
        var self = this;
        this._priceMapPromise = fetch(Config.API_BASE_URL + '/pricing/products')
            .then(function(r){ return r.ok ? r.json() : null; })
            .then(function(d){
                if (!d || !d.items) { self._priceMap = {}; self._priceMeta = {}; return self._priceMap; }
                var map = {};
                d.items.forEach(function(it){
                    var name = it.product || '';
                    if (!name) return;
                    var toks = name.split(/\s+/);
                    var keys = [];
                    if (toks[0]) keys.push(toks[0].toLowerCase());
                    // 末位英文 token 也作 key（处理「视频直播 Live」这类中英倒置）
                    if (toks.length > 1 && /^[A-Za-z0-9]+$/.test(toks[toks.length - 1])) keys.push(toks[toks.length - 1].toLowerCase());
                    keys.push(name.toLowerCase());
                    keys.forEach(function(k){ if (!map[k]) map[k] = it; });
                });
                self._priceMap = map;
                self._priceMeta = {
                    region: d.region || '',
                    annual_discount: (typeof d.annual_discount === 'number' && d.annual_discount > 0) ? d.annual_discount : 0.85
                };
                return map;
            })
            .catch(function(){ self._priceMap = {}; self._priceMeta = {}; return self._priceMap; });
        return this._priceMapPromise;
    },

    _priceFor(product) {
        var map = this._priceMap;
        if (!map || !product) return null;
        var cand = [];
        if (product.id) cand.push(String(product.id).toLowerCase());
        var toks = (product.name || '').split(/\s+/);
        if (toks[0]) cand.push(toks[0].toLowerCase());
        cand.push((product.name || '').toLowerCase());
        for (var i = 0; i < cand.length; i++) { if (map[cand[i]]) return map[cand[i]]; }
        return null;
    },

    _priceSectionHtml(item) {
        var meta = this._priceMeta || {};
        // 安全引用：优先 window._crEsc/_crMoney，兜底内联实现
        var _esc = (window._crEsc || function(s){ return String(s==null?'':s).replace(/[&<>"']/g,function(c){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":"&#39;"})[c];}); });
        var _money = (window._crMoney || function(n){ return Math.round((Number(n)||0)*100)/100; });
        if (item.business_only) {
            return '<div class="pp-price"><div class="pp-price-title">参考价格</div>' +
                '<div class="pp-price-body"><div class="pp-price-note pp-biz">商务定价：' + _esc(item.note || '请咨询华为云销售') + '</div></div></div>';
        }
        if (item.free) {
            return '<div class="pp-price"><div class="pp-price-title">参考价格</div>' +
                '<div class="pp-price-body"><div class="pp-price-note pp-free">基础功能免费：' + _esc(item.note || '按实际创建的资源计费') + '</div></div></div>';
        }
        if (item.no_price) {
            return '<div class="pp-price"><div class="pp-price-title">参考价格</div>' +
                '<div class="pp-price-body"><div class="pp-price-note pp-noprice">参考价待补充：' + _esc(item.note || '') + '</div></div></div>';
        }
        var unit = item.unit_label || '元/月';
        var rp = _money(item.ref_price || 0);
        var warn = (item.verified === false) ? ' <span class="pp-warn" title="待官网复核">⚠</span>' : '';
        var tierHtml = '';
        if (item.tier) {
            var lo = item.tier.low ? _money(item.tier.low.unit_price || 0) : '—';
            var mid = item.tier.mid ? _money(item.tier.mid.unit_price || 0) : '—';
            var hi = item.tier.high ? _money(item.tier.high.unit_price || 0) : '—';
            tierHtml = '<div class="pp-tiers">低 <b>¥' + lo + '</b> · 中 <b>¥' + mid + '</b> · 高 <b>¥' + hi + '</b> <span class="pp-unit">(' + _esc(unit) + ')</span></div>';
        }
        var noteHtml = item.note ? '<div class="pp-price-note">' + _esc(item.note) + '</div>' : '';
        var srcHtml = item.source_url ? '<a class="pp-price-src" href="' + _esc(item.source_url) + '" target="_blank" rel="noopener">正式下单，待官网核查 ↗</a>' : '';
        var metaHtml = (meta.region || meta.annual_discount) ? '<div class="pp-price-meta">地区 ' + _esc(meta.region || '—') + ' · 年付 ≈ 月×12×' + (meta.annual_discount || 0.85) + '</div>' : '';
        return '<div class="pp-price"><div class="pp-price-title">参考价格</div>' +
            '<div class="pp-price-body">' +
            '<div class="pp-row"><span>计费方式</span><b>' + _esc(item.billing || '—') + (item.unit_label ? (' · ' + _esc(item.unit_label)) : '') + '</b></div>' +
            '<div class="pp-row"><span>参考单价</span><b>¥' + rp + ' <i class="pp-unit">/' + _esc(unit) + '</i></b>' + warn + '</div>' +
            tierHtml + noteHtml + srcHtml + metaHtml +
            '</div></div>';
    },

    _attachPrice(product) {
        var self = this;
        this._ensurePriceMap().then(function(){
            var item = self._priceFor(product);
            var body = document.getElementById('product-modal-body');
            if (!body || !item) return;
            if (document.getElementById('pp-price-in-modal')) return; // 已追加
            var pd = body.querySelector('.product-detail-body');
            if (pd) pd.insertAdjacentHTML('beforeend', '<div id="pp-price-in-modal">' + self._priceSectionHtml(item) + '</div>');
        });
    },

    _attachPanelPrice(product) {
        var self = this;
        this._ensurePriceMap().then(function(){
            var item = self._priceFor(product);
            var container = document.getElementById('selected-detail-content');
            if (!container || !item) return;
            if (document.getElementById('pp-price-in-panel')) return; // 已追加
            container.insertAdjacentHTML('beforeend', '<div id="pp-price-in-panel">' + self._priceSectionHtml(item) + '</div>');
        });
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

/* ===== 3D产品架构树形图 (ArchTree3D) 已于 v20260531w 移除 ===== */

/* ===== Phase 3: 运行时图标转换助手（后端返回的符号也能转线性图标） ===== */
window.EMOJI_SVG = {
  '\u{2728}': '<svg class="icon" aria-hidden="true"><use href="#i-sparkles"></use></svg>',
  '\u{1F50D}': '<svg class="icon" aria-hidden="true"><use href="#i-search"></use></svg>',
  '\u{2694}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-swords"></use></svg>',
  '\u{1F4DA}': '<svg class="icon" aria-hidden="true"><use href="#i-book-open"></use></svg>',
  '\u{1F680}': '<svg class="icon" aria-hidden="true"><use href="#i-rocket"></use></svg>',
  '\u{1F4A1}': '<svg class="icon" aria-hidden="true"><use href="#i-lightbulb"></use></svg>',
  '\u{1F3AF}': '<svg class="icon" aria-hidden="true"><use href="#i-target"></use></svg>',
  '\u{2715}': '<svg class="icon" aria-hidden="true"><use href="#i-x"></use></svg>',
  '\u{1F3ED}': '<svg class="icon" aria-hidden="true"><use href="#i-factory"></use></svg>',
  '\u{1F33E}': '<svg class="icon" aria-hidden="true"><use href="#i-wheat"></use></svg>',
  '\u{1F3E2}': '<svg class="icon" aria-hidden="true"><use href="#i-building-2"></use></svg>',
  '\u{2601}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-cloud"></use></svg>',
  '\u{1F5FA}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-map"></use></svg>',
  '\u{1F4CA}': '<svg class="icon" aria-hidden="true"><use href="#i-bar-chart-3"></use></svg>',
  '\u{1F4CB}': '<svg class="icon" aria-hidden="true"><use href="#i-clipboard-list"></use></svg>',
  '\u{1F3C6}': '<svg class="icon" aria-hidden="true"><use href="#i-trophy"></use></svg>',
  '\u{2699}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-settings"></use></svg>',
  '\u{1F464}': '<svg class="icon" aria-hidden="true"><use href="#i-user"></use></svg>',
  '\u{1F6AA}': '<svg class="icon" aria-hidden="true"><use href="#i-log-out"></use></svg>',
  '\u{2630}': '<svg class="icon" aria-hidden="true"><use href="#i-menu"></use></svg>',
  '\u{1F310}': '<svg class="icon" aria-hidden="true"><use href="#i-globe"></use></svg>',
  '\u{26A0}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-triangle-alert"></use></svg>',
  '\u{1F9E0}': '<svg class="icon" aria-hidden="true"><use href="#i-brain"></use></svg>',
  '\u{1F4AC}': '<svg class="icon" aria-hidden="true"><use href="#i-message-circle"></use></svg>',
  '\u{1F4E5}': '<svg class="icon" aria-hidden="true"><use href="#i-download"></use></svg>',
  '\u{1F4D8}': '<svg class="icon" aria-hidden="true"><use href="#i-file-text"></use></svg>',
  '\u{2606}': '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg>',
  '\u{2197}': '<svg class="icon" aria-hidden="true"><use href="#i-arrow-up-right"></use></svg>',
  '\u{2198}': '<svg class="icon" aria-hidden="true"><use href="#i-arrow-down-right"></use></svg>',
  '\u{2190}': '<svg class="icon" aria-hidden="true"><use href="#i-arrow-left"></use></svg>',
  '\u{2192}': '<svg class="icon" aria-hidden="true"><use href="#i-arrow-right"></use></svg>',
  '\u{1F916}': '<svg class="icon" aria-hidden="true"><use href="#i-bot"></use></svg>',
  '\u{1F4E1}': '<svg class="icon" aria-hidden="true"><use href="#i-radio"></use></svg>',
  '\u{1F6E1}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-shield"></use></svg>',
  '\u{1F3AC}': '<svg class="icon" aria-hidden="true"><use href="#i-film"></use></svg>',
  '\u{1F4BC}': '<svg class="icon" aria-hidden="true"><use href="#i-briefcase"></use></svg>',
  '\u{1F512}': '<svg class="icon" aria-hidden="true"><use href="#i-lock"></use></svg>',
  '\u{1F4E7}': '<svg class="icon" aria-hidden="true"><use href="#i-mail"></use></svg>',
  '\u{26A1}': '<svg class="icon" aria-hidden="true"><use href="#i-zap"></use></svg>',
  '\u{1F3A8}': '<svg class="icon" aria-hidden="true"><use href="#i-palette"></use></svg>',
  '\u{1F949}': '<svg class="icon" aria-hidden="true"><use href="#i-medal"></use></svg>',
  '\u{1F948}': '<svg class="icon" aria-hidden="true"><use href="#i-medal"></use></svg>',
  '\u{1F947}': '<svg class="icon" aria-hidden="true"><use href="#i-medal"></use></svg>',
  '\u{1F48E}': '<svg class="icon" aria-hidden="true"><use href="#i-gem"></use></svg>',
  '\u{1F3AA}': '<svg class="icon" aria-hidden="true"><use href="#i-sparkles"></use></svg>',
  '\u{1F4C2}': '<svg class="icon" aria-hidden="true"><use href="#i-folder"></use></svg>',
  '\u{1F4C1}': '<svg class="icon" aria-hidden="true"><use href="#i-folder"></use></svg>',
  '\u{1F4BE}': '<svg class="icon" aria-hidden="true"><use href="#i-save"></use></svg>',
  '\u{1F5C4}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-database"></use></svg>',
  '\u{1F446}': '<svg class="icon" aria-hidden="true"><use href="#i-hand"></use></svg>',
  '\u{1F4C4}': '<svg class="icon" aria-hidden="true"><use href="#i-file"></use></svg>',
  '\u{1F504}': '<svg class="icon" aria-hidden="true"><use href="#i-refresh-cw"></use></svg>',
  '\u{1F5D1}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-trash-2"></use></svg>',
  '\u{23F3}': '<svg class="icon" aria-hidden="true"><use href="#i-loader"></use></svg>',
  '\u{2696}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-scale"></use></svg>',
  '\u{2B50}': '<svg class="icon" aria-hidden="true"><use href="#i-star"></use></svg>',
  '\u{1F4B0}': '<svg class="icon" aria-hidden="true"><use href="#i-banknote"></use></svg>',
  '\u{1F697}': '<svg class="icon" aria-hidden="true"><use href="#i-car"></use></svg>',
  '\u{1F3D9}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-building-2"></use></svg>',
  '\u{1F3E5}': '<svg class="icon" aria-hidden="true"><use href="#i-stethoscope"></use></svg>',
  '\u{1F3AD}': '<svg class="icon" aria-hidden="true"><use href="#i-landmark"></use></svg>',
  '\u{1F4CC}': '<svg class="icon" aria-hidden="true"><use href="#i-pin"></use></svg>',
  '\u{1F321}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-thermometer"></use></svg>',
  '\u{1F4C8}': '<svg class="icon" aria-hidden="true"><use href="#i-trending-up"></use></svg>',
  '\u{1F389}': '<svg class="icon" aria-hidden="true"><use href="#i-party-popper"></use></svg>',
  '\u{1F527}': '<svg class="icon" aria-hidden="true"><use href="#i-wrench"></use></svg>',
  '\u{1F4AD}': '<svg class="icon" aria-hidden="true"><use href="#i-message-circle"></use></svg>',
  '\u{1F3D7}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-building-2"></use></svg>',
  '\u{270F}\u{FE0F}': '<svg class="icon" aria-hidden="true"><use href="#i-pencil"></use></svg>',
  '\u{2705}': '<svg class="icon" aria-hidden="true"><use href="#i-circle-check"></use></svg>',
  '\u{2713}': '<svg class="icon" aria-hidden="true"><use href="#i-check"></use></svg>',
  '\u{1F534}': '<span class="cat-dot huawei"></span>',
  '\u{1F535}': '<span class="cat-dot competitor"></span>',
};
window.emojiToSvg = function(e, fb) {
  if (!e) return fb ? window.EMOJI_SVG[fb] || '' : '';
  return window.EMOJI_SVG[e] || (fb ? (window.EMOJI_SVG[fb] || e) : e);
};
