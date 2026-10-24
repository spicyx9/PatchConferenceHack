/* Local fixture conference and real cached offers; no itinerary changes. */
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const base = process.env.BASE_URL || 'http://127.0.0.1:8051';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
(async () => {
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/#travel');
  await page.waitForFunction(()=>document.querySelector('#main').getAttribute('aria-busy')==='false');
  const panel=page.locator('#travel-map-panel');
  for(const width of [1280,390]) {
    await page.setViewportSize({width,height:844});
    await page.locator('#travel-flights-tab').click();
    assert(await panel.isHidden(),'Flights must not show the neighborhood map');
    await page.locator('#travel-stays-tab').click();
    await page.waitForFunction(()=>document.querySelector('#travel-results-workspace').getAttribute('aria-busy')==='false');
    assert(await panel.isVisible(),'Stays retain the map');
    await page.locator('#travel-show-map').click();
    assert(await page.locator('#travel-map-title').evaluate(e=>e===document.activeElement));
    const bounds=await page.locator('#map').boundingBox();
    assert(bounds.width>200 && bounds.height>200,'Map is laid out after revealing Stays');
    await page.locator('#travel-back-results').click();
    await page.locator('#travel-flights-tab').click();
    assert(await panel.isHidden(),'Switching back to Flights hides the map');
    await page.locator('#travel-local-toggle').click();
    assert(await panel.isVisible(),'Already-booked path retains its promised places map');
    await page.locator('#travel-resume').click();
    assert(await panel.isHidden(),'Resuming Flights hides the map again');
  }
  assert.deepEqual(errors,[]);
  await browser.close();
  console.log('PASS Flights hide the map; Stays show/map/back work; local/resume remain consistent at desktop and mobile widths');
})().catch(e=>{console.error(e);process.exit(1);});
