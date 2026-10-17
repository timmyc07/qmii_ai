// Real API + shared mobile membership UI, isolated from the host's accounts and GPU.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const runtime = path.join(root, '.runtime');
  const fixture = fs.mkdtempSync(path.join(runtime, 'membership-ui-'));
  const listener = net.createServer();
  await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  const service = spawn(path.join(runtime, 'mobile-venv', 'Scripts', 'python.exe'), ['-X', 'utf8', '-c',
    `import sys; from pathlib import Path; import uvicorn; from mobile.server import create_app; p=Path(sys.argv[1]); uvicorn.run(create_app(p/'state',p/'output',runner=lambda *args: [],settings_path=p/'settings.json'),host='127.0.0.1',port=int(sys.argv[2]),log_level='error')`, fixture, String(port)],
  { cwd: root, windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
  let logs = '', browser, page;
  service.stderr.on('data', data => { logs += data; });
  try {
    for (let i = 0; i < 100; i++) {
      if (service.exitCode !== null) throw new Error(logs);
      try { if ((await fetch(origin + '/api/membership')).ok) break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    browser = await chromium.launch({ headless: true, channel: 'msedge' });
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const request = async (url, value, csrf = '') => {
      const response = await context.request.post(origin + url, { data: value, headers: { Origin: 'http://127.0.0.1:8787', 'X-Qianmi-CSRF': csrf } });
      assert.equal(response.ok(), true, await response.text()); return response.json();
    };
    const paired = await request('/api/login', { code: fs.readFileSync(path.join(fixture, 'state', 'access-code.txt'), 'utf8').trim() });
    await request('/api/membership/bootstrap', { email: 'admin@example.com', name: '管理員', password: 'admin password 123' }, paired.csrf);
    await context.clearCookies();
    // The fixture runs on a free port; the product API deliberately accepts only its configured origin.
    await context.route('**/api/**', async route => {
      const response = await route.fetch({ headers: { ...route.request().headers(), origin: 'http://127.0.0.1:8787' } });
      await route.fulfill({ response });
    });
    page = await context.newPage();
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin);
    await page.click('#member-login');
    await page.click('[data-register]');
    await page.fill('[name=name]', '會員 <測試>');
    await page.fill('[name=email]', 'member@example.com');
    await page.fill('[name=password]', 'member password 123');
    await page.click('[data-register-form] button');
    await page.waitForSelector('[data-ledger]');
    assert.match(await page.locator('.membership-dialog').innerText(), /可用點數：0/);
    assert.equal(await page.locator('.membership-dialog 測試').count(), 0);
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.locator('.membership-dialog').evaluate(el => el.scrollWidth <= el.clientWidth), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
    await page.click('[data-close]');
    await page.fill('#prompt', 'blue teacup');
    await page.click('#send');
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('本次需要 3 點'));
    await page.click('#account-button'); await page.click('[data-logout]');
    await page.waitForSelector('[data-login]');
    await page.fill('[name=email]', 'admin@example.com'); await page.fill('[name=password]', 'admin password 123');
    await page.click('[data-login] button'); await page.waitForSelector('[data-admin]'); await page.click('[data-admin]');
    await page.waitForSelector('[data-edit]');
    await page.fill('[name=search]', 'member@example.com'); await page.click('[data-search] button');
    await page.waitForFunction(() => document.querySelectorAll('[data-edit]').length === 1);
    await page.click('[data-edit]');
    await page.fill('[name=amount]', '12'); await page.fill('[name=reason]', '測試儲值單號'); await page.click('[data-credits] button');
    await page.waitForFunction(() => document.querySelector('[data-message]').textContent.includes('點數已調整'));
    await page.click('[data-issue-reset]');
    await page.waitForFunction(() => document.querySelector('[data-reset-token]').textContent.includes('重設碼（'));
    const token = (await page.locator('[data-reset-token]').innerText()).split('：').pop();
    await page.click('[data-back]');
    await page.waitForSelector('[data-audit]'); await page.click('[data-audit]');
    await page.waitForFunction(() => document.querySelector('[data-audit-list]').textContent.includes('測試儲值單號'));
    await page.setViewportSize({ width: 1280, height: 820 });
    await page.locator('.membership-dialog').evaluate(el => el.scrollTop = 0);
    await page.screenshot({ path: path.join(runtime, 'membership-admin.png'), fullPage: true });
    await page.click('[data-back]'); await page.waitForSelector('[data-logout]'); await page.click('[data-logout]');
    await page.waitForSelector('[data-reset]'); await page.click('[data-reset]');
    await page.fill('[name=token]', token); await page.fill('[name=password]', 'updated password 123'); await page.click('[data-reset-form] button');
    await page.waitForSelector('[data-login]');
    await page.fill('[name=email]', 'member@example.com'); await page.fill('[name=password]', 'updated password 123'); await page.click('[data-login] button');
    await page.waitForSelector('[data-ledger]');
    assert.match(await page.locator('[data-ledger]').innerText(), /\+12/);
    assert.equal(await page.locator('[data-admin]').count(), 0);
    await page.setViewportSize({ width: 390, height: 820 });
    await page.screenshot({ path: path.join(runtime, 'membership-mobile.png'), fullPage: true });
    await page.click('[data-close]');
    await page.fill('#prompt', 'blue teacup'); await page.click('#send');
    await page.waitForFunction(() => document.querySelectorAll('.job').length === 1);
    await page.waitForFunction(() => document.querySelector('.job').textContent.includes('圖片完成'));
    await page.click('#account-button');
    await page.waitForFunction(() => document.querySelector('[data-ledger]')?.textContent.includes('未完成輸出退點'));
    assert.match(await page.locator('.membership-dialog').innerText(), /可用點數：12/);
    assert.deepEqual(errors, []);
    console.log('Membership UI passed: registration, login, zero balance, admin top-up/audit, reset, point refund, 360/390/1280px.');
  } catch (error) {
    if (page) {
      console.error('Membership UI status:', await page.locator('[data-message]').innerText());
      await page.screenshot({ path: path.join(runtime, 'membership-ui-failure.png'), fullPage: true });
    }
    throw error;
  } finally {
    if (browser) await browser.close();
    if (service.exitCode === null) { service.kill(); await new Promise(resolve => service.once('exit', resolve)); }
    const target = path.resolve(fixture);
    assert.equal(path.dirname(target), path.resolve(runtime));
    assert.ok(path.basename(target).startsWith('membership-ui-'));
    fs.rmSync(target, { recursive: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
