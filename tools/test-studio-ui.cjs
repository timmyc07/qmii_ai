const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const root = path.join(__dirname, '..', 'mobile', 'static');
  const submissions = [];
  const server = http.createServer((request, response) => {
    const reply = value => { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(value)); };
    if (request.url === '/api/session') return reply({ csrf: 'test', presets: [], preciseMode: false, generation: {}, revision: '' });
    if (request.url === '/api/jobs' && request.method === 'GET') return reply({ jobs: [] });
    if (request.url === '/api/settings') return reply({ presets: [], preciseMode: false, generation: {}, revision: '' });
    if (request.url === '/api/uploads' && request.method === 'POST') return reply({ id: 'a'.repeat(32), url: '/a.png' });
    if (request.url === '/api/jobs' && request.method === 'POST') {
      let body = ''; request.on('data', value => body += value); request.on('end', () => {
        const value = JSON.parse(body); submissions.push(value);
        reply({ id: value.request_id, ...value, media_type: 'image', sources: [], created: 1, status: 'queued', message: '已排隊', results: [] });
      }); return;
    }
    const file = request.url === '/' ? 'index.html' : request.url.replace('/static/', '');
    const target = path.join(root, file);
    if (!target.startsWith(root) || !fs.existsSync(target)) return response.writeHead(404).end();
    response.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html; charset=utf-8');
    response.end(fs.readFileSync(target));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, channel: 'msedge' });
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.evaluate(() => window.localStorage.clear());
    await page.reload();
    assert.equal(await page.locator('#workflow option').count(), 4);
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 6);
    assert.match(await page.locator('#generation-parameters').textContent(), /調高.*調低/s);
    await page.selectOption('#workflow', 'superduper');
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 7);
    assert.equal(await page.locator('#files').isDisabled(), false);
    await page.selectOption('#workflow', 'nsfw_adv');
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 9);
    assert.equal(await page.locator('#files').isDisabled(), false);
    await page.check('#precise-mode');
    for (const workflow of ['quick', 'reference', 'superduper', 'nsfw_adv']) {
      await page.reload();
      await page.selectOption('#workflow', workflow);
      await page.check('#precise-mode');
      assert.equal(await page.locator('#files').isDisabled(), false);
      await page.locator('#files').setInputFiles([
        { name: 'a.png', mimeType: 'image/png', buffer: Buffer.from('test source a') },
        { name: 'b.png', mimeType: 'image/png', buffer: Buffer.from('test source b') }
      ]);
      await page.fill('#prompt', '  柔和花園\n"Hello, 世界!"  ');
      await Promise.all([
        page.waitForResponse(response => response.url().endsWith('/api/jobs') && response.request().method() === 'POST'),
        page.click('#send')
      ]);
      assert.equal(submissions.at(-1).workflow, workflow);
      assert.equal(submissions.at(-1).images.length, 2);
      assert.equal(submissions.at(-1).prompt, '  柔和花園\n"Hello, 世界!"  ');
      assert.equal(submissions.at(-1).precise_mode, true);
    }
    console.log('Mobile studio UI passed: Turbo, ComfyUI groups, and precise mode.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
