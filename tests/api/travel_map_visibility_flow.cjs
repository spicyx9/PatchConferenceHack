/* Local fixture conference and cached offers; Travel has no duplicate map. */
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
  for(const width of [1280,390]) {
    await page.setViewportSize({width,height:844});
    for(const tab of ['travel-flights-tab','travel-stays-tab']) {
      await page.locator('#'+tab).click();
      await page.waitForFunction(()=>document.querySelector('#travel-results-workspace').getAttribute('aria-busy')==='false');
      assert.equal(await page.locator('#travel-map-panel, #map, #travel-show-map, #travel-back-results').count(),0);
      await page.locator('#travel-local-toggle').click();
      assert(await page.locator('#travel-local-note').isVisible());
      assert.doesNotMatch(await page.locator('#travel-local-note').innerText(),/map/i);
      await page.locator('#travel-resume').click();
      assert(await page.locator('#travel-research-form').isVisible());
    }
  }
  await page.getByRole('link',{name:'Discover',exact:true}).click();
  assert(await page.locator('#story-map').isVisible(),'Discover retains its agenda map');
  assert(await page.locator('#story-map .leaflet-pane').count()>0,'Agenda map still initializes from the shared map data');
  assert.deepEqual(errors,[]);
  await browser.close();
  console.log('PASS no Travel map/actions in Flights, Stays or local/resume; Discover agenda map remains initialized; desktop/mobile, no JS errors');
})().catch(e=>{console.error(e);process.exit(1);});
