// BUG-1 E2E 验证：Agent 视图下经典欢迎引导页必须被隐藏
// 用全新浏览器上下文（无 localStorage）→ 首日逻辑下欢迎页会显示
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/33245/.workbuddy/binaries/node/workspace/node_modules/playwright');

const BASE = 'http://localhost:8000';

const browser = await chromium.launch();
const ctx = await browser.newContext(); // 全新上下文，localStorage 空 → 首日欢迎页弹出
const page = await ctx.newPage();
const logs = [];
page.on('console', m => logs.push('[console] ' + m.text()));

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForSelector('#welcome-page', { timeout: 10000 }).catch(() => {});
await page.waitForTimeout(800); // 等 welcome-script.js 跑完 show()

const disp = (sel) => page.evaluate((s) => {
  const el = document.querySelector(s);
  if (!el) return 'NOT_FOUND';
  return getComputedStyle(el).display;
}, sel);

const bodyClass = () => page.evaluate(() => document.body.className);

// 1) 经典视图：欢迎页应当可见（首日弹出）
const classicWelcome = await disp('#welcome-page');
const classicDemo = await disp('#demo-selector-modal');
const classicBody = await bodyClass();

// 2) 模拟 ViewManager 切到 agent 视图（与 ViewManager._apply 一致：改 body 类）
await page.evaluate(() => { document.body.className = 'view-agent'; });
await page.waitForTimeout(300);

const agentWelcome = await disp('#welcome-page');
const agentDemo = await disp('#demo-selector-modal');
const agentBody = await bodyClass();

// 3) 切回经典：不应破坏经典（欢迎页恢复显示）
await page.evaluate(() => { document.body.className = 'view-classic'; });
await page.waitForTimeout(300);
const backWelcome = await disp('#welcome-page');

await browser.close();

console.log('--- BUG-1 E2E 结果 ---');
console.log('classic body=', JSON.stringify(classicBody), '| welcome.display=', classicWelcome, '| demo.display=', classicDemo);
console.log('agent   body=', JSON.stringify(agentBody), '| welcome.display=', agentWelcome, '| demo.display=', agentDemo);
console.log('back    welcome.display=', backWelcome);

const ok = (classicWelcome === 'flex' || classicWelcome === 'block' || classicWelcome === 'grid')
  && agentWelcome === 'none'
  && agentDemo === 'none'
  && (backWelcome === 'flex' || backWelcome === 'block' || backWelcome === 'grid');

console.log(ok ? 'BUG-1 修复验证通过 ✅' : 'BUG-1 验证失败 ❌');
process.exit(ok ? 0 : 1);
