// Real studio browser submission. Credentials stay in memory and are never logged.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  let input = ''; for await (const chunk of process.stdin) input += chunk;
  const value = JSON.parse(input);
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:8787/');
    await page.waitForSelector('#login-view:not(.hidden)');
    const code = fs.readFileSync(path.join(__dirname, '../.runtime/mobile/access-code.txt'), 'utf8').trim();
    await page.fill('#code', code); await page.click('#login-button');
    await page.waitForSelector('#studio:not(.hidden)');
    if (value.action === 'observe') {
      for (const id of value.ids) {
        await page.waitForSelector(`.job[data-id="${id}"] .result img`, { timeout: 30000 });
        await page.locator(`.job[data-id="${id}"] .result img`).first().evaluate(async img => { await img.decode(); });
      }
      await page.screenshot({ path: value.screenshot, fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({ path: value.mobileScreenshot, fullPage: true });
      await page.click('#show-library'); await page.waitForSelector('#artworks .result img');
      await page.locator('#artworks .result img').first().evaluate(async img => { await img.decode(); });
      console.log(JSON.stringify({ observed: value.ids, browserErrors: errors }));
      return;
    }
    await page.selectOption('#workflow', value.workflow);
    await page.fill('#prompt', value.prompt);
    if (value.images.length) await page.setInputFiles('#files', value.images);
    const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/jobs') && response.request().method() === 'POST');
    await page.click('#send');
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`Job submission failed (${response.status()})`);
    const job = await response.json();
    console.log(JSON.stringify({ jobId: job.id, fixedPrompt: await page.locator('#fixed').inputValue(), browserErrors: errors }));
    // GPU work belongs to the host and continues after the browser closes.
    await page.click('#logout');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
