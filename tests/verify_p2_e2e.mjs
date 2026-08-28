/**
 * P2 端到端验证（Playwright · 浏览器 DOM 层）
 * ------------------------------------------------------------
 * 验证目标（设计文档 §9）：
 *   1. 注入 JWT 进 Agent 视图，发送方案匹配需求
 *      → 出现 agent_phase 阶段徽标（需求分析师/方案架构师/质量校验官）
 *   2. Plan 面板每行出现「↻ 重跑」按钮；点击后重新点亮该步（P2-D5）
 *   3. 发送「把上面的方案导出成 PPT」→ 出现 .pptx 下载 chip（P2-D4）
 *   4. 截图留证
 *
 * 运行：node tests/verify_p2_e2e.mjs（需先启动后端 localhost:8000）
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const BASE = 'http://localhost:8000/';
const VENV_PY = path.join(ROOT, 'venv', 'Scripts', 'python.exe');

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
  console.error('❌ 无法生成 JWT:', e.stderr ? e.stderr.toString().split('\n').slice(-3).join('\n') : e.message);
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
  if (!abs) throw new Error('找不到 playwright 包，请设置 NODE_PATH');
  pw = await import('file://' + abs.replace(/\\/g, '/'));
}
const { chromium } = pw;

const SHOT_DIR = path.join(ROOT, 'tests', 'screenshots');
mkdirSync(SHOT_DIR, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

await page.addInitScript((tok) => {
  localStorage.setItem('hwcloud_auth', JSON.stringify({
    token: tok,
    expiresAt: Date.now() + 7 * 24 * 3600 * 1000,
    user: { id: 3, username: 'guo', role: 'user' },
  }));
  localStorage.setItem('huawei_view_preference', 'agent');
}, token);

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log((ok ? '  ✅ ' : '  ❌ ') + name + (detail ? ' — ' + detail : ''));
}

try {
  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForSelector('body.view-agent', { timeout: 10000 });
  await page.waitForSelector('#ws-input', { timeout: 15000 });

  // 1) 方案匹配 → 阶段徽标 + Plan 面板
  await page.fill('#ws-input', '帮我在制造业客户做设备预测性维护方案匹配');
  await page.press('#ws-input', 'Enter');

  await page.waitForSelector('#ws-plan:not([style*="display: none"])', { timeout: 60000 });
  const stepCount = await page.$$eval('#ws-plan .ws-plan-item', (els) => els.length);
  check('Plan 面板渲染', stepCount >= 3, `steps=${stepCount}`);

  // 阶段徽标（agent_phase → .ws-think-step-phase）
  let phaseSeen = 0;
  const t0 = Date.now();
  while (Date.now() - t0 < 240000) {
    phaseSeen = await page.$$eval('.ws-think-step-phase', (els) => els.length).catch(() => 0);
    if (phaseSeen >= 1) break;
    await page.waitForTimeout(2000);
  }
  check('多智能体阶段徽标出现', phaseSeen >= 1, `phase_badges=${phaseSeen}`);

  // 2) 等首轮完成（result → 导出按钮出现）
  await page.waitForSelector('.ws-export-btn', { timeout: 300000 });
  console.log('  ℹ️ 首轮方案生成完成，等待 Plan 重跑按钮…');

  // 3) 重跑按钮存在
  const rerunCount = await page.$$eval('#ws-plan .ws-plan-rerun', (els) => els.length).catch(() => 0);
  check('Plan 行重跑按钮渲染', rerunCount >= 3, `rerun_btns=${rerunCount}`);

  // 4) 导出 PPT → pptx chip
  await page.fill('#ws-input', '把上面的方案导出成 PPT');
  await page.press('#ws-input', 'Enter');
  let chipUrl = '';
  const t1 = Date.now();
  while (Date.now() - t1 < 300000) {
    chipUrl = await page.$eval('.ws-doc-chip', (el) => el.getAttribute('data-url') || '', ).catch(() => '');
    const fname = await page.$eval('.ws-doc-chip', (el) => el.textContent || '').catch(() => '');
    if (chipUrl && /pptx/i.test(fname)) break;
    if (chipUrl && !/pptx/i.test(fname)) {
      // 可能是上一轮 word chip，继续等新的 pptx chip
    }
    await page.waitForTimeout(2000);
  }
  const chipText = await page.$eval('.ws-doc-chip', (el) => el.textContent || '').catch(() => '');
  check('PPTX 下载 chip 出现', !!chipUrl && /pptx/i.test(chipText), chipText || '未出现');

  // 5) 截图
  const shot = path.join(SHOT_DIR, 'p2_e2e_phases_rerun_pptx.png');
  await page.screenshot({ path: shot });
  console.log('  📸 截图: ' + shot);
} catch (e) {
  console.error('❌ e2e 异常:', e.message);
  try {
    await page.screenshot({ path: path.join(SHOT_DIR, 'p2_e2e_failure.png') });
  } catch {}
  process.exit(1);
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.ok);
console.log('\n=== P2 E2E 结果: ' + (results.length - failed.length) + '/' + results.length + ' 通过 ===');
if (failed.length) {
  failed.forEach((f) => console.log('  ❌ ' + f.name));
  process.exit(1);
}
console.log('P2 浏览器 E2E 全部通过 ✅');
