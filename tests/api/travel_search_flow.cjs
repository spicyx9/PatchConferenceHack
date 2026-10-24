/* Isolated local fixture UI + actual cached provider offers; does not book or mutate itinerary. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium } = require("playwright");
const base = process.env.BASE_URL || "http://127.0.0.1:8046";
assert(["127.0.0.1", "localhost"].includes(new URL(base).hostname));
const checks = [];
const pass = (name) => {
  checks.push(name);
  console.log("PASS " + name);
};
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const getTravel = async () => {
    const r = await page.request.get(base + "/api/v1/travel");
    assert(r.ok());
    return r.json();
  };
  const unexpectedLive = [];
  await page.route("**/api/v1/travel/search", async (route) => {
    const body = route.request().postDataJSON();
    if (body.mode === "live") {
      unexpectedLive.push(body);
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Unmocked live calls are forbidden in fixture browser tests",
        }),
      });
    }
    return route.continue();
  });
  const initialTravel = await getTravel();
  await page.goto(base + "/#travel");
  await page.waitForFunction(
    () =>
      document.querySelector("#main")?.getAttribute("aria-busy") === "false",
  );
  const search = async (selector = "#travel-show-collected") => {
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/v1/travel/search") &&
        r.request().method() === "POST",
    );
    await page.locator(selector).click();
    const r = await response;
    assert(r.ok(), "Travel search HTTP " + r.status());
    const data = await r.json();
    await page.waitForFunction(
      () =>
        document
          .querySelector("#travel-results-workspace")
          .getAttribute("aria-busy") === "false",
    );
    return data;
  };
  await page.locator("#research-origin").fill("New York");
  await page.locator("#research-destination").fill("San Francisco");
  await page.locator("#research-depart").fill("2026-10-27");
  await page.locator("#research-return").fill("2026-10-30");
  await page.locator("#research-adults").selectOption("1");
  const flights = await search();
  assert.equal(flights.items.length, 34, "Actual cached NYC–SF alternatives");
  assert.equal(
    await page.locator("#flights .travel-offer").count(),
    flights.items.length,
  );
  pass("Search criteria return 34 collected flight alternatives");
  assert.match(
    await page.locator("#travel-offer-context").innerText(),
    /Collected prices/i,
  );
  assert.match(
    await page.locator("#travel-offer-context").innerText(),
    /Bright Data|Google Flights/i,
  );
  let liveRequest;
  const mockLive = async (route) => {
    const body = route.request().postDataJSON();
    assert.equal(body.mode, "live");
    liveRequest = body;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        kind: body.kind,
        query: body,
        items: [],
        data_source: "unknown",
        status: "failed",
        warnings: ["Test provider unavailable"],
        fallback_url: "https://www.google.com/travel/flights",
      }),
    });
  };
  await page.route("**/api/v1/travel/search", mockLive);
  await search("#travel-search-button");
  assert.equal(liveRequest.mode, "live");
  assert.equal(await page.locator("#flights .travel-offer").count(), 0);
  assert.match(
    await page.locator("#travel-search-feedback").innerText(),
    /Test provider unavailable/,
  );
  await page.unroute("**/api/v1/travel/search", mockLive);
  const restored = await search("#travel-use-collected");
  assert.equal(restored.items.length, 34);
  assert.equal(await page.locator("#flights .travel-offer").count(), 34);
  pass(
    "Search requests live prices; explicit provider failure clears cards; collected action restores actual cache",
  );
  await page.locator("#flight-sort").selectOption("price");
  const prices = await page
    .locator("#flights .flight-fare > strong")
    .allTextContents();
  const numeric = prices.map((x) => Number(x.replace(/[^0-9.]/g, "")));
  assert.deepEqual(
    numeric,
    [...numeric].sort((a, b) => a - b),
  );
  pass("Lowest-price sorting orders real totals");
  await page.locator('input[name="travel-stops"][value="0"]').check();
  const nonstop = flights.items.filter(
    (x) => x.slices[0].segments.length === 1,
  );
  assert.equal(
    await page.locator("#flights .travel-offer").count(),
    nonstop.length,
  );
  const stopText = await page
    .locator("#flights .flight-duration small")
    .allTextContents();
  assert(stopText.every((x) => x === "Nonstop"));
  pass("Nonstop filter agrees with source segments");
  await page.locator("#travel-clear-filters").click();
  await page.locator("#research-origin").fill("Paris");
  assert.equal(
    await page.locator("#flights .travel-offer").count(),
    0,
    "Editing query clears stale cards",
  );
  await page.locator("#travel-max-price").fill("1000");
  await page.locator('input[name="travel-stops"][value="0"]').check();
  assert.equal(
    await page.locator("#flights .travel-offer").count(),
    0,
    "Filters cannot resurrect stale origin results",
  );
  await page.locator("#travel-clear-filters").click();
  const paris = await search();
  assert.equal(paris.items.length, 0);
  assert.equal(await page.locator("#flights .travel-offer").count(), 0);
  assert.match(
    await page.locator("#flights").innerText(),
    /No.*offers|No.*match/i,
  );
  assert(
    await page.locator("#flights a").count(),
    "Explicit external search fallback",
  );
  pass("Changed origin removes old offers and provides a truthful fallback");
  await page.locator("#research-origin").fill("New York");
  await page.locator("#flight-type").selectOption("one_way");
  const oneWay = await search();
  assert.equal(
    oneWay.items.length,
    0,
    "Collected round trip cannot satisfy a one-way request",
  );
  assert.equal(await page.locator("#flights .travel-offer").count(), 0);
  await page.locator("#flight-type").selectOption("round_trip");
  pass("One-way criteria do not reuse round-trip quotes");
  await page.locator("#travel-stays-tab").click();
  await page.waitForFunction(
    () => !document.querySelector("#travel-search-button").disabled,
  );
  await page.locator("#research-adults").selectOption("2");
  const stays = await search();
  assert(stays.items.length > 0, "Source stay occupancy is two adults");
  assert.equal(
    await page.locator("#stays .trip-stay").count(),
    stays.items.length,
  );
  assert(
    stays.items.every((x) => x.total_price != null),
    "Real stay totals",
  );
  const mappedStays = stays.items.filter(
    (x) =>
      typeof x.venue?.latitude === "number" &&
      typeof x.venue?.longitude === "number",
  );
  assert(mappedStays.length > 0, "Collected hotels have source coordinates");
  for (const stay of mappedStays) {
    const marker = page
      .locator("[data-travel-place]")
      .filter({ hasText: stay.name });
    assert.equal(
      await marker.count(),
      1,
      "Actual hotel appears in synchronized map list: " + stay.name,
    );
  }
  pass(
    "Stays return actual priced offers for matching two-adult occupancy and map the hotels",
  );
  await page.locator("#research-adults").selectOption("1");
  const solo = await search();
  assert.equal(
    solo.items.length,
    0,
    "No reuse of two-adult price for one adult",
  );
  assert.equal(await page.locator("#stays .trip-stay").count(), 0);
  for (const stay of mappedStays)
    assert.equal(
      await page
        .locator("[data-travel-place]")
        .filter({ hasText: stay.name })
        .count(),
      0,
      "Stale hotel removed from map",
    );
  pass("Occupancy mismatch clears stay quotes and their map options");
  await page.locator("#research-return").fill("2026-10-26");
  assert.equal(
    await page
      .locator("#travel-research-form")
      .evaluate((form) => form.checkValidity()),
    false,
  );
  await page.locator("#research-return").fill("2026-10-30");
  pass("Browser rejects return before departure");
  await page.locator("#travel-local-toggle").click();
  assert(await page.locator("#travel-research-form").isHidden());
  assert(await page.locator("#travel-results-workspace").isHidden());
  assert(await page.locator("#travel-local-note").isVisible());
  assert(await page.locator("#travel-map-title").isVisible());
  await page.locator("#travel-resume").click();
  assert(await page.locator("#travel-research-form").isVisible());
  pass("Local or already-booked path retains map and can resume search");
  const axePath = process.env.AXE_PATH || "/tmp/conferge-axe.min.js";
  if (fs.existsSync(axePath)) {
    await page.addScriptTag({ path: axePath });
    for (const tab of ["travel-flights-tab", "travel-stays-tab"]) {
      await page.locator("#" + tab).click();
      await page.waitForFunction(
        () => !document.querySelector("#travel-search-button").disabled,
      );
      const violations = await page.evaluate(
        async () =>
          (
            await axe.run("#tab-travel", {
              runOnly: {
                type: "tag",
                values: [
                  "wcag2a",
                  "wcag2aa",
                  "wcag21a",
                  "wcag21aa",
                  "wcag22aa",
                ],
              },
            })
          ).violations,
      );
      assert.deepEqual(
        violations.map((x) => ({
          id: x.id,
          nodes: x.nodes.map((n) => n.target),
        })),
        [],
        tab + " accessibility",
      );
    }
    pass("Travel Flights and Stays have zero axe WCAG A/AA violations");
  } else if (process.env.AXE_PATH) throw Error("AXE_PATH does not exist");
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: width < 600 ? 844 : 1000 });
    for (const tab of ["travel-flights-tab", "travel-stays-tab"]) {
      await page.locator("#" + tab).click();
      await page.waitForFunction(
        () => !document.querySelector("#travel-search-button").disabled,
      );
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        tab + " overflow at " + width,
      );
    }
  }
  pass("Both Travel tabs fit 320, 390, 768 and 1440px");
  const finalTravel = await getTravel();
  assert.deepEqual(
    finalTravel.itinerary,
    initialTravel.itinerary,
    "Search must not mutate planned itinerary",
  );
  assert.deepEqual(
    finalTravel.budget,
    initialTravel.budget,
    "Search must not mutate budget",
  );
  assert.deepEqual(
    unexpectedLive,
    [],
    "Only the explicitly mocked Search may request live mode",
  );
  assert.deepEqual(errors, []);
  pass(
    "Search leaves itinerary/budget unchanged and produces no JavaScript errors",
  );
  await browser.close();
  console.log(JSON.stringify({ checks, count: checks.length }));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
