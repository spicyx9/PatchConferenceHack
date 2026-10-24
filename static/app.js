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

  // Every amount shown carries the price_status of what it is made of (audit fix 5).
  function priceStatusText(statuses) {
    var list = (Array.isArray(statuses) ? statuses : [statuses]).filter(function (x) { return x != null; });
    return list.length ? " (price " + list.join(", ") + ")" : " (price status unknown)";
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
      (roi.budget_source ? " (" + roi.budget_source + ")" : "") +
      (roi.spend_note ? " · " + roi.spend_note : "");
    [ ["roi-spend", roi.spend_usd == null ? null : fmtUsd(roi.spend_usd)], ["roi-meetings", roi.meetings], ["roi-qualified", roi.qualified_contacts], ["roi-opportunities", roi.opportunities] ].forEach(function (pair) {
      var element = $(pair[0]);
      element.textContent = pair[1] == null ? "Not provided" : String(pair[1]);
      element.classList.toggle("unknown", pair[1] == null);
    });
    var spendStatus = roi.spend_price_status || {};
    $("roi-spend-note").textContent = (roi.spend_usd == null ? "Prices are not available yet." : "") +
      priceStatusText([].concat(spendStatus.flights || [], spendStatus.lodging == null ? [] : [spendStatus.lodging])) +
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
    $("plan-days").innerHTML = visible.length
      ? visible
          .map(function (d) {
            return (
              '<div class="day"><h3>' +
              esc(fmtDay(d.day)) +
              "</h3>" +
              ((d.items || []).length
                ? d.items
                    .map(function (i) {
                      return (
                        '<div class="event-item ' +
                        esc(i.status) +
                        '"><span class="time">' +
                        esc(
                          fmtHour(i.start_at, i.timezone) +
                            " – " +
                            fmtHour(i.end_at, i.timezone),
                        ) +
                        '</span><span class="title">' +
                        esc(i.title) +
                        '<span class="muted small-text">' +
                        esc(orUnknown(i.venue)) +
                        (i.room && i.room !== i.venue
                          ? " · " + esc(i.room)
                          : "") +
                        " · Score " +
                        esc(i.score) +
                        "</span></span>" +
                        sourceBadge(i.source_mode) +
                        '<span class="actions"><button class="small' +
                        (i.attended ? " on" : "") +
                        '" data-action="attended" data-id="' +
                        esc(i.event_id) +
                        '"' +
                        (i.attended ? " disabled" : "") +
                        ">" +
                        (i.attended ? "Attendance recorded" : "Mark attended") +
                        '</button><button class="small" data-action="skipped" data-id="' +
                        esc(i.event_id) +
                        '">Skip this event</button></span></div>'
                      );
                    })
                    .join("")
                : '<p class="muted section-note">No events planned for this day.</p>') +
              "</div>"
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
          .map(function (c) {
            return (
              '<div class="conflict"><b>' +
              esc(fmtDay(c.day)) +
              "</b><p>" +
              esc(c.verdict) +
              "</p><p>Kept: " +
              esc(c.winner && c.winner.title) +
              "<br>Skipped: " +
              esc(c.loser && c.loser.title) +
              '</p><div class="small-text">People you may miss: ' +
              esc(
                (c.what_you_miss || [])
                  .map(function (m) {
                    return m.name;
                  })
                  .join(", ") || "None from your list",
              ) +
              "</div></div>"
            );
          })
          .join("")
      : '<p class="muted section-note">No conflicts found in this plan.</p>';
    var excluded = (plan && plan.plan && plan.plan.excluded) || [];
    $("excluded").innerHTML =
      excluded
        .map(function (x) {
          return (
            "<li>" +
            esc(x.title) +
            ' <span class="badge neutral">' +
            esc(orUnknown(x.reason)) +
            "</span>" +
            (x.detail ? '<div class="muted">' + esc(x.detail) + "</div>" : "") +
            "</li>"
          );
        })
        .join("") || '<li class="muted">No events skipped.</li>';
  }

  function renderEvents(ev) {
    lastEvents = ev;
    var all = (ev && ev.items) || [];
    document.dispatchEvent(new CustomEvent("conferge:events", { detail: all }));
    $("stat-events").textContent = all.length;
    renderDiscoverEvents(all);
    var needle = fold($("events-search").value),
      type = $("events-type").value;
    var items = all.filter(function (e) {
      return (
        (type === "all" || e.event_type === type) &&
        (!needle ||
          fold(e.title + " " + ((e.venue && e.venue.name) || "")).indexOf(
            needle,
          ) >= 0)
      );
    });
    $("events-result-count").textContent = items.length + " / " + all.length;
    $("events-list").innerHTML = items.length
      ? items
          .map(function (e) {
            var date = e.start_at
              ? new Intl.DateTimeFormat("en-US", {
                  timeZone: e.timezone || EVENT_TZ,
                  day: "numeric",
                  month: "short",
                }).format(new Date(e.start_at))
              : "To be confirmed";
            var affiliation =
              {
                official: "Official program",
                confirmed_side_event: "Confirmed side event",
                candidate: "Affiliation unconfirmed",
                unknown: "Affiliation unknown",
                unrelated: "Unrelated to conference",
              }[e.conference_relation] || "Affiliation unknown";
            return (
              '<article class="event-browser-row">' +
              '<button type="button" class="event-cover-button" data-action="event" data-id="' +
              esc(e.id) +
              '" aria-label="View ' +
              esc(e.title) +
              '">' +
              eventArtwork(e, false) +
              "</button>" +
              '<div class="event-browser-date" title="' +
              esc(fmtTime(e.start_at, e.timezone)) +
              '"><strong>' +
              esc(date) +
              "</strong>" +
              esc(fmtHour(e.start_at, e.timezone)) +
              '</div><div class="event-browser-main"><h3>' +
              '<button type="button" class="event-title-button" data-action="event" data-id="' +
              esc(e.id) +
              '">' +
              esc(e.title) +
              "</button>" +
              "</h3><p>" +
              esc(orUnknown(e.venue && e.venue.name)) +
              '</p><div class="row">' +
              sourceBadge(e.source_mode) +
              '<span class="badge neutral">' +
              esc(affiliation) +
              "</span>" +
              (e.status !== "scheduled"
                ? '<span class="badge degraded">' +
                  esc(eventStatus(e.status)) +
                  "</span>"
                : "") +
              (e.attended
                ? '<span class="badge met">Attendance recorded</span>'
                : "") +
              (e.skipped ? '<span class="badge neutral">Skipped</span>' : "") +
              '</div></div><div><span class="event-score">Score ' +
              esc(e.score == null ? "—" : Math.round(e.score)) +
              "</span></div></article>"
            );
          })
          .join("")
      : emptyState(
          "No events match your search.",
          "Try a different name or remove the event type filter.",
          "clear-events",
          "Clear filters",
        );
  }

  function isPlaceholderStay(name) {
    return /^\[FIXTURE\]/i.test(name || "");
  }
  function renderTravel(t) {
    if (!t) return;
    var legs = t.itinerary || [];
    $("itinerary").innerHTML = legs.length
      ? legs
          .map(function (leg) {
            if (leg.kind === "flight") {
              var details = [];
              if (leg.departure_at)
                details.push("Departs " + fmtHour(leg.departure_at));
              if (leg.arrival_at)
                details.push("Arrives " + fmtHour(leg.arrival_at));
              if (leg.carrier) details.push(leg.carrier);
              return (
                "<li><b>" +
                esc(leg.from) +
                " to " +
                esc(leg.to) +
                '</b><span class="muted">' +
                esc(fmtDay(leg.date)) +
                '</span><span class="muted">' +
                esc(details.join(" · ") || "Flight details not available yet") +
                '</span><span class="badge neutral">' +
                esc(orUnknown(leg.price_status)) +
                "</span></li>"
              );
            }
            var selected = !isPlaceholderStay(leg.name);
            return (
              "<li><b>" +
              esc(selected ? leg.name : "No stay selected") +
              '</b><span class="muted">' +
              esc(shortDate(leg.check_in)) +
              " – " +
              esc(shortDate(leg.check_out)) +
              "</span>" +
              (selected
                ? '<span class="badge neutral">' +
                  esc(orUnknown(leg.price_status)) +
                  "</span>"
                : '<span class="muted">Explore stays near your conference.</span>') +
              "</li>"
            );
          })
          .join("")
      : '<li class="muted">No travel options available.</li>';

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
              text =
                "Arrive before " +
                fmtHour(arrival[1]) +
                " on " +
                shortDate(arrival[1].slice(0, 10)) +
                " for “" +
                arrival[2] +
                "”.";
              reason = "Leave time between landing and your first event.";
            }
            return (
              '<div class="event-item"><span class="title">' +
              esc(text) +
              '<br><span class="muted small-text">' +
              esc(reason) +
              "</span></span>" +
              (p.accepted
                ? '<span class="badge ok">Suggestion saved</span>'
                : '<button class="small primary" data-action="accept" data-id="' +
                  esc(p.id) +
                  '">Save suggestion</button>') +
              "</div>"
            );
          })
          .join("")
      : '<p class="muted">No suggestions available.</p>';

    var b = t.budget || {};
    $("budget").innerHTML =
      "<table><tbody>" +
      "<tr><th>Budget</th><td>" +
      esc(fmtUsd(b.budget_usd) + (b.budget_source ? " (" + b.budget_source + ")" : "")) +
      "</td></tr>" +
      "<tr><th>Flights</th><td>" +
      esc(fmtUsd(b.flights_usd) + priceStatusText(b.flights_price_status)) +
      "</td></tr>" +
      "<tr><th>Stay</th><td>" +
      esc(fmtUsd(b.lodging_usd) + priceStatusText(b.lodging_price_status)) +
      "</td></tr>" +
      "<tr><th>Remaining</th><td>" +
      esc(fmtUsd(b.remaining_usd)) +
      "</td></tr>" +
      "</tbody></table>" +
      (b.note
        ? '<p class="muted small-text">' +
          esc(
            /^null means/i.test(b.note)
              ? "Your totals will appear when prices are available."
              : b.note,
          ) +
          "</p>"
        : "");
  }

  function renderStays(s) {
    var items = ((s && s.items) || []).filter(function (stay) {
      return !isPlaceholderStay(stay.name);
    });
    $("stays").innerHTML = items.length
      ? items
          .map(function (st) {
            var link = safeUrl(st.booking_url);
            var dist =
              st.distance_to_venue_m === null ||
              st.distance_to_venue_m === undefined
                ? "Not provided"
                : st.distance_to_venue_m +
                  " m" +
                  (st.distance_is_straight_line_estimate
                    ? " (straight-line distance)"
                    : "");
            var priceCls = st.price_status === "verified" ? "ok" : "neutral";
            return (
              '<div class="card"><div class="row"><b>' +
              esc(st.name) +
              "</b></div>" +
              '<div class="row"><span class="badge ' +
              priceCls +
              '">price ' +
              esc(orUnknown(st.price_status)) +
              "</span>" +
              '<span class="badge neutral">availability ' +
              esc(orUnknown(st.availability)) +
              "</span>" +
              sourceBadge(st.source_mode) +
              "</div>" +
              '<div class="field"><b>Type:</b> ' +
              esc(orUnknown(st.lodging_type)) +
              "</div>" +
              '<div class="field"><b>Total:</b> ' +
              esc(
                st.total_price === null || st.total_price === undefined
                  ? "Not provided"
                  : st.total_price + " " + (st.currency || ""),
              ) +
              "</div>" +
              '<div class="field"><b>Distance to venue:</b> ' +
              esc(dist) +
              "</div>" +
              '<div class="field"><b>Dates:</b> ' +
              esc(orUnknown(st.check_in)) +
              " to " +
              esc(orUnknown(st.check_out)) +
              "</div>" +
              (link
                ? '<div class="field"><a href="' +
                  esc(link) +
                  '" target="_blank" rel="noopener noreferrer">View offer</a></div>'
                : "") +
              "</div>"
            );
          })
          .join("")
      : '<p class="muted">No stays available.</p>';
  }

  function markerColor(kind, planned) {
    if (kind === "conference") return "#385535";
    if (kind === "stay") return "#8b9fba";
    return planned ? "#87a361" : "#b2bd9f";
  }

  function renderMap(m) {
    lastMapData = m;
    $("map-places").innerHTML = placesHtml((m && m.markers) || []);
    var el = $("map");
    if (typeof L === "undefined") {
      el.innerHTML =
        '<p class="muted" style="padding:1rem">The map could not load. You can still browse the places below: ' +
        placesHtml((m && m.markers) || []) +
        "</p>";
      return;
    }
    if (!map) {
      map = L.map(el, { scrollWheelZoom: false }).setView([37.79, -122.42], 13);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors",
      }).addTo(map);
    }
    if (mapLayer) mapLayer.remove();
    mapLayer = L.layerGroup().addTo(map);
    var bounds = [];
    var dayColors = ["#5e7d46", "#a98f5c", "#738ca3", "#ad7d6b", "#899a72"];
    ((m && m.polylines) || []).forEach(function (p, idx) {
      if (!p.points || p.points.length < 2) return;
      L.polyline(p.points, {
        color: dayColors[idx % dayColors.length],
        weight: 4,
        opacity: 0.8,
        dashArray: "6 6",
      })
        .bindTooltip("Day " + esc(p.day))
        .addTo(mapLayer);
    });
    ((m && m.markers) || []).forEach(function (mk) {
      if (typeof mk.lat !== "number" || typeof mk.lng !== "number") return;
      bounds.push([mk.lat, mk.lng]);
      L.circleMarker([mk.lat, mk.lng], {
        radius: mk.kind === "conference" ? 12 : 9,
        color: "#ffffff",
        weight: 2,
        fillColor: markerColor(mk.kind, mk.planned),
        fillOpacity: 0.95,
      })
        .bindPopup(
          "<b>" +
            esc(mk.label) +
            "</b><br>" +
            esc(mk.kind) +
            (mk.planned === false ? " (not in your plan)" : "") +
            "<br>Location accuracy: " +
            esc(orUnknown(mk.precision)),
        )
        .addTo(mapLayer);
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30] });
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
    var request = ++pathRequest;
    $("graph-detail").textContent = "Loading connections and evidence…";
    return api(
      "/graph/path?person=" + encodeURIComponent(personId),
      null,
      "graph_path",
    )
      .then(function (res) {
        if (request !== pathRequest) return;
        var nodes = res.node_ids || [],
          edges = res.edge_ids || [],
          steps = res.path || [];
        $("graph-detail").innerHTML = steps.length
          ? "<b>Why this person?</b>" +
            pathHtml(steps) +
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
    var kind =
      {
        session: "SESSION",
        workshop: "WORKSHOP",
        party: "PARTY",
        side_event: "SIDE EVENT",
        meetup: "MEETUP",
        conference: "CONFERENCE",
      }[event.event_type] || "EVENT";
    return (
      '<div class="event-artwork artwork-typographic' +
      (large ? " large-artwork" : "") +
      '" aria-hidden="true"><span>' +
      esc(kind) +
      '</span><svg viewBox="0 0 120 80"><ellipse cx="60" cy="40" rx="47" ry="19"/><ellipse cx="60" cy="40" rx="47" ry="19" transform="rotate(60 60 40)"/><ellipse cx="60" cy="40" rx="47" ry="19" transform="rotate(120 60 40)"/><circle cx="60" cy="40" r="4"/></svg><b>' +
      esc(
        (envelopes.conference &&
          envelopes.conference.conference &&
          envelopes.conference.conference.name) ||
          "Conferge",
      ) +
      "</b></div>"
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
    var all = candidates.filter(function (card) { return !card.met; }).slice(0,10).concat(candidates.filter(function (card) { return card.met; })),
      needle = fold($("people-search").value);
    var items = all.filter(function (c) {
      return (
        !needle ||
        fold(
          ((c.person || {}).name || "") +
            " " +
            ((c.person || {}).title || "") +
            " " +
            ((c.company || {}).name || ""),
        ).indexOf(needle) >= 0
      );
    });
    $("stat-people").textContent = all.length;
    $("people-result-count").textContent =
      items.length + " suggestion" + (items.length !== 1 ? "s" : "");
    $("people-cards").innerHTML = items.length
      ? items
          .map(function (c, idx) {
            var o = c.opportunity || {},
              person = c.person || {},
              company = c.company || {};
            var pid = person.id || (o.person_ids && o.person_ids[0]) || "";
            var evidence = o.evidence || person.evidence || [];
            var sources = evidence
              .map(function (e) {
                var url = safeUrl(e.source_url);
                return (
                  "<li>" +
                  (url
                    ? '<a href="' +
                      esc(url) +
                      '" target="_blank" rel="noopener noreferrer">' +
                      esc(e.provider) +
                      "</a>"
                    : esc(e.provider)) +
                  " " +
                  sourceModeBadge(e.source_mode) +
                  (e.collected_at
                    ? '<br><span class="muted">Collected: ' +
                      esc(fmtTime(e.collected_at)) +
                      "</span>"
                    : "") +
                  "</li>"
                );
              })
              .join("");
            return (
              '<article class="card' +
              (c.met ? " is-met" : "") +
              '"><div class="person-heading"><span class="avatar tone-' +
              (idx % 3) +
              '" aria-hidden="true">' +
              esc(initials(person.name || o.title)) +
              '</span><div><div class="person-name">' +
              esc(person.name || o.title) +
              '</div><div class="person-role">' +
              esc(orUnknown(person.title)) +
              (company.name ? " · " + esc(company.name) : "") +
              '</div></div></div><div class="row">' +
              presenceBadge(person, o) +
              sourceBadge(modeOfEvidence(evidence)) +
              (c.met ? '<span class="badge met">Meeting recorded</span>' : "") +
              '<span class="score" title="Relevance score, not a probability">' +
              esc(o.score == null ? "—" : Math.round(o.score)) +
              '</span></div><div class="field"><b>WHY THIS PERSON</b>' +
              esc(friendlyRationale(orUnknown(o.rationale))) +
              '</div><div class="field field-location"><b>WHERE TO MEET</b>' +
              esc(orUnknown(o.where)) +
              '</div><details><summary>Prepare a conversation &amp; view sources</summary><div class="field"><b>CONVERSATION STARTER</b>' +
              esc(orUnknown(o.opener)) +
              "</div>" +
              (c.met_note
                ? '<div class="field"><b>YOUR NOTE</b>' +
                  esc(c.met_note) +
                  "</div>"
                : "") +
              '<ul class="plain-list">' +
              (sources ||
                '<li class="muted">No additional sources provided.</li>') +
              '</ul><p class="presence-note">An announced appearance does not guarantee a chance to meet.</p></details>' +
              (c.met ? '<div class="followup" id="followup-' + esc(pid) + '"></div>' : "") +
              '<div class="card-actions">' +
              (c.met
                ? '<button class="primary" data-action="followup" data-id="' + esc(pid) + '">Draft a follow-up</button>'
                : '<button data-action="met" data-id="' +
                  esc(pid) +
                  '" data-name="' +
                  esc(person.name || o.title) +
                  '" class="primary">Record a meeting</button>') +
              '<button data-action="showpath" data-id="' +
              esc(pid) +
              '">View connection</button></div></article>'
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
      settle(api("/travel/map", null, "map"), "map", renderMap, errors),
      settle(api("/graph", null, "graph"), "connections", renderGraph, errors),
      settle(api("/people?limit=100", null, "people"), "people", renderPeople, errors),
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
    ])
      .then(function () {
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
      .filter(function (c) {
        return c.person;
      })
      .slice(0, 3);
    storyTop = cards.length ? cards[0].person : null;
    $("story-opps").innerHTML = cards.length
      ? cards
          .map(function (c, idx) {
            var person = c.person,
              o = c.opportunity || {},
              company = c.company || {};
            return (
              '<article class="person-preview"><div class="person-heading"><span class="avatar tone-' +
              idx +
              '" aria-hidden="true">' +
              esc(initials(person.name)) +
              '</span><div><div class="person-name">' +
              esc(person.name) +
              '</div><div class="person-role">' +
              esc(orUnknown(person.title)) +
              (company.name ? " · " + esc(company.name) : "") +
              '</div></div></div><div class="person-reason">' +
              esc(friendlyRationale(o.rationale || "Suggested for your goal")) +
              '</div><div class="preview-foot"><span class="score-label"><b>' +
              esc(o.score == null ? "—" : Math.round(o.score)) +
              '</b> relevance</span><button class="text-button" data-action="showpath" data-id="' +
              esc(person.id) +
              '">See why</button></div></article>'
            );
          })
          .join("")
      : emptyState(
          "Your next connections start with a goal.",
          "Choose the people you would like to meet.",
          "edit-goal",
          "Set my goal",
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
    $("story-antifomo").innerHTML =
      skips
        .map(function (s) {
          return (
            '<div class="skip"><div class="cat">' +
            esc(
              {
                outside_hours: "Outside planning hours",
                other_timezone: "In another time zone",
                time_conflict: "Schedule conflict",
                travel: "Travel time",
                low_score: "Lower relevance",
              }[s.category] || "Planning trade-off",
            ) +
            "</div>" +
            "<div><b>Skip:</b> " +
            esc(s.title) +
            " " +
            '<span class="muted">(' +
            esc(fmtTime(s.start_at, s.timezone)) +
            ")</span></div>" +
            '<div class="muted">' +
            esc(s.reason) +
            "</div>" +
            '<div class="gain">What you gain: ' +
            esc(s.gain) +
            "</div></div>"
          );
        })
        .join("") ||
      '<p class="muted">No events skipped' +
        (res && res.computed_by ? "" : " (Anti-FOMO agent unavailable)") +
        ".</p>";
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

  function renderBrightData(res) {
    var u = (res && res.usage) || {},
      ready = (res && res.ready) || {};
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
      "</span>";
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
        return api("/followup?person=" + encodeURIComponent(id), null, "people").then(function (draft) {
          var box = $("followup-" + id), next = draft.next_action || {}, link = safeUrl(next.url);
          if (!box) return;
          box.innerHTML = '<p class="small-text muted">Your draft · review before sending</p><pre class="followup-text">' + esc(draft.message) + '</pre><p class="small-text">' + esc(next.label || "") + (link ? ' <a href="' + esc(link) + '" target="_blank" rel="noopener noreferrer">Open profile</a>' : "") + (next.due_at ? ' · ' + esc(shortDate(String(next.due_at).slice(0,10))) : "") + '</p><button class="secondary" data-action="copy-followup" data-id="' + esc(id) + '">Copy draft</button>';
        });
      });
    } else if (action === "copy-followup") {
      var box = $("followup-" + id), text = box && box.querySelector(".followup-text");
      if (text && navigator.clipboard) navigator.clipboard.writeText(text.textContent).then(function () { toast("Draft copied."); }).catch(function () { toast("Copying is not available in this browser."); });
    } else if (action === "showpath" || action === "path") {
      if (action === "showpath") switchTab("graph");
      setTimeout(function () {
        highlightPath(id);
      }, 80);
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
