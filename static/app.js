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
  var cy = null;

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
  // Score parts in short words, non-zero only: "goal fit 12 · presence 40 · corroboration 4".
  var BREAKDOWN_LABELS = [
    ["goal_fit", "goal fit"], ["presence", "presence"], ["identity", "identity"],
    ["corroboration", "corroboration"], ["graph", "graph"],
  ];
  function scoreBreakdownLine(parts) {
    if (!parts) return "";
    var words = BREAKDOWN_LABELS.filter(function (l) {
      return Math.round(parts[l[0]] || 0) !== 0;
    }).map(function (l) {
      return l[1] + " " + Math.round(parts[l[0]]);
    });
    return words.length
      ? '<p class="people-breakdown small-text muted">' + esc(words.join(" · ")) + "</p>"
      : "";
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
  var SITE_LABELS = {
    booking: "Booking",
    airbnb: "Airbnb",
    google_hotels: "Google Hotels",
    google_flights: "Google Flights",
    linkedin: "LinkedIn",
  };

  function sourceApiText(src) {
    var prov = src.provider || "unknown";
    if (prov === "fixture" || src.api === "fixture") return "Sample data";
    if (prov === "brightdata")
      return (
        "Bright Data · " + (BD_API_LABELS[src.api] || src.api || "unknown") +
        (SITE_LABELS[src.site] ? " · " + SITE_LABELS[src.site] : "")
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
    if (src.collected_at) tip.push("collected_at: " + src.collected_at);
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

  // Clock time of a collection, in the conference time zone ("11:41 AM").
  function fmtClock(iso) {
    var d = new Date(iso);
    if (!iso || isNaN(d.getTime())) return null;
    try {
      return new Intl.DateTimeFormat("en-US", {
        timeZone: EVENT_TZ,
        hour: "numeric",
        minute: "2-digit",
      }).format(d);
    } catch (e) {
      return null;
    }
  }

  // live / cached / fixture of a stay or flight: top-level when present, else its first evidence.
  function recordMode(r) {
    return (
      (r && r.source_mode) ||
      (r && r.evidence && r.evidence[0] && r.evidence[0].source_mode) ||
      "unknown"
    );
  }

  function travelPriceBadge(item) {
    if (recordMode(item) === "fixture")
      return '<span class="badge fixture">Demo prices</span>';
    var checkedAt = item.collected_at || (item.source && item.source.collected_at);
    if (!checkedAt || isNaN(new Date(checkedAt))) return "";
    var checked = new Intl.DateTimeFormat("en-US", {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: EVENT_TZ
    }).format(new Date(checkedAt));
    return '<span class="badge neutral">Checked ' + esc(checked) + '</span>';
  }

  // Every record says how it was obtained: "Cached · 11:41 AM", "Live · 9:02 AM", "Fixture".
  function sourceBadge(mode, collectedAt) {
    var labels = { live: "Live", cached: "Cached", fixture: "Fixture" };
    if (!labels[mode]) return sourceModeBadge(mode);
    var clock = mode !== "fixture" && collectedAt ? fmtClock(collectedAt) : null;
    return (
      '<span class="badge src-mode ' +
      (mode === "fixture" ? "fixture" : mode === "live" ? "live" : "neutral") +
      '" title="Data source: ' +
      esc(mode) +
      (collectedAt ? ", collected_at " + esc(collectedAt) : "") +
      '">' +
      esc(labels[mode] + (clock ? " · " + clock : "")) +
      "</span>"
    );
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

  // Every amount shown carries the price_status of what it is made of (audit fix 5).
  function priceStatusText(statuses) {
    var list = (Array.isArray(statuses) ? statuses : [statuses]).filter(
      function (x) {
        return x != null;
      },
    );
    return list.length
      ? " (price " + list.join(", ") + ")"
      : " (price status unknown)";
  }

  // What the draft is based on, and its warnings, under every draft (audit fix 2).
  function followupFacts(draft) {
    var labels = {
      goal: "Goal",
      event: "Met at",
      person_event: "Where they speak or host",
      company: "Company",
      shared_topic: "Shared topic",
      note: "Your note",
      path: "Graph path",
    };
    var b = draft.based_on || {};
    var facts = Object.keys(labels)
      .filter(function (k) {
        return b[k];
      })
      .map(function (k) {
        return "<li><b>" + esc(labels[k]) + ":</b> " + esc(b[k]) + "</li>";
      })
      .join("");
    var warns = (draft.warnings || [])
      .map(function (w) {
        return '<li class="warn">' + esc(w) + "</li>";
      })
      .join("");
    return (
      (facts
        ? '<p class="small-text muted">Based on</p><ul class="small-text followup-facts">' +
          facts +
          "</ul>"
        : "") +
      (warns
        ? '<ul class="small-text followup-warnings">' + warns + "</ul>"
        : "")
    );
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
    // The API decides the badge: conference data's mode, travel named apart when it differs
    // ("Sample data, live travel"), so live flights never turn the snapshot into "Mixed sources".
    var apiBadge = envelopes.sources && envelopes.sources.badge;
    var label = labels[mode] || labels.unknown;
    if (apiBadge && apiBadge.label) {
      mode = apiBadge.core_mode || mode;
      label = apiBadge.label;
    }
    var badge = $("badge-source");
    badge.className =
      "badge " +
      (mode === "fixture" ? "fixture" : mode === "live" ? "live" : "neutral");
    badge.textContent = label;
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
    return String(text || "");
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
  // "Meet: X" only for a confirmed speaker/host (SPEAKS_AT / HOSTS); else "Possibly: X (not confirmed)".
  function meetLine(people) {
    var sure = (people || []).filter(function (p) { return p.confirmed; }),
      maybe = (people || []).filter(function (p) { return !p.confirmed; });
    var names = function (list) { return list.map(function (p) { return p.name; }).join(", "); };
    return (sure.length ? "Meet: " + names(sure) : "") +
      (sure.length && maybe.length ? " · " : "") +
      (maybe.length ? "Possibly: " + names(maybe) + " (not confirmed)" : "");
  }
  // Events whose status comes from a /simulate-change scenario (API flag ``simulated``).
  var simulatedIds = {};
  function markSimulated(ids) {
    (ids || []).forEach(function (id) {
      simulatedIds[id] = true;
    });
  }
  function statusLabel(status, id) {
    if (status === "sold_out" && simulatedIds[id]) return "Sold out (simulated scenario)";
    return eventStatus(status);
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
    $("travel-context").textContent = [
      conf.name,
      conf.city,
      conf.start_date && shortDate(conf.start_date),
    ]
      .filter(Boolean)
      .join(" · ");
    if (!$("travel-research-form").dataset.initialized)
      $("research-destination").value = conf.city || "";
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
      roiTile(
        "Opportunities scoring " +
          (roi.opportunity_threshold == null
            ? "?"
            : roi.opportunity_threshold) +
          "+",
        roi.opportunities,
      );
    $("roi-note").textContent =
      "Indicative budget: " +
      fmtUsd(roi.budget_usd) +
      (roi.budget_source ? " (" + roi.budget_source + ")" : "") +
      (roi.spend_note ? " · " + roi.spend_note : "") +
      (roi.occupancy_note ? " · " + roi.occupancy_note : "");
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
    if (roi.opportunity_threshold != null)
      $("roi-opportunities-label").textContent =
        "Opportunities scoring " + roi.opportunity_threshold + "+";
    var spendStatus = roi.spend_price_status || {};
    $("roi-spend-note").textContent =
      (roi.spend_usd == null ? "Prices are not available yet." : "") +
      (roi.occupancy_note ? roi.occupancy_note + ". " : "") +
      priceStatusText(
        [].concat(
          spendStatus.flights || [],
          spendStatus.lodging == null ? [] : [spendStatus.lodging],
        ),
      ) +
      (roi.spend_basis ? " · " + roi.spend_basis : "");
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
            var who = meetLine(i.people);
            return (
              "<li><b>" +
              esc(fmtTime(i.start_at, i.timezone)) +
              "</b> " +
              esc(i.title) +
              ' <span class="muted">(' +
              esc(orUnknown(i.venue)) +
              ")</span>" +
              (who
                ? '<div class="muted small-text">' + esc(who) + "</div>"
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
            esc(item.reason === "sold_out" ? statusLabel("sold_out", item.event_id)
                                           : orUnknown(item.reason)) +
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
    markSimulated(all.filter(function (e) { return e.simulated; }).map(function (e) { return e.id; }));
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
                  esc(statusLabel(event.status, event.id)) +
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
    if (envelopes.travel) renderTravel(envelopes.travel);
  }

  function isPlaceholderStay(name) {
    return /^\[FIXTURE\]/i.test(name || "");
  }
  function renderTravel(t) {
    if (!t) return;
    var profile = (envelopes.conference && envelopes.conference.user) || {};
    var form = $("travel-research-form");
    if (!form.dataset.initialized && envelopes.conference) {
      $("research-origin").value = profile.origin_city || "";
      $("research-depart").value = profile.depart_date || "";
      $("research-return").value = profile.return_date || "";
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
                ? '<span class="badge ok">Noted as preferred</span>'
                : '<button class="small secondary" data-action="accept" data-id="' +
                  esc(p.id) +
                  '">Noted</button>') +
              "</div>"
            );
          })
          .join("")
      : '<p class="muted">No timing suggestions for your current agenda.</p>';
    var b = t.budget || {};
    $("budget").title = b.budget_source || "";
    $("budget").innerHTML =
      b.budget_usd == null
        ? ""
        : esc("Your budget · " + fmtUsd(b.budget_usd)) +
          " " +
          sourceModeBadge(b.source_mode) +
          (b.occupancy_note ? ' <span class="muted small-text occupancy-note">' + esc(b.occupancy_note) + "</span>" : "");
  }

  var travelSearchKind = "flights",
    travelSearchResults = {},
    travelSearchSequence = 0,
    travelAutoSearch = false;
  var travelGuests = { flights: "1", stays: "2" };
  function travelQuery() {
    return {
      kind: travelSearchKind,
      trip_type: $("flight-type").value,
      origin: $("research-origin").value.trim(),
      destination: $("research-destination").value.trim(),
      depart: $("research-depart").value,
      return_date: $("research-return").value,
      adults: Number($("research-adults").value),
      cabin: $("research-cabin").value,
      rooms: Number($("research-rooms").value),
      radius_km: Number($("travel-stay-radius").value),
    };
  }
  function updateResearchLinks() {
    var q = travelQuery();
    $("research-return").min = q.depart;
    $("research-return").setCustomValidity(
      (travelSearchKind === "stays" || q.trip_type !== "one_way") &&
        q.return_date <= q.depart
        ? "Return or check-out must be after departure."
        : "",
    );
    $("research-flights-link").href =
      "https://www.google.com/travel/flights?q=" +
      encodeURIComponent(
        "Flights from " +
          q.origin +
          " to " +
          q.destination +
          " on " +
          q.depart +
          (q.trip_type === "one_way"
            ? " one way"
            : " returning " + q.return_date) +
          ", " +
          q.adults +
          " adults, " +
          q.cabin,
      );
    $("research-stays-link").href =
      "https://www.booking.com/searchresults.html?ss=" +
      encodeURIComponent(q.destination) +
      "&checkin=" +
      q.depart +
      "&checkout=" +
      q.return_date +
      "&group_adults=" +
      q.adults +
      "&no_rooms=" +
      q.rooms;
  }
  function travelEmpty(message, link) {
    return (
      '<div class="travel-search-empty"><h3>No matching offers yet.</h3><p>' +
      esc(message) +
      "</p>" +
      (safeUrl(link)
        ? '<a href="' +
          esc(link) +
          '" target="_blank" rel="noopener noreferrer">Continue with a travel provider</a>'
        : "") +
      "</div>"
    );
  }
  function switchTravelKind(kind) {
    travelGuests[travelSearchKind] = $("research-adults").value;
    travelSearchKind = kind;
    var flights = kind === "flights";
    $("research-adults").value = travelGuests[kind];
    $("travel-flights-tab").setAttribute("aria-selected", String(flights));
    $("travel-stays-tab").setAttribute("aria-selected", String(!flights));
    $("flight-results-panel").hidden = !flights;
    $("stay-results-panel").hidden = flights;
    $("travel-title").textContent = flights
      ? "Find your flight."
      : "Find a place to stay.";
    $("research-origin-label").hidden = !flights;
    $("research-origin").required = flights;
    $("research-return").closest("label").hidden =
      flights && $("flight-type").value === "one_way";
    $("research-return").required = !(
      flights && $("flight-type").value === "one_way"
    );
    $("research-cabin-label").hidden = !flights;
    $("flight-type-label").hidden = !flights;
    $("research-rooms-label").hidden = flights;
    $("travel-stop-filters").hidden = !flights;
    $("stay-radius-filter").hidden = flights;
    $("research-destination-label").textContent = flights ? "To" : "Where";
    $("research-depart-label").textContent = flights ? "Departure" : "Check-in";
    $("research-return-label").textContent = flights ? "Return" : "Check-out";
    document
      .querySelector(".travel-search-fields")
      .classList.toggle("is-stays", !flights);
    $("travel-search-hint").textContent = flights
      ? "Destination set from your conference."
      : "Search near the conference. Quoted stays use the guest count above.";
    updateResearchLinks();
    document.dispatchEvent(new Event("travel:kindchange"));
    searchTravel("cached");
  }
  function searchTravel(mode) {
    if (!$("travel-research-form").reportValidity()) return Promise.resolve();
    updateResearchLinks();
    var q = travelQuery();
    q.mode = mode || "live";
    var sequence = ++travelSearchSequence,
      kind = q.kind;
    $("travel-search-button").disabled = true;
    $("travel-refresh-prices").disabled = true;
    $("travel-show-collected").disabled = true;
    $("travel-search-button").querySelector("span").textContent = "Searching…";
    $("travel-results-workspace").setAttribute("aria-busy", "true");
    $("travel-search-feedback").textContent = "";
    $("travel-offer-context").textContent = "Finding offers for your dates…";
    function awaitCollection(res) {
      if(sequence !== travelSearchSequence) return Promise.resolve(res);
      if(res.status !== "running" || !res.job_id) return Promise.resolve(res);
      $("travel-search-button").querySelector("span").textContent = "Collecting…";
      $("travel-offer-context").textContent = "Checking Booking and Airbnb. Collection can take a few minutes.";
      return new Promise(function(resolve){setTimeout(resolve,2500);}).then(function(){
        if(sequence !== travelSearchSequence) return res;
        return api("/travel/search/" + encodeURIComponent(res.job_id), null, null).then(awaitCollection);
      });
    }
    return api("/travel/search", { method: "POST", body: q }, null)
      .then(awaitCollection)
      .then(function (res) {
        if (sequence !== travelSearchSequence) return;
        travelSearchResults[kind] = res;
        var stamp = res.collected_at
          ? new Intl.DateTimeFormat("en-US", {
              month: "short",
              day: "numeric",
              hour: "numeric",
              minute: "2-digit",
              timeZoneName: "short",
              timeZone: EVENT_TZ,
            }).format(new Date(res.collected_at))
          : "";
        var priceContext = res.items && res.items.length
          ? (res.data_source === "fixture" ? "Demo prices" : "Prices checked")
          : q.mode === "live" ? "Prices unavailable" : "No matching offers";
        $("travel-offer-context").textContent =
          priceContext +
          (stamp ? " · " + stamp : "") +
          " · " +
          q.adults +
          (q.adults === 1 ? " adult" : " adults");
        if (q.mode === "live" && !res.items.length) {
          $("travel-search-feedback").innerHTML =
            "<p>" +
            esc(
              "We couldn’t update prices. Try again or check the booking site.",
            ) +
            '</p><button type="button" class="text-button" id="travel-use-collected">Show saved offers</button>';
          $("travel-use-collected").onclick = function () {
            searchTravel("cached");
          };
        }
        $("travel-research-form").dataset.changed = "";
        if (kind === "flights") renderFlights(res);
        else renderStays(res);
      })
      .catch(function () {
        if (sequence !== travelSearchSequence) return;
        $("travel-offer-context").textContent = "Search unavailable";
        var link = $(
          kind === "flights" ? "research-flights-link" : "research-stays-link",
        ).href;
        $(kind === "flights" ? "flights" : "stays").innerHTML = travelEmpty(
          "We couldn’t complete this search. Try again or use the same criteria with a travel provider.",
          link,
        );
      })
      .finally(function () {
        if (sequence !== travelSearchSequence) return;
        $("travel-search-button").disabled = false;
        $("travel-refresh-prices").disabled = false;
        $("travel-show-collected").disabled = false;
        $("travel-search-button").querySelector("span").textContent = "Search";
        $("travel-results-workspace").setAttribute("aria-busy", "false");
      });
  }
  function flightMinutes(offer) {
    var slice = (offer.slices || [])[0] || {},
      segments = slice.segments || [],
      first = segments[0] || {},
      last = segments[segments.length - 1] || {};
    if (slice.duration_minutes != null) return slice.duration_minutes;
    if (first.departure_at && last.arrival_at)
      return Math.round(
        (Date.parse(last.arrival_at) - Date.parse(first.departure_at)) / 60000,
      );
    return null;
  }
  function travelMoney(value, currency) {
    if (value == null) return "Price unavailable";
    try {
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: currency || "USD",
        maximumFractionDigits: 2,
        minimumFractionDigits: 0,
      }).format(Number(value));
    } catch (e) {
      return value + " " + (currency || "");
    }
  }
  function renderFlights(res) {
    if (
      res &&
      !res.query &&
      $("travel-research-form").dataset.changed &&
      travelSearchKind === "flights"
    )
      return;
    if (res && !res.query && travelSearchResults.flights)
      res = travelSearchResults.flights;
    var all = ((res && res.items) || []).filter(function (o) {
      return !(
        o.source &&
        o.source.provider === "fixture" &&
        o.total_price == null
      );
    });
    var stops = document.querySelector(
        'input[name="travel-stops"]:checked',
      ).value,
      max = Number($("travel-max-price").value) || Infinity;
    var items = all.filter(function (o) {
      var segments = ((o.slices || [])[0] || {}).segments || [];
      return (
        (stops === "all" || segments.length - 1 <= Number(stops)) &&
        (o.total_price == null || Number(o.total_price) <= max)
      );
    });
    function direction(offer) {
      if (
        offer.trip_type === "round_trip" ||
        offer.return_slice_collected === false
      )
        return 0;
      var slice = (offer.slices || [])[0] || {};
      var first = (slice.segments || [])[0] || {};
      return res &&
        res.query &&
        first.departure_at &&
        first.departure_at.slice(0, 10) === res.query.return_date
        ? 2
        : 1;
    }
    var directionLabels = [
      "Round-trip quotes",
      "Outbound · One-way fares",
      "Return · One-way fares",
    ];
    var presentDirections = Array.from(new Set(items.map(direction)));
    var lastDirection = null;
    var sort = $("flight-sort").value;
    items.sort(function (a, b) {
      if (direction(a) !== direction(b)) return direction(a) - direction(b);
      if (sort === "price" && a.currency === b.currency)
        return (
          (a.total_price == null ? Infinity : Number(a.total_price)) -
          (b.total_price == null ? Infinity : Number(b.total_price))
        );
      if (sort === "duration")
        return (flightMinutes(a) || Infinity) - (flightMinutes(b) || Infinity);
      var aa = (((a.slices || [])[0] || {}).segments || [])[0] || {},
        bb = (((b.slices || [])[0] || {}).segments || [])[0] || {};
      return String(
        sort === "departure" ? aa.departure_at || "z" : aa.origin_iata,
      ).localeCompare(
        String(sort === "departure" ? bb.departure_at || "z" : bb.origin_iata),
      );
    });
    $("flight-result-count").textContent = items.length + " matching offers";
    $("flight-compare-title").textContent =
      "Flights to " +
      ((res && res.query && res.query.destination) ||
        $("research-destination").value ||
        "your conference");
    $("flights").innerHTML = items.length
      ? items
          .map(function (leg) {
            var heading = presentDirections.length > 1 && direction(leg) !== lastDirection
              ? '<h3 class="flight-direction">' + directionLabels[direction(leg)] + '</h3>' : '';
            lastDirection = direction(leg);
            return heading + TravelCards.flight(leg, travelPriceBadge(leg));
          })
          .join("")
      : travelEmpty(
          all.length
            ? "Try fewer filters to see more options."
            : "No offers match these dates, travelers and cabin. Continue your search with the same criteria.",
          (res && res.fallback_url) || $("research-flights-link").href,
        );
  }

  function renderStays(s) {
    if (
      s &&
      !s.query &&
      $("travel-research-form").dataset.changed &&
      travelSearchKind === "stays"
    )
      return;
    if (s && !s.query && travelSearchResults.stays)
      s = travelSearchResults.stays;
    var items = ((s && s.items) || []).filter(function (stay) {
      return !isPlaceholderStay(stay.name);
    });
    var max = Number($("travel-max-price").value) || Infinity;
    items = items.filter(function (st) {
      return st.total_price == null || Number(st.total_price) <= max;
    });
    $("trip-stays-title").textContent =
      "Stays in " +
      ((s && s.query && s.query.destination) ||
        $("research-destination").value ||
        "your destination");
    $("stay-result-count").textContent =
      items.length + " matching stays · Total for the full stay";
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
            return TravelCards.stay(st, travelPriceBadge(st));
          })
          .join("")
      : travelEmpty(
          "No stays match these dates, guests and rooms. Try different criteria or continue with a travel provider.",
          (s && s.fallback_url) || $("research-stays-link").href,
        );
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
      esc(orUnknown(e.observed_at)) +
      (e.rationale
        ? '<br><span class="muted">' + esc(e.rationale) + "</span>"
        : "")
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
    if (window.Connections) return window.Connections.render();
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

  // What our graph has no recorded path for (not proof of absence); never an empty block.
  function renderGraphGaps(res) {
    var box = $("graph-gaps-body");
    if (!box) return;
    if (!res || !res.gaps) {
      box.textContent = (res && res.warnings && res.warnings[0]) || "Graph not reachable: no graph to query.";
      return;
    }
    var labels = { goals_without_path: "Goals with no path to anyone",
      target_companies_not_present: "Companies in your goals with no presence at an event",
      topics_uncovered: "Goal topics no event is about" };
    var parts = Object.keys(labels).map(function (k) {
      var g = res.gaps[k] || { rows: [], count: 0, cypher: "" };
      var rows = g.rows.map(function (r) {
        return "<li>" + esc(r.description || r.company || r.topic || r.goal_id) + ' <span class="muted">(' + esc(r.goal_id) + ")</span></li>";
      }).join("");
      return "<h3>" + esc(labels[k]) + " · " + esc(g.count) + "</h3>" +
        (rows ? "<ul>" + rows + "</ul>" : '<p class="muted">None.</p>') +
        '<pre class="cypher">' + esc(g.cypher) + "</pre>";
    }).join("");
    box.classList.remove("muted");
    box.innerHTML = (res.empty ? "<p><b>No gaps for these goals</b></p>" : "") +
      '<p class="small-text">Graph source mode: <b>' + esc(res.graph_source_mode) + "</b> " +
      esc(JSON.stringify(res.graph_source_modes || {})) + "</p>" + parts;
  }

  function renderGraph(g) {
    if (window.Connections) return window.Connections.render();
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
    if (window.Connections) return window.Connections.focus(personId);
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
        '" title="' +
        esc(
          "Luma capture" +
            (event.cover_captured_at
              ? " taken " +
                shortDate(String(event.cover_captured_at).slice(0, 10))
              : "") +
            "; live events have no artwork yet",
        ) +
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
    $("stat-people").textContent = p && p.total != null ? p.total : all.length; // all ranked people, not the page shown
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
            var evidence =
              (opportunity.evidence && opportunity.evidence.length
                ? opportunity.evidence
                : person.evidence) || [];
            var whyEdges = (card.why && card.why.edges) || [];
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
                  whyEdges
                    .filter(function (w) {
                      return (
                        entry.source_url &&
                        (w.evidence_ids || []).indexOf(entry.source_url) >= 0
                      );
                    })
                    .map(function (w) {
                      return (
                        '<br><span class="muted">' +
                        esc(w.rationale) +
                        "</span>"
                      );
                    })
                    .join("") +
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
              "</p>" +
              scoreBreakdownLine(opportunity.score_breakdown) +
              '<div class="people-session"><span class="people-session-label">' +
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
              '<div class="small-text people-why" id="why-' + esc(id) + '"></div>' +
              '<div class="people-actions">' +
              '<button class="secondary" data-action="why" data-id="' +
              esc(id) +
              '">Why?</button>' +
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
    markSimulated(res.changed_events);
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
          esc(b.status === "sold_out" ? statusLabel(b.status, x.event_id) : b.status) +
          ") to " +
          esc(fmtTime(a.start_at)) +
          " (" +
          esc(a.status === "sold_out" ? statusLabel(a.status, x.event_id) : a.status) +
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
              ")" +
              (meetLine(r.people) ? "<br>" + esc(meetLine(r.people)) : "")
            : "") +
          "<br><b>Reason:</b> " +
          esc(x.reason) +
          (p
            ? "<br><b>Path:</b> " +
              esc(p.nodes.join(" > ")) +
              (p.confirmed === false ? " (not confirmed)" : "") +
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
    travelSearchSequence++;
    $("travel-search-button").disabled = false;
    $("travel-search-button").querySelector("span").textContent = "Search";
    $("travel-offer-context").textContent =
      "Search to update results for your new criteria.";
    $(travelSearchKind === "flights" ? "flights" : "stays").innerHTML =
      '<p class="travel-empty">Your criteria have changed. Search to see matching offers.</p>';
    updateResearchLinks();
  });
  $("travel-research-form").onsubmit = function (event) {
    event.preventDefault();
    searchTravel();
  };
  $("travel-flights-tab").onclick = function () {
    switchTravelKind("flights");
  };
  $("travel-stays-tab").onclick = function () {
    switchTravelKind("stays");
  };
  ["travel-flights-tab", "travel-stays-tab"].forEach(function (id) {
    $(id).onkeydown = function (event) {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        var kind = travelSearchKind === "flights" ? "stays" : "flights";
        switchTravelKind(kind);
        $(
          kind === "flights" ? "travel-flights-tab" : "travel-stays-tab",
        ).focus();
      }
    };
  });
  function filterTravelResults() {
    if ($("travel-research-form").dataset.changed) return;
    if (travelSearchKind === "flights")
      renderFlights(travelSearchResults.flights || envelopes.flights);
    else renderStays(travelSearchResults.stays || envelopes.stays);
  }
  $("flight-type").onchange = function () {
    var one = this.value === "one_way" && travelSearchKind === "flights";
    $("research-return").closest("label").hidden = one;
    $("research-return").required = !one;
    document
      .querySelector(".travel-search-fields")
      .classList.toggle("is-oneway", one);
    updateResearchLinks();
  };
  $("flight-sort").onchange = filterTravelResults;
  $("stay-sort").onchange = filterTravelResults;
  $("travel-max-price").oninput = filterTravelResults;
  document
    .querySelectorAll('input[name="travel-stops"]')
    .forEach(function (input) {
      input.onchange = filterTravelResults;
    });
  $("travel-stay-radius").onchange = function () {
    searchTravel("cached");
  };
  $("travel-show-collected").onclick = function () {
    searchTravel("cached");
  };
  $("travel-refresh-prices").onclick = function () {
    searchTravel("live");
  };
  $("travel-mobile-filters").onclick = function () {
    var open = this.getAttribute("aria-expanded") !== "true";
    this.setAttribute("aria-expanded", String(open));
    document
      .querySelector(".travel-filter-sidebar")
      .classList.toggle("filters-open", open);
  };
  $("travel-clear-filters").onclick = function () {
    $("travel-max-price").value = "";
    document.querySelector('input[name="travel-stops"][value="all"]').checked =
      true;
    filterTravelResults();
  };
  $("travel-local-toggle").onclick = function () {
    $("travel-research-form").hidden = true;
    $("travel-results-workspace").hidden = true;
    $("travel-local-note").hidden = false;
    $("travel-offer-context").hidden = true;
  };
  $("travel-resume").onclick = function () {
    $("travel-research-form").hidden = false;
    $("travel-results-workspace").hidden = false;
    $("travel-local-note").hidden = true;
    $("travel-offer-context").hidden = false;
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
        api("/flights?alternatives=true", null, "flights"),
        "flights",
        renderFlights,
        errors,
      ),
      settle(api("/travel/map", null, "map"), "map", function (data) {
        if (envelopes.plan) renderStoryPlan(envelopes.plan, data);
      }, errors),
      settle(api("/graph", null, "graph"), "connections", renderGraph, errors),
      settle(api("/graph/gaps", null, null), "graph gaps", renderGraphGaps, errors),
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
        if (envelopes.travel) renderTravel(envelopes.travel);
        if (!travelAutoSearch && envelopes.conference) {
          travelAutoSearch = true;
          searchTravel("cached");
        }
        if (envelopes.people) renderPeople(envelopes.people);
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
    var products = (res && res.products) || [];
    var apiName = { dataset: "dataset", unlocker: "Web Unlocker", serp: "SERP" };
    var range = function (p) {
      if (!p.collected_first) return "—";
      var a = fmtTime(p.collected_first),
        b = fmtTime(p.collected_last);
      return a === b ? a : a + " to " + b;
    };
    var table = products.length
      ? '<table class="pipeline-table bd-products"><thead><tr><th>Product</th><th>API</th>' +
        "<th>Requests</th><th>Records</th><th>Collected (records' own time)</th>" +
        "</tr></thead><tbody>" +
        products
          .map(function (p) {
            return (
              "<tr><td>" + esc(p.product) + "</td><td>" + esc(apiName[p.api] || p.api) +
              "</td><td>" + esc(p.requests) + "</td><td>" + esc(p.records) + "</td><td>" +
              esc(range(p)) + "</td></tr>"
            );
          })
          .join("") +
        "</tbody></table>"
      : '<p class="muted">No Bright Data record in this demo.</p>';
    var notReady = ["datasets", "web_unlocker", "serp"].filter(function (k) {
      return !ready[k];
    });
    var live = (res && res.live) || { requests: 0, records: 0 };
    var cs = (res && res.cache_summary) || {};
    function collectedPhrase(first, last) {
      if (!last) return "collection time unknown";
      var l = new Date(last), f = new Date(first || last), now = new Date();
      var sameDay = l.toDateString() === now.toDateString();
      var hour = Number(new Intl.DateTimeFormat("en-US", { timeZone: EVENT_TZ, hour: "numeric", hour12: false }).format(l));
      if (sameDay && hour < 12) return "collected this morning";
      return "collected " + fmtTime(f.toISOString()) + (first && first !== last ? " to " + fmtTime(last) : "");
    }
    var cacheLine = cs.records
      ? '<div class="bd-cache-line">Served from cache: ' + esc(cs.records) + " records, " +
        esc(collectedPhrase(cs.collected_first, cs.collected_last)) + " (" +
        esc(cs.requests_at_collection_time || 0) + " requests at collection time)</div>"
      : "";
    $("bd-counter").innerHTML =
      "<b>Bright Data live: " + esc(live.requests || 0) + " requests, " + esc(live.records || 0) +
      " records" + (live.key_missing ? " (key missing)" : "") + "</b>" + cacheLine +
      ' <span class="bd-detail">(a request is one API call; one Web Unlocker page can yield many records). ' +
      "Cost: " + esc((res && res.cost_note) || "not read from any Bright Data response") + "." +
      (u.requests && u.requests.total
        ? " This process: " + esc(u.requests.total) + " requests, " +
          esc(u.returned.total) + " rows or pages returned live."
        : "") +
      (notReady.length
        ? ' <span class="muted">(not configured here: ' + esc(notReady.join(", ")) + ")</span>"
        : "") +
      "</span>" +
      table +
      travel;
  }

  function renderRefresh(res) {
    var r = (res && res.refresh) || {};
    var head = "Bright Data refresh: requests +" + esc(r.requests || 0) + ", records +" +
      esc(r.records || 0) + ", " + esc(r.seconds) + " s";
    $("pipeline-refresh-result").innerHTML =
      '<div class="refresh-head">' + head + "</div>" +
      (r.lines || []).map(function (l) { return '<div class="refresh-line">' + esc(l) + "</div>"; }).join("") +
      (r.notes || []).map(function (n) { return '<div class="refresh-line muted">' + esc(n) + "</div>"; }).join("") +
      (r.slow || []).map(function (e) { return '<div class="refresh-slow">' + esc(e) + "</div>"; }).join("") +
      (r.errors || []).map(function (e) { return '<div class="refresh-error">' + esc(e) + "</div>"; }).join("");
  }

  function bdRefresh() {
    var btn = $("btn-bd-refresh");
    btn.disabled = true;
    var started = Date.now();
    function tick() {
      var s = Math.floor((Date.now() - started) / 1000);
      $("pipeline-refresh-result").innerHTML = '<div class="muted">Calling Bright Data... ' + s + " s</div>";
      btn.textContent = "Refreshing... " + s + " s";
    }
    tick();
    var timer = setInterval(tick, 1000);
    api("/pipeline/refresh", { method: "POST" }, null)
      .then(function (res) {
        clearInterval(timer);
        renderRefresh(res);
        return Promise.all([api("/pipeline", null, null).then(renderPipeline),
          api("/brightdata", null, null).then(renderBrightData),
          api("/travel", null, "travel").then(renderTravel)]);
      })
      .catch(function (err) {
        $("pipeline-refresh-result").innerHTML = '<div class="refresh-error">Refresh failed: ' +
          esc(err && err.message ? err.message : String(err)) + "; cached data kept</div>";
      })
      .then(function () {
        clearInterval(timer);
        btn.disabled = false;
        btn.textContent = "Refresh via Bright Data";
      });
  }

  function renderPipeline(res) {
    $("pipeline-headline").textContent = (res && res.headline) || "";
    var rows = (res && res.rows) || [];
    $("pipeline-table").innerHTML = rows.length
      ? '<table class="pipeline-table"><thead><tr>' +
        "<th>Source</th><th>Provider</th><th>Mode</th><th>Bright Data API</th><th>Records</th>" +
        "<th>Collected</th><th>Run report</th></tr></thead><tbody>" +
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
    var req = (res && res.requests) || {};
    var atc = req.at_collection_time || [];
    var since = req.since_start || {};
    var reqLine =
      "<div><b>Requests at collection time:</b> " +
      (atc.length
        ? atc.map(function (p) { return esc(p.product) + " " + esc(p.requests) + " req / " + esc(p.records) + " rec"; }).join(" · ")
        : "none") +
      "</div><div><b>Requests since start:</b> " +
      ["dataset", "unlocker", "serp"].map(function (k) {
        var v = since[k] || since[k === "dataset" ? "datasets" : k] || { requests: 0 };
        return esc(k) + " " + esc(v.requests || 0);
      }).join(" · ") + "</div>";
    $("pipeline-calls").innerHTML =
      reqLine +
      "Bright Data records in these runs: " +
      esc(t.brightdata_records || 0) +
      ". Cost: " +
      esc(t.cost_note || "not read from any Bright Data response") +
      ". Bright Data calls in this process: " +
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
    renderTimings(res && res.timings, res && res.sources_report);
    renderReachability(res && res.reachability);
    api("/cost", null, null).then(renderCost, function () {
      renderCost(null);
    });
  }

  function renderCost(c) {
    var box = $("pipeline-cost");
    if (!box) return;
    if (!c) {
      box.innerHTML = '<span class="muted">Bright Data counter unavailable.</span>';
      return;
    }
    var by = c.by_api || {};
    var part = function (k, label) {
      var v = by[k] || {};
      return label + " " + esc(v.requests || 0) + " req / " + esc(v.records || 0) + " rec";
    };
    box.innerHTML =
      "<b>Bright Data, live in this process:</b> " + esc(c.requests) + " requests, " +
      esc(c.records) + " records · " +
      part("datasets", "datasets") + " · " + part("unlocker", "unlocker") + " · " +
      part("serp", "serp") +
      ' <span class="muted">(' + esc(c.cost_note || "cost not read from any Bright Data response") + ")</span>";
  }

  function renderTimings(t, overall) {
    var box = $("pipeline-timings");
    if (!box) return;
    var steps = (t && t.steps) || [],
      sources = (t && t.sources) || [];
    if (!steps.length && !sources.length) {
      box.innerHTML = "";
      return;
    }
    var secs = function (v) {
      return v === null || v === undefined ? "—" : Number(v).toFixed(2) + " s";
    };
    box.innerHTML =
      "<h3>Durations</h3>" +
      (overall && overall.display
        ? '<p>Sources overall: <b class="overall-' +
          esc(overall.display.label) +
          '">' +
          esc(overall.display.label) +
          "</b>: " +
          esc(overall.display.reason) +
          "</p>"
        : "") +
      '<table class="pipeline-table"><thead><tr><th>Step</th><th>Time</th></tr></thead><tbody>' +
      steps
        .map(function (s) {
          return (
            "<tr><td>" +
            esc(s.step) +
            (s.note
              ? ' <span class="muted">(' + esc(s.note) + ")</span>"
              : "") +
            "</td><td>" +
            esc(secs(s.seconds)) +
            "</td></tr>"
          );
        })
        .join("") +
      "</tbody></table>" +
      '<table class="pipeline-table"><thead><tr><th>Source</th><th>Status</th><th>Records</th><th>Time</th></tr></thead><tbody>' +
      sources
        .map(function (s) {
          return (
            "<tr><td>" +
            esc(s.source) +
            "</td><td>" +
            esc(
              s.status === "degraded" ? "partial (not exhausted)" : s.status,
            ) +
            "</td><td>" +
            esc(s.records) +
            "</td><td>" +
            esc(secs(s.seconds)) +
            "</td></tr>"
          );
        })
        .join("") +
      "</tbody></table>";
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
            toast("Noted as preferred. No flight or stay has changed.");
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
            "</p>" +
            followupFacts(draft) +
            '<button class="secondary" data-action="copy-followup" data-id="' +
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
    } else if (action === "why") {
      var whyBox = $("why-" + id);
      if (!whyBox) return;
      whyBox.textContent = "Reading the graph…";
      api("/graph/why/" + encodeURIComponent(id))
        .then(function (why) {
          var links = (why.evidence || [])
            .map(function (ev) {
              var link = safeUrl(ev.source_url);
              return (
                "<li>" +
                (link
                  ? '<a href="' +
                    esc(link) +
                    '" target="_blank" rel="noopener noreferrer">' +
                    esc(ev.evidence_id) +
                    "</a>"
                  : esc(ev.evidence_id)) +
                "</li>"
              );
            })
            .join("");
          whyBox.innerHTML = why.answer
            ? "<p>" +
              esc(why.answer) +
              '</p><ul class="plain-list">' +
              links +
              "</ul>"
            : '<p class="muted">No connection path in the graph for this person.</p>';
        })
        .catch(function (e) {
          whyBox.textContent = e.message;
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
    if ($("btn-bd-refresh")) $("btn-bd-refresh").addEventListener("click", bdRefresh);
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
        simulatedIds = {};
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
