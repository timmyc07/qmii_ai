// Real browser, isolated API fixtures; does not start the GPU service.
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  let settings = { presets: [], fixedPrompt: '共用固定提示', revision: '1' }, revision = 1;
  const submissions = [], jobs = [], errors = [];
  const server = http.createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    const reply = value => res.end(JSON.stringify(value));
    if (req.url === '/api/creation-library') {
      const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../config/creation_library.json'), 'utf8'));
      return reply({ ...catalog, templates: catalog.templates.map(item => ({ ...item, available: true })), loras: catalog.loras.map(item => ({ ...item, installed: true, available: true })) });
    }
    if (req.url === '/api/session') return reply({ csrf: 'fixture', ...settings });
    if (req.url === '/api/settings') {
      if (req.method === 'PUT') {
        assert.equal(req.headers['x-qianmi-csrf'], 'fixture');
        let body = ''; for await (const chunk of req) body += chunk;
        const value = JSON.parse(body);
        if (value.revision !== settings.revision) { res.statusCode = 409; return reply({ detail: '設定已由其他設備更新' }); }
        settings = { ...value, revision: String(++revision) };
      }
      return reply(settings);
    }
    if (req.url === '/api/jobs') {
      if (req.method === 'POST') {
        let body = ''; for await (const chunk of req) body += chunk;
        const value = JSON.parse(body); submissions.push(value);
        const job = { id: value.request_id, ...value, media_type: value.workflow.startsWith('wan') ? 'video' : 'image', sources: [], created: 1792000000, started: null, finished: null, status: 'queued', message: '已排隊', results: [] };
        jobs.push(job); return reply(job);
      }
      return reply({ jobs });
    }
    if (req.url.startsWith('/api/library?')) return reply({ items: [{ id: 'a'.repeat(64), url: '/static/icon-192.png', created: 1 }], next: null });
    const file = req.url === '/' ? 'index.html' : req.url.replace('/static/', '');
    if (!['index.html', 'mobile.js', 'mobile.css', 'icon-192.png'].includes(file)) { res.statusCode = 404; return res.end(); }
    res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.png') ? 'image/png' : 'text/html; charset=utf-8');
    res.end(fs.readFileSync(path.join(__dirname, '../mobile/static', file)));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage(); page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.waitForSelector('#studio:not(.hidden)');
    assert.equal(await page.locator('#fixed').inputValue(), '共用固定提示');
    await page.locator('.identity-settings summary').click();
    await page.fill('#identity-user', '<小迷>'); await page.fill('#identity-device', '測試手機'); await page.click('#save-identity');
    await page.click('#new-preset'); await page.fill('#preset-name', '花園'); await page.fill('#preset-prompt', '一座花園');
    await page.click('#preset-form button[type=submit]'); await page.waitForSelector('#preset-editor:not([open])', { state: 'attached' });
    assert.equal(settings.presets[0].prompt, '一座花園');
    await page.getByRole('button', { name: '花園', exact: true }).click();
    await page.waitForSelector('.job'); assert.equal(submissions[0].prompt, '共用固定提示\n\n一座花園');
    assert.equal(submissions[0].origin.user, '<小迷>');
    assert.equal(submissions[0].origin.device, '測試手機');
    assert.match(submissions[0].origin.platform, /網頁/);
    assert.match(await page.locator('.job-metadata').innerText(), /<小迷>/);
    const deviceId = submissions[0].origin.device_id;
    await page.selectOption('#workflow', 'chroma');
    await page.fill('#prompt', 'A blue ceramic teacup');
    await page.click('#send');
    await page.waitForFunction(() => document.querySelectorAll('.job').length === 2);
    assert.equal(submissions[1].workflow, 'chroma');
    assert.deepEqual(submissions[1].images, []);
    await page.reload(); await page.waitForSelector('.job');
    assert.equal(await page.locator('#identity-user').inputValue(), '<小迷>');
    assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('qianmi-identity')).device_id), deviceId);
    await page.getByRole('button', { name: '編輯花園', exact: true }).click();
    await page.fill('#preset-name', '新花園'); await page.click('#preset-form button[type=submit]');
    await page.getByRole('button', { name: '編輯新花園', exact: true }).click(); await page.click('#delete-preset');
    await page.waitForFunction(() => document.querySelector('#presets').children.length === 0);
    await page.fill('#fixed', '本機未儲存'); settings = { ...settings, fixedPrompt: '其他設備', revision: String(++revision) };
    await page.click('#save-settings'); await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('其他設備'));
    assert.equal(settings.fixedPrompt, '其他設備'); await page.click('#reload-settings');
    await page.waitForFunction(() => document.querySelector('#fixed').value === '其他設備');
    for (const width of [1440, 1280, 768, 390, 360]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Overflow at ${width}px`);
    }
    await page.click('#show-library'); await page.waitForSelector('.artwork-preview'); await page.click('.artwork-preview');
    assert.equal(await page.locator('#preview').evaluate(el => el.open), true);
    assert.equal(await page.locator('#preview-download').getAttribute('href'), '/static/icon-192.png');
    await page.click('#close-preview'); await page.click('#close-library');
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.screenshot({ path: path.join(__dirname, `../.runtime/studio-${width}.png`), fullPage: true });
    }
    await page.selectOption('#workflow', 'flux');
    for (const id of ['flux_figure', 'flux_anatomy', 'flux_undressing']) {
      await page.selectOption('#lora-choice', id); await page.locator('#lora-strength').fill('0.7');
      const count = submissions.length;
      await page.fill('#prompt', 'An adult portrait'); await page.click('#send');
      await page.waitForFunction(expected => document.querySelectorAll('.job').length === expected, count + 1);
      assert.equal(submissions.at(-1).workflow, 'flux');
      assert.equal(submissions.at(-1).lora, id); assert.equal(submissions.at(-1).lora_strength, .7);
    }
    await page.screenshot({ path: path.join(__dirname, '../.runtime/flux-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.selectOption('#workflow', 'wan');
    await page.locator('#parameter-panel summary').click();
    for (const [key, value] of Object.entries({ steps: '8', cfg: '2.7', frames: '49', fps: '24', seed: '123' })) {
      await page.fill(`[data-parameter="${key}"]`, value);
    }
    await page.click('#save-settings');
    assert.equal(settings.generation.wan.steps, 8);
    await page.fill('#prompt', 'A peaceful lake'); await page.click('#send');
    await page.waitForFunction(expected => document.querySelectorAll('.job').length === expected, submissions.length);
    assert.deepEqual(submissions.at(-1).parameters, { steps: 8, cfg: 2.7, frames: 49, fps: 24, seed: 123 });
    jobs.at(-1).results = ['/static/icon-192.png'];
    await page.evaluate(() => refresh());
    assert.equal(await page.locator(`.job[data-id="${jobs.at(-1).id}"] video[controls]`).count(), 1);
    await page.screenshot({ path: path.join(__dirname, '../.runtime/wan_parameters_mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log('Studio UI passed: shared settings, preset CRUD/run, conflict recovery, gallery preview/download, 1440/1280/768/390/360 layouts.');
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
