/**
 * 成就勋章 UI 模块
 */
const AchievementUI = {
    currentRarity: 'all',
    allItems: [],

    /**
     * 渲染成就图标：SVG symbol ID 直接 <use>，emoji 字符走 emojiToSvg 兜底
     */
    _renderIcon(icon, size) {
        if (icon && icon.startsWith('i-')) {
            return `<svg class="ach-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><use href="#${icon}"></use></svg>`;
        }
        return window.emojiToSvg(icon || 'i-trophy', size);
    },

    init() {
        this._bindEvents();
        this._observePage();
        // 绑定导航点击
        document.querySelectorAll('[data-page="achievement"]').forEach(btn => {
            btn.addEventListener('click', () => {
                setTimeout(() => this.load(), 200);
            });
        });
        // 页面访问成就检测（知识库/仪表盘/分享）
        this._bindPageViewAchievements();
    },

    _bindPageViewAchievements() {
        // 使用 MutationObserver 监听页面切换
        const pages = ['knowledge', 'dashboard', 'share'];
        pages.forEach(pageName => {
            const pageEl = document.getElementById(`page-${pageName}`);
            if (!pageEl) return;
            new MutationObserver((mutations) => {
                mutations.forEach(m => {
                    if (pageEl.classList.contains('active') && AuthManager.isLoggedIn()) {
                        API.checkPageView(pageName);
                    }
                });
            }).observe(pageEl, { attributes: true, attributeFilter: ['class'] });
        });
    },

    _observePage() {
        const page = document.getElementById('page-achievement');
        if (!page) return;
        const observer = new MutationObserver((mutations) => {
            mutations.forEach(m => {
                if (page.classList.contains('active')) {
                    this.load();
                }
            });
        });
        observer.observe(page, { attributes: true, attributeFilter: ['class'] });
    },

    _bindEvents() {
        // 过滤器点击
        const filterEl = document.getElementById('ach-filter');
        if (filterEl) {
            filterEl.addEventListener('click', (e) => {
                const btn = e.target.closest('.ach-filter-btn');
                if (!btn) return;
                filterEl.querySelectorAll('.ach-filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentRarity = btn.dataset.rarity;
                this._renderGrid();
            });
        }
    },

    async load() {
        if (!AuthManager.isLoggedIn()) {
            AuthManager._openModal();
            return;
        }
        const grid = document.getElementById('ach-grid');
        const fill = document.getElementById('ach-progress-fill');
        const text = document.getElementById('ach-progress-text');
        if (grid) grid.innerHTML = '<div class="kb-loading">加载中...</div>';

        try {
            const data = await API.getAchievements();
            console.log('[Achievement] API response:', data);
            this.allItems = data.items || [];
            // 更新进度条
            const pct = data.percent || 0;
            if (fill) fill.style.width = pct + '%';
            if (text) text.textContent = `${data.unlocked || 0} / ${data.total || 0}  (${pct}%)`;
            this._renderGrid();
        } catch (err) {
            console.error('[Achievement] Load failed:', err);
            if (grid) grid.innerHTML = `<div class="kb-error">加载失败: ${err.message}<br><small style="color:var(--text-muted);margin-top:4px;display:block;">请检查网络连接或刷新页面重试</small></div>`;
        }
    },

    _renderGrid() {
        const grid = document.getElementById('ach-grid');
        if (!grid) return;

        const items = this.currentRarity === 'all'
            ? this.allItems
            : this.allItems.filter(it => it.rarity === this.currentRarity);

        if (items.length === 0) {
            grid.innerHTML = '<div class="kb-empty">暂无成就</div>';
            return;
        }

        const rarityLabel = { copper: '铜', silver: '银', gold: '金', diamond: '钻', hidden: '隐藏' };

        grid.innerHTML = items.map(it => {
            const locked = !it.unlocked;
            const cls = locked ? 'achievement-card locked' : 'achievement-card unlocked';
            // 隐藏成就未解锁才显示占位符，普通成就直接显示名称
            const isHiddenLocked = !it.unlocked && it.rarity === 'hidden';
            const name = isHiddenLocked ? '???' : it.name;
            const desc = isHiddenLocked ? '解锁后可见' : it.description;
            const icon = isHiddenLocked ? this._renderIcon('i-lock', 'lock') : this._renderIcon(it.icon, 'trophy');
            const rarityCls = it.rarity || 'copper';
            const rarityText = rarityLabel[it.rarity] || it.rarity;
            const unlockedAt = it.unlocked_at ? `解锁于: ${it.unlocked_at}` : '';

            return `
                <div class="${cls}" title="${desc}\n${unlockedAt}">
                    <span class="ach-icon">${icon}</span>
                    <div class="ach-name">${name}</div>
                    <div class="ach-desc">${desc}</div>
                    <span class="ach-rarity ${rarityCls}">${rarityText}</span>
                </div>
            `;
        }).join('');
    },

    /**
     * 显示新解锁成就通知（右上角滑入，不阻挡操作）
     */
    showUnlockToast(newlyUnlocked) {
        if (!newlyUnlocked || newlyUnlocked.length === 0) return;
        newlyUnlocked.forEach((ach, idx) => {
            setTimeout(() => this._createSlideInToast(ach), idx * 600);
        });
    },

    _createSlideInToast(ach) {
        const rarityLabel = { copper:'铜', silver:'银', gold:'金', diamond:'钻', hidden:'隐藏' };
        const rarityCls = ach.rarity || 'copper';

        const toast = document.createElement('div');
        toast.className = 'achievement-toast';
        toast.innerHTML = `
            <span class="toast-icon">${this._renderIcon(ach.icon, 'trophy')}</span>
            <div class="toast-body">
                <div class="toast-title"><svg class="icon" aria-hidden="true"><use href="#i-party-popper"></use></svg> 成就解锁！</div>
                <div class="toast-name">${this._escapeHtml(ach.name || '???')}</div>
                <div class="toast-desc">${this._escapeHtml(ach.description || '')}</div>
                <span class="toast-rarity ${rarityCls}">${rarityLabel[ach.rarity] || ach.rarity}</span>
            </div>
            <button class="toast-close" title="关闭">×</button>
        `;

        document.body.appendChild(toast);

        // 点击关闭
        toast.querySelector('.toast-close').addEventListener('click', () => {
            this._dismissToast(toast);
        });

        // 点击跳转到成就页
        toast.addEventListener('click', (e) => {
            if (e.target.closest('.toast-close')) return;
            PageTransition.switchTo('achievement');
            setTimeout(() => this.load(), 300);
            this._dismissToast(toast);
        });

        // 5秒后自动消失
        setTimeout(() => this._dismissToast(toast), 5000);
    },

    _dismissToast(toast) {
        if (!toast || !toast.parentNode) return;
        toast.classList.add('toast-exit');
        setTimeout(() => { if (toast.parentNode) toast.remove(); }, 350);
    },

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
};

// 挂载到 window，确保 script.js 中的 window.AchievementUI 检查能通过
window.AchievementUI = AchievementUI;
