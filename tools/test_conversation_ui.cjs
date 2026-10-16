const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const source = path.join(__dirname, '..', 'src');
  const server = http.createServer((request, response) => {
    const file = { '/': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css' }[request.url];
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
      window.testGenerations = [];
      window.__TAURI__ = {
        core: { convertFileSrc: value => value, invoke: async (name, value) => {
          if (name === 'load_settings') return { presets: [], preciseMode: false, generation: {}, revision: '' };
          if (name === 'generate_images') { window.testGenerations.push(value); return; }
          if (name === 'mobile_status') return { running: false, registered: false, url: '', code: '', message: '' };
          if (name === 'studio_jobs') return { jobs: [] };
        } },
        dialog: { open: async () => window.testPickedImages || null }, event: { listen: async () => {} }
      };
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    assert.equal(await page.locator('#workflow-menu [data-value]').count(), 4);
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 6);
    assert.match(await page.locator('#generation-parameters').innerText(), /寬度 Width/);
    assert.match(await page.locator('#generation-parameters').innerText(), /調高.*調低/s);
    await page.click('#workflow-trigger'); await page.click('[data-value="superduper"]');
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 7);
    assert.match(await page.locator('#workflow-help').innerText(), /ComfyUI/);
    await page.click('#workflow-trigger'); await page.click('[data-value="nsfw_adv"]');
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 9);
    assert.equal(await page.locator('#upload-images').isDisabled(), false);
    assert.match(await page.locator('#workflow-help').innerText(), /LoKr/);
    await page.click('#workflow-trigger'); await page.click('[data-value="reference"]');
    assert.match(await page.locator('#workflow-help').innerText(), /Qwen Image Turbo/);
    await page.click('#workflow-trigger'); await page.click('[data-value="quick"]');
    await page.fill('#prompt', '柔和花園'); await page.click('#send');
    assert.equal((await page.evaluate(() => window.testGenerations.at(-1))).workflow, 'quick');
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
    await page.setViewportSize({ width: 1280, height: 820 });
    for (const workflow of ['quick', 'reference', 'superduper', 'nsfw_adv']) {
      await page.reload();
      await page.click('#workflow-trigger'); await page.click(`[data-value="${workflow}"]`);
      assert.equal(await page.locator('#upload-images').isDisabled(), false);
      await page.evaluate(() => { window.testPickedImages = ['/a.png', '/b.png']; });
      await page.click('#upload-images');
      assert.equal(await page.locator('#image-tray .thumb-wrap').count(), 2);
      await page.fill('#prompt', '柔和花園'); await page.click('#send');
      const submitted = await page.evaluate(() => window.testGenerations.at(-1));
      assert.equal(submitted.workflow, workflow);
      assert.deepEqual(submitted.images, ['/a.png', '/b.png']);
      assert.equal(submitted.prompt, '柔和花園');
    }
    assert.deepEqual(errors, []);
    console.log('Conversation UI passed: Turbo and ComfyUI groups, parameters, responsive layout.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
