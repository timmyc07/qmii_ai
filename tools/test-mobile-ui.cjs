// Run with Playwright available on NODE_PATH; no browser or cloud credentials used.
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const source = path.join(__dirname, '..', 'src');
  const server = http.createServer((request, response) => {
    const file = { '/': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css' }[request.url];
    if (!file) { response.writeHead(404).end(); return; }
    response.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'text/html; charset=utf-8');
    response.end(fs.readFileSync(path.join(source, file)));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, channel: 'msedge' });
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      const stopped = { running: false, registered: false, url: '', code: '', message: '手機連線尚未開啟。' };
      window.testMobile = { info: stopped, pending: null, fail: false, calls: [] };
      window.__TAURI__ = {
        core: {
          convertFileSrc: value => value,
          invoke: async name => {
            const test = window.testMobile;
            test.calls.push(name);
            if (name === 'load_settings') return { presets: [], fixedPrompt: '' };
            if (name === 'studio_jobs') return { jobs: [{ id: 'fixture', workflow: 'quick', prompt: '其他設備提交', message: '已排隊', created: 1792000000, started: 1792000001, finished: 1792000010, origin: { platform: 'Windows 桌面', device: '<測試電腦>', user: '小迷', device_id: 'fixture-device' }, results: [] }] };
            if (name === 'mobile_status') {
              if (test.fail) throw new Error('Test status failure');
              return test.info;
            }
            if (name === 'start_mobile') {
              await new Promise(resolve => { test.pending = resolve; });
              return test.info = { running: true, registered: true, url: 'https://test-only.trycloudflare.com', code: 'dummy-test-code', message: '手機服務與 HTTPS 通道已啟動。' };
            }
            if (name === 'stop_mobile') {
              await new Promise(resolve => { test.pending = resolve; });
              return test.info = { ...stopped };
            }
          }
        }, dialog: { open: async () => null }, event: { listen: async () => {} }
      };
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.click('#mobile-connection');
    await page.waitForFunction(() => !document.querySelector('#mobile-start').disabled);
    await page.keyboard.press('Escape');
    await page.click('#shared-jobs');
    await page.waitForFunction(() => document.querySelector('#shared-job-list').textContent.includes('其他設備提交'));
    assert.match(await page.locator('#shared-job-list').innerText(), /小迷/);
    assert.match(await page.locator('#shared-job-list').innerText(), /<測試電腦>/);
    assert.match(await page.locator('#shared-job-list').innerText(), /提交：/);
    await page.locator('#shared-job-list summary').click();
    assert.match(await page.locator('.job-prompt').innerText(), /其他設備提交/);
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.locator('.modal').evaluate(el => el.scrollWidth <= el.clientWidth), true);
      if (width !== 360) await page.screenshot({ path: path.join(__dirname, `../.runtime/shared-jobs-${width}.png`), fullPage: true });
    }
    await page.keyboard.press('Escape');
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Desktop overflows at ${width}px`);
    }
    await page.click('#mobile-connection');
    await page.click('#mobile-start');
    assert.equal(await page.locator('#mobile-start').isDisabled(), true);
    await page.keyboard.press('Escape');
    await page.click('#mobile-connection');
    assert.match(await page.locator('#mobile-status').innerText(), /正在開啟/);
    await page.evaluate(() => window.testMobile.pending());
    await page.waitForSelector('#mobile-details:not(.hidden)');
    assert.equal(await page.locator('#mobile-code').getAttribute('type'), 'password');
    await page.click('#mobile-show-code');
    assert.equal(await page.locator('#mobile-code').getAttribute('type'), 'text');
    assert.equal(await page.locator('#mobile-url').inputValue(), 'https://test-only.trycloudflare.com');
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.evaluate(() => {
        const modal = document.querySelector('.modal');
        return modal.scrollWidth <= modal.clientWidth && modal.getBoundingClientRect().right <= innerWidth;
      }), true, `Modal overflows at ${width}px`);
    }
    await page.click('#mobile-stop');
    assert.match(await page.locator('#mobile-status').innerText(), /等待目前生成完成/);
    assert.equal(await page.locator('#mobile-details').isVisible(), false);
    await page.evaluate(() => window.testMobile.pending());
    await page.waitForFunction(() => !document.querySelector('#mobile-start').disabled);
    await page.evaluate(() => { window.testMobile.info = { running: false, registered: true, url: '', code: '', message: '連線已中斷' }; });
    await page.click('#mobile-refresh');
    await page.waitForFunction(() => document.querySelector('#mobile-start').textContent === '重新連線');
    await page.evaluate(() => { window.testMobile.fail = true; });
    await page.click('#mobile-refresh');
    await page.waitForFunction(() => document.querySelector('#mobile-error').textContent.includes('Test status failure'));
    assert.equal(await page.locator('#mobile-url').inputValue(), '');
    await page.evaluate(() => { window.testMobile.fail = false; });
    await page.click('#mobile-refresh');
    await page.waitForFunction(() => !document.querySelector('#mobile-start').disabled);
    assert.deepEqual(errors, []);
    console.log('Mobile UI passed: pending/reopen, masked code, responsive 1280/390/360, drain, stale state, error recovery.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
