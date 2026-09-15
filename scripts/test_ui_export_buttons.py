# -*- coding: utf-8 -*-
"""UI 可视化验证：登录 guo → 经典结果区两按钮 + Agent 动作栏「导出 PPT」按钮。
按钮渲染用真实 _appendExportActions 调用（注入最小 shell），截图留档。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8000'
OUT = Path(__file__).resolve().parents[1] / 'test_shots'
OUT.mkdir(exist_ok=True)


def main():
    # 登录需图形验证码——UI 冒烟直接签发 JWT 注入 shared_runtime 的存储键
    from app.utils.auth_utils import create_access_token
    token = create_access_token(2, 'guo', 'admin')[0]
    import json as _json
    auth_payload = _json.dumps({
        'token': token,
        'expiresAt': int(time.time() * 1000) + 3600_000,
        'user': {'id': 2, 'username': 'guo', 'role': 'admin', 'status': 'active'},
    })

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1600, 'height': 950})
        page.goto(BASE + '/index.html', wait_until='domcontentloaded')
        page.evaluate(
            "p => localStorage.setItem('hwcloud_auth', p)", auth_payload)

        # ---- Agent 动作栏按钮渲染（真实 _appendExportActions 注入） ----
        page.evaluate("""() => {
            document.body.classList.remove('view-classic');
            document.body.classList.add('view-agent');
            const host = document.createElement('div');
            host.id = 'pw-agent-actions-host';
            host.style.cssText = 'padding:40px;background:#fff;';
            const actions = document.createElement('div');
            actions.className = 'ws-msg-actions';  // 与线上 shell.actions 同类名（gap:10px）
            host.appendChild(actions);
            document.body.appendChild(host);
            // 真实函数：与线上渲染路径一致
            window.AgentWorkspace._appendExportActions(
                {actions: actions}, '测试答案文本', 'solution');
        }""")
        time.sleep(1)
        page.locator('#pw-agent-actions-host').screenshot(
            path=str(OUT / 'agent_export_buttons.png'))

        # 断言两个按钮都在 + PPT 按钮文本
        n_word = page.locator('#pw-agent-actions-host .ws-export-btn').count()
        n_ppt = page.locator('#pw-agent-actions-host .ws-export-ppt-btn').count()
        ppt_txt = (page.locator('#pw-agent-actions-host .ws-export-ppt-btn')
                   .inner_text() if n_ppt else '(缺失)')
        print(f'Agent 动作栏: Word按钮={n_word} PPT按钮={n_ppt} 文本={ppt_txt!r}')
        assert n_word == 1 and n_ppt == 1, '按钮缺失'

        # 点击 PPT 按钮应触发 /api/export/report (format=pptx) —— route 捕获请求体断言
        captured = {}

        def _capture(route):
            import json as _j
            try:
                captured['body'] = _j.loads(route.request.post_data or '{}')
            except Exception:
                captured['body'] = {}
            route.fulfill(status=200, content_type='application/json',
                          body='{"status":"FAILED","error_message":"UI冒烟拦截，不真正生成"}')

        page.route('**/api/export/report', _capture)
        page.click('#pw-agent-actions-host .ws-export-ppt-btn')
        page.wait_for_timeout(1200)
        fmt = (captured.get('body') or {}).get('format')
        print('PPT按钮请求体 format =', fmt)
        assert fmt == 'pptx', f'请求体 format 错误: {fmt}'

        # ---- 经典模式结果区两按钮存在性（DOM 静态检查） ----
        page.evaluate("""() => {
            document.body.classList.remove('view-agent');
            document.body.classList.add('view-classic');
        }""")
        n_docx = page.locator('#export-docx-btn').count()
        n_pptx = page.locator('#export-pptx-btn').count()
        icon_ok = page.locator('#export-pptx-btn use[href="#i-presentation"]').count()
        print(f'经典模式: Word按钮={n_docx} PPT按钮={n_pptx} PPT图标引用={icon_ok}')
        assert n_docx == 1 and n_pptx == 1 and icon_ok == 1, '经典按钮缺失'

        page.locator('.result-actions').first.screenshot(
            path=str(OUT / 'classic_export_buttons.png')) \
            if page.locator('.result-actions').first.is_visible() else None

        browser.close()
        print('UI SMOKE OK')


if __name__ == '__main__':
    main()
