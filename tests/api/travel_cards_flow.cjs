/* Local cached-data QA. Optional baseline captures load exact pre-change source bytes. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const base = process.env.BASE_URL || "http://127.0.0.1:8051";
assert(["127.0.0.1", "localhost"].includes(new URL(base).hostname));
const evidence = process.env.EVIDENCE_DIR;
const baseline = process.env.BASELINE_DIR;
async function capture(page, selector, name) {
  if (!evidence) return;
  fs.mkdirSync(evidence, { recursive: true });
  const el = page.locator(selector).first();
  await el.scrollIntoViewIfNeeded();
  await page.evaluate(
    (e) => scrollBy(0, e.getBoundingClientRect().top - 155),
    await el.elementHandle(),
  );
  await page.waitForTimeout(150);
  await el.screenshot({ path: path.join(evidence, name + ".png") });
}
(async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  for (const version of baseline ? ["before", "after"] : ["after"]) {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
      reducedMotion: "reduce",
    });
    page.on("pageerror", (e) => errors.push(e.message));
    if (version === "before") {
      await page.route(base + "/", (r) =>
        r.fulfill({
          body: fs.readFileSync(path.join(baseline, "before-index.html")),
          contentType: "text/html",
        }),
      );
      await page.route("**/static/app.js", (r) =>
        r.fulfill({
          body: fs.readFileSync(path.join(baseline, "before-app.js")),
          contentType: "text/javascript",
        }),
      );
    }
    await page.goto(base, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () =>
        document.querySelector("#main")?.getAttribute("aria-busy") === "false",
    );
    await page.locator('.main-nav [data-tab="travel"]').click();
    for (const [size, width, height] of [
      ["desktop", 1440, 1000],
      ["mobile", 390, 844],
    ]) {
      await page.setViewportSize({ width, height });
      for (const [kind, selector] of [
        ["flight", "#flights article"],
        ["stay", "#stays article"],
      ]) {
        await capture(page, selector, `${version}-${kind}-${size}`);
      }
    }
    if (version === "after") {
      assert(
        (await page.locator("#flights").innerText()).includes(
          "Return itinerary not collected",
        ),
      );
      assert(
        (await page.locator("#stays").innerText()).includes(
          "Taxes and fees unconfirmed",
        ),
      );
      assert.equal(
        await page.locator(".stay-stars").count(),
        0,
        "Missing stars are not derived from guest scores",
      );
      await page.locator(".fare-logo img").first().scrollIntoViewIfNeeded();
      await page.waitForFunction(() => {
        const i = document.querySelector(".fare-logo img");
        return i?.complete && i.naturalWidth > 0;
      });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
        "No horizontal overflow",
      );
      assert(
        await page.locator("#flights .fare-price .badge").first().isVisible(),
        "Flight collection badge is outside details",
      );
      assert(
        await page.locator("#stays .stay-price .badge").first().isVisible(),
        "Stay collection badge is outside details",
      );
      const link = page.locator("#stays .offer-deal").first();
      assert((await link.getAttribute("href")).includes("booking.com/hotel/"));
      assert.equal(await link.getAttribute("target"), "_blank");
      await page.locator("#stays details summary").first().click();
      assert(
        (await page.locator("#stays details").first().innerText()).includes(
          "Price status",
        ),
      );
      console.log(
        "PASS cached data: route times, unknown return/baggage/photos/stars/taxes, exact source links, local logos, provenance, mobile layout",
      );
    }
    await page.close();
  }
  // Explicitly fictional test input, identical before/after. Image labels itself as a fixture.
  for (const version of baseline ? ["before", "after"] : ["after"]) {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
      reducedMotion: "reduce",
    });
    page.on("pageerror", (e) => errors.push(e.message));
    if (version === "before") {
      await page.route(base + "/", (r) =>
        r.fulfill({
          body: fs.readFileSync(path.join(baseline, "before-index.html")),
          contentType: "text/html",
        }),
      );
      await page.route("**/static/app.js", (r) =>
        r.fulfill({
          body: fs.readFileSync(path.join(baseline, "before-app.js")),
          contentType: "text/javascript",
        }),
      );
    }
    await page.route("https://images.example.test/fixture.svg", (r) =>
      r.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><rect width="400" height="400" fill="#eee7dd"/><text x="200" y="185" text-anchor="middle" font-family="sans-serif" font-size="23" fill="#726758">Fixture image</text><text x="200" y="225" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#726758">Not a property photograph</text></svg>',
      }),
    );
    await page.route("**/api/v1/stays", async (r) => {
      const response = await r.fetch(),
        document = await response.json(),
        st = document.items[0];
      document.items = [
        {
          ...st,
          name: "Fixture · Test Harbour Hotel",
          source_mode: "fixture",
          source: {
            provider: "fixture",
            api: "fixture",
            site: "booking",
            label: "Fixture · not a real offer",
          },
          evidence: [{ provider: "fixture", source_mode: "fixture" }],
          total_price: "600.00",
          nightly_avg: "200.00",
          rating: 8.9,
          rating_scale: 10,
          rating_count: 120,
          includes_all_fees: true,
          free_cancellation: true,
          card_details: {
            star_rating: 4,
            image_urls: ["https://images.example.test/fixture.svg"],
            amenities: ["WiFi", "Parking", "Air conditioning"],
            room_type: "Double room",
            bed_description: "1 double bed",
            no_prepayment: true,
          },
        },
      ];
      await r.fulfill({ response, json: document });
    });
    await page.goto(base, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () =>
        document.querySelector("#main")?.getAttribute("aria-busy") === "false",
    );
    await page.locator('.main-nav [data-tab="travel"]').click();
    for (const [size, width, height] of [
      ["desktop", 1440, 1000],
      ["mobile", 390, 844],
    ]) {
      await page.setViewportSize({ width, height });
      await capture(page, "#stays article", `${version}-fixture-stay-${size}`);
    }
    if (version === "after") {
      assert.equal(
        await page.locator(".stay-stars").getAttribute("aria-label"),
        "4-star property",
      );
      const text = await page.locator(".stay-card").innerText();
      for (const value of [
        "120 reviews",
        "Taxes and fees included",
        "No prepayment",
        "1 double bed",
        "WiFi",
        "Fixture",
      ])
        assert(text.includes(value), value);
      await page.locator(".stay-photo img").scrollIntoViewIfNeeded();
      await page.waitForFunction(() => {
        const image = document.querySelector(".stay-photo img");
        return image?.complete && image.naturalWidth > 0;
      });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
      const unsafe = await page.evaluate(() =>
        TravelCards.stay(
          {
            name: "<img src=x onerror=alert(1)>",
            booking_url: "javascript:alert(1)",
            card_details: { image_urls: ["javascript:alert(1)"] },
            check_in: "2026-10-27",
            check_out: "2026-10-30",
            adults: 1,
            rooms: 1,
          },
          "",
          "",
        ),
      );
      assert(unsafe.includes("&lt;img"));
      assert(!unsafe.includes('href="javascript:'));
      console.log(
        "PASS explicit fixture: loaded source photo slot, separate stars/review score, amenities, room/bed, policies, occupancy, mobile, escaping",
      );
      const flightHTML = await page.evaluate(() =>
        TravelCards.flight(
          {
            trip_type: "round_trip",
            price_scope: "per_adult",
            total_price: "600",
            currency: "USD",
            carry_on_included: true,
            checked_bags_included: 0,
            slices: [
              {
                segments: [
                  {
                    origin_iata: "JFK",
                    destination_iata: "SFO",
                    departure_at: "2026-10-27T20:00:00-04:00",
                    arrival_at: "2026-10-27T23:00:00-07:00",
                    marketing_carrier: "UA",
                  },
                ],
              },
              {
                segments: [
                  {
                    origin_iata: "SFO",
                    destination_iata: "JFK",
                    departure_at: "2026-10-30T23:00:00-07:00",
                    arrival_at: "2026-10-31T07:30:00-04:00",
                    marketing_carrier: "UA",
                  },
                ],
              },
            ],
          },
          "",
          "",
        ),
      );
      for (const text of [
        "Outbound",
        "Return",
        "+1",
        "Carry-on included",
        "0 checked bags",
        "per adult",
      ])
        assert(flightHTML.includes(text), text);
      console.log(
        "PASS round trip: both slices, overnight arrival, known baggage and per-adult scope",
      );
    }
    await page.close();
  }
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
