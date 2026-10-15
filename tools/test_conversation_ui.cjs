// Isolated headless fixture; never connects to the user's desktop or GPU.
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const server = http.createServer((req, res) => {
    const file = { '/': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css' }[req.url];
    if (!file) return res.writeHead(404).end();
    res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html; charset=utf-8');
    res.end(fs.readFileSync(path.join(__dirname, '../src', file)));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../config/creation_library.json'), 'utf8'));
    await page.addInitScript(value => { window.testCatalog = value; }, {
      ...catalog, loras: catalog.loras.map(item => ({ ...item, installed: !!item.modes.length, available: !!item.modes.length })),
      templates: catalog.templates.map(item => ({ ...item, available: true, missingModels: [], missingNodes: [] }))
    });
    await page.addInitScript(() => {
      window.testEvents = {}; window.testGenerations = []; window.testUploads = null;
      window.__TAURI__ = {
        core: { convertFileSrc: value => value, invoke: async (name, args) => {
          if (name === 'generate_images') window.testGenerations.push(args);
          if (name === 'creation_library') return window.testCatalog;
          if (name === 'load_settings') return { presets: Array.from({ length: 40 }, (_, i) => ({ id: String(i), name: `按鈕 ${i}`, prompt: '完整提示詞 '.repeat(40) })), fixedPrompt: '', revision: 'fixture' };
          if (name === 'mobile_status') return { running: false, registered: false, message: '未開啟' };
        } },
        dialog: { open: async () => window.testUploads },
        event: { listen: async (name, fn) => { window.testEvents[name] = fn; } }
      };
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    const emit = payload => page.evaluate(value => window.testEvents['generation-progress']({ payload: value }), payload);
    const frame = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const position = () => page.locator('#conversation').evaluate(el => ({ top: el.scrollTop, bottom: el.scrollHeight - el.clientHeight - el.scrollTop }));
    await page.waitForFunction(() => document.querySelector('#library-status').textContent.includes('11 個'));
    assert.equal(await page.locator('.composer-area .workflow-picker').count(), 0);
    assert.equal(await page.locator('#creation-panel .workflow-picker').count(), 1);
    assert.equal(await page.locator('.template-card').count(), 4);
    await page.click('#workflow-trigger'); await page.click('[data-value="pose"]');
    assert.equal(await page.locator('#lora-choice option[value="qwen_edit"]').isDisabled(), true);
    await page.selectOption('#lora-choice', 'qwen_fullbody');
    await page.locator('#lora-strength').fill('0.65');
    await page.fill('#prompt', 'A mountain landscape'); await page.click('#send');
    assert.equal(await page.evaluate(() => window.testGenerations.at(-1).lora), 'qwen_fullbody');
    assert.equal(await page.evaluate(() => window.testGenerations.at(-1).loraStrength), .65);
    assert.equal(await page.locator('#workflow-trigger').isDisabled(), true);
    assert.equal(await page.locator('#lora-choice').isDisabled(), true);
    await emit({ index: 1, total: 1, message: '已完成', done: true });
    await page.evaluate(() => { window.testUploads = ['/fixture.png']; });
    await page.click('#upload-images');
    assert.equal(await page.locator('#lora-choice option[value="qwen_edit"]').isDisabled(), false);
    await page.selectOption('#lora-choice', 'qwen_edit');
    await page.fill('[data-parameter="denoise"]', '0.48');
    await page.fill('[data-parameter="cfg"]', '2.7');
    await page.fill('[data-parameter="steps"]', '10');
    await page.locator('#lora-strength').fill('0.3');
    await page.locator('#generation-parameters').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(__dirname, '../.runtime/wan_parameters_desktop.png'), fullPage: true });
    await page.fill('#prompt', 'A natural portrait'); await page.click('#send');
    assert.deepEqual(await page.evaluate(() => window.testGenerations.at(-1).parameters), { denoise: .48, cfg: 2.7, steps: 10 });
    assert.equal(await page.evaluate(() => window.testGenerations.at(-1).loraStrength), .3);
    await emit({ index: 1, total: 1, message: '已完成', done: true });
    await page.click('#upload-images');
    await page.selectOption('#lora-choice', 'qwen_edit');
    await page.click('#image-tray button');
    assert.equal(await page.locator('#lora-choice').inputValue(), '');
    await page.click('#workflow-trigger');
    await page.click('[data-value="chroma"]');
    assert.equal(await page.locator('#workflow-value').innerText(), 'Chroma1-HD');
    await page.fill('#prompt', 'A blue teacup'); await page.click('#send');
    assert.equal(await page.evaluate(() => window.testGenerations.at(-1).workflow), 'chroma');
    assert.equal(await page.evaluate(() => window.testGenerations.at(-1).lora), '');
    assert.equal(await page.locator('#lora-choice').isDisabled(), true);
    await emit({ index: 1, total: 1, message: '已完成', done: true });
    await page.waitForTimeout(250);
    await page.screenshot({ path: path.join(__dirname, '../.runtime/creation-desktop.png'), fullPage: true });
    await page.click('#workflow-trigger'); await page.click('[data-value="flux"]');
    assert.equal(await page.locator('#lora-choice option:not([value=""])').count(), 3);
    for (const id of ['flux_figure', 'flux_anatomy', 'flux_undressing']) {
      await page.selectOption('#lora-choice', id);
      await page.locator('#lora-strength').fill('0.7');
      await page.fill('#prompt', 'An adult portrait'); await page.click('#send');
      const value = await page.evaluate(() => window.testGenerations.at(-1));
      assert.equal(value.workflow, 'flux'); assert.equal(value.lora, id); assert.equal(value.loraStrength, .7);
      await emit({ index: 1, total: 1, message: '已完成', done: true });
    }
    await page.screenshot({ path: path.join(__dirname, '../.runtime/flux-desktop.png'), fullPage: true });
    await page.click('[data-template="chroma_hades"]');
    await page.fill('#prompt', 'An adult portrait'); await page.click('#send');
    assert.equal(await page.evaluate(() => window.testGenerations.at(-1).workflow), 'chroma_hades');
    assert.equal(await page.evaluate(() => window.testGenerations.at(-1).lora), '');
    await emit({ index: 1, total: 1, message: '已完成', done: true });
    await page.click('[data-template="chroma_full"]');
    const beforeFull = await page.evaluate(() => window.testGenerations.length);
    await page.fill('#prompt', 'An adult standing'); await page.click('#send');
    assert.equal(await page.evaluate(() => window.testGenerations.length), beforeFull);
    await page.evaluate(() => { window.testUploads = ['/pose.png', '/color.png']; });
    await page.click('#upload-images');
    assert.match(await page.locator('#batch-label').innerText(), /色彩參考/);
    await page.click('#send');
    assert.equal(await page.evaluate(() => window.testGenerations.at(-1).workflow), 'chroma_full');
    assert.equal(await page.evaluate(() => window.testGenerations.at(-1).images.length), 2);
    await emit({ index: 1, total: 1, message: '已完成', done: true });
    await page.evaluate(() => { window.testCatalog.templates[0].available = false; window.testCatalog.templates[0].missingModels = ['Velvet Chroma v2.0_Q8_0.gguf']; });
    await page.click('#refresh-library');
    assert.equal(await page.locator('[data-template="chroma_hades"]').isDisabled(), true);
    assert.equal(await page.locator('[data-value="chroma_hades"]').isDisabled(), true);
    await page.click('#workflow-trigger'); await page.click('[data-value="quick"]');
    for (let i = 0; i < 14; i++) {
      await page.fill('#prompt', `歷史任務 ${i}\n` + '可閱讀的歷史對話內容\n'.repeat(9));
      await page.click('#send');
      await emit({ index: 1, total: 1, message: '已完成', done: true });
    }
    await frame(); assert.ok((await position()).bottom <= 2);
    await page.fill('#prompt', '正在進行的新任務'); await page.click('#send'); await frame();
    await page.locator('#conversation').hover(); await page.mouse.wheel(0, -350);
    await page.waitForFunction(() => !document.querySelector('#latest-message').classList.contains('hidden'));
    const reading = await position(); assert.ok(reading.bottom > 100);
    for (let i = 0; i < 8; i++) await emit({ index: 0, total: 1, message: `生成進度 ${i}`, done: false });
    await frame(); assert.ok(Math.abs((await position()).top - reading.top) <= 2, 'Progress updates pulled reader down');
    // A delayed image load and final completion must also preserve the reader.
    await page.route('**/delayed.png*', async route => {
      await new Promise(resolve => setTimeout(resolve, 150));
      await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024"><rect width="1024" height="1024" fill="plum"/></svg>' });
    });
    await emit({ index: 1, total: 1, message: '圖片完成', image: '/delayed.png', done: false });
    await page.locator('.result-image').evaluate(img => img.decode());
    await emit({ index: 1, total: 1, message: '完成', done: true }); await frame();
    assert.ok(Math.abs((await position()).top - reading.top) <= 2, 'Image load or completion pulled reader down');
    // Sidebar content keeps its width while toggling. The conversation gets one
    // layout change, rather than a new text wrapping width on every frame.
    const sidebarWidth = await page.locator('#sidebar').evaluate(el => el.getBoundingClientRect().width);
    for (let i = 0; i < 3; i++) {
      await page.click('#sidebar-collapse'); await page.click('#sidebar-toggle');
    }
    assert.ok(Math.abs(await page.locator('#sidebar').evaluate(el => el.getBoundingClientRect().width) - sidebarWidth) < 1);
    const transitions = await page.locator('#app-shell').evaluate(el => getComputedStyle(el).transitionProperty);
    assert.ok(!transitions.includes('grid-template-columns'));
    await page.click('#latest-message'); await frame(); assert.ok((await position()).bottom <= 2);
    await emit({ index: 1, total: 1, message: '第二張完成', image: '/delayed.png?second', done: false });
    await page.locator('.result-image').last().evaluate(img => img.decode());
    await frame(); assert.ok((await position()).bottom <= 2, 'Following latest should remain pinned');
    // Even a small intentional upward move must unpin; no broad threshold.
    await page.locator('#conversation').evaluate(el => { el.scrollTop -= 30; }); await frame();
    const nearBottom = await position(); await emit({ message: '更新', done: false }); await frame();
    assert.ok(Math.abs((await position()).top - nearBottom.top) <= 2, 'Small scroll was overridden');
    await page.locator('#conversation').focus(); await page.keyboard.press('Home'); await frame();
    await emit({ message: '鍵盤捲動後更新', done: false }); await frame();
    assert.ok((await position()).top < nearBottom.top);
    await page.click('#workflow-trigger'); await page.click('[data-value="wan"]');
    await page.fill('[data-parameter="frames"]', '49');
    await page.fill('[data-parameter="fps"]', '24');
    await page.fill('#prompt', 'A peaceful lake'); await page.click('#send');
    assert.equal(await page.evaluate(() => window.testGenerations.at(-1).workflow), 'wan');
    assert.deepEqual(await page.evaluate(() => window.testGenerations.at(-1).parameters), { frames: 49, fps: 24 });
    await emit({ index: 1, total: 1, message: '影片完成', image: '/lake.mp4', done: false });
    assert.equal(await page.locator('video.result-image[controls]').count(), 1);
    await emit({ index: 1, total: 1, message: '完成', done: true });
    // Touch drawer and rapid desktop toggles remain usable at narrow sizes.
    for (const width of [768, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      await page.click('#creation-toggle');
      await page.locator('#creation-panel').waitFor({ state: 'visible' });
      await page.click('#workflow-trigger'); await page.click('[data-value="pose"]');
      await page.selectOption('#lora-choice', 'qwen_fullbody');
      if (width === 390) {
        await page.locator('#creation-panel').evaluate(el => { el.scrollTop = 0; });
        await page.waitForTimeout(250);
        await page.screenshot({ path: path.join(__dirname, '../.runtime/creation-mobile.png'), fullPage: true });
      }
      await page.keyboard.press('Escape');
      await page.click('#sidebar-toggle');
      await page.waitForFunction(() => document.querySelector('#app-shell').classList.contains('sidebar-open'));
      assert.equal(await page.locator('#sidebar').evaluate(el => getComputedStyle(el).visibility), 'visible');
      await page.keyboard.press('Escape');
      await page.waitForFunction(() => !document.querySelector('#app-shell').classList.contains('sidebar-open'));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
    assert.deepEqual(errors, []);
    console.log('Conversation UI passed: right settings panel, LoRA filtering/strength/submission, HaDeS/Full selection, reference roles, missing-model controls, busy controls, conversation scrolling, 1280/768/390/360 layouts.');
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
