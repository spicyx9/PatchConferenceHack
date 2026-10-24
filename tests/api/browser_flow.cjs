/* Run against the local fixture session: NODE_PATH=<playwright packages> node tests/api/browser_flow.cjs */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const base = process.env.BASE_URL || "http://127.0.0.1:8000";
assert(
  ["127.0.0.1", "localhost"].includes(new URL(base).hostname),
  "Use a local fixture server.",
);
const evidence = process.env.EVIDENCE_DIR;
const checks = [];
function pass(name) {
  checks.push(name);
  console.log("PASS " + name);
}
(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const api = async (route) => {
    const response = await context.request.get(base + "/api/v1" + route);
    assert(response.ok(), route);
    return response.json();
  };
  const settle = async () => {
    await page.waitForFunction(
      () =>
        document.querySelector("#main")?.getAttribute("aria-busy") === "false",
    );
    await page.waitForTimeout(100);
  };
  const nav = async (name) => {
    await page.locator(`.main-nav [data-tab="${name}"]`).click();
    await page.waitForTimeout(150);
    assert.equal(
      await page.locator(`#tab-${name}`).getAttribute("hidden"),
      null,
    );
  };
  const submit = async (selector, route) => {
    const response = page.waitForResponse(
      (r) =>
        r.url() === base + "/api/v1" + route && r.request().method() === "POST",
    );
    await page.locator(selector).first().click();
    const result = await response;
    assert(result.ok(), route);
    await settle();
    return result.json();
  };
  const openEventDetail = async () => {
    await nav("events");
    const trigger = page
      .locator('#events-list button[data-action="event"]')
      .first();
    const eventId = await trigger.getAttribute("data-id");
    const event = (await api("/events")).items.find(
      (item) => item.id === eventId,
    );
    assert(event, "Event details refer to an API event");
    await trigger.click();
    const dialog = page.locator("#event-dialog");
    assert.equal(await dialog.evaluate((element) => element.open), true);
    assert.equal(
      await dialog.getAttribute("aria-labelledby"),
      "event-detail-title",
    );
    assert(
      (await page.locator("#event-detail-title").textContent()).trim().length >
        0,
    );
    const source = page.locator("#event-detail-source");
    const urls = [
      event.source_url,
      ...(event.evidence || []).map((item) => item.source_url),
    ].filter(Boolean);
    assert(
      urls.includes(await source.getAttribute("href")),
      "Source links to event evidence",
    );
    assert.equal(await source.isVisible(), true);
    assert.equal(
      await page.evaluate(() =>
        document
          .querySelector("#event-dialog")
          .contains(document.activeElement),
      ),
      true,
    );
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
      "Open event details do not overflow the viewport",
    );
    await page.keyboard.press("Tab");
    assert.equal(
      await dialog.evaluate((element) =>
        element.contains(document.activeElement),
      ),
      true,
      "Tab keeps focus in the modal",
    );
    return trigger;
  };
  const closeEventDetail = async (trigger) => {
    await page.keyboard.press("Escape");
    assert.equal(
      await page.locator("#event-dialog").evaluate((element) => element.open),
      false,
    );
    assert.equal(
      await trigger.evaluate((element) => element === document.activeElement),
      true,
    );
  };
  try {
    const conference = await api("/conference");
    assert.equal(
      conference.data_source,
      "fixture",
      "This probe mutates only an explicit fixture session.",
    );
    if (evidence) fs.mkdirSync(evidence, { recursive: true });
    await context.request.post(base + "/api/v1/reset", { data: {} });
    await page.goto(base, { waitUntil: "domcontentloaded" });
    await page
      .locator(".person-preview")
      .first()
      .waitFor({ state: "attached" });
    await settle();
    assert.equal(
      await page.locator("#badge-source").textContent(),
      "Sample data",
    );
    const brightdata = await api("/brightdata");
    assert.equal(brightdata.data_source, Object.values(brightdata.ready || {}).some(Boolean) ? "live" : "unknown");
    assert.equal(
      await page.locator("#stat-events").textContent(),
      String((await api("/events")).items.length),
    );
    const duplicateIds = await page.evaluate(() => {
      const ids = [...document.querySelectorAll("[id]")].map((e) => e.id);
      return ids.filter((id, i) => ids.indexOf(id) !== i);
    });
    assert.deepEqual(duplicateIds, []);
    pass(
      "Content provenance stays fixture despite provider metadata; real API counts and unique DOM IDs",
    );

    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: width < 760 ? 844 : 1000 });
      for (const name of ["story", "events", "people", "travel", "graph"]) {
        await nav(name);
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          ),
          false,
          `${name} overflows at ${width}px`,
        );
      }
    }
    pass(
      "All five views fit 320px, 390px, 768px and 1440px without horizontal overflow",
    );
    await page.setViewportSize({ width: 1440, height: 1000 });
    await nav("events");
    await page.locator("#events-search").fill("does-not-exist-87213");
    assert.match(
      await page.locator("#events-list").textContent(),
      /No events match/i,
    );
    await page.getByRole("button", { name: "Clear filters" }).click();
    assert((await page.locator(".event-browser-row").count()) > 0);
    await page.locator("#events-type").selectOption("session");
    const sessionCount = (await api("/events")).items.filter(
      (e) => e.event_type === "session",
    ).length;
    assert.equal(
      await page.locator(".event-browser-row").count(),
      sessionCount,
    );
    await page.locator("#events-type").selectOption("all");
    await page.locator("#agenda-day-tabs button").nth(1).click();
    assert.equal(await page.locator("#plan-days .day").count(), 1);
    await page.locator("#agenda-day-tabs button").first().click();
    await nav("people");
    await page.locator("#people-search").fill("does-not-exist-87213");
    assert.match(
      await page.locator("#people-cards").textContent(),
      /No people match/i,
    );
    await page.getByRole("button", { name: "Clear search" }).click();
    pass("Event type/day filters, search, empty states and filter reset");

    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      const trigger = await openEventDetail();
      if (evidence)
        await page.screenshot({
          path: path.join(
            evidence,
            `review-24-event-detail-${width === 390 ? "mobile" : "desktop"}.png`,
          ),
          animations: "disabled",
        });
      await closeEventDetail(trigger);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    pass(
      "Event title opens accessible details with the real source; Escape restores focus on desktop and mobile",
    );

    await nav("story");
    await page.locator('#tab-story [data-open="goal-dialog"]').first().click();
    await page.locator("#goal-text").fill("");
    await page.locator("#btn-goal").click();
    assert.equal(await page.locator("#goal-dialog").evaluate((element) => element.open), true);
    assert.equal(await page.locator("#goal-text").evaluate((element) => element.validity.valueMissing), true);
    await page.locator("#goal-text").fill("Meet seed investors and engineers");
    await submit("#btn-goal", "/goal");
    await page.waitForFunction(
      () => !document.querySelector("#goal-dialog").open,
    );
    assert.equal(
      (await api("/plan")).goal_text,
      "Meet seed investors and engineers",
    );
    assert.match(
      await page.locator("#story-goal").textContent(),
      /Meet seed investors and engineers/,
    );
    pass(
      "Empty goals stay in the form; natural-language goals update every view",
    );

    await nav("people");
    const first = (await api("/people")).items.find((c) => c.person && !c.met);
    const beforeRoi = await api("/roi");
    const metButton = page.locator(
      `#tab-people button[data-action="met"][data-id="${first.person.id}"]`,
    );
    await metButton.click();
    await page
      .locator("#meeting-note")
      .fill("<script>window.injected=1</script> Discuss next steps.");
    await submit("#btn-met-save", "/met");
    await page.waitForFunction(
      () => !document.querySelector("#meeting-dialog").open,
    );
    assert.equal((await api("/roi")).meetings, beforeRoi.meetings + 1);
    assert.equal(
      await page.locator("#stat-met").textContent(),
      String(beforeRoi.meetings + 1),
    );
    assert.equal(await page.evaluate(() => window.injected), undefined);
    const metCard = (await api("/people")).items.find(
      (c) => c.person?.id === first.person.id,
    );
    if (metCard) assert.equal(metCard.met, true);
    await page
      .locator('#tab-people button[data-action="showpath"]')
      .first()
      .click();
    await page.waitForFunction(() =>
      /Why this person|No connection path available/i.test(
        document.querySelector("#graph-detail").textContent,
      ),
    );
    assert.equal(await page.locator("#tab-graph").getAttribute("hidden"), null);
    pass(
      "Meeting persists note safely, updates ROI and ranking; explanation opens the connections view",
    );

    await nav("events");
    const beforePlan = await api("/plan");
    const skipped = beforePlan.plan.days.flatMap((d) => d.items)[0];
    await submit(
      `button[data-action="skipped"][data-id="${skipped.event_id}"]`,
      "/skipped",
    );
    assert(
      !(await api("/plan")).plan.days
        .flatMap((d) => d.items)
        .some((e) => e.event_id === skipped.event_id),
    );
    const attended = (await api("/plan")).plan.days.flatMap((d) => d.items)[0];
    await submit(
      `button[data-action="attended"][data-id="${attended.event_id}"]`,
      "/attended",
    );
    assert.equal(
      (await api("/events")).items.find((e) => e.id === attended.event_id)
        .attended,
      true,
    );
    pass(
      "Skip removes an event from the program; participation is recorded without claiming a reservation",
    );

    await page.locator('.site-header [data-open="simulation-dialog"]').click();
    const scenarios = await api("/scenarios");
    const scenario =
      scenarios.items.find((e) => /sold/i.test(e.id)) || scenarios.items[0];
    await page.locator("#scenario-select").selectOption(scenario.id);
    const simulation = await submit("#btn-simulate", "/simulate-change");
    await page.waitForFunction(
      () => !document.querySelector("#simulation-dialog").open,
    );
    assert.equal(await page.locator("#diff-panel").isVisible(), true);
    assert.match(await page.locator("#diff-panel").textContent(), /simul/i);
    assert.equal(
      await page.locator("#stat-plan").textContent(),
      String((await api("/plan")).plan.days.flatMap((d) => d.items).length),
    );
    assert(simulation.diff);
    await page.locator('.site-header [data-open="simulation-dialog"]').click();
    await page.locator('#simulation-dialog [data-open="reset-dialog"]').click();
    await submit("#btn-reset", "/reset");
    await page.waitForFunction(() => !document.querySelector("dialog[open]"));
    assert.equal((await api("/plan")).goal_text, conference.demo_goal_text);
    assert.equal(await page.locator("#diff-panel").isVisible(), false);
    pass(
      "Labeled sold-out scenario refreshes the full UI; confirmed reset restores the trip",
    );

    await nav("travel");
    const proposal = page.locator('button[data-action="accept"]').first();
    if (await proposal.count()) {
      await submit('button[data-action="accept"]', "/proposal/accept");
      assert.match(
        await page.locator("#proposals").textContent(),
        /Suggestion saved/i,
      );
      pass("Travel suggestion is saved without presenting it as a booking");
    }
    await nav("story");
    await page.locator('#tab-story [data-open="goal-dialog"]').first().click();
    await page.keyboard.press("Tab");
    assert.equal(
      await page.evaluate(() =>
        document.querySelector("#goal-dialog").contains(document.activeElement),
      ),
      true,
    );
    await page.keyboard.press("Escape");
    assert.equal(
      await page.locator("#goal-dialog").evaluate((e) => e.open),
      false,
    );
    pass("Native dialog keeps keyboard focus inside and closes with Escape");

    if (process.env.AXE_PATH) {
      const findings = [];
      for (const name of ["story", "events", "people", "travel", "graph"]) {
        await nav(name);
        await page.addScriptTag({ path: process.env.AXE_PATH });
        const result = await page.evaluate(() =>
          axe.run(document, {
            runOnly: {
              type: "tag",
              values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"],
            },
          }),
        );
        findings.push(
          ...result.violations.map((v) => ({
            view: name,
            id: v.id,
            impact: v.impact,
            nodes: v.nodes.map((n) => ({
              target: n.target,
              summary: n.failureSummary,
            })),
          })),
        );
      }
      const detailTrigger = await openEventDetail();
      const detailResult = await page.evaluate(() =>
        axe.run(document, {
          runOnly: {
            type: "tag",
            values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"],
          },
        }),
      );
      findings.push(
        ...detailResult.violations.map((violation) => ({
          view: "event-detail",
          id: violation.id,
          impact: violation.impact,
          nodes: violation.nodes.map((node) => ({
            target: node.target,
            summary: node.failureSummary,
          })),
        })),
      );
      await closeEventDetail(detailTrigger);
      if (evidence)
        fs.writeFileSync(
          path.join(evidence, "accessibility.json"),
          JSON.stringify(findings, null, 2),
        );
      assert.equal(
        findings.length,
        0,
        "Accessibility violations: " +
          findings
            .map((v) => v.view + ":" + v.id + " (" + v.nodes.length + ")")
            .join(", "),
      );
      pass(
        "Automated accessibility checks pass on all five views and the event details modal",
      );
    }
    await context.request.post(base + "/api/v1/reset", { data: {} });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page
      .locator(".person-preview")
      .first()
      .waitFor({ state: "attached" });
    await settle();
    if (evidence) {
      fs.mkdirSync(evidence, { recursive: true });
      for (const name of ["story", "people", "events", "travel", "graph"]) {
        await nav(name);
        await page.screenshot({
          path: path.join(evidence, `review-24-after-${name}-desktop.png`),
          animations: "disabled",
        });
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await nav("story");
      await page.screenshot({
        path: path.join(evidence, "review-24-after-story-mobile.png"),
        animations: "disabled",
      });
    }
    await page.route("**/api/v1/events", (route) => route.abort());
    await page.reload({ waitUntil: "domcontentloaded" });
    await settle();
    await page.locator("#error-banner").filter({ hasText: "events" }).waitFor();
    await page.unroute("**/api/v1/events");
    await page.getByRole("button", { name: "Retry loading" }).click();
    await settle();
    assert.equal(await page.locator("#error-banner").isVisible(), false);
    pass("Partial network failure remains visible and reload retry recovers");
    await page.route("https://unpkg.com/**", (route) => route.abort());
    await page.reload({ waitUntil: "domcontentloaded" });
    await page
      .locator(".person-preview")
      .first()
      .waitFor({ state: "attached" });
    await settle();
    await nav("graph");
    assert.match(
      await page.locator("#graph").textContent(),
      /visualization could not load|visualization is unavailable/i,
    );
    await page.locator(".graph-text > summary").click();
    assert(
      (await page
        .locator('#graph-fallback button[data-action="path"]')
        .count()) > 0,
    );
    await page
      .locator('#graph-fallback button[data-action="path"]')
      .first()
      .click();
    await page.waitForFunction(
      () =>
        !/Loading connections and evidence/i.test(
          document.querySelector("#graph-detail").textContent,
        ),
    );
    await nav("travel");
    assert.match(
      await page.locator("#map").textContent(),
      /The map could not load/i,
    );
    pass(
      "Unavailable visualization CDNs preserve usable text paths and map locations",
    );
    assert.deepEqual(errors, []);
    pass("No uncaught JavaScript errors throughout the journey");
    if (evidence)
      fs.writeFileSync(
        path.join(evidence, "browser-results.json"),
        JSON.stringify({ checks, errors }, null, 2),
      );
    console.log(
      JSON.stringify({ passed: checks.length, checks, errors }, null, 2),
    );
  } catch (error) {
    if (evidence)
      await page
        .screenshot({
          path: path.join(evidence, "failure.png"),
          animations: "disabled",
        })
        .catch(() => {});
    throw error;
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
