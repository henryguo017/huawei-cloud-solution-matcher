
// ==================== 欢迎引导页和快速体验 Demo 功能 ====================

// Demo 案例数据
const DemoCases = {
    manufacturing: {
        title: '制造业预测性维护',
        demand: '我们是一家中型制造企业，有50台生产设备，经常因为设备突发故障导致生产线停工，每次停工损失约5万元。我们希望能够实现设备的预测性维护，提前发现故障隐患，减少停机时间，降低维护成本。'
    },
    agriculture: {
        title: '智慧农业植物方舱',
        demand: '我们是农业科技公司，想建设智慧植物方舱，通过传感器监测温湿度、光照、CO2等环境参数，实现自动化管理，构建植物生长模型，提高产量30%以上，降低人工成本50%以上。'
    },
    park: {
        title: '智慧园区管理',
        demand: '我们有一个大型产业园区，希望实现园区智能化管理，包括安防监控、能源管理、停车管理、访客管理等，提升园区运营效率，降低管理成本，为入驻企业提供更好的服务体验。'
    }
};

// 欢迎页状态管理
const WelcomeState = {
    hasSeenWelcome: false,
    
    init() {
        // 使用 sessionStorage 实现会话级别的记忆
        // 每次新会话（打开新窗口/标签页）都会重新显示
        const stored = sessionStorage.getItem('huawei-cloud-welcome-seen');
        this.hasSeenWelcome = stored === 'true';
        return this.hasSeenWelcome;
    },
    
    setSeen() {
        this.hasSeenWelcome = true;
        // 只在当前会话有效，关闭浏览器后失效
        sessionStorage.setItem('huawei-cloud-welcome-seen', 'true');
    },
    
    reset() {
        this.hasSeenWelcome = false;
        sessionStorage.removeItem('huawei-cloud-welcome-seen');
    }
};

// 欢迎页管理器
const WelcomeManager = {
    welcomePage: null,
    statNumbers: [],
    
    // 从后端 API 获取真实知识库统计数据
    async fetchRealStats() {
        try {
            const resp = await fetch(`${Config.API_BASE_URL}/knowledge/stats`);
            if (!resp.ok) throw new Error('stats api failed');
            const stats = await resp.json();
            return {
                accuracy: stats.accuracy || 85,
                // 效率提升固定展示 95（产品价值主张，不随知识库变化）
                efficiency: 95,
                industries: (stats.supported_industries || []).length || 0
            };
        } catch (e) {
            // API 不可达时降级为与知识库规模相符的保守值
            console.warn('无法获取知识库统计，使用默认值', e);
            return { accuracy: 85, efficiency: 95, industries: 7 };
        }
    },

    init() {
        this.welcomePage = document.getElementById('welcome-page');
        
        if (!this.welcomePage) {
            return;
        }
        
        const startBtn = document.getElementById('start-experience-btn');
        const skipBtn = document.getElementById('skip-welcome-btn');
        
        if (!startBtn && !skipBtn) {
            this.hide();
            return;
        }
        
        if (!WelcomeState.init()) {
            this.show();
        } else {
            this.hide();
        }
        
        this.bindEvents();
    },
    
    show() {
        if (this.welcomePage) {
            this.welcomePage.classList.remove('hidden');
            this.welcomePage.style.display = 'flex';
            this.welcomePage.style.zIndex = '9999';
            this.welcomePage.style.pointerEvents = 'auto';
            this.startAnimations();
            this.initParticleCanvas();
        }
    },
    
    hide() {
        if (this.welcomePage) {
            this.welcomePage.classList.add('hidden');
            this.welcomePage.style.display = 'none';
            this.welcomePage.style.zIndex = '-1';
            this.welcomePage.style.pointerEvents = 'none';
        }
    },
    
    bindEvents() {
        const startBtn = document.getElementById('start-experience-btn');
        const skipBtn = document.getElementById('skip-welcome-btn');
        const skipCheckbox = document.getElementById('skip-permanently-checkbox');
        
        startBtn?.addEventListener('click', () => {
            // 点击"立即体验"时，检查复选框
            if (skipCheckbox?.checked) {
                WelcomeState.setSeen();
            }
            this.hide();
            DemoManager.showSelector();
        });
        
        skipBtn?.addEventListener('click', () => {
            // 点击"跳过引导"时，检查复选框
            if (skipCheckbox?.checked) {
                WelcomeState.setSeen();
            }
            this.hide();
        });
    },
    
    async startAnimations() {
        // 先获取真实数据，再做动画，避免展示硬编码假数字
        const stats = await this.fetchRealStats();

        // 根据 stat-label 内容匹配对应真实值
        const statBoxes = document.querySelectorAll('.welcome-stats .stat-box');
        statBoxes.forEach(box => {
            const label = box.querySelector('.stat-label')?.textContent?.trim() || '';
            const numEl = box.querySelector('.stat-number[data-target]');
            if (!numEl) return;

            let realTarget = parseInt(numEl.dataset.target); // 兜底保留原值
            if (label.includes('准确率')) {
                realTarget = stats.accuracy;
            } else if (label.includes('效率')) {
                realTarget = stats.efficiency;
            } else if (label.includes('行业')) {
                realTarget = stats.industries;
            }

            // 同步更新 data-target 属性，使数值与知识库一致
            numEl.dataset.target = realTarget;
        });

        setTimeout(() => {
            const numbers = document.querySelectorAll('.stat-number[data-target]');
            numbers.forEach(num => {
                const target = parseInt(num.dataset.target);
                this.animateNumber(num, 0, target, 1500);
            });
        }, 500);
    },
    
    animateNumber(element, start, end, duration) {
        const startTime = performance.now();
        
        const update = (currentTime) => {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            
            const easeOut = 1 - Math.pow(1 - progress, 3);
            const current = Math.floor(start + (end - start) * easeOut);
            
            element.textContent = current;
            
            if (progress < 1) {
                requestAnimationFrame(update);
            }
        };
        
        requestAnimationFrame(update);
    },
    
    initParticleCanvas() {
        const canvas = document.getElementById('welcome-particle-canvas');
        if (!canvas) return;
        
        const ctx = canvas.getContext('2d');
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        
        const particles = [];
        const particleCount = 50;
        
        for (let i = 0; i < particleCount; i++) {
            particles.push({
                x: Math.random() * canvas.width,
                y: Math.random() * canvas.height,
                vx: (Math.random() - 0.5) * 0.5,
                vy: (Math.random() - 0.5) * 0.5,
                radius: Math.random() * 2 + 1
            });
        }
        
        const animate = () => {
            if (this.welcomePage.classList.contains('hidden')) return;
            
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            particles.forEach(p => {
                p.x += p.vx;
                p.y += p.vy;
                
                if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
                if (p.y < 0 || p.y > canvas.height) p.vy *= -1;
                
                ctx.beginPath();
                ctx.fillStyle = 'rgba(100, 150, 255, 0.4)';
                ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                ctx.fill();
            });
            
            requestAnimationFrame(animate);
        };
        
        animate();
    }
};

// Demo 管理器
const DemoManager = {
    modal: null,
    cases: null,
    
    init() {
        this.modal = document.getElementById('demo-selector-modal');
        this.cases = document.querySelectorAll('.demo-case');
        
        this.bindEvents();
    },
    
    showSelector() {
        if (this.modal) {
            this.modal.style.display = 'flex';
        }
    },
    
    hideSelector() {
        if (this.modal) {
            this.modal.style.display = 'none';
        }
    },
    
    bindEvents() {
        const quickBtn = document.getElementById('quick-demo-btn');
        const closeBtn = document.getElementById('close-demo-modal');
        const overlay = this.modal?.querySelector('.demo-modal-overlay');
        
        quickBtn?.addEventListener('click', () => {
            this.showSelector();
        });
        
        closeBtn?.addEventListener('click', () => {
            this.hideSelector();
        });
        
        overlay?.addEventListener('click', () => {
            this.hideSelector();
        });
        
        this.cases.forEach(caseEl => {
            caseEl.addEventListener('click', () => {
                const caseType = caseEl.dataset.case;
                this.runDemo(caseType);
                this.hideSelector();
            });
        });
    },
    
    runDemo(caseType) {
        const caseData = DemoCases[caseType];
        if (!caseData) return;

        const demandInput = document.getElementById('demand-input');
        const matchBtn = document.getElementById('match-btn');

        if (!demandInput || !matchBtn) {
            UI.showToast('请先切换到解决方案匹配页面', 'warning');
            return;
        }

        UI.switchPage('solution');

        // 标记为快速体验，绕过登录检查和历史记录
        if (typeof State !== 'undefined') State.isQuickDemo = true;
        
        setTimeout(() => {
            this.fillDemand(demandInput, caseData.demand, () => {
                matchBtn.click();
                this.showNotice();
            });
        }, 300);
    },

    fillDemand(input, text, onComplete) {
        input.value = '';
        let index = 0;
        const speed = 15;

        const typeChar = () => {
            if (index < text.length) {
                input.value += text[index];
                index++;
                setTimeout(typeChar, speed);
            } else {
                if (onComplete) onComplete();
            }
        };

        typeChar();

        const charCount = document.getElementById('demand-char-count');
        if (charCount) {
            const updateCount = () => {
                charCount.textContent = input.value.length;
                if (index < text.length) {
                    setTimeout(updateCount, speed);
                }
            };
            updateCount();
        }
    },
    
    showNotice() {
        const notice = document.getElementById('demo-notice');
        if (notice) {
            notice.style.display = 'flex';
            
            setTimeout(() => {
                notice.style.display = 'none';
            }, 5000);
        }
    },
    
    hideNotice() {
        const notice = document.getElementById('demo-notice');
        if (notice) {
            notice.style.display = 'none';
        }
    }
};

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    WelcomeManager.init();
    DemoManager.init();
    
    const closeNoticeBtn = document.getElementById('close-demo-notice');
    closeNoticeBtn?.addEventListener('click', () => {
        DemoManager.hideNotice();
    });
});
