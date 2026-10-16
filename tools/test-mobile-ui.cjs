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
          invoke: async (name, args) => {
            const test = window.testMobile;
            test.calls.push(name);
            if (name === 'load_settings') return { presets: [], preciseMode: false };
            if (name === 'save_settings') return { ...args.settings, revision: 'saved' };
            if (name === 'generate_images') { test.generation = args; return; }
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
        }, dialog: { open: async () => window.testMobile.openPath || null }, event: { listen: async (name, handler) => { if (name === 'generation-progress') window.testMobile.progress = handler; } }
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
    await page.keyboard.press('Escape');
    await page.setViewportSize({ width: 1280, height: 820 });
    await page.fill('#prompt', '圖片草稿');
    await page.click('[data-studio-mode="h3_image"]');
    assert.equal(await page.locator('#conversation').isVisible(), false);
    assert.equal(await page.locator('#video-page').isVisible(), true);
    assert.equal(await page.locator('[data-studio-mode]').count(), 2);
    await page.fill('#video-duration', '6');
    await page.click('#video-save-settings');
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('已儲存'));
    await page.evaluate(() => { window.testMobile.openPath = '/fixture.png'; });
    await page.click('#video-upload');
    await page.waitForSelector('#video-image-preview img');
    await page.click('#video-example');
    assert.match(await page.locator('#video-prompt').inputValue(), /00:06\.000/);
    await page.fill('#video-seed', '42');
    await page.click('[data-studio-mode="image"]');
    assert.equal(await page.locator('#prompt').inputValue(), '圖片草稿');
    await page.click('[data-studio-mode="h3_image"]');
    assert.equal(await page.locator('#video-duration').inputValue(), '6');
    assert.equal(await page.locator('#video-seed').inputValue(), '42');
    await page.click('#video-send');
    const submitted = await page.evaluate(() => window.testMobile.generation);
    assert.equal(submitted.workflow, 'h3_image');
    assert.deepEqual(submitted.images, ['/fixture.png']);
    assert.equal(submitted.parameters.duration, 6);
    assert.equal(submitted.parameters.seed, 42);
    assert.equal(submitted.preciseMode, false);
    await page.click('[data-studio-mode="image"]');
    await page.evaluate(() => window.testMobile.progress({ payload: { video: '/fixture.mp4', index: 1, total: 1, message: '影片完成', done: true } }));
    assert.equal(await page.locator('#video-results-h3_image video[controls]').count(), 1);
    assert.equal(await page.locator('#feed video').count(), 0);
    await page.click('[data-studio-mode="h3_image"]');
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.querySelector('#video-page').scrollWidth <= document.querySelector('#video-page').clientWidth), true, `Video page overflows at ${width}px`);
      await page.locator('#video-page').evaluate(el => { el.scrollTop = 0; });
      await page.waitForTimeout(350);
      if (width !== 360) await page.screenshot({ path: path.join(__dirname, `../.runtime/h3-video-${width}.png`), fullPage: true });
    }
    assert.deepEqual(errors, []);
    console.log('UI passed: mobile lifecycle, image/video pages, preserved drafts, I2V submission, MP4 result routing, responsive 1280/390/360.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
