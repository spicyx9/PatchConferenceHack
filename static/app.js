/* Conferge interface: plain JS, no build step. Data text is escaped before insertion. */
(function () {
  "use strict";

  var API = "/api/v1";
  var EVENT_TZ = "America/Los_Angeles";
  var STATUS_RANK = { ok: 0, degraded: 1, failed: 2 };
  var TYPE_COLORS = {
    User: "#30343c",
    Goal: "#e6def3",
    Person: "#dce8f6",
    Event: "#f3ded5",
    Company: "#e8e4f2",
    Topic: "#eaebee",
    Conference: "#ead0c4",
    Meeting: "#dee6f1",
  };
  var OTHER_COLOR = "#e7e8ec";
  var selectedStoryDay = null;
  var selectedAgendaDay = "all";
  var lastEvents = null;
  var lastPeople = null;
  var mutationBusy = false;
  var pendingMeeting = null;
  var toastTimer = null;
  var pathRequest = 0;
  var contentKeys = [
    "conference",
    "plan",
    "events",
    "people",
    "travel",
    "stays",
    "flights",
    "map",
    "graph",
    "roi",
    "antifomo",
  ];
  var COSE = {
    name: "cose",
    animate: false,
    nodeRepulsion: 400000,
    idealEdgeLength: 140,
    nodeOverlap: 40,
    componentSpacing: 120,
    padding: 30,
  };

  var envelopes = {}; // latest envelope per endpoint key
  var map = null;
  var mapLayer = null;
  var cy = null;
  var lastMapData = null;

  // Helpers

  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function orUnknown(value) {
    if (value === null || value === undefined || value === "")
      return "Not provided";
    return (
      {
        unknown: "Not provided",
        unverified: "Needs verification",
        verified: "Verified",
        available: "Available",
        unavailable: "Unavailable",
        not_checked: "Not verified",
        hotel: "Hotel",
        apartment: "Apartment",
        hostel: "Hostel",
        verified_bookable: "Availability and total verified",
        quoted_total: "Quoted total",
        indicative: "Indicative price",
        verified_available: "Availability verified",
        observed_live: "Observed price",
        revalidated: "Price revalidated",
        cached: "Cached price",
        sandbox: "Sample price",
        exact: "Exact",
        approximate: "Approximate",
        city: "City-level",
        outside_hours: "Outside planning hours",
        other_timezone: "In another time zone",
        outside_trip: "Outside trip dates",
        skipped: "Skipped",
        sold_out: "Sold out",
        cancelled: "Cancelled",
      }[value] || value
    );
  }

  function safeUrl(url) {
    if (typeof url !== "string") return null;
    return /^https?:\/\//i.test(url) ? url : null;
  }

  function $(id) {
    return document.getElementById(id);
  }

  var avatarAssignments = {},
    avatarUsed = {};
  function personAvatar(person, size) {
    var value = String((person && (person.id || person.name)) || "avatar"),
      hash = 0;
    for (var i = 0; i < value.length; i++)
      hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
    var cell = avatarAssignments[value];
    if (cell === undefined) {
      cell = hash % 8;
      if (Object.keys(avatarUsed).length < 8)
        while (avatarUsed[cell]) cell = (cell + 1) % 8;
      avatarAssignments[value] = cell;
      avatarUsed[cell] = true;
    }
    return (
      '<span class="illustrated-avatar avatar-' +
      (size === "large" ? "large" : size === "small" ? "small" : "medium") +
      '" aria-hidden="true" style="background-position:' +
      ((cell % 4) * 100) / 3 +
      "% " +
      Math.floor(cell / 4) * 100 +
      '%"></span>'
    );
  }
  function candidatePriority(card) {
    var ids = (card.opportunity && card.opportunity.goal_ids) || [],
      goals = (envelopes.plan && envelopes.plan.goals) || [];
    var goal = goals.find(function (entry) {
      return ids.indexOf(entry.id) >= 0;
    });
    return goal
      ? goal.description
          .replace(/^Meet /i, "")
          .replace(/\s*\(([^)]+)\)/, " · $1")
      : "Suggested for your priorities";
  }

  var PROVIDER_LABELS = {
    brightdata: "Bright Data",
    pyairbnb: "pyairbnb",
    "fast-flights": "fast-flights",
    serpapi: "SerpApi",
  };
  var BD_API_LABELS = {
    dataset: "dataset",
    unlocker: "Web Unlocker",
    serp: "SERP API",
  };

  function sourceApiText(src) {
    var prov = src.provider || "unknown";
    if (prov === "fixture" || src.api === "fixture") return "Sample data";
    if (prov === "brightdata")
      return (
        "Bright Data · " + (BD_API_LABELS[src.api] || src.api || "unknown")
      );
    if (src.api === "fallback")
      return "Fallback " + (PROVIDER_LABELS[prov] || prov);
    return (
      (PROVIDER_LABELS[prov] || prov) +
      (src.api && src.api !== "unknown" ? " · " + src.api : "")
    );
  }

  // How a travel record was collected (Bright Data API, fallback or sample data).
  function sourceApiBadge(src) {
    if (!src || typeof src !== "object") return "";
    var tier = Number(src.tier);
    var cls =
      tier === 0 || tier === 1
        ? "src-bd"
        : tier === 2
          ? "src-fallback"
          : tier === 3
            ? "src-fixture"
            : "neutral";
    var tip = [];
    if (src.label) tip.push(src.label);
    if (src.id) tip.push("id: " + src.id);
    if (src.site) tip.push("site: " + src.site);
    if (src.snapshot_id) tip.push("snapshot: " + src.snapshot_id);
    return (
      '<span class="badge src ' +
      cls +
      '" title="' +
      esc(tip.join(" | ")) +
      '">' +
      esc(sourceApiText(src)) +
      "</span>"
    );
  }

  // Observed price only: total_price as given, else the raw scraped text. Never computed.
  function flightPriceText(f) {
    if (f.total_price !== null && f.total_price !== undefined) {
      return (
        f.total_price +
        " " +
        (f.currency || "") +
        (f.price_label ? " (" + f.price_label + ")" : "") +
        (f.return_slice_collected === false ? ", return not collected" : "")
      );
    }
    if (f.raw_price_text) return "observed price: " + f.raw_price_text;
    return "price not available";
  }

  // LinkedIn evidence collected through Bright Data: headline and company only, never presence.
  function linkedinField(li) {
    if (!li) return "";
    var tip = [
      "dataset: " + li.dataset_id,
      "snapshot: " + orUnknown(li.snapshot_id),
      "collected_at: " + li.collected_at,
      "identity_confidence: " + orUnknown(li.identity_confidence),
    ];
    var url = safeUrl(li.source_url);
    return (
      '<div class="field field-linkedin"><b>LINKEDIN</b>' +
      esc(orUnknown(li.headline)) +
      (li.company ? " · " + esc(li.company) : "") +
      " " +
      (url
        ? '<a href="' +
          esc(url) +
          '" target="_blank" rel="noopener noreferrer">profile</a> '
        : "") +
      '<span class="badge src src-bd" title="' +
      esc(tip.join(" | ")) +
      '">' +
      esc(li.provider || "brightdata:linkedin") +
      "</span></div>"
    );
  }

  function sourceBadge(mode) {
    if (["fixture", "cached", "live"].indexOf(mode) >= 0) return "";
    return sourceModeBadge(mode);
  }

  function sourceModeBadge(mode) {
    var labels = {
      live: "Live",
      fixture: "Sample data",
      cached: "Cached",
      mixed: "Mixed sources",
      unknown: "Unknown source",
    };
    var m = mode || "unknown";
    return (
      '<span class="badge ' +
      (m === "fixture" ? "fixture" : m === "live" ? "live" : "neutral") +
      '" title="Data source: ' +
      esc(m) +
      '">' +
      esc(labels[m] || labels.unknown) +
      "</span>"
    );
  }

  function statusBadge(status) {
    var labels = {
      ok: "Available",
      degraded: "Partial coverage",
      failed: "Unavailable",
    };
    return (
      '<span class="badge ' +
      (STATUS_RANK.hasOwnProperty(status) ? status : "neutral") +
      '">' +
      esc(labels[status] || "Needs verification") +
      "</span>"
    );
  }

  // Events held in another timezone keep their own clock time, labelled with that zone.
  function zoneLabel(tz) {
    return tz && tz !== EVENT_TZ ? " (" + tz + ")" : "";
  }

  function fmtTime(iso, tz) {
    if (!iso) return "Time to be confirmed";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "Time to be confirmed";
    try {
      return (
        new Intl.DateTimeFormat("en-US", {
          timeZone: tz || EVENT_TZ,
          weekday: "short",
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        }).format(d) + zoneLabel(tz)
      );
    } catch (e) {
      return iso;
    }
  }

  function fmtHour(iso, tz) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    try {
      return (
        new Intl.DateTimeFormat("en-US", {
          timeZone: tz || EVENT_TZ,
          hour: "2-digit",
          minute: "2-digit",
        }).format(d) + zoneLabel(tz)
      );
    } catch (e) {
      return iso;
    }
  }

  function fmtDay(day) {
    if (!day) return "Day to be confirmed";
    var d = new Date(day + "T12:00:00Z");
    if (isNaN(d.getTime())) return day;
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "UTC",
      weekday: "long",
      day: "numeric",
      month: "long",
    }).format(d);
  }

  function fmtUsd(value) {
    if (value === null || value === undefined) return "Not provided";
    var n = Number(value);
    return isNaN(n)
      ? String(value)
      : "$" + n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  function showError(msg) {
    var el = $("error-banner");
    el.textContent = msg;
    var retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "Retry loading";
    retry.className = "secondary";
    retry.addEventListener("click", function () {
      withBusy(retry, refreshAll);
    });
    el.appendChild(document.createElement("br"));
    el.appendChild(retry);
    el.classList.remove("hidden");
  }

  function clearError() {
    $("error-banner").classList.add("hidden");
  }

  // Fetch layer

  function api(path, options, key) {
    var opts = options || {};
    var init = {
      method: opts.method || "GET",
      headers: { Accept: "application/json" },
    };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    return fetch(API + path, init)
      .catch(function () {
        throw new Error(
          "The connection was interrupted. We could not confirm your action.",
        );
      })
      .then(function (res) {
        return res.text().then(function (text) {
          var data = null;
          try {
            data = text ? JSON.parse(text) : null;
          } catch (e) {
            data = null;
          }
          if (!res.ok) {
            if (path === "/goal" && res.status === 422)
              throw new Error(
                "Choose a supported profile: seed investors, AI agent founders, Copilot product managers, or engineers.",
              );
            throw new Error(
              "We could not confirm your action. Try again in a moment.",
            );
          }
          if (!data)
            throw new Error("The response was incomplete. Try loading again.");
          if (key) {
            envelopes[key] = data;
            updateGlobalBadges();
          }
          return data;
        });
      });
  }

  function updateDegradedBanner() {
    var degraded = Object.keys(envelopes).some(function (k) {
      return envelopes[k] && envelopes[k].data_source === "degraded_no_graph";
    });
    $("degraded-banner").classList.toggle("hidden", !degraded);
  }

  function updateGlobalBadges() {
    updateDegradedBanner();
    var modes = {},
      worst = null,
      collected = null,
      warnings = {};
    var domains = envelopes.sources && envelopes.sources.domains;
    if (domains)
      Object.keys(domains).forEach(function (k) {
        modes[domains[k].source_mode] = true;
      });
    contentKeys.forEach(function (k) {
      var env = envelopes[k];
      if (!env) return;
      if (
        !domains &&
        ["live", "fixture", "cached", "mixed"].indexOf(env.data_source) >= 0
      )
        modes[env.data_source] = true;
      if (
        STATUS_RANK.hasOwnProperty(env.status) &&
        (worst === null || STATUS_RANK[env.status] > STATUS_RANK[worst])
      )
        worst = env.status;
      if (env.collected_at && (!collected || env.collected_at > collected))
        collected = env.collected_at;
      (env.warnings || []).forEach(function (w) {
        warnings[w] = true;
      });
    });
    var list = Object.keys(modes);
    var mode = list.length === 1 ? list[0] : list.length ? "mixed" : "unknown";
    var labels = {
      fixture: "Sample data",
      live: "Live data",
      cached: "Cached data",
      mixed: "Mixed sources",
      unknown: "Sources need verification",
    };
    var badge = $("badge-source");
    badge.className =
      "badge " +
      (mode === "fixture" ? "fixture" : mode === "live" ? "live" : "neutral");
    badge.textContent = labels[mode] || labels.unknown;
    badge.title = "Record sources, separate from the ranking engine";
    var st = $("badge-status");
    st.className = "badge " + (worst || "neutral");
    st.textContent =
      {
        ok: "Available",
        degraded: "Partial coverage",
        failed: "Unavailable",
      }[worst] || "Needs verification";
    $("collected-at").textContent = collected
      ? fmtTime(collected)
      : "Collection date unavailable";
    var wl = Object.keys(warnings).sort();
    $("warnings-count").textContent = String(wl.length);
    $("warnings-list").innerHTML = wl
      .map(function (w) {
        return "<li>" + esc(w) + "</li>";
      })
      .join("");
  }

  function friendlyRationale(text) {
    return String(text)
      .replace(/Meet seed investors/g, "Seed investors")
      .replace(/Meet AI agent founders/g, "AI agent founders")
      .replace(/Meet Copilot product managers/g, "Copilot product managers")
      .replace(/Meet engineers/g, "Engineers")
      .replace(/\(weight ([0-9.]+)\)/g, function (_, weight) {
        return "(priority " + Math.round(Number(weight) * 100) + "%)";
      })
      .replace(/founder, executive at/g, "founder or executive at")
      .replace(/participation confirmed_speaker/g, "announced speaker")
      .replace(/participation confirmed_organizer/g, "announced organizer")
      .replace(
        /participation public_attendee_listing/g,
        "publicly listed attendee",
      )
      .replace(/participation unknown/g, "attendance unconfirmed");
  }
  function displayGoalText(text) {
    var value = String(text || "");
    if (
      /^fondateur d.un outil dev ia, je vais a github universe pour rencontrer des investisseurs seed, des fondateurs d.agents ia et des pm copilot\.$/.test(
        fold(value),
      )
    )
      return "I'm an AI developer tools founder attending GitHub Universe to meet seed investors, AI agent founders, and Copilot product managers.";
    return value;
  }
  function fold(text) {
    return String(text || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  }
  function initials(name) {
    return String(name || "?")
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map(function (part) {
        return part.charAt(0);
      })
      .join("")
      .toUpperCase();
  }
  function emptyState(title, detail, action, label) {
    return (
      '<div class="empty-state"><h3>' +
      esc(title) +
      "</h3><p>" +
      esc(detail) +
      "</p>" +
      (action
        ? '<button data-action="' + action + '">' + esc(label) + "</button>"
        : "") +
      "</div>"
    );
  }
  function eventStatus(status) {
    return (
      {
        scheduled: "Scheduled",
        sold_out: "Sold out",
        cancelled: "Cancelled",
        postponed: "Postponed",
        unknown: "Status unconfirmed",
      }[status] || "Status unconfirmed"
    );
  }
  function presenceBadge(person, opp) {
    var label = {
      confirmed_speaker: "Announced speaker",
      confirmed_organizer: "Confirmed organizer",
      public_attendee_listing: "Publicly listed attendee",
    }[person.participation];
    if (label) return '<span class="badge confirmed">' + label + "</span>";
    return (
      '<span class="badge ' +
      (opp.presence === "probable" ? "probable" : "unknown") +
      '">' +
      (opp.presence === "probable"
        ? "Attendance likely"
        : "Attendance unconfirmed") +
      "</span>"
    );
  }
  function toast(message) {
    clearTimeout(toastTimer);
    $("toast").textContent = message;
    $("toast").classList.remove("hidden");
    toastTimer = setTimeout(function () {
      $("toast").classList.add("hidden");
    }, 5500);
  }
  function openDialog(id) {
    var dialog = $(id);
    if (!dialog) return;
    if (id === "goal-dialog") {
      $("goal-error").textContent = "";
      $("goal-text").removeAttribute("aria-invalid");
    }
    var error = dialog.querySelector(".dialog-error");
    if (error) error.remove();
    dialog.showModal();
  }
  function renderDayTabs(id, days, selected, action, all) {
    var list = all ? [{ day: "all" }].concat(days) : days;
    $(id).innerHTML = list
      .map(function (d) {
        var label =
          d.day === "all"
            ? "Entire trip"
            : new Intl.DateTimeFormat("en-US", {
                timeZone: "UTC",
                weekday: "short",
                day: "numeric",
                month: "short",
              }).format(new Date(d.day + "T12:00:00Z"));
        return (
          '<button type="button" data-action="' +
          action +
          '" data-id="' +
          esc(d.day) +
          '" aria-pressed="' +
          (selected === d.day) +
          '" class="' +
          (selected === d.day ? "active" : "") +
          '">' +
          esc(label) +
          "</button>"
        );
      })
      .join("");
  }
  function placesHtml(markers) {
    return (
      '<ul class="plain-list">' +
      markers
        .map(function (m) {
          return (
            "<li><b>" +
            esc(m.label) +
            "</b><br>" +
            esc(m.lat) +
            ", " +
            esc(m.lng) +
            " · " +
            esc(
              {
                exact: "Exact location",
                approximate: "Approximate location",
                city: "City-level location",
                unknown: "Location accuracy unknown",
              }[m.precision] || "Location accuracy unknown",
            ) +
            (m.planned ? " · In your plan" : "") +
            "</li>"
          );
        })
        .join("") +
      "</ul>"
    );
  }
  function renderSources(res) {
    var names = {
      conference: "Conference",
      events: "Events",
      people: "People",
      companies: "Companies",
      stays: "Stays",
      flights: "Flights",
    };
    $("source-domains").innerHTML = Object.keys(res.domains || {})
      .map(function (key) {
        var d = res.domains[key];
        return (
          '<div class="source-domain"><span>' +
          esc(names[key] || key) +
          "</span><span>" +
          sourceModeBadge(d.source_mode) +
          " " +
          statusBadge(d.status) +
          "</span></div>"
        );
      })
      .join("");
  }
  function renderConference(c) {
    var conf = c.conference || {},
      user = c.user || {};
    if (!$("goal-text").value)
      $("goal-text").value = displayGoalText(c.demo_goal_text);
    $("conference-title").textContent = conf.name || "Your conference";
    $("sidebar-conference").textContent = conf.name || "Your conference";
    $("conference-place").textContent =
      conf.venue_name || "Venue to be confirmed";
    $("conference-city").textContent = conf.city || "City to be confirmed";
    $("hero-city").textContent = conf.city || "Your next conference";
    $("conference-dates").textContent =
      conf.start_date && conf.end_date
        ? shortDate(conf.start_date) + " — " + shortDate(conf.end_date)
        : "Dates to be confirmed";
    $("trip-dates").textContent =
      user.depart_date && user.return_date
        ? shortDate(user.depart_date) +
          " — " +
          shortDate(user.return_date) +
          " · " +
          (conf.city || "")
        : "Trip dates to be confirmed";
    $("conf-name").textContent = [conf.name, conf.venue_name, conf.city]
      .filter(Boolean)
      .join(" · ");
    var route = document.querySelector(".journey-route");
    if (route)
      route.firstElementChild.textContent =
        user.origin_city === "New York" ? "NYC" : user.origin_city || "Origin";
    if (route)
      route.lastElementChild.textContent =
        conf.city === "San Francisco" ? "SF" : conf.city || "Destination";
  }
  function shortDate(date) {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "UTC",
      day: "numeric",
      month: "short",
    }).format(new Date(date + "T12:00:00Z"));
  }

  // Renderers

  function renderGoals(plan) {
    var goals = (plan && plan.goals) || [];
    $("goals-list").innerHTML = goals.length
      ? goals
          .map(function (g) {
            var w = typeof g.priority === "number" ? g.priority : null;
            var pct = w === null ? 0 : Math.round(w * 100);
            return (
              '<div class="goal"><span class="weight">' +
              esc(w === null ? "unknown" : w.toFixed(2)) +
              '</span><span class="bar"><span style="width:' +
              pct +
              '%"></span></span><span>' +
              esc(g.description) +
              ' <span class="muted small-text">' +
              esc((g.target_roles || []).join(", ")) +
              "</span></span></div>"
            );
          })
          .join("")
      : '<p class="muted">No supported goal found.</p>';
    $("computed-by").textContent = plan
      ? "Calculated by: " +
        orUnknown(plan.computed_by) +
        (plan.scenario_id ? " | active scenario: " + plan.scenario_id : "")
      : "";
  }

  function roiTile(name, value) {
    var unknown = value === null || value === undefined;
    return (
      '<div class="roi-tile"><div class="value' +
      (unknown ? " unknown" : "") +
      '">' +
      esc(unknown ? "Not provided" : value) +
      '</div><div class="name">' +
      esc(name) +
      "</div></div>"
    );
  }

  function renderRoi(roi) {
    if (!roi) {
      $("roi-grid").innerHTML = emptyState(
        "Your summary is unavailable.",
        "Try loading again in a moment.",
      );
      return;
    }
    $("roi-grid").innerHTML =
      roiTile(
        "Known costs (USD)",
        roi.spend_usd == null ? null : fmtUsd(roi.spend_usd),
      ) +
      roiTile("Meetings recorded", roi.meetings) +
      roiTile("Qualified contacts", roi.qualified_contacts) +
      roiTile("Opportunities scoring 30+", roi.opportunities);
    $("roi-note").textContent =
      "Indicative budget: " +
      fmtUsd(roi.budget_usd) +
      (roi.spend_note ? " · " + roi.spend_note : "");
    [
      ["roi-spend", roi.spend_usd == null ? null : fmtUsd(roi.spend_usd)],
      ["roi-meetings", roi.meetings],
      ["roi-qualified", roi.qualified_contacts],
      ["roi-opportunities", roi.opportunities],
    ].forEach(function (pair) {
      var element = $(pair[0]);
      element.textContent = pair[1] == null ? "Not provided" : String(pair[1]);
      element.classList.toggle("unknown", pair[1] == null);
    });
    $("roi-spend-note").textContent =
      roi.spend_usd == null ? "Prices are not available yet." : "";
    $("stat-met").textContent = roi.meetings == null ? "—" : roi.meetings;
  }

  function planItems(plan) {
    var out = [];
    ((plan && plan.plan && plan.plan.days) || []).forEach(function (d) {
      (d.items || []).forEach(function (i) {
        out.push(i);
      });
    });
    return out;
  }

  function renderNextActions(plan) {
    var items = planItems(plan)
      .filter(function (i) {
        return !i.attended;
      })
      .slice(0, 5);
    $("next-actions").innerHTML = items.length
      ? items
          .map(function (i) {
            var who = (i.people || [])
              .map(function (p) {
                return p.name;
              })
              .join(", ");
            return (
              "<li><b>" +
              esc(fmtTime(i.start_at, i.timezone)) +
              "</b> " +
              esc(i.title) +
              ' <span class="muted">(' +
              esc(orUnknown(i.venue)) +
              ")</span>" +
              (who
                ? '<div class="muted small-text">Meet: ' + esc(who) + "</div>"
                : "") +
              "</li>"
            );
          })
          .join("")
      : '<li class="muted">No actions planned.</li>';
  }

  function renderPlan(plan) {
    var days = (plan && plan.plan && plan.plan.days) || [];
    var count = planItems(plan).length;
    $("stat-plan").textContent = count;
    $("nav-plan-count").textContent = count;
    var tabs = $("agenda-day-tabs");
    if (
      (!tabs.dataset.initialized || tabs.dataset.initialized === "pending") &&
      days.length
    ) {
      var conferenceDay =
        envelopes.conference &&
        envelopes.conference.conference &&
        envelopes.conference.conference.start_date;
      selectedAgendaDay = days.some(function (d) {
        return d.day === conferenceDay && d.items.length;
      })
        ? conferenceDay
        : (
            days.find(function (d) {
              return d.items.length;
            }) || days[0]
          ).day;
      tabs.dataset.initialized = conferenceDay ? "true" : "pending";
    }
    if (
      selectedAgendaDay !== "all" &&
      !days.some(function (d) {
        return d.day === selectedAgendaDay;
      })
    )
      selectedAgendaDay = "all";
    renderDayTabs(
      "agenda-day-tabs",
      days,
      selectedAgendaDay,
      "agenda-day",
      true,
    );
    var visible = days.filter(function (d) {
      return selectedAgendaDay === "all" || d.day === selectedAgendaDay;
    });
    var records = (envelopes.events || lastEvents || {}).items || [];
    var byId = {};
    records.forEach(function (event) {
      byId[event.id] = event;
    });
    var types = {
      session: "Session",
      workshop: "Workshop",
      party: "Party",
      side_event: "Side event",
      meetup: "Meetup",
      conference: "Conference",
      other: "Event",
    };
    $("plan-days").innerHTML = visible.length
      ? visible
          .map(function (day) {
            var date = new Date(day.day + "T12:00:00Z");
            var dateLabel = new Intl.DateTimeFormat("en-US", {
              timeZone: "UTC",
              month: "short",
              day: "numeric",
            }).format(date);
            var weekday = new Intl.DateTimeFormat("en-US", {
              timeZone: "UTC",
              weekday: "long",
            }).format(date);
            return (
              '<section class="day agenda-feed-day"><div class="agenda-date-rail"><h3>' +
              esc(dateLabel) +
              "</h3><span>" +
              esc(weekday) +
              '</span></div><div class="agenda-day-events">' +
              ((day.items || []).length
                ? day.items
                    .map(function (item) {
                      var event = byId[item.event_id] || {
                        title: item.title,
                        event_type: item.event_type,
                      };
                      var venue =
                        item.venue || (event.venue && event.venue.name);
                      var room =
                        item.room && item.room !== venue ? item.room : "";
                      if (venue && room.endsWith(" @ " + venue))
                        room = room.slice(0, -(venue.length + 3));
                      var place = [venue, room].filter(Boolean).join(" · ");
                      return (
                        '<article class="event-item agenda-event-card' +
                        (item.attended ? " agenda-attended" : "") +
                        '"><div class="agenda-event-copy"><div class="agenda-event-time"><time datetime="' +
                        esc(item.start_at || "") +
                        '">' +
                        esc(fmtHour(item.start_at, item.timezone)) +
                        "</time>" +
                        (item.end_at
                          ? "<span>– " +
                            esc(fmtHour(item.end_at, item.timezone)) +
                            "</span>"
                          : "") +
                        '</div><h3><button type="button" class="event-title-button" data-action="event" data-id="' +
                        esc(item.event_id) +
                        '">' +
                        esc(item.title) +
                        '</button></h3><p class="agenda-event-place"><svg class="icon" aria-hidden="true"><use href="#i-pin"/></svg>' +
                        esc(place || "Venue to be confirmed") +
                        '</p><div class="agenda-event-bottom"><span class="agenda-format">' +
                        esc(types[item.event_type] || "Event") +
                        '</span><div class="actions"><button type="button" class="agenda-quiet-action' +
                        (item.attended ? " on" : "") +
                        '" data-action="attended" data-id="' +
                        esc(item.event_id) +
                        '"' +
                        (item.attended ? " disabled" : "") +
                        ">" +
                        (item.attended
                          ? "Attendance recorded"
                          : "Mark attended") +
                        '</button><button type="button" class="agenda-quiet-action" data-action="skipped" data-id="' +
                        esc(item.event_id) +
                        '">Skip this event</button></div></div></div><button type="button" class="event-cover-button agenda-poster-button" data-action="event" data-id="' +
                        esc(item.event_id) +
                        '" aria-label="View ' +
                        esc(item.title) +
                        '">' +
                        eventArtwork(event, false) +
                        "</button></article>"
                      );
                    })
                    .join("")
                : '<p class="agenda-empty-day">A little room to explore. No events planned for this day.</p>') +
              "</div></section>"
            );
          })
          .join("")
      : emptyState(
          "Nothing planned for this day.",
          "Explore the other days of your trip.",
        );
    var conflicts = (plan && plan.plan && plan.plan.conflicts) || [];
    $("conflicts").innerHTML = conflicts.length
      ? conflicts
          .map(function (conflict) {
            return (
              '<div class="agenda-alternative"><span>' +
              esc(fmtDay(conflict.day)) +
              "</span><h3>" +
              esc(conflict.loser && conflict.loser.title) +
              "</h3><p>" +
              esc(conflict.verdict) +
              "</p></div>"
            );
          })
          .join("")
      : '<p class="muted">No conflicts found in this plan.</p>';
    var excluded = (plan && plan.plan && plan.plan.excluded) || [];
    $("excluded").innerHTML =
      excluded
        .map(function (item) {
          return (
            "<li><span>" +
            esc(item.title) +
            '</span><span class="muted">' +
            esc(orUnknown(item.reason)) +
            "</span></li>"
          );
        })
        .join("") || '<li class="muted">No events skipped.</li>';
    var alternativesCount = $("agenda-alternatives-count");
    if (alternativesCount)
      alternativesCount.textContent = String(
        conflicts.length + excluded.length,
      );
  }

  function renderEvents(ev) {
    lastEvents = ev;
    var all = (ev && ev.items) || [];
    document.dispatchEvent(new CustomEvent("conferge:events", { detail: all }));
    $("stat-events").textContent = all.length;
    renderDiscoverEvents(all);
    var needle = fold($("events-search").value),
      type = $("events-type").value;
    var items = all.filter(function (event) {
      return (
        (type === "all" || event.event_type === type) &&
        (!needle ||
          fold(
            event.title + " " + ((event.venue && event.venue.name) || ""),
          ).indexOf(needle) >= 0)
      );
    });
    $("events-result-count").textContent =
      items.length + (items.length === 1 ? " event" : " events");
    var types = {
      session: "Session",
      workshop: "Workshop",
      party: "Party",
      side_event: "Side event",
      meetup: "Meetup",
      conference: "Conference",
      other: "Event",
    };
    var lastDay = null;
    $("events-list").innerHTML = items.length
      ? items
          .map(function (event) {
            var dayKey = event.start_at
              ? new Intl.DateTimeFormat("en-CA", {
                  timeZone: event.timezone || EVENT_TZ,
                  year: "numeric",
                  month: "2-digit",
                  day: "2-digit",
                }).format(new Date(event.start_at))
              : "unknown";
            var heading = "";
            if (dayKey !== lastDay) {
              lastDay = dayKey;
              heading =
                '<h3 class="agenda-browse-day">' +
                esc(
                  dayKey === "unknown"
                    ? "Date to be confirmed"
                    : fmtDay(dayKey),
                ) +
                "</h3>";
            }
            var status =
              event.status !== "scheduled"
                ? '<span class="agenda-event-status">' +
                  esc(eventStatus(event.status)) +
                  "</span>"
                : "";
            return (
              heading +
              '<article class="event-browser-row agenda-browse-card"><div class="agenda-browse-copy"><div class="agenda-event-time">' +
              esc(fmtHour(event.start_at, event.timezone)) +
              "<span>· " +
              esc(types[event.event_type] || "Event") +
              '</span></div><h3><button type="button" class="event-title-button" data-action="event" data-id="' +
              esc(event.id) +
              '">' +
              esc(event.title) +
              '</button></h3><p class="agenda-event-place"><svg class="icon" aria-hidden="true"><use href="#i-pin"/></svg>' +
              esc(orUnknown(event.venue && event.venue.name)) +
              "</p>" +
              status +
              (event.attended
                ? '<span class="agenda-recorded">Attendance recorded</span>'
                : "") +
              (event.skipped
                ? '<span class="agenda-event-status">Skipped</span>'
                : "") +
              '</div><button type="button" class="event-cover-button agenda-poster-button" data-action="event" data-id="' +
              esc(event.id) +
              '" aria-label="View ' +
              esc(event.title) +
              '">' +
              eventArtwork(event, false) +
              "</button></article>"
            );
          })
          .join("")
      : emptyState(
          "No events match your search.",
          "Try a different name or remove the event type filter.",
          "clear-events",
          "Clear filters",
        );
    if (envelopes.plan) renderPlan(envelopes.plan);
  }

  function isPlaceholderStay(name) {
    return /^\[FIXTURE\]/i.test(name || "");
  }
  function renderTravel(t) {
    if (!t) return;
    var legs = t.itinerary || [];
    var flights = legs.filter(function (leg) {
      return leg.kind === "flight";
    });
    var outbound = flights[0],
      inbound = flights[flights.length - 1];
    var form = $("travel-research-form");
    if (!form.dataset.initialized) {
      $("research-origin").value = outbound ? outbound.from : "JFK";
      $("research-depart").value = (outbound && outbound.date) || "2026-10-27";
      $("research-return").value = (inbound && inbound.date) || "2026-10-30";
      form.dataset.initialized = "true";
    }
    updateResearchLinks();
    var props = t.proposals || [];
    $("proposals").innerHTML = props.length
      ? props
          .map(function (p) {
            var text = p.text || "",
              reason = p.reason || "";
            var arrival = text.match(
              /^You land on [^:]+: pick a flight arriving before (\S+) to make '(.*)'\.$/,
            );
            if (arrival) {
              text = "Planning your arrival?";
              reason =
                "“" +
                arrival[2] +
                "” starts at " +
                fmtHour(arrival[1]) +
                " on " +
                shortDate(arrival[1].slice(0, 10)) +
                ". Check your arrival and allow time to get there.";
            }
            return (
              '<div class="trip-suggestion"><div><h3>' +
              esc(text) +
              "</h3><p>" +
              esc(reason) +
              "</p></div>" +
              (p.accepted
                ? '<span class="badge ok">Suggestion saved</span>'
                : '<button class="small secondary" data-action="accept" data-id="' +
                  esc(p.id) +
                  '">Save suggestion</button>') +
              "</div>"
            );
          })
          .join("")
      : '<p class="muted">No timing suggestions for your current agenda.</p>';
    var b = t.budget || {};
    $("budget").textContent =
      b.budget_usd == null ? "" : "Your budget · " + fmtUsd(b.budget_usd);
  }

  function updateResearchLinks() {
    var origin = $("research-origin").value.trim(),
      depart = $("research-depart").value,
      back = $("research-return").value;
    $("research-return").min = depart;
    $("research-return").setCustomValidity(
      back < depart ? "Return must be after departure." : "",
    );
    $("research-flights-link").href =
      "https://www.google.com/travel/flights?q=" +
      encodeURIComponent(
        "Flights from " +
          origin +
          " to San Francisco on " +
          depart +
          " returning " +
          back,
      );
    $("research-stays-link").href =
      "https://www.booking.com/searchresults.html?ss=San+Francisco&checkin=" +
      encodeURIComponent(depart) +
      "&checkout=" +
      encodeURIComponent(back) +
      "&group_adults=1&no_rooms=1";
    var changed = $("travel-research-form").dataset.changed;
    $("travel-offer-context").textContent = changed
      ? "Search links use your dates. Collected offers below retain their original dates."
      : "Collected offers for your conference trip. Check current prices with the provider.";
  }

  function renderFlights(res) {
    var items = ((res && res.items) || []).filter(function (offer) {
      return !(
        offer.source &&
        offer.source.provider === "fixture" &&
        offer.total_price == null &&
        !offer.booking_url
      );
    });
    var sort = $("flight-sort").value;
    items.sort(function (a, b) {
      if (sort === "price" && a.currency === b.currency)
        return (
          (a.total_price == null ? Infinity : Number(a.total_price)) -
          (b.total_price == null ? Infinity : Number(b.total_price))
        );
      return String(a.id).localeCompare(String(b.id));
    });
    $("flights").innerHTML = items.length
      ? items
          .map(function (leg) {
            var slice = (leg.slices || [])[0] || {},
              segments = slice.segments || [],
              first = segments[0] || {},
              last = segments[segments.length - 1] || first;
            var link = safeUrl(leg.booking_url),
              from = first.origin_iata || "Departure",
              to = last.destination_iata || "SFO";
            return (
              '<article class="travel-offer"><div><span class="eyebrow">' +
              esc(
                (leg.slices || []).length > 1 ||
                  leg.return_slice_collected === false
                  ? "Round-trip quote"
                  : "One-way",
              ) +
              "</span><h3>" +
              esc(from) +
              " → " +
              esc(to) +
              "</h3><p>" +
              esc(
                [
                  first.marketing_carrier,
                  first.departure_at
                    ? fmtTime(first.departure_at)
                    : "Time to be confirmed",
                  segments.length
                    ? segments.length === 1
                      ? "Nonstop"
                      : segments.length - 1 + " stop(s)"
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · "),
              ) +
              '</p></div><div class="travel-offer-price"><strong>' +
              esc(flightPriceText(leg)) +
              "</strong>" +
              (link
                ? '<a class="secondary" href="' +
                  esc(link) +
                  '" target="_blank" rel="noopener noreferrer">View flight</a>'
                : '<span class="muted small-text">Search the airline for this route</span>') +
              "</div><details><summary>Offer details</summary>" +
              sourceBadge(leg.source_mode) +
              sourceApiBadge(leg.source) +
              "<p>Collected " +
              esc(
                leg.collected_at
                  ? fmtTime(leg.collected_at)
                  : "date unavailable",
              ) +
              "</p></details></article>"
            );
          })
          .join("")
      : '<p class="travel-empty">No flight offers collected yet. Search flights above to compare current options.</p>';
  }

  function renderStays(s) {
    var items = ((s && s.items) || []).filter(function (stay) {
      return !isPlaceholderStay(stay.name);
    });
    if ($("stay-sort").value === "distance")
      items.sort(function (a, b) {
        return (
          (a.distance_to_venue_m == null ? Infinity : a.distance_to_venue_m) -
          (b.distance_to_venue_m == null ? Infinity : b.distance_to_venue_m)
        );
      });
    else if ($("stay-sort").value === "price")
      items.sort(function (a, b) {
        return a.currency === b.currency
          ? (a.total_price == null ? Infinity : Number(a.total_price)) -
              (b.total_price == null ? Infinity : Number(b.total_price))
          : 0;
      });
    $("stays").innerHTML = items.length
      ? items
          .map(function (st) {
            var link = safeUrl(st.booking_url);
            var distance =
              st.distance_to_venue_m == null
                ? ""
                : (st.distance_to_venue_m / 1000).toFixed(1) +
                  " km from the conference" +
                  (st.distance_is_straight_line_estimate
                    ? " · straight-line estimate"
                    : "");
            return (
              '<article class="trip-stay"><div><h3>' +
              esc(st.name) +
              "</h3><p>" +
              esc(distance || "Check the location before booking") +
              '</p><p class="small-text">' +
              esc(shortDate(st.check_in)) +
              " – " +
              esc(shortDate(st.check_out)) +
              '</p></div><div class="trip-stay-price"><strong>' +
              esc(
                st.total_price == null
                  ? "Price unavailable"
                  : st.total_price + " " + (st.currency || ""),
              ) +
              '</strong><span class="muted small-text">' +
              esc(
                st.price_status === "verified_bookable"
                  ? "Verified for these dates"
                  : "Availability needs checking",
              ) +
              "</span>" +
              (link
                ? '<a class="secondary" href="' +
                  esc(link) +
                  '" target="_blank" rel="noopener noreferrer">View stay</a>'
                : "") +
              "</div><details><summary>Offer details</summary>" +
              sourceApiBadge(st.source) +
              "<p>" +
              esc(
                [
                  st.availability,
                  st.price_status,
                  st.collected_at
                    ? "Collected " + fmtTime(st.collected_at)
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · "),
              ) +
              "</p></details></article>"
            );
          })
          .join("")
      : '<div class="trip-stay-empty"><span class="trip-stay-symbol" aria-hidden="true">⌂</span><div><h3>A good stay starts with the right location.</h3><p>No stay offers are available for these dates yet. Use the map to find the neighborhoods around your agenda.</p></div></div>';
  }

  var travelMapState = { day: "all", scope: "planned", selected: null };
  function markerColor(kind, planned) {
    if (kind === "conference") return "#7c5cc4";
    if (kind === "stay") return "#58778b";
    return planned ? "#353b49" : "#8f98a8";
  }

  function renderMap(m) {
    lastMapData = m;
    var events = (lastEvents || envelopes.events || {}).items || [],
      byId = {};
    events.forEach(function (event) {
      byId[event.id] = event;
    });
    var markers = ((m && m.markers) || []).filter(function (place) {
      return (
        typeof place.lat === "number" &&
        typeof place.lng === "number" &&
        !isPlaceholderStay(place.label)
      );
    });
    var anchor = markers.find(function (place) {
      return place.kind === "conference";
    });
    var local = markers.filter(function (place) {
      return (
        !anchor ||
        (Math.abs(place.lat - anchor.lat) < 0.7 &&
          Math.abs(place.lng - anchor.lng) < 0.9)
      );
    });
    function eventDay(place) {
      var event = byId[place.id];
      return event && event.start_at
        ? new Intl.DateTimeFormat("en-CA", {
            timeZone: EVENT_TZ,
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
          }).format(new Date(event.start_at))
        : null;
    }
    var days = [];
    local.forEach(function (place) {
      var day = eventDay(place);
      if (day && days.indexOf(day) === -1) days.push(day);
    });
    days.sort();
    var daySelect = $("travel-map-day"),
      scopeSelect = $("travel-map-scope");
    daySelect.innerHTML =
      '<option value="all">All days</option>' +
      days
        .map(function (day) {
          return (
            '<option value="' +
            esc(day) +
            '">' +
            esc(shortDate(day)) +
            "</option>"
          );
        })
        .join("");
    if (travelMapState.day !== "all" && days.indexOf(travelMapState.day) === -1)
      travelMapState.day = "all";
    daySelect.value = travelMapState.day;
    scopeSelect.value = travelMapState.scope;
    daySelect.onchange = function () {
      travelMapState.day = this.value;
      travelMapState.selected = null;
      renderMap(lastMapData);
    };
    scopeSelect.onchange = function () {
      travelMapState.scope = this.value;
      travelMapState.selected = null;
      renderMap(lastMapData);
    };
    var candidates = local.filter(function (place) {
      return (
        place.kind === "conference" ||
        ((place.kind === "stay" ||
          travelMapState.scope === "nearby" ||
          place.planned) &&
          (place.kind === "stay" ||
            travelMapState.day === "all" ||
            eventDay(place) === travelMapState.day))
      );
    });
    candidates.sort(function (a, b) {
      if (a.kind === "conference") return -1;
      if (b.kind === "conference") return 1;
      if (a.planned !== b.planned) return a.planned ? -1 : 1;
      return ((byId[a.id] || {}).start_at || "z").localeCompare(
        (byId[b.id] || {}).start_at || "z",
      );
    });
    var cap = travelMapState.scope === "nearby" ? 30 : 13,
      visible = candidates.slice(0, cap);
    if (
      !visible.some(function (place) {
        return place.id === travelMapState.selected;
      })
    )
      travelMapState.selected = (visible[1] || visible[0] || {}).id || null;
    $("travel-map-count").textContent =
      visible.length +
      " places" +
      (candidates.length > cap
        ? " · first " + (cap - 1) + " events shown"
        : "");
    $("travel-map-note").textContent =
      travelMapState.day === "all"
        ? "Choose a day to see your visits in order. Locations may be approximate."
        : "The dotted line shows visit order, not walking or driving directions.";
    var leafletMarkers = {},
      bounds = [],
      selected = null;
    function showSelection(id, center) {
      travelMapState.selected = id;
      selected = visible.find(function (place) {
        return place.id === id;
      });
      if (!selected) return;
      var event = byId[id];
      $("travel-place-detail").innerHTML =
        '<span class="eyebrow">' +
        esc(
          selected.kind === "conference"
            ? "CONFERENCE"
            : selected.kind === "stay"
              ? "STAY OPTION"
              : selected.planned
                ? "IN YOUR AGENDA"
                : "NEARBY EVENT",
        ) +
        "</span><h3>" +
        esc(selected.label) +
        "</h3><p>" +
        esc(
          event
            ? fmtTime(event.start_at, event.timezone)
            : selected.kind === "stay"
              ? "A place to stay · check the offer for your dates"
              : "Your conference venue",
        ) +
        '</p><p class="small-text muted">' +
        esc(
          selected.precision === "exact"
            ? "Venue location"
            : "Approximate location · confirm before you go",
        ) +
        "</p>" +
        (event
          ? '<button class="text-button" data-action="event" data-id="' +
            esc(id) +
            '">View event details</button>'
          : "");
      $("map-places")
        .querySelectorAll("[data-travel-place]")
        .forEach(function (button) {
          var active = button.getAttribute("data-travel-place") === id;
          button.setAttribute("aria-pressed", String(active));
        });
      Object.keys(leafletMarkers).forEach(function (key) {
        var marker = leafletMarkers[key];
        marker.setZIndexOffset(key === id ? 1000 : 0);
        var element = marker.getElement();
        if (element) element.classList.toggle("is-selected", key === id);
      });
      if (center && map && leafletMarkers[id])
        map.flyTo([selected.lat, selected.lng], Math.max(map.getZoom(), 14), {
          duration: 0.4,
          animate: !window.matchMedia("(prefers-reduced-motion: reduce)")
            .matches,
        });
    }
    $("map-places").innerHTML = visible.length
      ? visible
          .map(function (place, index) {
            var event = byId[place.id];
            return (
              '<button type="button" class="travel-place-row" data-travel-place="' +
              esc(place.id) +
              '" aria-pressed="false"><span class="travel-place-number' +
              (place.kind === "conference" ? " is-conference" : "") +
              '">' +
              (place.kind === "conference" ? "C" : index) +
              "</span><span><strong>" +
              esc(place.label) +
              "</strong><small>" +
              esc(
                event
                  ? shortDate(eventDay(place)) +
                      " · " +
                      fmtHour(event.start_at, event.timezone)
                  : place.kind === "stay"
                    ? "Stay option"
                    : "Conference venue",
              ) +
              "</small></span></button>"
            );
          })
          .join("")
      : '<p class="travel-map-empty">No locations for this selection. Try nearby events or another day.</p>';
    $("map-places")
      .querySelectorAll("[data-travel-place]")
      .forEach(function (button) {
        button.onclick = function () {
          showSelection(this.getAttribute("data-travel-place"), true);
        };
      });
    var el = $("map");
    if (typeof L === "undefined") {
      el.innerHTML =
        '<div class="map-fallback"><h3>The map could not load.</h3><p>Select a place in the list to explore its details.</p></div>';
      showSelection(travelMapState.selected, false);
      $("travel-map-fit").disabled = true;
      return;
    }
    $("travel-map-fit").disabled = false;
    if (!map) {
      map = L.map(el, { scrollWheelZoom: false, zoomControl: true }).setView(
        anchor ? [anchor.lat, anchor.lng] : [37.79, -122.42],
        13,
      );
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors",
      }).addTo(map);
    }
    if (mapLayer) mapLayer.remove();
    mapLayer = L.layerGroup().addTo(map);
    visible.forEach(function (place, index) {
      bounds.push([place.lat, place.lng]);
      var marker = L.marker([place.lat, place.lng], {
        icon: L.divIcon({
          className:
            "travel-map-marker" +
            (place.kind === "conference" ? " is-conference" : ""),
          html:
            "<span>" + (place.kind === "conference" ? "C" : index) + "</span>",
          iconSize: [32, 36],
          iconAnchor: [16, 36],
        }),
        title: place.label,
        keyboard: true,
      }).addTo(mapLayer);
      marker.on("click", function () {
        showSelection(place.id, true);
      });
      leafletMarkers[place.id] = marker;
    });
    if (travelMapState.day !== "all") {
      var route = visible
        .filter(function (place) {
          return place.kind === "event" && place.planned;
        })
        .map(function (place) {
          return [place.lat, place.lng];
        });
      if (route.length > 1)
        L.polyline(route, {
          color: "#74628f",
          weight: 2,
          opacity: 0.65,
          dashArray: "4 7",
          interactive: false,
        }).addTo(mapLayer);
    }
    function fitPlaces() {
      if (bounds.length)
        map.fitBounds(bounds, { padding: [46, 46], maxZoom: 14 });
    }
    $("travel-map-fit").onclick = fitPlaces;
    fitPlaces();
    showSelection(travelMapState.selected, false);
  }

  function renderLegend(types) {
    $("graph-legend").innerHTML = types
      .map(function (t) {
        return (
          '<span><span class="swatch" style="background:' +
          (TYPE_COLORS[t] || OTHER_COLOR) +
          '"></span>' +
          esc(t) +
          "</span>"
        );
      })
      .join("");
  }

  function edgeDetail(e) {
    return (
      "<b>" +
      esc(e.type) +
      "</b>: " +
      esc(e.source) +
      " to " +
      esc(e.target) +
      "<br>Evidence: " +
      esc(orUnknown(e.evidence_source)) +
      " | confidence " +
      esc(orUnknown(e.confidence)) +
      " | observed at " +
      esc(orUnknown(e.observed_at))
    );
  }

  var connectionCards = [];
  var selectedConnectionId = null;

  function connectionAvatar(person, size) {
    if (typeof personAvatar === "function") return personAvatar(person, size);
    var initials = (person.name || "")
      .split(/\s+/)
      .slice(0, 2)
      .map(function (part) {
        return part.charAt(0);
      })
      .join("");
    return (
      '<span class="connection-avatar-placeholder" aria-hidden="true">' +
      esc(initials) +
      "</span>"
    );
  }

  function connectionGoal(card) {
    var ids = (card.opportunity || {}).goal_ids || [];
    var goals = (envelopes.plan && envelopes.plan.goals) || [];
    return (
      goals.filter(function (goal) {
        return ids.indexOf(goal.id) >= 0;
      })[0] || null
    );
  }

  function connectionPathHtml(steps) {
    var names = {
      HAS_GOAL: "Your priority",
      SERVES_GOAL: "Profile match",
      SPEAKS_AT: "Speaker listing",
      HOSTS: "Organizer listing",
      PART_OF: "Conference affiliation",
      WORKS_AT: "Company",
      ABOUT: "Topic",
      CONNECTED_TO: "Linked profile",
      ATTENDS_CONFIRMED: "Public attendee listing",
      MET: "Saved conversation",
    };
    return (
      '<div class="connection-source-path">' +
      (steps || [])
        .map(function (step) {
          if (step.node)
            return (
              '<span class="connection-source-node">' +
              esc(
                (step.node.label || step.node.id).replace(
                  /\s*\([0-9.]+\)$/,
                  "",
                ),
              ) +
              "</span>"
            );
          if (step.edge)
            return (
              '<span class="connection-source-relation">' +
              esc(
                names[step.edge.type] ||
                  step.edge.type.replace(/_/g, " ").toLowerCase(),
              ) +
              "</span>"
            );
          return "";
        })
        .join("") +
      "</div>"
    );
  }

  function connectionSourceHtml(evidence) {
    return (evidence || [])
      .map(function (source) {
        var url = safeUrl(source.source_url);
        return (
          "<li>" +
          (url
            ? '<a href="' +
              esc(url) +
              '" target="_blank" rel="noopener noreferrer">' +
              esc(source.provider || "View source") +
              "</a>"
            : esc(source.provider || "Source not specified")) +
          " " +
          sourceBadge(source.source_mode) +
          (source.collected_at
            ? ' <span class="muted small-text">Collected ' +
              esc(fmtTime(source.collected_at)) +
              "</span>"
            : "") +
          "</li>"
        );
      })
      .join("");
  }

  function connectionChoiceHtml(card) {
    return (
      '<button class="connection-choice" data-action="path" data-id="' +
      esc(card.person.id) +
      '" aria-pressed="false"><span class="connection-choice-avatar">' +
      connectionAvatar(card.person, "small") +
      '</span><span class="connection-choice-name">' +
      esc(card.person.name) +
      "</span></button>"
    );
  }

  function renderConnectionSelection(personId) {
    var available =
      (lastPeople && lastPeople.items) ||
      (envelopes.people && envelopes.people.items) ||
      connectionCards;
    var card =
      available.filter(function (c) {
        return c.person && c.person.id === personId;
      })[0] ||
      connectionCards.filter(function (c) {
        return c.person && c.person.id === personId;
      })[0];
    if (!card) return;
    selectedConnectionId = personId;
    var buttons = $("connection-choices").querySelectorAll("button[data-id]");
    if (
      !Array.prototype.some.call(buttons, function (button) {
        return button.getAttribute("data-id") === personId;
      })
    ) {
      $("connection-choices").insertAdjacentHTML(
        "afterbegin",
        connectionChoiceHtml(card),
      );
      if (buttons.length >= 6) buttons[buttons.length - 1].remove();
    }
    var person = card.person,
      opportunity = card.opportunity || {},
      company = card.company || {},
      goal = connectionGoal(card);
    var events =
      (lastEvents && lastEvents.items) ||
      (envelopes.events && envelopes.events.items) ||
      [];
    var event = events.filter(function (item) {
      return item.id === opportunity.event_id;
    })[0];
    var goalLabel = goal ? goal.description : "Your conference priorities";
    var sharedTopics = goal
      ? (person.topics || []).filter(function (topic) {
          return (goal.topics || []).some(function (g) {
            return fold(g) === fold(topic);
          });
        })
      : [];
    var roleLabel =
      {
        confirmed_speaker: "Listed speaker",
        confirmed_organizer: "Listed organizer",
        public_attendee_listing: "Public attendee listing",
        relevant_candidate: "Suggested contact",
        unknown: "Suggested contact",
      }[person.participation] || "Suggested contact";
    var eventRelation =
      person.participation === "confirmed_speaker" &&
      (person.event_ids || []).indexOf(opportunity.event_id) >= 0
        ? "Speaking at"
        : person.participation === "confirmed_organizer" &&
            (person.event_ids || []).indexOf(opportunity.event_id) >= 0
          ? "Organizing"
          : "Linked event";
    var profile = safeUrl(
      person.linkedin_url || person.public_profile_url || person.github_url,
    );
    $("connection-choices")
      .querySelectorAll("button[data-id]")
      .forEach(function (button) {
        var active = button.getAttribute("data-id") === personId;
        button.classList.toggle("selected", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    $("connection-selected").innerHTML =
      '<article class="connection-profile"><div class="connection-portrait">' +
      connectionAvatar(person, "large") +
      '</div><div class="connection-profile-copy"><span class="connection-participation">' +
      esc(roleLabel) +
      "</span><h2>" +
      esc(person.name) +
      '</h2><p class="connection-role">' +
      esc(person.title || person.role || "Role not provided") +
      (company.name ? " <span>at " + esc(company.name) + "</span>" : "") +
      "</p>" +
      ((person.topics || []).length
        ? '<div class="connection-topics">' +
          person.topics
            .slice(0, 4)
            .map(function (topic) {
              return "<span>" + esc(topic) + "</span>";
            })
            .join("") +
          "</div>"
        : "") +
      '<div class="connection-actions">' +
      (card.met
        ? '<span class="connection-saved">Conversation saved</span>'
        : '<button class="primary" data-action="met" data-id="' +
          esc(person.id) +
          '" data-name="' +
          esc(person.name) +
          '">Record a conversation</button>') +
      (profile
        ? '<a class="connection-profile-link" href="' +
          esc(profile) +
          '" target="_blank" rel="noopener noreferrer">View profile</a>'
        : "") +
      "</div></div></article>" +
      '<div class="connection-context-grid"><section class="connection-reason"><span class="connection-step-label">THE REASON TO CONNECT</span><h3>' +
      esc(goalLabel) +
      "</h3><p>" +
      (sharedTopics.length
        ? "You share an interest in " + esc(sharedTopics.join(", ")) + "."
        : (person.roles || []).length
          ? "Their profile lists " +
            esc(person.title || person.roles.join(", ")) +
            (company.name ? " at " + esc(company.name) : "") +
            "."
          : "Selected by your current conference priorities.") +
      "</p>" +
      (opportunity.opener
        ? '<div class="connection-opener"><span>Start the conversation</span><p>“' +
          esc(opportunity.opener) +
          "”</p></div>"
        : "") +
      '</section><section class="connection-event"><span class="connection-step-label">A PLACE TO START</span>' +
      (event
        ? '<span class="connection-event-relation">' +
          esc(eventRelation) +
          '</span><h3><button class="event-title-button" data-action="event" data-id="' +
          esc(event.id) +
          '">' +
          esc(event.title) +
          '</button></h3><p class="connection-event-time">' +
          esc(fmtTime(event.start_at, event.timezone)) +
          "</p><p>" +
          esc(
            (event.venue && event.venue.name) ||
              event.room ||
              "Venue to be confirmed",
          ) +
          '</p><button class="secondary" data-action="event" data-id="' +
          esc(event.id) +
          '">View session details</button>'
        : "<h3>No event linked yet</h3><p>Explore their profile or keep this person in mind as you plan your trip.</p>") +
      "</section></div>";
    $("connection-source-notes").innerHTML =
      "<p>" +
      esc(person.name) +
      " · " +
      esc(roleLabel) +
      ". A speaker listing is context for an introduction, not a guaranteed meeting.</p><ul>" +
      connectionSourceHtml(
        opportunity.evidence && opportunity.evidence.length
          ? opportunity.evidence
          : person.evidence,
      ) +
      "</ul>";
  }

  function loadConnectionChoices() {
    var current =
      (lastPeople && lastPeople.items) ||
      (envelopes.people && envelopes.people.items);
    var pending = current
      ? Promise.resolve({ items: current })
      : api("/people?limit=10", null, null);
    return pending
      .then(function (data) {
        connectionCards = (data.items || []).filter(function (card) {
          return card.person;
        });
        var choices = connectionCards
          .filter(function (card) {
            return !card.met;
          })
          .slice(0, 6);
        if (
          selectedConnectionId &&
          !choices.some(function (card) {
            return card.person.id === selectedConnectionId;
          })
        ) {
          var previous = connectionCards.filter(function (card) {
            return card.person.id === selectedConnectionId;
          })[0];
          if (previous) choices = [previous].concat(choices.slice(0, 5));
        }
        $("connection-choices").innerHTML =
          choices.map(connectionChoiceHtml).join("") ||
          '<p class="muted">No connections match your priorities yet. Adjust your priorities to explore another direction.</p>';
        var selected =
          choices.filter(function (card) {
            return card.person.id === selectedConnectionId;
          })[0] || choices[0];
        if (selected) return highlightPath(selected.person.id);
        $("connection-selected").innerHTML = "";
      })
      .then(function () {
        var details = $("connection-map-details");
        if (details && !details._connectionDisclosureInitialized) {
          details._connectionDisclosureInitialized = true;
          details.open = false;
        }
      })
      .catch(function () {
        $("connection-selected").innerHTML =
          '<p class="muted">Suggestions could not load. Try again in a moment.</p>';
      });
  }

  function focusedGraph(nodes, edges) {
    var narrow = window.innerWidth < 620,
      targetLimit = narrow ? 1 : 5;
    var byId = {},
      adjacent = {},
      chosen = {},
      targets = [];
    nodes.forEach(function (n) {
      byId[n.id] = n;
      adjacent[n.id] = [];
    });
    edges.forEach(function (e) {
      adjacent[e.source].push(e.target);
      adjacent[e.target].push(e.source);
    });
    var cards =
      (lastPeople && lastPeople.items) ||
      (envelopes.people && envelopes.people.items) ||
      [];
    cards.forEach(function (c) {
      var id = c.person && c.person.id;
      if (byId[id] && targets.indexOf(id) < 0 && targets.length < targetLimit)
        targets.push(id);
    });
    nodes.forEach(function (n) {
      if (
        n.type === "Person" &&
        targets.length < targetLimit &&
        targets.indexOf(n.id) < 0
      )
        targets.push(n.id);
      if (n.type === "User" || (!narrow && n.type === "Goal"))
        chosen[n.id] = true;
    });
    var queue = nodes
      .filter(function (n) {
        return n.type === "User";
      })
      .map(function (n) {
        return n.id;
      });
    var previous = {};
    queue.forEach(function (id) {
      previous[id] = null;
    });
    for (var index = 0; index < queue.length; index++) {
      adjacent[queue[index]].forEach(function (id) {
        if (!Object.prototype.hasOwnProperty.call(previous, id)) {
          previous[id] = queue[index];
          queue.push(id);
        }
      });
    }
    targets.forEach(function (id) {
      chosen[id] = true;
      var cursor = previous[id];
      while (cursor) {
        chosen[cursor] = true;
        cursor = previous[cursor];
      }
    });
    var contextCount = 0;
    ["Event", "Company", "Topic"].forEach(function (type) {
      targets.forEach(function (id) {
        var added = 0;
        adjacent[id].forEach(function (neighbor) {
          if (
            byId[neighbor].type === type &&
            !chosen[neighbor] &&
            added < 1 &&
            contextCount < (narrow ? 2 : 8) &&
            Object.keys(chosen).length < 40
          ) {
            chosen[neighbor] = true;
            contextCount++;
            added++;
          }
        });
      });
    });
    var focusedNodes = nodes.filter(function (n) {
      return chosen[n.id];
    });
    return {
      nodes: focusedNodes,
      edges: edges.filter(function (e) {
        return chosen[e.source] && chosen[e.target];
      }),
    };
  }

  function graphPositions(nodes) {
    var groups = [[], [], [], []],
      positions = {};
    nodes.forEach(function (n) {
      var group =
        n.type === "User"
          ? 0
          : n.type === "Goal"
            ? 1
            : n.type === "Person"
              ? 2
              : 3;
      groups[group].push(n);
    });
    var narrow = window.innerWidth < 620,
      mobileRow = 0;
    groups.forEach(function (group, column) {
      group.forEach(function (n, row) {
        if (narrow) {
          positions[n.id] = { x: 160, y: 45 + mobileRow++ * 86 };
          return;
        }
        var gap = Math.min(94, 480 / Math.max(1, group.length));
        positions[n.id] = {
          x: [55, 245, 475, 715][column],
          y: 260 + (row - (group.length - 1) / 2) * gap,
        };
      });
    });
    return positions;
  }

  function renderGraph(g) {
    pathRequest++;
    loadConnectionChoices();
    var details = $("connection-map-details");
    if (details && !details._graphToggleBound) {
      details._graphToggleBound = true;
      details.addEventListener("toggle", function () {
        if (details.open && cy) {
          cy.resize();
          cy.fit(undefined, 25);
        }
      });
    }
    $("graph-detail").textContent =
      "Select a person to explore the connection.";
    var nodes = ((g && g.nodes) || []).slice(0, 400),
      keep = {};
    nodes.forEach(function (n) {
      keep[n.id] = true;
    });
    var edges = ((g && g.edges) || []).filter(function (e) {
      return keep[e.source] && keep[e.target];
    });
    var focused = focusedGraph(nodes, edges),
      positions = graphPositions(focused.nodes);
    $("graph-backend").textContent =
      g && g.backend === "falkordb" ? "FalkorDB connected" : "Fallback mode";
    var types = [];
    focused.nodes.forEach(function (n) {
      if (types.indexOf(n.type) < 0) types.push(n.type);
    });
    renderLegend(types);
    var summary = $("graph-focus-summary");
    if (!summary) {
      summary = document.createElement("p");
      summary.id = "graph-focus-summary";
      summary.className = "muted small-text";
      $("graph").parentNode.insertBefore(summary, $("graph"));
    }
    var narrow = window.innerWidth < 620;
    $("graph").style.height = narrow
      ? Math.max(420, focused.nodes.length * 86 + 20) + "px"
      : "";
    if (!$("graph")._focusResizeBound) {
      $("graph")._focusResizeBound = true;
      window.addEventListener("resize", function () {
        if (
          $("graph")._focusNarrow !== window.innerWidth < 620 &&
          envelopes.graph
        )
          renderGraph(envelopes.graph);
      });
    }
    $("graph")._focusNarrow = narrow;
    summary.textContent =
      (narrow
        ? "Focused on your leading suggestion · "
        : "Focused on your priorities and suggested people · ") +
      focused.nodes.length +
      " of " +
      nodes.length +
      " loaded entities. Explore all entities and sources in the text view below.";
    $("graph-fallback").innerHTML =
      "<h3>All loaded entities (" +
      nodes.length +
      ")</h3><ul>" +
      nodes
        .map(function (n) {
          return (
            "<li>" +
            esc(n.type + " · " + n.label) +
            " " +
            sourceBadge(n.source_mode) +
            (n.type === "Person"
              ? ' <button data-action="path" data-id="' +
                esc(n.id) +
                '">Explain connection</button>'
              : "") +
            "</li>"
          );
        })
        .join("") +
      "</ul><details><summary>Evidence for " +
      edges.length +
      " loaded connections</summary><ul>" +
      edges
        .map(function (e) {
          return "<li>" + edgeDetail(e) + "</li>";
        })
        .join("") +
      "</ul></details>";
    if (typeof cytoscape === "undefined") {
      $("graph").innerHTML =
        '<div class="map-fallback"><h3>The visualization could not load.</h3><p>People, paths, and evidence are still available in the text view below.</p></div>';
      return;
    }
    var elements = focused.nodes
      .map(function (n) {
        return {
          group: "nodes",
          position: positions[n.id],
          data: {
            id: n.id,
            label: n.label,
            type: n.type,
            source_mode: n.source_mode,
            color: TYPE_COLORS[n.type] || OTHER_COLOR,
          },
        };
      })
      .concat(
        focused.edges.map(function (e) {
          return { group: "edges", data: e };
        }),
      );
    if (cy) cy.destroy();
    $("graph").setAttribute("data-layout-ready", "false");
    cy = cytoscape({
      container: $("graph"),
      elements: elements,
      minZoom: 0.35,
      maxZoom: 2,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            label: "data(label)",
            color: "#30343c",
            "font-family": "Arial, sans-serif",
            "font-size": 12,
            width: 150,
            height: 48,
            shape: "round-rectangle",
            "border-width": 1,
            "border-color": "#ffffff",
            "text-valign": "center",
            "text-halign": "center",
            "text-max-width": 132,
            "text-wrap": "ellipsis",
          },
        },
        {
          selector: 'node[type = "User"]',
          style: {
            width: 55,
            height: 55,
            shape: "ellipse",
            color: "#ffffff",
            "font-weight": "bold",
            "background-color": "#30343c",
          },
        },
        {
          selector: 'node[type = "Person"]',
          style: {
            "font-size": 13,
            "font-weight": "bold",
            "border-color": "#c8d8ed",
          },
        },
        {
          selector: 'node[type = "Goal"]',
          style: { height: 58, "text-wrap": "wrap", "font-size": 11 },
        },
        {
          selector: 'node[type = "Topic"]',
          style: { height: 34, width: 130, "font-size": 11 },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#c8cbd1",
            "target-arrow-color": "#b7bdc8",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "arrow-scale": 0.7,
            opacity: 0.65,
          },
        },
        { selector: ".dim", style: { opacity: 0.12 } },
        {
          selector: "node.path",
          style: { "border-width": 3, "border-color": "#698bb9", opacity: 1 },
        },
        {
          selector: "edge.path",
          style: {
            width: 3,
            "line-color": "#698bb9",
            "target-arrow-color": "#698bb9",
            opacity: 1,
            label: "data(type)",
            color: "#4e6380",
            "font-size": 10,
            "text-outline-color": "#f8f8f8",
            "text-outline-width": 3,
          },
        },
        {
          selector: "edge.selected-edge",
          style: {
            width: 4,
            "line-color": "#c08c79",
            "target-arrow-color": "#c08c79",
            opacity: 1,
          },
        },
      ],
      layout: {
        name: "preset",
        fit: false,
        stop: function () {
          $("graph").setAttribute("data-layout-ready", "true");
        },
      },
    });
    if ($("graph").clientWidth && $("graph").clientHeight)
      cy.fit(undefined, 25);
    cy.on("tap", "node", function (evt) {
      var d = evt.target.data();
      if (d.type === "Person") highlightPath(d.id);
      else {
        clearHighlight();
        $("graph-detail").innerHTML =
          "<b>" +
          esc(d.type) +
          "</b> · " +
          esc(d.label) +
          " " +
          sourceBadge(d.source_mode);
      }
    });
    cy.on("tap", "edge", function (evt) {
      pathRequest++;
      cy.edges().removeClass("selected-edge");
      evt.target.addClass("selected-edge");
      $("graph-detail").innerHTML = edgeDetail(evt.target.data());
    });
    cy.on("tap", function (evt) {
      if (evt.target === cy) {
        clearHighlight();
        $("graph-detail").textContent =
          "Select a person to explore the connection.";
      }
    });
  }

  function clearHighlight() {
    pathRequest++;
    if (!cy) return;
    cy.elements().removeClass("dim path selected-edge");
  }

  function highlightPath(personId) {
    renderConnectionSelection(personId);
    var request = ++pathRequest;
    $("graph-detail").textContent = "Loading connections and evidence…";
    return api(
      "/graph/path?person=" + encodeURIComponent(personId),
      null,
      "graph_path",
    )
      .then(function (res) {
        if (request !== pathRequest) return;
        renderConnectionSelection(personId);
        var nodes = res.node_ids || [],
          edges = res.edge_ids || [],
          steps = res.path || [];
        $("graph-detail").innerHTML = steps.length
          ? "<b>Why this person?</b>" +
            connectionPathHtml(steps) +
            (res.explanation ? "<p>" + esc(res.explanation) + "</p>" : "") +
            steps
              .filter(function (s) {
                return s.edge;
              })
              .map(function (s) {
                return "<p>" + edgeDetail(s.edge) + "</p>";
              })
              .join("") +
            '<p class="muted small-text">Engine: ' +
            esc(res.backend === "falkordb" ? "FalkorDB" : "fallback mode") +
            "</p>"
          : "<b>No connection path available.</b><p>The sources do not show a connection to this person.</p>";
        if (cy) {
          steps.forEach(function (step) {
            if (step.node && !cy.getElementById(step.node.id).length) {
              var node = step.node;
              cy.add({
                group: "nodes",
                data: {
                  id: node.id,
                  label: node.label || node.id,
                  type: node.type,
                  source_mode: node.source_mode,
                  color: TYPE_COLORS[node.type] || OTHER_COLOR,
                },
              });
            }
          });
          steps.forEach(function (step) {
            if (
              step.edge &&
              !cy.getElementById(step.edge.id).length &&
              cy.getElementById(step.edge.source).length &&
              cy.getElementById(step.edge.target).length
            )
              cy.add({ group: "edges", data: step.edge });
          });
          cy.elements().removeClass("path selected-edge").addClass("dim");
          nodes.forEach(function (id) {
            cy.getElementById(id).removeClass("dim").addClass("path");
          });
          edges.forEach(function (id) {
            cy.getElementById(id).removeClass("dim").addClass("path");
          });
        }
        if (steps.length && cy && nodes.length) {
          cy.elements(".path")
            .layout({
              name: "breadthfirst",
              directed: true,
              spacingFactor: 1.7,
              fit: false,
            })
            .run();
          cy.fit(
            cy.nodes().filter(function (n) {
              return nodes.indexOf(n.id()) >= 0;
            }),
            80,
          );
        }
      })
      .catch(function () {
        if (request === pathRequest)
          $("graph-detail").textContent =
            "The connection path could not load. Select a person to try again.";
      });
  }

  function eventArtwork(event, large) {
    var cover = safeUrl(event.cover_url);
    if (cover)
      return (
        '<div class="event-artwork' +
        (large ? " large-artwork" : "") +
        '"><img src="' +
        esc(cover) +
        '" alt="Artwork for ' +
        esc(event.title) +
        '" loading="lazy" referrerpolicy="no-referrer"></div>'
      );
    var value = String(event.id || event.title || "event"),
      hash = 0;
    for (var index = 0; index < value.length; index++)
      hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
    var tile = hash % 6;
    return (
      '<div class="event-artwork artwork-atmosphere' +
      (large ? " large-artwork" : "") +
      '" aria-hidden="true" style="background-position:' +
      (tile % 3) * 50 +
      "% " +
      Math.floor(tile / 3) * 100 +
      '%"></div>'
    );
  }
  function renderDiscoverEvents(all) {
    var conf = (envelopes.conference && envelopes.conference.conference) || {};
    var user = (envelopes.conference && envelopes.conference.user) || {};
    var items = all
      .filter(function (event) {
        if (!event.cover_url || !event.start_at) return false;
        var day = new Intl.DateTimeFormat("en-CA", {
          timeZone: event.timezone || EVENT_TZ,
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
        }).format(new Date(event.start_at));
        return (
          (!user.depart_date || day >= user.depart_date) &&
          (!user.return_date || day <= user.return_date)
        );
      })
      .sort(function (a, b) {
        return new Date(a.start_at) - new Date(b.start_at);
      })
      .slice(0, 4);
    if (!items.length) items = all.slice(0, 4);
    $("discover-events").innerHTML = items.length
      ? items
          .map(function (event) {
            var date = event.start_at
              ? shortDate(
                  new Intl.DateTimeFormat("en-CA", {
                    timeZone: event.timezone || EVENT_TZ,
                    year: "numeric",
                    month: "2-digit",
                    day: "2-digit",
                  }).format(new Date(event.start_at)),
                )
              : "Date to be confirmed";
            var affiliation =
              {
                official: "Official program",
                confirmed_side_event: "Confirmed side event",
                candidate: "Affiliation unconfirmed",
                unknown: "Affiliation unknown",
                unrelated: "Unrelated to conference",
              }[event.conference_relation] || "Affiliation unknown";
            return (
              '<article class="discovery-event">' +
              '<button type="button" class="event-cover-button" data-action="event" data-id="' +
              esc(event.id) +
              '" aria-label="View ' +
              esc(event.title) +
              '">' +
              eventArtwork(event, false) +
              "</button>" +
              '<div class="discovery-event-info"><div class="event-when">' +
              esc(date) +
              " <span>· " +
              esc(fmtHour(event.start_at, event.timezone)) +
              "</span></div><h3>" +
              '<button type="button" class="event-title-button" data-action="event" data-id="' +
              esc(event.id) +
              '">' +
              esc(event.title) +
              "</button>" +
              '</h3><p><svg class="icon"><use href="#i-pin"/></svg>' +
              esc(orUnknown(event.venue && event.venue.name)) +
              '</p><div class="row">' +
              sourceBadge(event.source_mode) +
              '<span class="badge neutral">' +
              esc(affiliation) +
              "</span></div></div></article>"
            );
          })
          .join("")
      : emptyState(
          "No events to discover yet.",
          "Try loading again or explore your agenda.",
        );
  }

  function renderPeople(p) {
    lastPeople = p;
    var candidates = (p && p.items) || [];
    var all = candidates
      .filter(function (card) {
        return !card.met;
      })
      .slice(0, 10)
      .concat(
        candidates.filter(function (card) {
          return card.met;
        }),
      );
    var needle = fold($("people-search").value);
    var items = all.filter(function (card) {
      return (
        !needle ||
        fold(
          ((card.person || {}).name || "") +
            " " +
            ((card.person || {}).title || "") +
            " " +
            ((card.company || {}).name || ""),
        ).includes(needle)
      );
    });
    $("stat-people").textContent = all.length;
    $("people-result-count").textContent =
      items.length + (items.length === 1 ? " person" : " people");
    $("people-cards").innerHTML = items.length
      ? items
          .map(function (card) {
            var person = card.person || {},
              opportunity = card.opportunity || {},
              company = card.company || {};
            var id = person.id || (opportunity.person_ids || [])[0] || "";
            var event = ((lastEvents && lastEvents.items) || []).find(
              function (entry) {
                return entry.id === opportunity.event_id;
              },
            );
            var evidence = opportunity.evidence || person.evidence || [];
            var sources = evidence
              .map(function (entry) {
                var link = safeUrl(entry.source_url);
                return (
                  "<li>" +
                  (link
                    ? '<a href="' +
                      esc(link) +
                      '" target="_blank" rel="noopener noreferrer">' +
                      esc(entry.provider) +
                      "</a>"
                    : esc(entry.provider)) +
                  " " +
                  sourceModeBadge(entry.source_mode) +
                  "</li>"
                );
              })
              .join("");
            return (
              '<article class="people-card' +
              (card.met ? " is-met" : "") +
              '"><div class="people-card-top">' +
              personAvatar(person) +
              '<span class="people-match">' +
              esc(candidatePriority(card)) +
              '</span></div><h2 class="people-name">' +
              esc(person.name || opportunity.title) +
              '</h2><p class="people-position">' +
              esc(person.title || "") +
              '</p><p class="people-company">' +
              esc(company.name || "") +
              '</p><div class="people-session"><span class="people-session-label">' +
              (card.met ? "Conversation saved" : "Find them at") +
              "</span>" +
              (event
                ? '<button class="people-session-title" data-action="event" data-id="' +
                  esc(event.id) +
                  '">' +
                  esc(event.title) +
                  '</button><span class="people-session-date">' +
                  esc(fmtTime(event.start_at, event.timezone)) +
                  "</span>"
                : '<p class="people-session-date">' +
                  esc(opportunity.where || "Location to be confirmed") +
                  "</p>") +
              '</div><details class="people-context"><summary>Why this match</summary><p>' +
              esc(
                friendlyRationale(
                  opportunity.rationale || "Based on your priorities.",
                ),
              ) +
              "</p><p>" +
              esc(opportunity.opener || "") +
              "</p>" +
              (card.met_note
                ? "<p><b>Your note</b><br>" + esc(card.met_note) + "</p>"
                : "") +
              '<p class="people-presence">' +
              presenceBadge(person, opportunity) +
              "</p>" +
              linkedinField(card.linkedin) +
              "<ul>" +
              sources +
              "</ul></details>" +
              (card.met
                ? '<div class="followup" id="followup-' + esc(id) + '"></div>'
                : "") +
              '<div class="people-actions">' +
              (card.met
                ? '<button class="primary" data-action="followup" data-id="' +
                  esc(id) +
                  '">Draft a follow-up</button>'
                : '<button class="primary" data-action="showpath" data-id="' +
                  esc(id) +
                  '">View connection</button>') +
              (card.met
                ? '<span class="people-met-status">Meeting saved</span>'
                : '<button class="people-met" data-action="met" data-id="' +
                  esc(id) +
                  '" data-name="' +
                  esc(person.name || opportunity.title) +
                  '">We met</button>') +
              "</div></article>"
            );
          })
          .join("")
      : emptyState(
          "No people match your search.",
          "Try another name or company.",
          "clear-people",
          "Clear search",
        );
  }

  function modeOfEvidence(ev) {
    var modes = {};
    (ev || []).forEach(function (e) {
      if (e && e.source_mode) modes[e.source_mode] = true;
    });
    var l = Object.keys(modes);
    return l.length === 1 ? l[0] : l.length === 0 ? "unknown" : "mixed";
  }

  function renderDiff(res) {
    var d = res.diff || {};
    function section(name, cls, list, fmt) {
      return (
        '<div class="diff-section ' +
        cls +
        '"><span class="tag">' +
        esc(name) +
        " (" +
        (list || []).length +
        "):</span>" +
        ((list || []).length
          ? "<ul>" + list.map(fmt).join("") + "</ul>"
          : '<span class="muted">none</span>') +
        "</div>"
      );
    }
    $("diff-body").innerHTML =
      "<p><b>" +
      esc(res.scenario && res.scenario.label) +
      "</b></p>" +
      section("Added", "diff-added", d.added, function (x) {
        return "<li>" + esc(x.title || x.event_id) + "</li>";
      }) +
      section("Removed", "diff-removed", d.removed, function (x) {
        return "<li>" + esc(x.title || x.event_id) + "</li>";
      }) +
      section("Updated", "diff-changed", d.changed, function (x) {
        var b = x.before || {},
          a = x.after || {};
        return (
          "<li>" +
          esc(x.event_id) +
          ": " +
          esc(fmtTime(b.start_at)) +
          " (" +
          esc(b.status) +
          ") to " +
          esc(fmtTime(a.start_at)) +
          " (" +
          esc(a.status) +
          ")</li>"
        );
      }) +
      section("Replanning", "diff-replan", res.replan, function (x) {
        var r = x.replacement,
          p = x.graph_path;
        return (
          "<li><b>Removed:</b> " +
          esc(x.removed.title) +
          (r
            ? "<br><b>Replaced by:</b> " +
              esc(r.title) +
              " (" +
              esc(fmtTime(r.start_at)) +
              ")"
            : "") +
          "<br><b>Reason:</b> " +
          esc(x.reason) +
          (p
            ? "<br><b>Path:</b> " +
              esc(p.nodes.join(" > ")) +
              (p.explanation
                ? '<br><span class="muted">' + esc(p.explanation) + "</span>"
                : "")
            : "") +
          "</li>"
        );
      }) +
      '<p class="muted small-text">Simulated change, not an update from the source.</p>';
    $("diff-panel").classList.remove("hidden");
  }

  // Loading

  function settle(promise, label, render, errors) {
    return promise
      .then(function (data) {
        try {
          render(data);
        } catch (e) {
          errors.push(label + ": rendering " + e.message);
        }
      })
      .catch(function (e) {
        errors.push(label + ": " + e.message);
      });
  }

  $("travel-research-form").addEventListener("input", function () {
    this.dataset.changed = "true";
    updateResearchLinks();
  });
  ["research-flights-link", "research-stays-link"].forEach(function (id) {
    $(id).onclick = function (event) {
      if (!$("travel-research-form").reportValidity()) event.preventDefault();
    };
  });
  $("flight-sort").onchange = function () {
    renderFlights(envelopes.flights);
  };
  $("stay-sort").onchange = function () {
    renderStays(envelopes.stays);
  };
  function refreshAll() {
    clearError();
    var errors = [];
    $("main").setAttribute("aria-busy", "true");
    return Promise.all([
      settle(
        api("/conference", null, "conference"),
        "conference",
        renderConference,
        errors,
      ),
      settle(
        api("/plan", null, "plan"),
        "agenda",
        function (p) {
          renderGoals(p);
          renderNextActions(p);
          renderPlan(p);
        },
        errors,
      ),
      settle(api("/roi", null, "roi"), "summary", renderRoi, errors),
      settle(api("/events", null, "events"), "events", renderEvents, errors),
      settle(api("/travel", null, "travel"), "travel", renderTravel, errors),
      settle(api("/stays", null, "stays"), "stays", renderStays, errors),
      settle(
        api("/flights", null, "flights"),
        "flights",
        renderFlights,
        errors,
      ),
      settle(api("/travel/map", null, "map"), "map", renderMap, errors),
      settle(api("/graph", null, "graph"), "connections", renderGraph, errors),
      settle(
        api("/people?limit=100", null, "people"),
        "people",
        renderPeople,
        errors,
      ),
      settle(
        api("/scenarios", null, "scenarios"),
        "simulations",
        renderScenarios,
        errors,
      ),
      settle(
        api("/sources", null, "sources"),
        "sources",
        renderSources,
        errors,
      ),
      settle(
        api("/brightdata", null, null),
        "collection",
        renderBrightData,
        errors,
      ),
      settle(
        api("/pipeline", null, null),
        "data pipeline",
        renderPipeline,
        errors,
      ),
    ])
      .then(function () {
        if (envelopes.plan) renderPlan(envelopes.plan);
        if (envelopes.people) renderPeople(envelopes.people);
        if (lastMapData) renderMap(lastMapData);
        if (selectedConnectionId)
          renderConnectionSelection(selectedConnectionId);
        return settle(
          api("/antifomo", null, "antifomo"),
          "trade-offs",
          renderStoryAntifomo,
          errors,
        );
      })
      .then(loadStory)
      .then(loadAgentsState)
      .then(function () {
        $("main").setAttribute("aria-busy", "false");
        if (errors.length)
          showError("Some sections could not refresh: " + errors.join(" · "));
      })
      .catch(function (e) {
        $("main").setAttribute("aria-busy", "false");
        showError(e.message);
      });
  }

  function renderScenarios(s) {
    var sel = $("scenario-select");
    var current = sel.value;
    var items = (s && s.items) || [];
    sel.innerHTML = items
      .map(function (it) {
        return (
          '<option value="' + esc(it.id) + '">' + esc(it.label) + "</option>"
        );
      })
      .join("");
    if (
      current &&
      items.some(function (it) {
        return it.id === current;
      })
    )
      sel.value = current;
    else if (s && s.active) sel.value = s.active;
  }

  function withBusy(button, fn) {
    if (mutationBusy) return Promise.resolve();
    mutationBusy = true;
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    clearError();
    return Promise.resolve()
      .then(fn)
      .catch(function (e) {
        if ($("goal-dialog").open) {
          $("goal-error").textContent = e.message;
          $("goal-text").setAttribute("aria-invalid", "true");
        } else {
          var activeDialog = document.querySelector("dialog[open]");
          if (activeDialog) {
            var error = activeDialog.querySelector(".dialog-error");
            if (!error) {
              error = document.createElement("p");
              error.className = "form-error dialog-error";
              error.setAttribute("role", "alert");
              activeDialog.appendChild(error);
            }
            error.textContent =
              e.message || "We could not confirm your action.";
            error.scrollIntoView({ block: "nearest" });
          } else showError(e.message || "We could not confirm your action.");
        }
      })
      .then(function () {
        mutationBusy = false;
        if (button) {
          button.disabled = false;
          button.removeAttribute("aria-busy");
        }
      });
  }

  function mutate(path, body, key) {
    return api(path, { method: "POST", body: body }, key || "plan").then(
      function (res) {
        return refreshAll().then(function () {
          return res;
        });
      },
    );
  }

  // Overview: goal -> opportunities -> plan -> trade-offs -> change -> meeting

  var storyMap = null;
  var storyMapLayer = null;
  var storyTop = null;

  function pathHtml(steps) {
    var nodes = (steps || [])
      .filter(function (s) {
        return s.node;
      })
      .map(function (s) {
        return (
          '<span class="path-node t-' +
          esc(s.node.type || "Node") +
          '">' +
          esc(s.node.label || s.node.id) +
          "</span>"
        );
      });
    return (
      '<div class="path">' +
      nodes.join('<span class="path-arrow">&rarr;</span>') +
      "</div>"
    );
  }

  function fmtMs(ms) {
    if (ms === null || ms === undefined) return "Never";
    return fmtTime(new Date(Number(ms)).toISOString(), EVENT_TZ);
  }

  function renderAgentsState(res) {
    var box = $("agents-state");
    if (!box) return;
    if (!res || res.backend !== "falkordb") {
      $("agents-plan-version").textContent = "?";
      box.innerHTML =
        '<p class="muted">FalkorDB is unavailable. Shared agent state could not load.</p>';
      return;
    }
    var plan = res.plan || {};
    $("agents-plan-version").textContent = "v" + (plan.plan_version || 0);
    var rows = (res.agents || [])
      .map(function (a) {
        return (
          "<tr><td><b>" +
          esc(a.agent) +
          "</b></td><td>" +
          esc(a.writes) +
          "</td><td>" +
          esc(fmtMs(a.last_at_ms)) +
          "</td></tr>"
        );
      })
      .join("");
    var open =
      res.browser_url && safeUrl(res.browser_url)
        ? '<a class="btn primary" target="_blank" rel="noopener" href="' +
          esc(safeUrl(res.browser_url)) +
          '">Show in FalkorDB Browser</a> '
        : "";
    box.innerHTML =
      "<table><thead><tr><th>Agent</th><th>Writes</th><th>Last update</th></tr></thead><tbody>" +
      rows +
      "</tbody></table>" +
      '<p class="small-text">' +
      esc((plan.items || []).length) +
      " events in the plan (PLANS), " +
      esc((res.skips || []).length) +
      " skipped (SKIPS), " +
      esc((res.changes || []).length) +
      " changes (Change).</p>" +
      '<div class="cypher-panel">' +
      open +
      '<button data-action="copy-agents-cypher" class="small">Copy query</button>' +
      '<pre id="agents-cypher" class="cypher">' +
      esc(res.cypher) +
      "</pre></div>";
  }

  function loadAgentsState() {
    return api("/agents/state", null, "agents")
      .then(renderAgentsState)
      .catch(function () {
        renderAgentsState(null);
      });
  }

  function renderStoryGoal(plan) {
    $("story-goal").textContent =
      displayGoalText(plan && plan.goal_text) ||
      "Set what you would like to accomplish at this conference.";
    var translations = {
      "Meet seed investors": "Seed investors",
      "Meet AI agent founders": "AI agent founders",
      "Meet Copilot product managers": "Copilot product managers",
      "Meet engineers": "Engineers",
    };
    $("story-goals").innerHTML = ((plan && plan.goals) || [])
      .map(function (g) {
        return (
          '<span class="chip">' +
          esc(translations[g.description] || g.description || g.id) +
          (typeof g.priority === "number"
            ? " · " + Math.round(g.priority * 100) + " %"
            : "") +
          "</span>"
        );
      })
      .join("");
  }

  function renderStoryOpps(people) {
    var cards = ((people && people.items) || [])
      .filter(function (card) {
        return card.person;
      })
      .slice(0, 3);
    storyTop = cards.length ? cards[0].person : null;
    $("story-opps").innerHTML = cards.length
      ? cards
          .map(function (card) {
            return (
              '<article class="person-preview">' +
              personAvatar(card.person) +
              '<div class="person-name">' +
              esc(card.person.name) +
              '</div><div class="person-role">' +
              esc(
                (card.company && card.company.name) || card.person.title || "",
              ) +
              '</div><button class="text-button" data-action="showpath" data-id="' +
              esc(card.person.id) +
              '">View connection</button></article>'
            );
          })
          .join("")
      : emptyState(
          "Who would you like to meet?",
          "Set your priorities to find relevant people.",
          "edit-goal",
          "Set priorities",
        );
    return Promise.resolve();
  }

  function renderStoryPlan(plan, mapData) {
    var days = ((plan && plan.plan && plan.plan.days) || []).filter(
      function (d) {
        return (d.items || []).length;
      },
    );
    if (
      !days.some(function (d) {
        return d.day === selectedStoryDay;
      })
    ) {
      var confStart =
        envelopes.conference &&
        envelopes.conference.conference &&
        envelopes.conference.conference.start_date;
      selectedStoryDay = days.some(function (d) {
        return d.day === confStart;
      })
        ? confStart
        : days[0] && days[0].day;
    }
    renderDayTabs("story-day-tabs", days, selectedStoryDay, "story-day", false);
    var chosen = days.filter(function (d) {
      return d.day === selectedStoryDay;
    })[0];
    var items = (chosen && chosen.items) || [];
    $("story-plan").innerHTML = items.length
      ? items
          .slice(0, 4)
          .map(function (i) {
            return (
              '<div class="agenda-entry"><time class="agenda-time" datetime="' +
              esc(i.start_at) +
              '">' +
              esc(fmtHour(i.start_at, i.timezone)) +
              '</time><div class="agenda-item"><h3>' +
              esc(i.title) +
              "</h3><p>" +
              esc(orUnknown(i.venue)) +
              "</p></div></div>"
            );
          })
          .join("") +
        (items.length > 4
          ? '<a class="text-button" href="#events" data-nav="events">View all ' +
            items.length +
            " events for the day</a>"
          : "")
      : '<p class="muted">No events planned for this day.</p>';
    var markers = ((mapData && mapData.markers) || []).filter(function (m) {
      return (
        m.kind === "conference" ||
        items.some(function (i) {
          return i.event_id === m.id;
        })
      );
    });
    if (typeof L === "undefined") {
      $("story-map").innerHTML =
        '<div class="map-fallback"><b>Places in your plan</b><p>The map could not load.</p>' +
        placesHtml(markers) +
        "</div>";
      return;
    }
    if (!storyMap) {
      storyMap = L.map($("story-map"), { scrollWheelZoom: false }).setView(
        [37.79, -122.42],
        13,
      );
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors",
      }).addTo(storyMap);
    }
    if (storyMapLayer) storyMapLayer.remove();
    storyMapLayer = L.layerGroup().addTo(storyMap);
    var bounds = [];
    markers.forEach(function (m) {
      if (typeof m.lat !== "number" || typeof m.lng !== "number") return;
      bounds.push([m.lat, m.lng]);
      L.circleMarker([m.lat, m.lng], {
        radius: m.kind === "conference" ? 10 : 7,
        color: "#ffffff",
        weight: 2,
        fillColor: m.kind === "conference" ? "#385535" : "#8ca56b",
        fillOpacity: 1,
      })
        .bindTooltip(esc(m.label), { direction: "top" })
        .addTo(storyMapLayer);
    });
    setTimeout(function () {
      storyMap.invalidateSize();
      if (bounds.length)
        storyMap.fitBounds(bounds, { padding: [35, 35], maxZoom: 14 });
    }, 50);
  }

  function renderStoryAntifomo(res) {
    var skips = (res && res.skips) || [];
    if ($("alternatives-count"))
      $("alternatives-count").textContent = skips.length;
    $("story-antifomo").innerHTML = skips.length
      ? skips
          .map(function (entry) {
            return (
              '<div class="quiet-alternative"><div><strong>' +
              esc(entry.title) +
              "</strong><span>" +
              esc(fmtTime(entry.start_at, entry.timezone)) +
              "</span></div><details><summary>Why it’s not in your agenda</summary><p>" +
              esc(entry.reason || entry.gain || "") +
              "</p></details></div>"
            );
          })
          .join("")
      : '<p class="muted">No alternatives right now.</p>';
  }

  function renderStoryDiff(res) {
    var replan = (res && res.replan) || [];
    var d = (res && res.diff) || {};
    var rows = replan.map(function (r) {
      var html =
        '<div class="diff-row removed"><span class="tag-r">REMOVED</span> ' +
        esc(r.removed.title) +
        "</div>";
      if (r.replacement) {
        html +=
          '<div class="diff-row added"><span class="tag-a">ADDED</span> ' +
          esc(r.replacement.title) +
          ' <span class="muted">(' +
          esc(fmtTime(r.replacement.start_at)) +
          ")</span></div>";
      }
      html += '<div class="explain"><b>Reason:</b> ' + esc(r.reason) + "</div>";
      if (r.graph_path) {
        html += pathHtml(
          r.graph_path.nodes.map(function (n, i) {
            return {
              node: {
                label: n,
                type:
                  i === r.graph_path.nodes.length - 1
                    ? "Person"
                    : i === 0
                      ? "Goal"
                      : "Opportunity",
              },
            };
          }),
        );
      }
      return html;
    });
    var added = (d.added || []).filter(function (a) {
      return !replan.some(function (r) {
        return r.replacement && r.replacement.event_id === a.event_id;
      });
    });
    rows = rows.concat(
      added.map(function (a) {
        return (
          '<div class="diff-row added"><span class="tag-a">ADDED</span> ' +
          esc(a.title) +
          "</div>"
        );
      }),
    );
    $("story-diff").innerHTML =
      "<p><b>" +
      esc(res.scenario && res.scenario.label) +
      "</b></p>" +
      rows.join("") +
      '<p class="muted small-text">Simulated change, not an update from the source.</p>';
  }

  function storyMetButton() {
    if (!storyTop) {
      $("story-met").innerHTML =
        '<p class="muted">Explore your suggestions to record a meeting.</p>';
      return;
    }
    $("story-met").innerHTML =
      '<button data-action="met" data-id="' +
      esc(storyTop.id) +
      '" data-name="' +
      esc(storyTop.name) +
      '" class="secondary">I met ' +
      esc(storyTop.name) +
      "</button>";
  }

  // "X/Y" of items whose source.provider is brightdata; null when the list was not loaded.
  function bdShare(res) {
    if (!res || !Array.isArray(res.items)) return null;
    var n = res.items.filter(function (it) {
      return it && it.source && it.source.provider === "brightdata";
    }).length;
    return n + "/" + res.items.length;
  }

  function renderBrightData(res, stays, flights) {
    if (stays === undefined && flights === undefined) {
      // Null keys: these reads must not feed the global source badge.
      Promise.all([
        api("/stays", null, null).catch(function () {
          return null;
        }),
        api("/flights", null, null).catch(function () {
          return null;
        }),
      ]).then(function (r) {
        renderBrightData(res, r[0], r[1]);
      });
    }
    var u = (res && res.usage) || {},
      ready = (res && res.ready) || {};
    var sShare = bdShare(stays),
      fShare = bdShare(flights);
    var travel =
      sShare !== null || fShare !== null
        ? '<div class="bd-travel">' +
          (sShare !== null ? "Stays via Bright Data: " + esc(sShare) : "") +
          (sShare !== null && fShare !== null ? " · " : "") +
          (fShare !== null ? "Flights via Bright Data: " + esc(fShare) : "") +
          "</div>"
        : "";
    function part(api, label) {
      return (
        esc(label) +
        " " +
        esc(u[api] || 0) +
        (ready[api] ? "" : ' <span class="muted">(not configured)</span>')
      );
    }
    $("bd-counter").innerHTML =
      "<b>Records collected through Bright Data: " +
      esc(u.total || 0) +
      "</b>" +
      ' <span class="bd-detail">' +
      part("datasets", "datasets") +
      " | " +
      part("web_unlocker", "Web Unlocker") +
      " | " +
      part("serp", "SERP API") +
      "</span>" +
      travel;
  }

  function renderPipeline(res) {
    $("pipeline-headline").textContent = (res && res.headline) || "";
    var rows = (res && res.rows) || [];
    $("pipeline-table").innerHTML = rows.length
      ? '<table class="pipeline-table"><thead><tr>' +
        "<th>Source</th><th>Provider</th><th>Mode</th><th>Bright Data API</th><th>Records</th>" +
        "<th>Collected</th><th>Run report</th><th>Est. cost</th></tr></thead><tbody>" +
        rows
          .map(function (r) {
            var outcome =
              r.status === "failed"
                ? "failed: " + (r.reason || r.termination)
                : (r.termination || r.status) +
                  (r.reason ? " (" + r.reason + ")" : "");
            return (
              '<tr class="kind-' +
              esc(r.kind) +
              '"><td>' +
              esc(r.source) +
              "</td><td>" +
              esc(r.provider) +
              "</td><td>" +
              esc(r.kind) +
              "</td><td>" +
              esc(r.brightdata_api || "—") +
              "</td><td>" +
              esc(r.records === null ? "—" : r.records) +
              "</td><td>" +
              esc(r.collected_at ? fmtTime(r.collected_at) : "—") +
              "</td><td>" +
              esc(outcome) +
              "</td><td>" +
              esc(
                r.estimated_cost_usd !== null
                  ? "$" + r.estimated_cost_usd + " (estimate)"
                  : "—",
              ) +
              "</td></tr>"
            );
          })
          .join("") +
        "</tbody></table>"
      : '<p class="muted">' +
        esc((res && res.note) || "No collection run in this session.") +
        "</p>";
    var t = (res && res.totals) || {},
      calls = (res && res.brightdata_calls) || [];
    $("pipeline-calls").innerHTML =
      "Bright Data records: " +
      esc(t.brightdata_records || 0) +
      ", estimated cost $" +
      esc(t.estimated_cost_usd || "0") +
      " (estimate: records × 1.5 / 1000). Bright Data calls: " +
      (calls.length
        ? calls
            .map(function (c) {
              return (
                esc(c.api) +
                (c.dataset_id ? " " + esc(c.dataset_id) : "") +
                (c.snapshot_id ? " snapshot " + esc(c.snapshot_id) : "") +
                " (" +
                esc(c.rows) +
                " rows)"
              );
            })
            .join("; ")
        : "none");
    renderReachability(res && res.reachability);
  }

  function renderReachability(r) {
    var box = $("pipeline-reach");
    if (!box) return;
    if (!r) {
      box.innerHTML =
        '<h3>Reachability: plain fetch vs Bright Data</h3><p class="muted">Block matrix not run yet (scripts/probes/block_matrix.py).</p>';
      return;
    }
    var c = r.counts || {};
    var cell = function (v) {
      return '<span class="reach-' + esc(v) + '">' + esc(v) + "</span>";
    };
    box.innerHTML =
      "<h3>Reachability: plain fetch vs Bright Data</h3><p><b>" +
      esc(c.reachable_without_brightdata) +
      " of " +
      esc(c.n) +
      " sites reachable without Bright Data, " +
      esc(c.reachable_with_brightdata) +
      " of " +
      esc(c.n) +
      " with</b> (Web Unlocker or dataset; Web Unlocker alone " +
      esc(c.reachable_with_unlocker_only) +
      " of " +
      esc(c.n) +
      ') <span class="muted">(run ' +
      esc(fmtTime(r.run_at)) +
      ", Web Unlocker zone " +
      esc(r.zone) +
      ")</span></p>" +
      (c.kyc_pending && c.kyc_pending.length
        ? "<p><b>KYC pending:</b> " +
          esc(c.kyc_pending.join(", ")) +
          ' <span class="muted">(refused by Web Unlocker until KYC is approved; then ' +
          esc(c.reachable_with_brightdata_if_kyc_approved) +
          " of " +
          esc(c.n) +
          " with Bright Data, projection)</span></p>"
        : "") +
      '<table class="pipeline-table"><thead><tr><th>Site</th><th>Plain fetch</th><th>Plain fetch, browser UA</th>' +
      "<th>Web Unlocker</th><th>Bright Data dataset</th></tr></thead><tbody>" +
      (r.sites || [])
        .map(function (s) {
          return (
            "<tr><td>" +
            esc(s.site) +
            "</td><td>" +
            cell(s.plain_default_ua) +
            "</td><td>" +
            cell(s.plain_browser_ua) +
            '</td><td title="' +
            esc(s.detail) +
            '">' +
            cell(s.brightdata_unlocker) +
            '</td><td title="' +
            esc(s.dataset_detail || "") +
            '">' +
            (s.brightdata_dataset === "not_run"
              ? '<span class="muted">—</span>'
              : cell(s.brightdata_dataset)) +
            "</td></tr>"
          );
        })
        .join("") +
      "</tbody></table>";
  }

  function loadStory() {
    renderStoryGoal(envelopes.plan);
    renderStoryPlan(envelopes.plan, envelopes.map);
    renderStoryOpps(envelopes.people);
    storyMetButton();
    return Promise.resolve();
  }

  function storySimulate() {
    return api("/scenarios", null, "scenarios")
      .then(function (s) {
        var items = s.items || [];
        var pick =
          items.filter(function (it) {
            return /sold/i.test(it.id);
          })[0] || items[0];
        if (!pick) throw new Error("No simulation scenarios available.");
        return mutate("/simulate-change", { scenario_id: pick.id });
      })
      .then(function (res) {
        renderStoryDiff(res);
        renderDiff(res);
        toast(
          "Simulation applied. Your agenda and suggestions are up to date.",
        );
      });
  }

  // Wiring

  function initTabs() {
    document.addEventListener("click", function (e) {
      var link = e.target.closest("[data-tab], [data-nav]");
      if (!link) return;
      e.preventDefault();
      switchTab(link.getAttribute("data-tab") || link.getAttribute("data-nav"));
    });
    window.addEventListener("hashchange", function () {
      switchTab(location.hash.slice(1), false);
    });
  }

  function switchTab(name, updateHash) {
    if (!$("tab-" + name)) name = "story";
    var labels = {
      story: "Overview",
      events: "My agenda",
      people: "People",
      travel: "Travel",
      graph: "Connections",
      dashboard: "My summary",
    };
    document.querySelectorAll("[data-tab]").forEach(function (link) {
      var active = link.getAttribute("data-tab") === name;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.querySelectorAll(".tab-panel").forEach(function (panel) {
      var active = panel.id === "tab-" + name;
      panel.classList.toggle("active", active);
      panel.hidden = !active;
    });
    $("page-label").textContent = labels[name];
    document.title = labels[name] + " · Conferge";
    if (updateHash !== false) history.pushState(null, "", "#" + name);
    window.scrollTo(0, 0);
    if (name === "story" && storyMap)
      setTimeout(function () {
        storyMap.invalidateSize();
      }, 50);
    if (name === "travel" && map)
      setTimeout(function () {
        map.invalidateSize();
        if (lastMapData) renderMap(lastMapData);
      }, 50);
    if (name === "graph" && cy)
      setTimeout(function () {
        cy.resize();
        cy.fit(undefined, 25);
      }, 50);
    $("main").focus({ preventScroll: true });
  }

  function onClick(e) {
    var opener = e.target.closest("[data-open]");
    if (opener) {
      openDialog(opener.getAttribute("data-open"));
      return;
    }
    var closer = e.target.closest("[data-close]");
    if (closer) {
      $(closer.getAttribute("data-close")).close();
      return;
    }
    var btn = e.target.closest("button[data-action]");
    if (!btn) return;
    var action = btn.getAttribute("data-action"),
      id = btn.getAttribute("data-id");
    if (action === "attended" || action === "skipped")
      withBusy(btn, function () {
        return mutate("/" + action, { event_id: id }).then(function () {
          toast(
            action === "attended"
              ? "Attendance recorded."
              : "Event skipped. Your agenda is up to date.",
          );
        });
      });
    else if (action === "accept")
      withBusy(btn, function () {
        return mutate("/proposal/accept", { proposal_id: id }, "travel").then(
          function () {
            toast("Suggestion saved. No booking has been made.");
          },
        );
      });
    else if (action === "met") {
      pendingMeeting = {
        id: id,
        name: btn.getAttribute("data-name") || "this person",
      };
      $("meeting-person").textContent = pendingMeeting.name;
      $("meeting-note").value = "";
      openDialog("meeting-dialog");
    } else if (action === "followup") {
      withBusy(btn, function () {
        return api(
          "/followup?person=" + encodeURIComponent(id),
          null,
          "people",
        ).then(function (draft) {
          var box = $("followup-" + id),
            next = draft.next_action || {},
            link = safeUrl(next.url);
          if (!box) return;
          box.innerHTML =
            '<p class="small-text muted">Your draft · review before sending</p><pre class="followup-text">' +
            esc(draft.message) +
            '</pre><p class="small-text">' +
            esc(next.label || "") +
            (link
              ? ' <a href="' +
                esc(link) +
                '" target="_blank" rel="noopener noreferrer">Open profile</a>'
              : "") +
            (next.due_at
              ? " · " + esc(shortDate(String(next.due_at).slice(0, 10)))
              : "") +
            '</p><button class="secondary" data-action="copy-followup" data-id="' +
            esc(id) +
            '">Copy draft</button>';
        });
      });
    } else if (action === "copy-followup") {
      var box = $("followup-" + id),
        text = box && box.querySelector(".followup-text");
      if (text && navigator.clipboard)
        navigator.clipboard
          .writeText(text.textContent)
          .then(function () {
            toast("Draft copied.");
          })
          .catch(function () {
            toast("Copying is not available in this browser.");
          });
    } else if (action === "showpath" || action === "path") {
      if (action === "showpath") switchTab("graph");
      highlightPath(id);
    } else if (action === "clear-events") {
      $("events-search").value = "";
      $("events-type").value = "all";
      renderEvents(lastEvents);
      $("events-search").focus();
    } else if (action === "clear-people") {
      $("people-search").value = "";
      renderPeople(lastPeople);
      $("people-search").focus();
    } else if (action === "edit-goal") openDialog("goal-dialog");
    else if (action === "story-day") {
      selectedStoryDay = id;
      renderStoryPlan(envelopes.plan, envelopes.map);
    } else if (action === "agenda-day") {
      selectedAgendaDay = id;
      renderPlan(envelopes.plan);
    } else if (action === "copy-cypher" || action === "copy-agents-cypher") {
      var el = $(action === "copy-cypher" ? "story-cypher" : "agents-cypher");
      if (el && navigator.clipboard)
        navigator.clipboard
          .writeText(el.textContent)
          .then(function () {
            toast("Query copied.");
          })
          .catch(function () {
            toast("Copying is not available in this browser.");
          });
    }
  }

  function init() {
    initTabs();
    document.addEventListener("click", onClick);
    $("events-search").addEventListener("input", function () {
      renderEvents(lastEvents);
    });
    $("events-type").addEventListener("change", function () {
      renderEvents(lastEvents);
    });
    $("people-search").addEventListener("input", function () {
      renderPeople(lastPeople);
    });
    $("goal-form").addEventListener("submit", function (e) {
      e.preventDefault();
      var text = $("goal-text").value.trim();
      $("goal-error").textContent = "";
      $("goal-text").removeAttribute("aria-invalid");
      if (!text) {
        $("goal-error").textContent =
          "Describe at least one type of person you would like to meet.";
        $("goal-text").setAttribute("aria-invalid", "true");
        return;
      }
      withBusy($("btn-goal"), function () {
        return mutate("/goal", { text: text }).then(function () {
          $("goal-dialog").close();
          toast(
            "Goal updated. Your agenda and suggested people have been recalculated.",
          );
        });
      });
    });
    $("meeting-form").addEventListener("submit", function (e) {
      e.preventDefault();
      if (!pendingMeeting) return;
      var person = pendingMeeting;
      withBusy($("btn-met-save"), function () {
        return mutate("/met", {
          person_id: person.id,
          note: $("meeting-note").value.trim() || null,
        }).then(function () {
          $("meeting-dialog").close();
          toast(
            "Meeting with " + person.name + " recorded. Suggestions updated.",
          );
          pendingMeeting = null;
        });
      });
    });
    $("btn-simulate").addEventListener("click", function () {
      var id = $("scenario-select").value;
      if (!id) {
        toast("No scenarios available.");
        return;
      }
      withBusy($("btn-simulate"), function () {
        return mutate("/simulate-change", { scenario_id: id }).then(
          function (res) {
            $("simulation-dialog").close();
            renderDiff(res);
            renderStoryDiff(res);
            window.scrollTo(0, 0);
            toast("Simulation applied. All views are up to date.");
          },
        );
      });
    });
    $("story-simulate").addEventListener("click", function () {
      withBusy($("story-simulate"), storySimulate);
    });
    $("btn-reset").addEventListener("click", function () {
      withBusy($("btn-reset"), function () {
        return mutate("/reset", {}).then(function () {
          document.querySelectorAll("dialog[open]").forEach(function (d) {
            d.close();
          });
          $("diff-panel").classList.add("hidden");
          $("story-diff").innerHTML = "";
          if (envelopes.plan)
            $("goal-text").value = displayGoalText(envelopes.plan.goal_text);
          toast("The scenario has been reset.");
        });
      });
    });
    $("btn-close-diff").addEventListener("click", function () {
      $("diff-panel").classList.add("hidden");
    });
    api("/conference", null, "conference")
      .then(renderConference)
      .then(refreshAll)
      .then(function () {
        switchTab(location.hash.slice(1) || "story", false);
      })
      .catch(function (e) {
        showError(e.message);
      });
    document.querySelectorAll("dialog").forEach(function (dialog) {
      dialog.addEventListener("click", function (e) {
        if (e.target !== dialog) return;
        var r = dialog.getBoundingClientRect();
        if (
          e.clientX < r.left ||
          e.clientX > r.right ||
          e.clientY < r.top ||
          e.clientY > r.bottom
        )
          dialog.close();
      });
    });
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
