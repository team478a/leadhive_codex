// Local protocol lab only; never receives LeadHive credentials or company URLs.
const { chromium } = require('../../frontend/node_modules/playwright');

(async () => {
  const url = new URL(process.argv[2]);
  const email = process.argv[3] || 'operator@example.invalid';
  const groupMode = process.argv[4] || '';
  if (process.env.CF7_PROTOCOL_LAB !== '1' || url.hostname !== '127.0.0.1'
      || url.protocol !== 'http:' || !url.port || url.username || url.password
      || !['operator@example.invalid', 'operator@example.com'].includes(email)
      || !['', 'groups_required', 'radio'].includes(groupMode)) {
    throw new Error('Explicit loopback lab required');
  }
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const blocked = [];
    await page.route('**/*', async route => {
      if (new URL(route.request().url()).origin !== url.origin) {
        blocked.push('outside-origin');
        await route.abort();
      } else await route.continue();
    });
    const posts = [];
    page.on('request', request => {
      if (request.method() === 'POST') {
        const body = request.postDataBuffer().toString('utf8');
        const fields = [...body.matchAll(/name="([^"]+)"\r\n\r\n([\s\S]*?)\r\n--/g)]
          .map(match => [match[1], match[2]]);
        posts.push({ url: request.url(), type: request.headers()['content-type'], fields });
      }
    });
    await page.goto(url.href);
    const form = page.locator('form.wpcf7-form').nth(groupMode === 'radio' ? 6 : groupMode ? 4 : 0);
    await form.locator('[name="your-name"]').fill('Lab operator');
    await form.locator('[name="your-email"]').fill(email);
    await form.locator('[name="your-message"]').fill('Lab fixture only 日本語\n第二行');
    await form.locator('[name="consent"]').check();
    if (groupMode === 'groups_required') {
      await form.locator('[name="services[]"][value="SNS運用"]').check();
      await form.locator('[name="services[]"][value="OEM"]').check();
    }
    if (groupMode === 'radio') await form.locator('[name="topic"][value="OEM"]').check();
    const responsePromise = page.waitForResponse(response =>
      response.request().method() === 'POST' && response.url().includes('/feedback'));
    await form.locator('[type="submit"]').click();
    const response = await responsePromise;
    const result = await response.json();
    if (posts.length !== 1 || result.status !== 'mail_sent' || blocked.length !== 0) {
      throw new Error('Unexpected browser protocol or outside-origin request');
    }
    process.stdout.write(JSON.stringify({ posts, http_status: response.status(),
      result, outside_origin_blocked: blocked.length, browser_version: browser.version() }));
  } finally {
    await browser.close();
  }
})().catch(() => {
  process.stderr.write('Browser lab verification failed\n');
  process.exitCode = 1;
});
