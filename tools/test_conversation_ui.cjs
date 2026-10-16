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
          if (name === 'load_settings') return { presets: [], fixedPrompt: '', generation: {}, revision: '' };
          if (name === 'generate_images') { window.testGenerations.push(value); return; }
          if (name === 'mobile_status') return { running: false, registered: false, url: '', code: '', message: '' };
          if (name === 'studio_jobs') return { jobs: [] };
        } },
        dialog: { open: async () => null }, event: { listen: async () => {} }
      };
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    assert.equal(await page.locator('#workflow-menu [data-value]').count(), 2);
    assert.equal(await page.locator('body').innerText().then(text => /ComfyUI|LoRA|Chroma|FLUX|Wan 2\.2/.test(text)), false);
    await page.click('#workflow-trigger'); await page.click('[data-value="reference"]');
    assert.match(await page.locator('#workflow-help').innerText(), /Qwen Image Turbo/);
    await page.click('#workflow-trigger'); await page.click('[data-value="quick"]');
    await page.fill('#prompt', '柔和花園'); await page.click('#send');
    assert.equal((await page.evaluate(() => window.testGenerations.at(-1))).workflow, 'quick');
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
    assert.deepEqual(errors, []);
    console.log('Conversation UI passed: Turbo-only modes and responsive layout.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
