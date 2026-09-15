/* ============================================================================
 * 共享运行时（中性模块，非经典 / 非 Agent 任一分支的业务代码）
 * ----------------------------------------------------------------------------
 * 本模块被经典(script.js)与 Agent(agent_workspace.js)共同引用，但自身不引用
 * 任一分支的内部 DOM / 状态，不属于“串分支”。它提供两件跨分支基础设施：
 *
 *  1. Session：读取同一份登录态（localStorage 'hwcloud_auth'）。
 *     经典模式把 token 存进此键（见 script.js AuthManager.STORAGE_KEY）。
 *     Agent 模式必须读同一个键，才能保证请求带着同一 JWT、作用于同一个账号——
 *     这是“两个分支都能对用户数据产生作用”的根基。
 *
 *  2. TaskGuard：任务登记 + 切换守卫。
 *     任一分支有长任务（方案生成 / 竞争分析 / Agent 对话流式输出）在跑时，
 *     用户点胶囊切换视图会被拦截，弹出提醒“任务进行中，请稍后再切换”。
 * ==========================================================================*/
(function () {
    'use strict';

    /* ---------- 1. Session：与经典同源的登录态读取 ---------- */
    var AUTH_KEY = 'hwcloud_auth';

    var Session = {
        // 返回当前有效 JWT（过期返回 null）；Agent 请求必须带此 token
        getToken: function () {
            try {
                var raw = localStorage.getItem(AUTH_KEY);
                if (!raw) return null;
                var data = JSON.parse(raw);
                if (data && data.token && data.expiresAt && Date.now() < data.expiresAt) {
                    return data.token;
                }
                return null;
            } catch (e) {
                return null;
            }
        },
        getUser: function () {
            try {
                var raw = localStorage.getItem(AUTH_KEY);
                if (!raw) return null;
                var data = JSON.parse(raw);
                return (data && data.user) ? data.user : null;
            } catch (e) {
                return null;
            }
        }
    };

    /* ---------- 2. TaskGuard：任务登记 + 切换守卫 ---------- */
    var tasks = new Map(); // key -> { label, abort }

    var TaskGuard = {
        // 登记一个正在运行的任务；abort 为可选的中断回调（用户坚持切换时调用）
        begin: function (key, label, abort) {
            tasks.set(key, { label: label || '任务进行中', abort: abort || null });
        },
        end: function (key) {
            tasks.delete(key);
        },
        isBusy: function () {
            return tasks.size > 0;
        },
        // 当前正在跑的任务描述列表（用于提醒文案）
        list: function () {
            var arr = [];
            tasks.forEach(function (t) { arr.push(t.label); });
            return arr;
        },
        // 用户坚持要切换：中断当前所有任务（调用各自 abort）
        abortAll: function () {
            tasks.forEach(function (t) {
                if (t.abort) { try { t.abort(); } catch (e) { /* 忽略中断异常 */ } }
            });
        },
        // 切换守卫：当前有任务在跑才弹提醒；无任务直接放行。
        // 返回 Promise<boolean>：true = 允许切换，false = 留在原视图。
        confirmSwitch: function () {
            if (!TaskGuard.isBusy()) return Promise.resolve(true);

            return new Promise(function (resolve) {
                var labels = TaskGuard.list();
                var msg = labels.length === 1
                    ? ('当前有任务正在进行：' + labels[0] + '。')
                    : ('当前有多个任务正在进行：' + labels.join('、') + '。');

                var overlay = document.createElement('div');
                overlay.className = 'switch-guard-overlay';
                overlay.innerHTML =
                    '<div class="switch-guard-modal" role="alertdialog" aria-modal="true">' +
                        '<div class="switch-guard-icon">' +
                            '<svg class="icon" aria-hidden="true"><use href="#i-info"></use></svg>' +
                        '</div>' +
                        '<h3 class="switch-guard-title">任务进行中，请稍候切换</h3>' +
                        '<p class="switch-guard-text">' + msg +
                            '切换视图会中断该任务，并可能丢失已经生成的内容。建议任务完成后再切换。</p>' +
                        '<div class="switch-guard-actions">' +
                            '<button type="button" class="btn btn-ghost switch-guard-stay">留在本页</button>' +
                            '<button type="button" class="btn btn-primary switch-guard-force">仍要切换（中断任务）</button>' +
                        '</div>' +
                    '</div>';

                document.body.appendChild(overlay);

                function cleanup() {
                    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                    document.removeEventListener('keydown', onKey);
                }
                function close(allow) {
                    cleanup();
                    resolve(allow);
                }
                function onKey(e) {
                    if (e.key === 'Escape') close(false);
                }

                overlay.querySelector('.switch-guard-stay')
                    .addEventListener('click', function () { close(false); });
                overlay.querySelector('.switch-guard-force')
                    .addEventListener('click', function () {
                        TaskGuard.abortAll();
                        close(true);
                    });
                // 点遮罩空白处 = 取消切换
                overlay.addEventListener('click', function (e) {
                    if (e.target === overlay) close(false);
                });
                document.addEventListener('keydown', onKey);
            });
        }
    };

    window.Session = Session;
    window.TaskGuard = TaskGuard;
})();
