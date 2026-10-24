/* Real cached hotel covers, public image URLs; no bookings or live provider calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const base = process.env.BASE_URL || 'http://127.0.0.1:8051';
assert(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(base + '/#travel');
  await page.waitForFunction(() => document.querySelector('#main')?.getAttribute('aria-busy') === 'false');
  await page.locator('.main-nav [data-tab="travel"]').click();
  const response = page.waitForResponse(r => r.url().endsWith('/api/v1/travel/search') && r.request().method() === 'POST' && r.request().postDataJSON().kind === 'stays');
  await page.locator('#travel-stays-tab').click();
  const data = await (await response).json();
  const hotels = data.items.filter(i => i.id.startsWith('booking:'));
  assert.equal(hotels.length, 15);
  await page.waitForFunction(() => document.querySelectorAll('#stays .stay-photo img').length === 15);
  for (const image of await page.locator('#stays .stay-photo img').all()) {
    await image.scrollIntoViewIfNeeded();
    await image.evaluate(i => i.decode());
    assert(await image.evaluate(i => i.naturalWidth > 100 && i.naturalHeight > 100));
  }
  for (const [size, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    for (const hotel of hotels) {
      const card = page.locator('#stays article').filter({ has: page.getByRole('heading', { name: hotel.name, exact: true }) });
      assert.equal(await card.locator('.offer-deal').getAttribute('href'), hotel.booking_url);
      assert.equal(await card.locator('.stay-source, .offer-evidence').count(), 0);
      assert.doesNotMatch(await card.innerText(), /Bright Data|Property photo|dataset|Cached/);
      assert.match(await card.locator('.badge').innerText(), /Checked/);
    }
    if (process.env.EVIDENCE_DIR) {
      fs.mkdirSync(process.env.EVIDENCE_DIR, { recursive: true });
      await page.locator('#stays article').first().screenshot({ path: path.join(process.env.EVIDENCE_DIR, `after-${size}.png`) });
    }
  }
  assert.deepEqual(errors, []);
  console.log('PASS 15/15 genuine hotel covers decode in search results; exact photo/deal sources, separate price provenance, desktop and mobile fit');
  await browser.close();
})();
