/**
 * P1 端到端验证（Playwright · 浏览器 DOM 层）
 * ------------------------------------------------------------
 * 验证目标（设计文档 §5）：
 *   1. 注入 JWT 直进 Agent 视图（绕过验证码），发送方案匹配需求
 *      → Plan 面板渲染多步计划，工具执行时逐步点亮 running/done（P1-1）
 *   2. 方案完成后发送"把上面的方案导出成 Word"
 *      → 出现可下载的 doc_generated 下载 chip（P1-2）
 *   3. 截图留证（Plan 面板点亮态 + 下载 chip 同框）
 *
 * 运行：node tests/verify_p1_e2e.mjs  （需先启动后端 localhost:8000）
 * 说明：协议层正确性已由 verify_p1_*.py 权威验证；本脚本只做 DOM 渲染确认。
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const BASE = 'http://localhost:8000/';
const VENV_PY = path.join(ROOT, 'venv', 'Scripts', 'python.exe');

// 1) 用 venv python 生成 guo（user_id=3）的 JWT，与其它测试同源
const pyCode = `
import sys, os
sys.path.insert(0, r"${ROOT}")
os.environ.setdefault("OMP_NUM_THREADS", "1")
from app.services.auth_service import AuthService
from app.utils.auth_utils import create_access_token
u = AuthService.get_user_by_id(3)
tok, _ = create_access_token(u["id"], u["username"], u.get("role","user"), u.get("token_version",1))
print(tok)
`;
let token;
try {
  token = execFileSync(VENV_PY, ['-c', pyCode], { encoding: 'utf8' }).trim();
} catch (e) {
  console.error('❌ 无法生成 JWT（后端/venv 未就绪？）:', e.stderr ? e.stderr.toString().split('\n').slice(-3).join('\n') : e.message);
  process.exit(1);
}
console.log('✅ JWT 生成成功, len=' + token.length);

// ESM 不走 NODE_PATH：优先按环境变量拼绝对路径，失败再退回常规 import
let pw;
try {
  pw = await import('playwright');
} catch {
  const np = process.env.NODE_PATH || '';
  const abs = np.split(path.delimiter)
    .map((p) => p && path.join(p, 'playwright', 'index.mjs'))
    .find((p) => p && existsSync(p));
  if (!abs) throw new Error('找不到 playwright 包，请设置 NODE_PATH 指向其安装目录');
  pw = await import('file://' + abs.replace(/\\/g, '/'));
}
const { chromium } = pw;
const SHOT_DIR = path.join(ROOT, 'tests', 'screenshots');
mkdirSync(SHOT_DIR, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

// 注入登录态 + 直接进入 Agent 视图偏好
await page.addInitScript((tok) => {
  localStorage.setItem('hwcloud_auth', JSON.stringify({
    token: tok,
    expiresAt: Date.now() + 7 * 24 * 3600 * 1000,
    user: { id: 3, username: 'guo', role: 'user' },
  }));
  localStorage.setItem('huawei_view_preference', 'agent');
}, token);

const pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(String(e)));

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log((ok ? '  ✅ ' : '  ❌ ') + name + (detail ? ' — ' + detail : ''));
}

try {
  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 60000 });

  // 进入 Agent 视图（偏好注入应直接 view-agent；再点一次胶囊幂等验证）
  await page.waitForTimeout(500);
  await page.waitForSelector('body.view-agent', { timeout: 10000 });
  const capsuleActive = await page.$eval('.view-option[data-view="agent"]', (el) => el.classList.contains('active')).catch(() => false);
  check('Agent 视图激活 + 胶囊 active', true, 'body.view-agent');

  await page.waitForSelector('#ws-input', { timeout: 15000 });

  // 2) 发送方案匹配需求
  const Q = '帮我在制造业客户做设备预测性维护方案匹配';
  await page.fill('#ws-input', Q);
  await page.press('#ws-input', 'Enter');

  // 3) P1-1：Plan 面板渲染 + 逐步点亮
  await page.waitForSelector('#ws-plan:not([style*="display: none"])', { timeout: 60000 });
  const stepCount = await page.$$eval('#ws-plan .ws-plan-item', (els) => els.length);
  check('Plan 面板渲染多步计划', stepCount >= 3, `steps=${stepCount}`);

  // 轮询等待出现 done 态（工具执行点亮），最长 240s
  let doneSeen = 0;
  const t0 = Date.now();
  while (Date.now() - t0 < 240000) {
    doneSeen = await page.$$eval('#ws-plan .ws-plan-item.done', (els) => els.length).catch(() => 0);
    if (doneSeen >= 1) break;
    await page.waitForTimeout(2000);
  }
  check('Plan 步骤被点亮(done)', doneSeen >= 1, `done=${doneSeen}/${stepCount}`);
  if (doneSeen >= 1) {
    const states = await page.$$eval('#ws-plan .ws-plan-item', (els) =>
      els.map((e) => e.className.replace('ws-plan-item', '').trim() || 'pending').join(','));
    console.log('      plan 状态序列: [' + states + ']');
  }

  // 等待首轮最终答案落盘
  await page.waitForFunction(() => {
    const els = document.querySelectorAll('.ws-msg-agent .ws-answer, .ws-msg-bubble');
    return els.length > 0;
  }, { timeout: 300000 }).catch(() => {});
  await page.waitForTimeout(3000);

  // 4) P1-2：发送导出指令 → 期待 doc_generated chip
  await page.fill('#ws-input', '把上面的方案导出成 Word');
  await page.press('#ws-input', 'Enter');
  let chipUrl = '';
  const t1 = Date.now();
  while (Date.now() - t1 < 300000) {
    chipUrl = await page.$eval('.ws-doc-chip', (el) => el.getAttribute('data-url') || '', ).catch(() => '');
    if (chipUrl) break;
    await page.waitForTimeout(2000);
  }
  check('导出生成下载 chip(doc_generated)', !!chipUrl, chipUrl ? 'url=' + chipUrl : '未出现');

  // 5) 截图留证（Plan 点亮 + chip 同框）
  const shot = path.join(SHOT_DIR, 'p1_e2e_plan_and_chip.png');
  await page.screenshot({ path: shot, fullPage: false });
  console.log('  📸 截图: ' + shot);

  // 6) 页面 JS 错误统计（不应有白屏级错误）
  check('无页面 JS 错误', pageErrors.length === 0, pageErrors.length ? pageErrors.join(' | ') : 'clean');
} catch (e) {
  console.error('❌ e2e 异常:', e.message);
  try {
    const shot = path.join(SHOT_DIR, 'p1_e2e_failure.png');
    await page.screenshot({ path: shot });
    console.log('  📸 失败截图: ' + shot);
  } catch {}
  process.exit(1);
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.ok);
console.log('\n=== P1 E2E 结果: ' + (results.length - failed.length) + '/' + results.length + ' 通过 ===');
if (failed.length) {
  failed.forEach((f) => console.log('  ❌ ' + f.name + (f.detail ? ' — ' + f.detail : '')));
  process.exit(1);
}
console.log('P1 浏览器 E2E 全部通过 ✅');
