/* Local search interactions. Quotes remain the actual cached observations. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium } = require("playwright");
const base = process.env.BASE_URL || "http://127.0.0.1:8051";
assert(["127.0.0.1", "localhost"].includes(new URL(base).hostname));
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 930, height: 752 } });
  // The cached conference dates stay fixed; timers continue to run normally.
  await page.clock.setFixedTime(new Date("2026-10-24T19:00:00Z"));
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const live = [];
  await page.route("**/api/v1/travel/search", async (route) => {
    const query = route.request().postDataJSON();
    if (query.mode === "live") {
      live.push(query);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          kind: query.kind,
          query,
          items: [],
          status: "failed",
          warnings: ["Mock provider unavailable"],
          data_source: "unknown",
        }),
      });
    }
    return route.continue();
  });
  await page.goto(base + "/#travel");
  await page.waitForFunction(
    () => document.querySelector("#main").getAttribute("aria-busy") === "false",
  );
  await page.locator("#travel-flights-tab").click();
  const settled = () =>
    page.waitForFunction(
      () =>
        document
          .querySelector("#travel-results-workspace")
          .getAttribute("aria-busy") === "false",
    );
  await settled();
  const popup = page.locator("#travel-search-popover");
  const axePath = process.env.AXE_PATH || "/tmp/conferge-axe.min.js";
  if (fs.existsSync(axePath)) await page.addScriptTag({ path: axePath });
  async function accessiblePicker() {
    if (!fs.existsSync(axePath)) return;
    const violations = await page.evaluate(async () =>
      (
        await axe.run("#tab-travel", {
          runOnly: {
            type: "tag",
            values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"],
          },
        })
      ).violations.map((v) => ({
        id: v.id,
        nodes: v.nodes.map((n) => n.target),
      })),
    );
    assert.deepEqual(violations, []);
  }
  const origin = page.locator("#research-origin"),
    destination = page.locator("#research-destination");
  await origin.fill("New York");
  assert.match(await popup.innerText(), /John F. Kennedy/);
  await accessiblePicker();
  await origin.press("ArrowDown");
  await origin.press("ArrowDown");
  await origin.press("Enter");
  assert.equal(await origin.inputValue(), "JFK");
  assert.equal(
    await destination.evaluate((el) => el === document.activeElement),
    true,
  );
  await destination.fill("SFO");
  await popup
    .getByRole("option")
    .filter({ hasText: "San Francisco International" })
    .click();
  assert.equal(await destination.inputValue(), "SFO");
  assert.match(await popup.innerText(), /Choose departure date/);
  console.log("PASS airport names, codes, keyboard choice and onward focus");
  await page.keyboard.press("Escape");
  await page.locator("#travel-swap-route").click();
  assert.equal(await origin.inputValue(), "SFO");
  assert.equal(await destination.inputValue(), "JFK");
  await page.locator("#travel-swap-route").click();
  console.log("PASS route swap updates real query fields");
  await page.locator("#research-depart").click();
  assert.equal(await popup.locator(".travel-calendar-month").count(), 2);
  await accessiblePicker();
  await popup.locator('[data-date="2026-10-28"]').click();
  assert.equal(await page.locator("#research-return").inputValue(), "");
  assert.match(await popup.innerText(), /Choose return date/);
  assert.equal(
    await popup.locator('[data-date="2026-10-27"]').isDisabled(),
    true,
  );
  await popup.locator('[data-date="2026-10-31"]').click();
  assert.equal(await popup.isVisible(), false);
  assert.equal(
    await page
      .locator("#research-adults")
      .evaluate((el) => el === document.activeElement),
    true,
  );
  assert.equal(
    await page.locator("#research-depart").inputValue(),
    "2026-10-28",
  );
  assert.equal(
    await page.locator("#research-return").inputValue(),
    "2026-10-31",
  );
  await page.locator("#research-return").press("Enter");
  await page.locator('[data-date="2026-10-31"]').press("ArrowRight");
  assert.equal(
    await page
      .locator('[data-date="2026-11-01"]')
      .evaluate((el) => el === document.activeElement),
    true,
  );
  await page.keyboard.press("Enter");
  assert.equal(
    await page.locator("#research-return").inputValue(),
    "2026-11-01",
  );
  console.log(
    "PASS range selection, invalid end dates and keyboard month boundary",
  );
  await page.locator("#research-adults").click();
  await accessiblePicker();
  await popup.getByRole("button", { name: "Add adult", exact: true }).click();
  await popup.getByRole("radio", { name: "Business", exact: true }).check();
  await popup.getByRole("button", { name: "Done", exact: true }).click();
  assert.equal(await page.locator("#research-adults").inputValue(), "2");
  assert.equal(await page.locator("#research-cabin").inputValue(), "business");
  await page.locator("#travel-search-button").click();
  await settled();
  assert.equal(live.at(-1).origin, "JFK");
  assert.equal(live.at(-1).destination, "SFO");
  assert.equal(live.at(-1).adults, 2);
  assert.equal(live.at(-1).cabin, "business");
  assert.equal(live.at(-1).depart, "2026-10-28");
  assert.equal(live.at(-1).return_date, "2026-11-01");
  console.log(
    "PASS combined party/cabin picker submits the selected criteria (mock live response)",
  );
  await page.locator("#flight-type").selectOption("one_way");
  assert.equal(await page.locator("#research-return").isVisible(), false);
  await page.locator("#research-depart").click();
  await popup.locator('[data-date="2026-10-29"]').click();
  assert.equal(await popup.isVisible(), false);
  await page.locator("#travel-stays-tab").click();
  await settled();
  assert.equal(await page.locator("#research-return").isVisible(), true);
  assert.equal(await page.locator("#travel-swap-route").isVisible(), false);
  await page.locator("#research-adults").click();
  assert.equal(await popup.getByRole("radio").count(), 0);
  await popup.getByRole("button", { name: "Add room", exact: true }).click();
  for (let i = 0; i < 7; i++)
    await popup.getByRole("button", { name: "Add adult", exact: true }).click();
  assert.equal(await page.locator("#research-adults").inputValue(), "9");
  assert.equal(
    await popup
      .getByRole("button", { name: "Add adult", exact: true })
      .isDisabled(),
    true,
  );
  await popup.getByRole("button", { name: "Done", exact: true }).click();
  assert.equal(await page.locator("#research-rooms").inputValue(), "2");
  await page.locator("#travel-search-button").click();
  await settled();
  assert.equal(live.at(-1).kind, "stays");
  assert.equal(live.at(-1).rooms, 2);
  assert.equal(live.at(-1).adults, 9);
  console.log(
    "PASS one-way, stay guest/room counters, supported limit and exact request",
  );
  await page.locator("#research-adults").click();
  await page.locator("#travel-title").click();
  assert.equal(await popup.isVisible(), false);
  assert.equal(await page.locator("#travel-show-map, #travel-back-results").count(),0);
  await page.getByRole("link", { name: "Travel", exact: true }).click();
  await page.locator("#travel-flights-tab").click();
  await settled();
  await page.locator("#flight-type").selectOption("round_trip");
  await origin.fill("New York");
  await destination.fill("San Francisco");
  await page.locator("#research-depart").fill("2026-10-27");
  await page.locator("#research-return").fill("2026-10-30");
  await page.locator("#research-adults").selectOption("1");
  await page.locator("#research-cabin").selectOption("economy");
  await page.locator("#travel-show-collected").click();
  await settled();
  assert.equal(await page.locator(".fare-card").count(), 34);
  await page.locator('[data-travel-sort="duration"]').click();
  assert.equal(await page.locator("#flight-sort").inputValue(), "duration");
  assert.equal(
    await page
      .locator('[data-travel-sort="duration"]')
      .getAttribute("aria-pressed"),
    "true",
  );
  await page.locator("#flight-sort").selectOption("departure");
  assert.equal(
    await page
      .locator('[data-travel-sort="duration"]')
      .getAttribute("aria-pressed"),
    "false",
  );
  console.log(
    "PASS outside dismissal and synchronized sort shortcuts",
  );
  for (const width of [320, 390, 768, 930, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    for (const tab of ["travel-flights-tab", "travel-stays-tab"]) {
      await page.locator("#" + tab).click();
      await settled();
      if (width === 390 && tab === "travel-flights-tab") {
        await page.locator("#research-depart").fill("2026-10-27");
        await page.locator("#research-depart").click();
        await popup.locator('[data-date="2026-10-31"]').click();
        assert.match(
          await popup.locator(".travel-calendar-month").first().innerText(),
          /November 2026/,
        );
        await popup.locator('[data-date="2026-11-03"]').click();
        assert.equal(
          await page.locator("#research-return").inputValue(),
          "2026-11-03",
        );
      }
      if (width <= 650) {
        assert(await page.locator("#travel-mobile-filters").isVisible());
        await page.locator("#travel-mobile-filters").click();
        assert(await page.locator("#travel-max-price").isVisible());
        await page.locator("#travel-mobile-filters").click();
        assert.equal(
          await page.locator("#travel-max-price").isVisible(),
          false,
        );
      }
      await page.locator("#research-depart").click();
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        "Calendar overflows at " + width,
      );
      const date = await popup
        .locator("[data-date]:not(:disabled)")
        .first()
        .boundingBox();
      assert(
        date.width >= 35 && date.height >= 40,
        "Date target too small at " + width,
      );
      await page.keyboard.press("Escape");
      await page.locator("#research-adults").click();
      assert(await popup.isVisible());
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        "Party overflows at " + width,
      );
      await page.keyboard.press("Escape");
    }
  }
  assert.deepEqual(errors, []);
  console.log(
    "PASS Flights/Stays pickers fit 320, 390, 768, 930 and 1440px without JavaScript errors",
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
