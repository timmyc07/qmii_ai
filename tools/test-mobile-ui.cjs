// Run with Playwright available on NODE_PATH; no browser or cloud credentials used.
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const source = path.join(__dirname, '..', 'src');
  const server = http.createServer((request, response) => {
    if (/^\/(fixture|second|third|fourth|last)\.png$/.test(request.url)) {
      response.setHeader('Content-Type', 'image/svg+xml');
      response.end('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="240"><rect width="160" height="240" fill="#dbcdf4"/><circle cx="110" cy="65" r="25" fill="#fff0c5"/><path d="M0 180L55 100L160 230V240H0" fill="#a59bc9"/></svg>'); return;
    }
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
      let settings = { presets: [], preciseMode: false, generation: {}, revision: '' };
      const stopped = { running: false, registered: false, url: '', code: '', message: '手機連線尚未開啟。' };
      window.testMobile = { info: stopped, pending: null, fail: false, calls: [] };
      window.__TAURI__ = {
        core: {
          convertFileSrc: value => value,
          invoke: async (name, args) => {
            const test = window.testMobile;
            test.calls.push(name);
            if (name === 'load_settings') return structuredClone(settings);
            if (name === 'save_settings') { settings = structuredClone({ ...args.settings, revision: 'saved' }); return structuredClone(settings); }
            if (name === 'generate_images') { test.generation = args; return; }
            if (name === 'google_drive') {
              if (args.action === 'save') test.drive = args.value;
              if (args.action === 'connect') { test.oauthPath = args.value.path; return { connected: true, message: '授權完成' }; }
              return { enabled: true, folder_id: '1LQUNBvxtG6ONE7hAO_s8m6l5eicsRlza', message: '等待 Google Drive 授權。', ...test.drive };
            }
            if (name === 'import_svi_lora') {
              test.importPath = args.path;
              if (test.deferImport) await new Promise(resolve => { test.finishImport = resolve; });
              return { name: 'svi_custom/' + (args.path.includes('High') ? 'a' : 'b').repeat(64) + '/' + args.path.split('/').pop() };
            }
            if (name === 'cancel_generation') { test.cancelled = args.jobId; test.sharedStatus = 'cancelled'; return; }
            if (name === 'studio_jobs') return { jobs: [{ id: 'b'.repeat(32), status: test.sharedStatus || 'running', workflow: 'quick', prompt: '其他設備提交', message: '已排隊', created: 1792000000, started: 1792000001, finished: 1792000010, origin: { platform: 'Windows 桌面', device: '<測試電腦>', user: '小迷', device_id: 'fixture-device' }, results: [] }] };
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
        }, dialog: { open: async options => { window.testMobile.openOptions = options; return window.testMobile.openPath || null; } }, event: { listen: async (name, handler) => { if (name === 'generation-progress') window.testMobile.progress = handler; } }
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
    assert.equal(await page.locator('[data-cancel-job]').count(), 1);
    assert.equal(await page.locator('[data-cancel-job]').isEnabled(), true);
    await page.locator('#shared-job-list summary').click();
    assert.match(await page.locator('.job-prompt').first().innerText(), /其他設備提交/);
    assert.equal(await page.locator('.job-prompt').nth(1).innerText(), '未填寫');
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.locator('.modal').evaluate(el => el.scrollWidth <= el.clientWidth), true);
      if (width !== 360) await page.screenshot({ path: path.join(__dirname, `../.runtime/shared-jobs-${width}.png`), fullPage: true });
    }
    await page.click('[data-cancel-job]');
    await page.waitForFunction(() => window.testMobile.cancelled === 'b'.repeat(32));
    await page.waitForSelector('[data-cancel-job]', { state: 'detached' });
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
    await page.fill('#negative-prompt', '圖片負面草稿');
    await page.click('[data-studio-mode="h3_image"]');
    assert.equal(await page.locator('#conversation').isVisible(), true);
    assert.equal(await page.locator('.composer-area').isVisible(), true);
    assert.equal(await page.locator('#video-form').isVisible(), true);
    assert.equal(await page.locator('#video-refmod').isChecked(), false);
    await page.check('#video-refmod');
    assert.equal(await page.locator('#negative-prompt').isDisabled(), true);
    assert.equal(await page.locator('#negative-prompt').inputValue(), '');
    assert.equal(await page.locator('#negative-label').isVisible(), false);
    assert.equal(await page.locator('#negative-prompt').isVisible(), false);
    assert.equal(await page.locator('[data-studio-mode]').count(), 3);
    await page.fill('#video-duration', '6');
    await page.click('#video-save-settings');
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('已儲存'));
    await page.evaluate(() => { window.testMobile.openPath = '/fixture.png'; });
    await page.click('#upload-images');
    await page.waitForSelector('#image-tray img');
    assert.equal(await page.evaluate(() => window.testMobile.openOptions.multiple), true);
    assert.match(await page.locator('#batch-label').innerText(), /1 張首幀.*每張各自生成一支影片/);
    await page.click('#video-example');
    assert.match(await page.locator('#prompt').inputValue(), /00:06\.000/);
    await page.fill('#video-seed', '42');
    await page.click('[data-studio-mode="image"]');
    assert.equal(await page.locator('#prompt').inputValue(), '圖片草稿');
    assert.equal(await page.locator('#negative-prompt').inputValue(), '圖片負面草稿');
    await page.click('[data-studio-mode="h3_image"]');
    assert.equal(await page.locator('#video-duration').inputValue(), '6');
    assert.equal(await page.locator('#video-seed').inputValue(), '42');
    await page.click('#send');
    const submitted = await page.evaluate(() => window.testMobile.generation);
    assert.equal(submitted.workflow, 'h3_image');
    assert.deepEqual(submitted.images, ['/fixture.png']);
    assert.equal(submitted.lastImage, null);
    assert.equal(submitted.parameters.duration, 6);
    assert.equal(submitted.parameters.seed, 42);
    assert.equal(submitted.preciseMode, false);
    assert.equal(submitted.parameters.video_profile, 'turbo4');
    assert.equal(submitted.parameters.shift_video, 6);
    assert.equal(submitted.parameters.refmod, true);
    assert.ok(!('negative' in submitted.parameters));
    assert.equal(await page.locator('#video-results-h3_image .user-message .reference-prompt').count(), 0);
    assert.equal(await page.locator('#video-results-h3_image .user-message img').count(), 1);
    assert.equal(await page.locator('#cancel-generation').isVisible(), true);
    assert.equal(await page.locator('#cancel-generation').isEnabled(), true);
    await page.click('#cancel-generation');
    assert.equal(await page.evaluate(() => window.testMobile.cancelled), 'b'.repeat(32));
    assert.equal(await page.locator('#cancel-generation').isDisabled(), true);
    await page.evaluate(() => window.testMobile.progress({ payload: { jobId: 'a'.repeat(32), index: 0, total: 1, message: '正在生成', done: false } }));
    await page.waitForFunction(() => window.testMobile.cancelled === 'a'.repeat(32));
    const cancelCount = await page.evaluate(() => window.testMobile.calls.filter(name => name === 'cancel_generation').length);
    await page.evaluate(() => window.testMobile.progress({ payload: { jobId: 'a'.repeat(32), index: 0, total: 1, message: '正在生成', done: false } }));
    assert.equal(await page.evaluate(() => window.testMobile.calls.filter(name => name === 'cancel_generation').length), cancelCount);
    assert.equal(await page.evaluate(() => window.testMobile.cancelled), 'a'.repeat(32));
    assert.equal(await page.locator('#cancel-generation').isDisabled(), true);
    await page.click('[data-studio-mode="image"]');
    await page.evaluate(() => window.testMobile.progress({ payload: { video: '/fixture.mp4', index: 1, total: 1, message: '影片完成', done: true } }));
    assert.equal(await page.locator('#video-results-h3_image video[controls]').count(), 1);
    assert.equal(await page.locator('#feed video').count(), 0);
    assert.equal(await page.locator('#cancel-generation').isVisible(), false);
    await page.click('[data-studio-mode="h3_image"]');
    await page.selectOption('#video-profile', 'turbo8');
    assert.equal(await page.locator('#video-steps').inputValue(), '8');
    assert.equal(await page.locator('#video-shift-video').inputValue(), '12');
    await page.selectOption('#video-profile', 'base');
    await page.locator('#video-advanced summary').click();
    assert.equal(await page.locator('#video-lora').isDisabled(), true);
    await page.fill('#video-steps', '25');
    await page.fill('#video-crf', '23');
    await page.selectOption('#video-crop', 'disabled');
    await page.uncheck('#video-audio');
    await page.check('#video-identity');
    await page.selectOption('#video-end-frame', 'custom');
    await page.evaluate(() => { window.testMobile.openPath = ['/fixture.png', '/second.png', '/third.png', '/fourth.png', '/overflow.png']; });
    await page.click('#upload-images');
    assert.equal(await page.locator('#image-tray img').count(), 4);
    assert.match(await page.locator('#batch-label').innerText(), /4 張首幀.*每張各自生成一支影片/);
    assert.match(await page.locator('#toast').innerText(), /最多 4 張/);
    await page.fill('#prompt', 'cat blinks');
    await page.click('#send');
    assert.match(await page.locator('#toast').innerText(), /請選擇尾幀圖片/);
    assert.equal(await page.evaluate(() => window.testMobile.calls.filter(name => name === 'generate_images').length), 1);
    await page.evaluate(() => { window.testMobile.openPath = '/last.png'; });
    await page.click('#video-last-upload');
    assert.equal(await page.evaluate(() => window.testMobile.openOptions.multiple), false);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 820 });
      await page.waitForTimeout(350);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.locator('#image-tray img').count(), 4);
      await page.screenshot({ path: path.join(__dirname, `../.runtime/h3-batch-preview-${width}.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 1280, height: 820 });
    await page.waitForTimeout(350);
    await page.fill('#prompt', 'cat blinks');
    await page.click('#send');
    const custom = await page.evaluate(() => window.testMobile.generation);
    assert.deepEqual(custom.images, ['/fixture.png', '/second.png', '/third.png', '/fourth.png']);
    assert.equal(custom.lastImage, '/last.png');
    assert.equal(custom.parameters.steps, 25);
    assert.equal(custom.parameters.video_audio, false);
    assert.equal(custom.parameters.identity_prompt, true);
    assert.equal(custom.parameters.crop, 'disabled');
    assert.equal(custom.parameters.video_crf, 23);
    assert.ok(!('lora_strength' in custom.parameters));
    assert.equal(await page.locator('#video-results-h3_image .user-message').last().innerText(), '');
    assert.equal(await page.locator('#video-results-h3_image .user-message').last().locator('img').count(), 5);
    await page.evaluate(() => window.testMobile.progress({ payload: { video: '/first.mp4', index: 1, total: 4, message: '已完成 1/4 支影片', done: false } }));
    assert.match(await page.locator('.progress-card').innerText(), /1\/4/);
    assert.equal(await page.locator('#send').isDisabled(), true);
    await page.evaluate(() => window.testMobile.progress({ payload: { index: 1, total: 4, message: '第 2/4 支影片生成失敗，已保留 1 支完成的影片。', error: '第 2/4 支影片生成失敗', done: true } }));
    assert.equal(await page.locator('#video-results-h3_image video[controls]').count(), 2);
    assert.match(await page.locator('.error-card').innerText(), /已保留 1 支/);
    assert.equal(await page.locator('#send').isDisabled(), false);
    await page.selectOption('#video-end-frame', 'first');
    await page.fill('#prompt', 'return to each starting pose');
    await page.click('#send');
    const loop = await page.evaluate(() => window.testMobile.generation);
    assert.equal(loop.images.length, 4);
    assert.equal(loop.lastImage, null);
    assert.equal(loop.parameters.end_frame, 'first');
    for (let index = 1; index <= 4; index++) {
      await page.evaluate(index => window.testMobile.progress({ payload: { video: `/batch-${index}.mp4`, index, total: 4, message: `已完成 ${index}/4 支影片`, done: index === 4 } }), index);
    }
    assert.equal(await page.locator('#video-results-h3_image video[controls]').count(), 6);
    assert.equal(new Set(await page.locator('#video-results-h3_image video').evaluateAll(nodes => nodes.map(node => node.src))).size, 6);
    await page.click('#video-reset-settings');
    assert.equal(await page.locator('#video-profile').inputValue(), 'turbo4');
    assert.equal(await page.locator('#video-end-frame').inputValue(), 'none');
    assert.equal(await page.locator('#video-refmod').isChecked(), false);
    await page.locator('#video-advanced summary').click();
    await page.evaluate(() => {
      const target = document.querySelector('#video-results-h3_image');
      for (let index = 0; index < 10; index++) {
        const message = document.createElement('article'); message.className = 'message user-message';
        message.textContent = `鏡頭 ${index + 1}：` + '橘貓在窗邊轉頭，微風吹動窗簾。\n'.repeat(60);
        target.appendChild(message);
      }
    });
    await page.waitForFunction(() => document.querySelector('#conversation').scrollHeight > document.querySelector('#conversation').clientHeight * 3);
    for (const viewport of [{ width: 1280, height: 820 }, { width: 390, height: 820 }, { width: 360, height: 520 }]) {
      await page.setViewportSize(viewport);
      const geometry = await page.evaluate(() => {
        const conversation = document.querySelector('#conversation').getBoundingClientRect();
        const composer = document.querySelector('.composer-area').getBoundingClientRect();
        return { top: conversation.top, bottom: conversation.bottom, composerTop: composer.top, composerBottom: composer.bottom, height: innerHeight };
      });
      assert.ok(geometry.bottom <= geometry.composerTop + 1, 'Transcript must end above the fixed composer');
      assert.ok(geometry.bottom - geometry.top >= 24, `Transcript must remain readable: ${JSON.stringify(geometry)}`);
      assert.ok(geometry.composerBottom <= geometry.height, 'Long video history must not push composer out of view');
      await page.locator('#conversation').evaluate(el => { el.scrollTop = el.scrollHeight; });
      await page.waitForFunction(() => document.querySelector('#latest-message').classList.contains('hidden'));
      await page.locator('#conversation').hover(); await page.mouse.wheel(0, -700);
      await page.waitForFunction(() => !document.querySelector('#latest-message').classList.contains('hidden'));
      await page.waitForTimeout(250);
      const olderPosition = await page.locator('#conversation').evaluate(el => el.scrollTop);
      await page.evaluate(() => window.testMobile.progress({ payload: { video: '/fixture.mp4', index: 1, total: 1, message: '影片完成', done: true } }));
      await page.waitForTimeout(350);
      assert.ok(Math.abs(await page.locator('#conversation').evaluate(el => el.scrollTop) - olderPosition) < 2, 'New video must not pull user away from older messages');
      await page.click('[data-studio-mode="image"]'); await page.click('[data-studio-mode="h3_image"]');
      await page.waitForTimeout(100);
      assert.ok(Math.abs(await page.locator('#conversation').evaluate(el => el.scrollTop) - olderPosition) < 2, 'Mode switching must preserve reading position');
      await page.click('#latest-message');
      await page.waitForFunction(() => {
        const el = document.querySelector('#conversation'); return el.scrollHeight - el.clientHeight - el.scrollTop <= 2;
      });
      await page.fill('#prompt', '影片草稿\n'.repeat(120));
      assert.ok(await page.locator('#prompt').evaluate(el => el.scrollHeight > el.clientHeight), 'Long drafts must scroll inside the composer');
      assert.ok(await page.locator('.composer-area').evaluate(el => el.getBoundingClientRect().bottom <= innerHeight), 'Long drafts must keep send controls visible');
      await page.fill('#prompt', '影片草稿');
    }
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.querySelector('#conversation').scrollWidth <= document.querySelector('#conversation').clientWidth), true, `Video page overflows at ${width}px`);
      await page.locator('#conversation').evaluate(el => { el.scrollTop = 0; });
      await page.waitForTimeout(350);
      if (width !== 360) await page.screenshot({ path: path.join(__dirname, `../.runtime/h3-video-${width}.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 1280, height: 820 });
    await page.click('[data-studio-mode="svi_image"]');
    assert.equal(await page.locator('#svi-prompts').isVisible(), true);
    assert.equal(await page.locator('#latest-message').isVisible(), false);
    assert.match(await page.locator('#prompt-label').innerText(), /第一段/);
    await page.fill('#prompt', 'A cat blinks.');
    await page.click('#send');
    assert.match(await page.locator('#toast').innerText(), /完整填寫三段/);
    await page.fill('#svi-prompt-2', 'The cat stretches.');
    await page.fill('#svi-prompt-3', 'The cat settles down.');
    await page.fill('#negative-prompt', 'blur');
    await page.fill('#svi-seed', '42');
    assert.equal(await page.evaluate(() => state.generation.svi_image.seed), 42, 'Seed must update before importing');
    await page.evaluate(() => { window.testMobile.openPath = 'D:/models/HighStyle.safetensors'; window.testMobile.deferImport = true; });
    await page.click('#svi-high-lora-pick');
    await page.waitForFunction(() => Boolean(window.testMobile.finishImport));
    assert.equal(await page.locator('#send').isDisabled(), true);
    assert.equal(await page.locator('#svi-low-lora-pick').isDisabled(), true);
    await page.evaluate(() => { window.testMobile.deferImport = false; window.testMobile.finishImport(); });
    await page.waitForFunction(() => !document.querySelector('#send').disabled);
    assert.equal(await page.evaluate(() => window.testMobile.openOptions.multiple), false);
    assert.deepEqual(await page.evaluate(() => window.testMobile.openOptions.filters[0].extensions), ['safetensors']);
    assert.equal(await page.locator('#svi-high-lora-name').innerText(), 'HighStyle.safetensors');
    await page.fill('#svi-high-lora-strength', '0.4');
    await page.evaluate(() => { window.testMobile.openPath = 'D:/models/LowStyle.safetensors'; });
    await page.click('#svi-low-lora-pick');
    await page.waitForFunction(() => !document.querySelector('#svi-low-lora-strength').disabled);
    await page.fill('#svi-low-lora-strength', '-0.2');
    await page.click('#svi-high-lora-clear');
    assert.equal(await page.locator('#svi-high-lora-strength').isDisabled(), true);
    assert.equal(await page.locator('#svi-low-lora-name').innerText(), 'LowStyle.safetensors');
    await page.evaluate(() => { window.testMobile.openPath = 'D:/models/HighStyle.safetensors'; });
    await page.click('#svi-high-lora-pick');
    await page.waitForFunction(() => !document.querySelector('#svi-high-lora-strength').disabled);
    await page.fill('#svi-high-lora-strength', '0.4');
    await page.click('#svi-save-settings');
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('高耗能模式預設已儲存'));
    assert.equal(await page.evaluate(() => state.generation.svi_image.seed), 42, 'Seed must survive importing and saving');
    assert.equal(await page.evaluate(() => state.generation.svi_image.negative), 'blur', 'Negative must survive importing and saving');
    await page.waitForTimeout(5100);
    assert.equal(await page.locator('#negative-prompt').inputValue(), 'blur', 'Settings polling must preserve the saved negative prompt');
    await page.click('[data-studio-mode="image"]');
    await page.click('[data-studio-mode="svi_image"]');
    assert.equal(await page.locator('#prompt').inputValue(), 'A cat blinks.');
    assert.equal(await page.locator('#svi-prompt-2').inputValue(), 'The cat stretches.');
    assert.equal(await page.locator('#svi-prompt-3').inputValue(), 'The cat settles down.');
    assert.equal(await page.locator('#negative-prompt').inputValue(), 'blur');
    assert.equal(await page.locator('#svi-high-lora-strength').inputValue(), '0.4');
    assert.equal(await page.locator('#svi-low-lora-strength').inputValue(), '-0.2');
    await page.evaluate(() => { window.testMobile.openPath = '/fixture.png'; });
    await page.click('#upload-images');
    assert.equal(await page.evaluate(() => window.testMobile.openOptions.multiple), false);
    await page.evaluate(() => { window.testMobile.openPath = '/second.png'; });
    await page.click('#upload-images');
    assert.equal(await page.locator('#image-tray img').count(), 1);
    assert.equal(await page.locator('#negative-prompt').inputValue(), 'blur', 'Selecting first frame must preserve negative prompt');
    const generatedBeforeInvalid = await page.evaluate(() => window.testMobile.calls.filter(name => name === 'generate_images').length);
    await page.fill('#svi-high-lora-strength', '2.1');
    await page.click('#send');
    assert.equal(await page.evaluate(() => window.testMobile.calls.filter(name => name === 'generate_images').length), generatedBeforeInvalid);
    await page.fill('#svi-high-lora-strength', '0.4');
    await page.locator('#creation-panel').evaluate(el => { el.scrollTop = 0; });
    await page.screenshot({ path: path.join(__dirname, '../.runtime/svi-loras-1280.png'), fullPage: true });
    for (const viewport of [{ width: 1280, height: 820 }, { width: 390, height: 820 }, { width: 360, height: 520 }]) {
      await page.setViewportSize(viewport);
      await page.waitForTimeout(100);
      assert.equal(await page.locator('#negative-prompt').inputValue(), 'blur', `Resize to ${viewport.width} must preserve negative prompt`);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.ok(await page.locator('.composer-area').evaluate(el => el.getBoundingClientRect().bottom <= innerHeight));
      await page.screenshot({ path: path.join(__dirname, `../.runtime/svi-page-${viewport.width}.png`), fullPage: true });
      assert.ok(await page.locator('#conversation').evaluate(el => el.clientHeight >= 24), `SVI composer must leave room for results at ${viewport.width}px`);
    }
    await page.click('#send');
    const svi = await page.evaluate(() => window.testMobile.generation);
    assert.equal(svi.workflow, 'svi_image');
    assert.deepEqual(svi.parameters.segment_prompts, ['A cat blinks.', 'The cat stretches.', 'The cat settles down.']);
    assert.deepEqual(svi.images, ['/second.png']);
    assert.equal(svi.parameters.seed, 42);
    assert.equal(svi.parameters.negative, 'blur');
    assert.deepEqual(svi.parameters.high_lora, { name: 'svi_custom/' + 'a'.repeat(64) + '/HighStyle.safetensors', strength: .4 });
    assert.deepEqual(svi.parameters.low_lora, { name: 'svi_custom/' + 'b'.repeat(64) + '/LowStyle.safetensors', strength: -.2 });
    assert.equal(svi.preciseMode, false);
    assert.equal(svi.lastImage, null);
    assert.equal(await page.locator('#svi-prompt-2').inputValue(), '');
    await page.evaluate(() => window.testMobile.progress({ payload: { video: '/svi.mp4', index: 1, total: 1, message: '影片已儲存，正在釋放模型與快取…', done: false } }));
    assert.equal(await page.locator('#send').isDisabled(), true);
    await page.click('[data-studio-mode="image"]');
    await page.evaluate(() => window.testMobile.progress({ payload: { index: 1, total: 1, message: '影片完成，生成資源已釋放', done: true } }));
    assert.equal(await page.locator('#video-results-svi_image video[controls]').count(), 1);
    assert.equal(await page.locator('#video-results-svi_image .user-message').innerText(), '');
    assert.equal(await page.locator('#video-results-svi_image .user-message img').count(), 1);
    assert.equal(await page.locator('#send').isDisabled(), false);
    await page.setViewportSize({ width: 1280, height: 820 });
    await page.evaluate(() => document.querySelector('#google-drive').click());
    await page.waitForFunction(() => document.querySelector('#drive-folder').value.includes('1LQUNB'));
    assert.match(await page.locator('#drive-status').innerText(), /等待.*授權/);
    await page.fill('#drive-folder', 'https://example.com/drive/folders/valid_folder_id');
    await page.click('#drive-save');
    assert.match(await page.locator('#drive-status').innerText(), /分享連結/);
    await page.fill('#drive-folder', 'https://drive.google.com/drive/folders/valid_folder_id?usp=sharing');
    await page.uncheck('#drive-enabled');
    await page.click('#drive-save');
    assert.deepEqual(await page.evaluate(() => window.testMobile.drive), { enabled: false, folder_id: 'valid_folder_id' });
    await page.evaluate(() => { window.testMobile.openPath = 'D:/client.json'; });
    await page.click('#drive-connect');
    await page.waitForFunction(() => window.testMobile.oauthPath === 'D:/client.json');
    for (const width of [1280, 390, 360]) {
      await page.setViewportSize({ width, height: 820 });
      assert.equal(await page.locator('.modal').evaluate(el => el.scrollWidth <= el.clientWidth), true);
      await page.screenshot({ path: path.join(__dirname, `../.runtime/drive-${width}.png`), fullPage: true });
    }
    await page.keyboard.press('Escape');
    assert.deepEqual(errors, []);
    console.log('UI passed: HIGH/LOW local LoRA selection, independent weights/clear, saved defaults, three ordered prompts with image-only messages, cleanup progress and responsive 1280/390/360.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
