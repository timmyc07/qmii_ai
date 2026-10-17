const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const source = path.join(__dirname, '..', 'src');
  const server = http.createServer((request, response) => {
    const file = { '/': 'index.html', '/app.js': 'app.js', '/studio.js': 'studio.js', '/styles.css': 'styles.css' }[request.url];
    if (!file) return response.writeHead(404).end();
    response.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'text/html; charset=utf-8');
    response.end(fs.readFileSync(path.join(source, file)));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, channel: 'msedge' });
    const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      let settings = { presets: [], preciseMode: false, generation: {}, revision: '' };
      window.testGenerations = [];
      window.__TAURI__ = {
        core: { convertFileSrc: value => value, invoke: async (name, value) => {
          if (name === 'load_settings') return structuredClone(settings);
          if (name === 'save_settings') { window.testSavedSettings = value.settings; settings = structuredClone({ ...value.settings, revision: 'saved' }); return structuredClone(settings); }
          if (name === 'generate_images') { window.testGenerations.push(value); return; }
          if (name === 'cancel_generation') { window.testCancelled = value.jobId; return; }
          if (name === 'mobile_status') return { running: false, registered: false, url: '', code: '', message: '' };
          if (name === 'studio_jobs') return { jobs: [] };
        } },
        dialog: { open: async () => window.testPickedImages || null }, event: { listen: async (name, handler) => { if (name === 'generation-progress') window.testProgress = handler; } }
      };
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    assert.equal(await page.locator('#workflow-menu [data-value]').count(), 4);
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 5);
    assert.equal(await page.locator('label[for="prompt"]').innerText(), '正向提示詞');
    assert.equal(await page.locator('label[for="negative-prompt"]').innerText(), '負面提示詞');
    assert.match(await page.locator('#generation-parameters').innerText(), /寬度 Width/);
    assert.match(await page.locator('#generation-parameters').innerText(), /調高.*調低/s);
    await page.click('#workflow-trigger'); await page.click('[data-value="superduper"]');
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 6);
    assert.match(await page.locator('#workflow-help').innerText(), /ComfyUI/);
    await page.click('#workflow-trigger'); await page.click('[data-value="nsfw_adv"]');
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 8);
    assert.equal(await page.locator('#upload-images').isDisabled(), false);
    assert.match(await page.locator('#workflow-help').innerText(), /LoKr/);
    await page.click('#workflow-trigger'); await page.click('[data-value="reference"]');
    assert.match(await page.locator('#workflow-help').innerText(), /Qwen Image Turbo/);
    await page.click('#workflow-trigger'); await page.click('[data-value="quick"]');
    await page.fill('#prompt', '柔和花園'); await page.click('#send');
    assert.equal((await page.evaluate(() => window.testGenerations.at(-1))).workflow, 'quick');
    await page.evaluate(() => window.testProgress({ payload: { jobId: 'a'.repeat(32), done: false, message: '正在生成' } }));
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.locator('#cancel-generation').isVisible(), true);
    }
    await page.click('#cancel-generation');
    assert.equal(await page.evaluate(() => window.testCancelled), 'a'.repeat(32));
    assert.equal(await page.locator('#cancel-generation').isDisabled(), true);
    await page.evaluate(() => window.testProgress({ payload: { done: true, message: '任務已終止' } }));
    assert.equal(await page.locator('#cancel-generation').isVisible(), false);
    await page.setViewportSize({ width: 1280, height: 820 });
    for (const workflow of ['quick', 'reference', 'superduper', 'nsfw_adv']) {
      await page.reload();
      await page.click('#workflow-trigger'); await page.click(`[data-value="${workflow}"]`);
      assert.equal(await page.locator('#upload-images').isDisabled(), false);
      assert.equal(await page.locator('#image-refmod').isDisabled(), true);
      assert.match(await page.locator('#image-refmod-help').innerText(), /Qwen.*RefMod.*H3/);
      await page.evaluate(() => { window.testPickedImages = ['/a.png', '/b.png']; });
      await page.click('#upload-images');
      assert.equal(await page.locator('#image-tray .thumb-wrap').count(), 2);
      await page.fill('#prompt', '柔和花園');
      await page.fill('#negative-prompt', '  模糊\n"水印" <文字>  ');
      await page.click('#send');
      const submitted = await page.evaluate(() => window.testGenerations.at(-1));
      assert.equal(submitted.workflow, workflow);
      assert.deepEqual(submitted.images, ['/a.png', '/b.png']);
      assert.equal(submitted.prompt, '柔和花園');
      assert.equal(submitted.parameters.negative, '  模糊\n"水印" <文字>  ');
    }
    await page.reload();
    await page.click('#new-preset-shortcut');
    await page.fill('#preset-name', '正負模板');
    await page.fill('#preset-prompt', '柔和花園');
    await page.fill('#preset-negative', '模糊\n<水印>');
    await page.click('#preset-save');
    await page.waitForSelector('[data-preset]');
    assert.equal(await page.evaluate(() => window.testSavedSettings.presets[0].negative), '模糊\n<水印>');
    await page.click('[data-preset]');
    assert.equal((await page.evaluate(() => window.testGenerations.at(-1))).parameters.negative, '模糊\n<水印>');
    await page.evaluate(() => window.testProgress({ payload: { done: true, message: '完成' } }));
    await page.click('[data-studio-mode="h3_image"]');
    const beforeVideoPreset = await page.evaluate(() => window.testGenerations.length);
    await page.evaluate(() => { window.testPickedImages = ['/first.png']; });
    await page.click('#upload-images');
    await page.click('[data-preset]');
    assert.equal(await page.evaluate(() => window.testGenerations.length), beforeVideoPreset + 1);
    const video = await page.evaluate(() => window.testGenerations.at(-1));
    assert.equal(video.prompt, '柔和花園');
    assert.ok(!('negative' in video.parameters));
    assert.equal(await page.locator('#negative-label').isVisible(), false);
    assert.equal(await page.locator('#negative-prompt').isVisible(), false);
    await page.evaluate(() => window.testProgress({ payload: { done: true, message: '完成' } }));
    await page.click('[data-studio-mode="image"]');
    assert.equal(await page.locator('#negative-prompt').inputValue(), '模糊\n<水印>');
    await page.click('#manage-presets'); await page.click('.manager-row .edit');
    assert.equal(await page.locator('#preset-negative').inputValue(), '模糊\n<水印>');
    await page.fill('#preset-negative', ''); await page.click('#preset-save');
    await page.waitForSelector('#preset-save', { state: 'detached' });
    await page.fill('#negative-prompt', '上一筆負面提示詞'); await page.click('[data-preset]');
    assert.equal((await page.evaluate(() => window.testGenerations.at(-1))).parameters.negative, '');
    await page.evaluate(() => window.testProgress({ payload: { done: true, message: '完成' } }));
    await page.fill('#prompt', '正向草稿\n'.repeat(100));
    await page.fill('#negative-prompt', '負面草稿\n'.repeat(100));
    for (const viewport of [{ width: 1280, height: 820 }, { width: 390, height: 820 }, { width: 360, height: 520 }]) {
      await page.setViewportSize(viewport); await page.waitForTimeout(350);
      const layout = await page.evaluate(() => {
        const box = document.querySelector('#send').getBoundingClientRect();
        return { fits: document.documentElement.scrollWidth <= innerWidth, bottom: box.bottom, height: innerHeight, transcript: document.querySelector('#conversation').clientHeight,
          scrolls: ['prompt', 'negative-prompt'].every(id => { const el = document.getElementById(id); return el.scrollHeight > el.clientHeight; }) };
      });
      assert.equal(layout.fits, true); assert.ok(layout.bottom <= layout.height); assert.equal(layout.scrolls, true); assert.ok(layout.transcript >= 24);
      await page.screenshot({ path: path.join(__dirname, `../.runtime/separate-prompts-${viewport.width}.png`), fullPage: true });
    }
    assert.deepEqual(errors, []);
    console.log('Conversation UI passed: Turbo and ComfyUI groups, parameters, responsive layout.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
