const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const root = path.join(__dirname, '..', 'mobile', 'static');
  const submissions = [];
  const jobs = [];
  const cancelled = [];
  let recipes = [], uploads = 0;
  let settings = { presets: [], preciseMode: false, generation: {}, revision: '' };
  const server = http.createServer((request, response) => {
    const reply = value => { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(value)); };
    const member = { id: 'a'.repeat(32), name: '測試會員', email: 'test@example.com', role: 'admin', balance: 1000 };
    if (request.url === '/api/session') return reply({ csrf: 'test', member, ...settings });
    if (request.url === '/api/membership') return reply({ initialized: true, registration_open: true, image_points: 3, video_points: 10 });
    if (request.url === '/api/membership/me') return reply({ member, image_points: 3, video_points: 10 });
    if (request.url === '/api/membership/ledger?offset=0') return reply({ items: [] });
    if (request.url === '/api/jobs' && request.method === 'GET') return reply({ jobs });
    if (/^\/api\/jobs\/[^/]+\/cancel$/.test(request.url)) {
      const id = request.url.split('/')[3]; cancelled.push(id);
      const job = jobs.find(job => job.id === id); job.status = 'cancelled'; job.message = '任務已終止'; reply(job); return;
    }
    if (request.url === '/api/settings') {
      if (request.method === 'PUT') {
        let body = ''; request.on('data', value => body += value); request.on('end', () => { settings = { ...JSON.parse(body), revision: 'saved' }; reply(settings); }); return;
      }
      return reply(settings);
    }
    if (request.url === '/api/uploads' && request.method === 'POST') return reply({ id: (++uploads).toString(16).padStart(32, '0'), url: '/a.png' });
    if (request.url === '/api/recipes') {
      if (request.method === 'POST') {
        let body = ''; request.on('data', value => body += value); request.on('end', () => { recipes.push({ id: 'c'.repeat(32), ...JSON.parse(body) }); reply({ recipes }); }); return;
      }
      return reply({ recipes });
    }
    if (request.url.startsWith('/api/recipes/') && request.method === 'DELETE') { recipes = recipes.filter(item => item.id !== request.url.split('/').pop()); return reply({ recipes }); }
    if (request.url === '/api/jobs' && request.method === 'POST') {
      let body = ''; request.on('data', value => body += value); request.on('end', () => {
        const value = JSON.parse(body); submissions.push(value);
        jobs.forEach(job => { job.status = 'completed'; });
        const job = { id: value.request_id, ...value, media_type: 'image', sources: [], created: 1, status: 'running', message: '正在生成', result_files: [], results: [] };
        jobs.push(job); reply(job);
      }); return;
    }
    const file = request.url === '/' ? 'index.html' : request.url.replace('/static/', '');
    const shared = ['membership.js', 'membership.css', 'taskprogress.js', 'taskprogress.css'].includes(file);
    const target = path.join(shared ? path.join(__dirname, '..', 'src') : root, file);
    if ((!shared && !target.startsWith(root)) || !fs.existsSync(target)) return response.writeHead(404).end();
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
    assert.equal(await page.locator('#workflow option').count(), 5);
    assert.equal(await page.locator('#image-refmod').isDisabled(), true);
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 5);
    assert.match(await page.locator('#generation-parameters').textContent(), /調高.*調低/s);
    await page.selectOption('#workflow', 'superduper');
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 6);
    assert.equal(await page.locator('#files').isDisabled(), false);
    await page.selectOption('#workflow', 'nsfw_adv');
    assert.equal(await page.locator('#generation-parameters [data-parameter]').count(), 8);
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
      await page.fill('#negative-prompt', '  模糊\n<水印>  ');
      await Promise.all([
        page.waitForResponse(response => response.url().endsWith('/api/jobs') && response.request().method() === 'POST'),
        page.click('#send')
      ]);
      assert.equal(submissions.at(-1).workflow, workflow);
      assert.equal(submissions.at(-1).images.length, 2);
      assert.equal(submissions.at(-1).prompt, '  柔和花園\n"Hello, 世界!"  ');
      assert.equal(submissions.at(-1).precise_mode, true);
      assert.equal(submissions.at(-1).parameters.negative, '  模糊\n<水印>  ');
    }
    await page.click('#new-preset');
    await page.fill('#preset-name', '正負模板'); await page.fill('#preset-prompt', '花園'); await page.fill('#preset-negative', '模糊\n<水印>');
    await page.click('#preset-form button[type="submit"]');
    await page.waitForSelector('#preset-editor', { state: 'hidden' });
    assert.equal(settings.presets[0].negative, '模糊\n<水印>');
    await page.reload();
    await page.locator('#presets .preset-row button').first().click();
    await page.waitForFunction(() => !document.querySelector('#send').disabled);
    assert.equal(submissions.at(-1).prompt, '花園');
    assert.equal(submissions.at(-1).parameters.negative, '模糊\n<水印>');
    await page.locator('#presets .preset-row button').nth(1).click();
    assert.equal(await page.locator('#preset-negative').inputValue(), '模糊\n<水印>');
    await page.fill('#preset-negative', ''); await page.click('#preset-form button[type="submit"]');
    await page.waitForSelector('#preset-editor', { state: 'hidden' });
    await page.fill('#negative-prompt', '上一筆負面提示詞');
    await page.locator('#presets .preset-row button').first().click();
    await page.waitForFunction(() => !document.querySelector('#send').disabled);
    assert.equal(submissions.at(-1).parameters.negative, '');
    assert.equal(await page.locator('#cancel-generation').isVisible(), true);
    const lastId = submissions.at(-1).request_id;
    await page.click('#cancel-generation');
    await page.waitForSelector('#cancel-generation', { state: 'hidden' });
    assert.equal(cancelled.at(-1), lastId);
    await page.selectOption('#workflow', 'h3_image');
    assert.equal(await page.locator('#negative-prompt').isVisible(), false);
    assert.equal(await page.locator('#precise-mode').isDisabled(), true);
    await page.locator('#parameter-panel summary').click();
    await page.selectOption('[data-parameter="video_profile"]', 'turbo8');
    await page.selectOption('[data-parameter="end_frame"]', 'custom');
    for (const width of [390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
    await page.screenshot({ path: path.join(__dirname, '../.runtime/mobile-h3.png'), animations: 'disabled' });
    await page.setViewportSize({ width: 1280, height: 820 });
    await page.locator('#files').setInputFiles(Array.from({ length: 4 }, (_, i) => ({ name: `first${i}.png`, mimeType: 'image/png', buffer: Buffer.from(`first${i}`) })));
    await page.locator('#last-file').setInputFiles({ name: 'end.png', mimeType: 'image/png', buffer: Buffer.from('last frame') });
    await page.fill('#prompt', '轉頭並微笑');
    await page.click('#show-recipes'); await page.fill('#recipe-name', '有聲批次'); await page.click('#save-recipe');
    await page.waitForFunction(() => document.querySelector('#recipe-list').textContent.includes('有聲批次'));
    await page.click('#close-recipes');
    await page.click('#send'); await page.waitForFunction(() => !document.querySelector('#send').disabled);
    assert.equal(submissions.at(-1).workflow, 'h3_image');
    assert.equal(submissions.at(-1).images.length, 4);
    assert.ok(submissions.at(-1).last_image);
    assert.equal(submissions.at(-1).parameters.steps, 8);
    assert.equal(submissions.at(-1).parameters.video_profile, 'turbo8');
    assert.equal(submissions.at(-1).parameters.end_frame, 'custom');
    assert.equal('negative' in submissions.at(-1).parameters, false);
    assert.equal(submissions.at(-1).precise_mode, false);
    await page.selectOption('#workflow', 'quick');
    await page.click('#show-recipes'); await page.locator('#recipe-list button').first().click();
    assert.equal(await page.locator('#workflow').inputValue(), 'h3_image');
    assert.equal(await page.locator('#prompt').inputValue(), '轉頭並微笑');
    assert.equal(await page.locator('#tray img').count(), 0);
    await page.click('#show-recipes'); await page.locator('#recipe-list button').nth(1).click();
    await page.waitForFunction(() => document.querySelector('#recipe-list').childElementCount === 0);
    await page.click('#close-recipes'); await page.selectOption('#workflow', 'quick');
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 }); await page.waitForTimeout(350);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.locator('#negative-prompt').isVisible(), true);
    }
    await page.evaluate(() => {
      window.progressFixture = { id: 'f'.repeat(32), workflow: 'quick', parameters: {}, prompt: '進度測試', sources: [],
        results: [], result_files: [], status: 'queued', message: '已排隊',
        progress: { elapsed_seconds: 10, queue_position: 3, completed: 0, total: 1 } };
      renderJob(window.progressFixture);
    });
    const progressStatus = page.locator('.job-status').last();
    assert.match(await progressStatus.innerText(), /排隊第 3 位（前方 2 個任務）/);
    await page.evaluate(() => renderJob({ ...window.progressFixture, status: 'running', message: '正在載入模型…' }));
    assert.match(await progressStatus.innerText(), /暫無法估算/);
    await page.evaluate(() => renderJob({ ...window.progressFixture, status: 'running', message: '正在生成圖片…',
      progress: { elapsed_seconds: 85, running_seconds: 80, estimated_seconds: 180, sample_count: 2, completed: 0, total: 1 } }));
    assert.match(await progressStatus.innerText(), /預計剩餘約/);
    await page.evaluate(() => renderJob({ ...window.progressFixture, status: 'running', message: '正在生成第二段影片…',
      progress: { elapsed_seconds: 85, completed: 0, total: 1,
        sampling: { label: '第 2/3 段 · 低噪採樣', step: 2, total: 4, seconds_per_step: 3, remaining_seconds: 6, age_seconds: 0, state: 'sampling' } } }));
    assert.match(await progressStatus.innerText(), /第 2 \/ 4 步/);
    assert.match(await progressStatus.innerText(), /每步約 3.00 秒/);
    assert.match(await progressStatus.innerText(), /本輪採樣預計剩餘約/);
    await progressStatus.evaluate(element => { element.taskProgress.received -= 2000; });
    await page.waitForTimeout(1100);
    assert.match(await progressStatus.innerText(), /本輪採樣預計剩餘約 [1-4] 秒/);
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      await progressStatus.evaluate(element => window.scrollTo(0, scrollY + element.getBoundingClientRect().top - 100));
      assert.equal(await progressStatus.evaluate(element => element.scrollWidth <= element.clientWidth), true);
      await page.screenshot({ path: path.join(__dirname, `../.runtime/mobile-task-progress-${width}.png`), fullPage: true, animations: 'disabled' });
      await progressStatus.screenshot({ path: path.join(__dirname, `../.runtime/mobile-sampling-${width}.png`), animations: 'disabled' });
    }
    await page.evaluate(() => renderJob({ ...window.progressFixture, status: 'running',
      progress: { elapsed_seconds: 100, sampling: { label: '本輪採樣', step: 4, total: 4, state: 'complete' } } }));
    assert.match(await progressStatus.innerText(), /本輪採樣完成，等待後續處理/);
    assert.doesNotMatch(await progressStatus.innerText(), /預計剩餘約/);
    await page.evaluate(() => renderJob({ ...window.progressFixture, status: 'running',
      progress: { elapsed_seconds: 100, sampling: { state: 'disconnected' } } }));
    assert.match(await progressStatus.innerText(), /即時採樣連線中斷/);
    assert.equal(await progressStatus.locator('progress').isVisible(), false);
    await page.evaluate(() => renderJob({ ...window.progressFixture, status: 'running',
      progress: { elapsed_seconds: 200, running_seconds: 190, estimated_seconds: 180, sample_count: 2 } }));
    assert.match(await progressStatus.innerText(), /已超過歷史估時/);
    await page.evaluate(() => renderJob({ ...window.progressFixture, status: 'completed', message: '圖片完成',
      progress: { elapsed_seconds: 200, completed: 1, total: 1 } }));
    assert.equal(await progressStatus.locator('.task-spinner').isVisible(), false);
    const finishedText = await progressStatus.innerText();
    await progressStatus.evaluate(element => { element.taskProgress.received -= 20000; });
    await page.waitForTimeout(1100);
    assert.equal(await progressStatus.innerText(), finishedText);
    console.log('Mobile studio UI passed: workflows, progress, ETA, queue, terminal timing and responsive layout.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
