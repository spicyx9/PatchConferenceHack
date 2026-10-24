/* Conferge demo UI: plain JS, no build step. All data text is escaped before insertion. */
(function () {
  "use strict";

  var API = "/api/v1";
  var EVENT_TZ = "America/Los_Angeles";
  var STATUS_RANK = { ok: 0, degraded: 1, failed: 2 };
  var TYPE_COLORS = {
    User: "#ffffff",
    Goal: "#58a6ff",
    Person: "#3fb950",
    Event: "#f0b429",
    Company: "#bc8cff",
    Topic: "#8b949e",
    Conference: "#ff7b72",
    Meeting: "#39c5cf"
  };
  var OTHER_COLOR = "#6e7681";
  var COSE = { name: "cose", animate: false, nodeRepulsion: 400000, idealEdgeLength: 140, nodeOverlap: 40, componentSpacing: 120, padding: 30 };

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
    return value === null || value === undefined || value === "" ? "unknown" : value;
  }

  function safeUrl(url) {
    if (typeof url !== "string") return null;
    return /^https?:\/\//i.test(url) ? url : null;
  }

  function $(id) { return document.getElementById(id); }

  function sourceBadge(mode) {
    var m = mode || "unknown";
    var cls = m === "live" ? "live" : m === "fixture" ? "fixture" : "neutral";
    return '<span class="badge ' + cls + '">' + esc(m.toUpperCase()) + "</span>";
  }

  function statusBadge(status) {
    var s = status || "unknown";
    var cls = STATUS_RANK.hasOwnProperty(s) ? s : "neutral";
    return '<span class="badge ' + cls + '">' + esc(s.toUpperCase()) + "</span>";
  }

  // Events held in another timezone keep their own clock time, labelled with that zone.
  function zoneLabel(tz) {
    return tz && tz !== EVENT_TZ ? " (" + tz + ")" : "";
  }

  function fmtTime(iso, tz) {
    if (!iso) return "time unknown";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "time unknown";
    try {
      return new Intl.DateTimeFormat("en-US", {
        timeZone: tz || EVENT_TZ, weekday: "short", day: "2-digit", month: "short",
        hour: "2-digit", minute: "2-digit"
      }).format(d) + zoneLabel(tz);
    } catch (e) {
      return iso;
    }
  }

  function fmtHour(iso, tz) {
    if (!iso) return "?";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "?";
    try {
      return new Intl.DateTimeFormat("en-US", {
        timeZone: tz || EVENT_TZ, hour: "2-digit", minute: "2-digit"
      }).format(d) + zoneLabel(tz);
    } catch (e) {
      return iso;
    }
  }

  function fmtDay(day) {
    if (!day) return "day unknown";
    var d = new Date(day + "T12:00:00Z");
    if (isNaN(d.getTime())) return day;
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "UTC", weekday: "long", day: "numeric", month: "long"
    }).format(d);
  }

  function fmtUsd(value) {
    if (value === null || value === undefined) return "unknown";
    var n = Number(value);
    return isNaN(n) ? String(value) : "$" + n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  function showError(msg) {
    var el = $("error-banner");
    el.textContent = msg;
    el.classList.remove("hidden");
  }

  function clearError() {
    $("error-banner").classList.add("hidden");
  }

  // Fetch layer

  function api(path, options, key) {
    var opts = options || {};
    var init = { method: opts.method || "GET", headers: { Accept: "application/json" } };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    return fetch(API + path, init).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (!res.ok) {
          var detail = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : res.statusText;
          throw new Error((init.method) + " " + path + ": HTTP " + res.status + " " + detail);
        }
        if (data && key) {
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
    var modes = {};
    var worst = null;
    var collected = null;
    var warnings = {};
    Object.keys(envelopes).forEach(function (k) {
      var env = envelopes[k];
      if (!env) return;
      if (env.data_source) modes[env.data_source] = true;
      if (env.status && STATUS_RANK.hasOwnProperty(env.status)) {
        if (worst === null || STATUS_RANK[env.status] > STATUS_RANK[worst]) worst = env.status;
      }
      if (env.collected_at && (!collected || env.collected_at > collected)) collected = env.collected_at;
      (env.warnings || []).forEach(function (w) { warnings[w] = true; });
    });
    var list = Object.keys(modes);
    var mode = list.length === 1 ? list[0] : list.length === 0 ? "unknown" : "mixed";
    var badge = $("badge-source");
    badge.className = "badge " + (mode === "live" ? "live" : mode === "fixture" ? "fixture" : "neutral");
    badge.textContent = mode.toUpperCase();
    badge.title = "data_source aggregated over the latest responses";

    var st = $("badge-status");
    st.className = "badge " + (worst || "neutral");
    st.textContent = (worst || "unknown").toUpperCase();

    $("collected-at").textContent = collected ? collected : "unknown";

    var wl = Object.keys(warnings).sort();
    $("warnings-count").textContent = String(wl.length);
    $("warnings-list").innerHTML = wl.map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("");
  }

  // Renderers

  var DEFAULT_GOALS_NOTE = "No role recognised in the text: default goals.";

  function usesDefaultGoals(goals) {
    return goals.some(function (g) {
      return (g.tags || []).some(function (t) { return t.indexOf("default:") === 0; });
    });
  }

  function renderGoals(plan) {
    var goals = (plan && plan.goals) || [];
    $("goals-list").innerHTML = (usesDefaultGoals(goals) ? '<p class="muted">' + DEFAULT_GOALS_NOTE + "</p>" : "") +
      (goals.length ? goals.map(function (g) {
      var w = typeof g.priority === "number" ? g.priority : null;
      var pct = w === null ? 0 : Math.round(w * 100);
      return '<div class="goal"><span class="weight">' + esc(w === null ? "unknown" : w.toFixed(2)) +
        '</span><span class="bar"><span style="width:' + pct + '%"></span></span><span>' +
        esc(g.description) + ' <span class="muted small-text">' + esc((g.target_roles || []).join(", ")) +
        "</span></span></div>";
    }).join("") : '<p class="muted">No goal recognized.</p>');
    $("computed-by").textContent = plan ? "Computed by: " + orUnknown(plan.computed_by) +
      (plan.scenario_id ? " | active scenario: " + plan.scenario_id : "") : "";
  }

  function roiTile(name, value) {
    var unknown = value === null || value === undefined;
    return '<div class="roi-tile"><div class="value' + (unknown ? " unknown" : "") + '">' +
      esc(unknown ? "unknown" : value) + '</div><div class="name">' + esc(name) + "</div></div>";
  }

  // One value per tile: a count or a formatted amount; null stays "unknown", never 0.
  function setRoiFigure(id, value) {
    var el = $(id);
    if (!el) return;
    var unknown = value === null || value === undefined;
    el.textContent = unknown ? "unknown" : String(value);
    el.classList.toggle("unknown", unknown);
  }

  function renderRoi(roi) {
    if (!roi) { $("roi-grid").innerHTML = '<p class="muted">ROI unavailable.</p>'; return; }
    var spendKnown = roi.spend_usd !== null && roi.spend_usd !== undefined;
    var spend = spendKnown ? fmtUsd(roi.spend_usd) : null;
    // Dashboard tab (same figures, grid rebuilt).
    $("roi-grid").innerHTML =
      roiTile("Flight + hotel spend", spend) +
      roiTile("Meetings", roi.meetings) +
      roiTile("Qualified contacts", roi.qualified_contacts) +
      roiTile("Opportunities (score >= 30)", roi.opportunities);
    $("roi-note").textContent = "Budget: " + fmtUsd(roi.budget_usd) + (roi.spend_note ? " | " + roi.spend_note : "");
    // Demo tab, step 7: fixed ids so the figures can be checked after each /met, /attended, /skipped.
    setRoiFigure("roi-spend", spend);
    setRoiFigure("roi-meetings", roi.meetings);
    setRoiFigure("roi-qualified", roi.qualified_contacts);
    setRoiFigure("roi-opportunities", roi.opportunities);
    if ($("roi-spend-note")) $("roi-spend-note").textContent = spendKnown ? "" : (roi.spend_note || "");
  }

  function refreshRoi() {
    return api("/roi", null, "roi").then(renderRoi).catch(function (e) { showError("ROI: " + e.message); });
  }

  function planItems(plan) {
    var out = [];
    ((plan && plan.plan && plan.plan.days) || []).forEach(function (d) {
      (d.items || []).forEach(function (i) { out.push(i); });
    });
    return out;
  }

  function renderNextActions(plan) {
    var items = planItems(plan).filter(function (i) { return !i.attended; }).slice(0, 5);
    $("next-actions").innerHTML = items.length ? items.map(function (i) {
      var who = (i.people || []).map(function (p) { return p.name; }).join(", ");
      return "<li><b>" + esc(fmtTime(i.start_at, i.timezone)) + "</b> " + esc(i.title) +
        ' <span class="muted">(' + esc(orUnknown(i.venue)) + ")</span>" +
        (who ? '<div class="muted small-text">Meet: ' + esc(who) + "</div>" : "") + "</li>";
    }).join("") : '<li class="muted">No action planned.</li>';
  }

  function renderPlan(plan) {
    var days = (plan && plan.plan && plan.plan.days) || [];
    $("plan-days").innerHTML = days.length ? days.map(function (d) {
      return '<div class="day"><h3>' + esc(fmtDay(d.day)) + '</h3>' + (d.items || []).map(function (i) {
        var tz = i.timezone || EVENT_TZ;
        return '<div class="event-item ' + esc(i.status) + '"><span class="time">' +
          esc(fmtHour(i.start_at, tz) + " - " + fmtHour(i.end_at, tz)) + '</span><span class="title">' +
          esc(i.title) + '<br><span class="muted small-text">' + esc(orUnknown(i.venue)) +
          (i.room ? ", " + esc(i.room) : "") + " | score " + esc(i.score) + " | " + esc(i.event_type) +
          "</span></span>" + sourceBadge(i.source_mode) + '<span class="actions">' +
          '<button class="small' + (i.attended ? " on" : "") + '" data-action="attended" data-id="' + esc(i.event_id) + '">' +
          (i.attended ? "Attended" : "Attend") + "</button>" +
          '<button class="small" data-action="skipped" data-id="' + esc(i.event_id) + '">Skip</button>' +
          "</span></div>";
      }).join("") + "</div>";
    }).join("") : '<p class="muted">No event planned.</p>';

    var conflicts = (plan && plan.plan && plan.plan.conflicts) || [];
    $("conflicts").innerHTML = conflicts.length ? conflicts.map(function (c) {
      var miss = c.what_you_miss || [];
      return '<div class="conflict"><div><b>' + esc(fmtDay(c.day)) + ":</b> " + esc(c.verdict) + "</div>" +
        '<div class="small-text">Winner: ' + esc(c.winner && c.winner.title) + " | Loser: " + esc(c.loser && c.loser.title) + "</div>" +
        "<div><b>What you miss:</b>" + (miss.length ? "<ul>" + miss.map(function (m) {
          return "<li>" + esc(m.name) + ' <span class="muted">(score ' + esc(m.score) + ")</span></li>";
        }).join("") + "</ul>" : ' <span class="muted">nobody from your list</span>') + "</div></div>";
    }).join("") : '<p class="muted">No conflict.</p>';

    var excluded = (plan && plan.plan && plan.plan.excluded) || [];
    $("excluded").innerHTML = excluded.length ? excluded.map(function (x) {
      return "<li>" + esc(x.title) + ' <span class="badge failed">' + esc(x.reason) + "</span>" +
        (x.detail ? ' <span class="muted small-text">' + esc(x.detail) + "</span>" : "") + "</li>";
    }).join("") : '<li class="muted">None.</li>';
  }

  function renderEvents(ev) {
    var items = (ev && ev.items) || [];
    $("events-list").innerHTML = items.length ? "<table><thead><tr><th>When (LA)</th><th>Title</th><th>Type</th>" +
      "<th>Venue</th><th>Status</th><th>Score</th><th>Source</th></tr></thead><tbody>" + items.map(function (e) {
        var venue = e.venue && e.venue.name ? e.venue.name : null;
        var link = safeUrl(e.source_url) || safeUrl(e.registration_url);
        return "<tr><td>" + esc(fmtTime(e.start_at, e.timezone)) + "</td><td>" +
          (link ? '<a href="' + esc(link) + '" target="_blank" rel="noopener noreferrer">' + esc(e.title) + "</a>" : esc(e.title)) +
          (e.attended ? ' <span class="badge ok">attended</span>' : "") +
          (e.skipped ? ' <span class="badge degraded">skipped</span>' : "") +
          "</td><td>" + esc(e.event_type) + "</td><td>" + esc(orUnknown(venue)) + "</td><td>" + esc(orUnknown(e.status)) +
          "</td><td>" + esc(e.score) + "</td><td>" + sourceBadge(e.source_mode) + "</td></tr>";
      }).join("") + "</tbody></table>" : '<p class="muted">No event.</p>';
  }

  function renderTravel(t) {
    if (!t) return;
    var legs = t.itinerary || [];
    $("itinerary").innerHTML = legs.length ? legs.map(function (l) {
      if (l.kind === "flight") {
        return "<li><b>Flight</b> " + esc(l.date) + ": " + esc(l.from) + " to " + esc(l.to) +
          ' <span class="muted">departs ' + esc(orUnknown(l.departure_at)) + ", arrives " + esc(orUnknown(l.arrival_at)) +
          ", carrier " + esc(orUnknown(l.carrier)) + '</span> <span class="badge neutral">price ' + esc(orUnknown(l.price_status)) +
          "</span> " + sourceBadge(l.source_mode) + "</li>";
      }
      return "<li><b>Stay</b> " + esc(l.name) + ' <span class="muted">' + esc(orUnknown(l.check_in)) + " to " +
        esc(orUnknown(l.check_out)) + '</span> <span class="badge neutral">price ' + esc(orUnknown(l.price_status)) + "</span> " +
        sourceBadge(l.source_mode) + "</li>";
    }).join("") : '<li class="muted">No leg.</li>';

    var props = t.proposals || [];
    $("proposals").innerHTML = props.length ? props.map(function (p) {
      return '<div class="event-item"><span class="title">' + esc(p.text) +
        '<br><span class="muted small-text">' + esc(p.reason || "") + "</span></span>" +
        (p.accepted ? '<span class="badge ok">Noted</span>'
          : '<button class="small primary" data-action="accept" data-id="' + esc(p.id) + '">Note</button>') + "</div>";
    }).join("") : '<p class="muted">No proposal.</p>';

    var b = t.budget || {};
    $("budget").innerHTML = "<table><tbody>" +
      "<tr><th>Budget</th><td>" + esc(fmtUsd(b.budget_usd)) + " " + sourceBadge(b.source_mode) + "</td></tr>" +
      "<tr><th>Flights</th><td>" + esc(fmtUsd(b.flights_usd)) + "</td></tr>" +
      "<tr><th>Lodging</th><td>" + esc(fmtUsd(b.lodging_usd)) + "</td></tr>" +
      "<tr><th>Remaining</th><td>" + esc(fmtUsd(b.remaining_usd)) + "</td></tr>" +
      "</tbody></table>" + (b.note ? '<p class="muted small-text">' + esc(b.note) + "</p>" : "");
  }

  function renderStays(s) {
    var items = (s && s.items) || [];
    $("stays").innerHTML = items.length ? items.map(function (st) {
      var link = safeUrl(st.booking_url);
      var dist = st.distance_to_venue_m === null || st.distance_to_venue_m === undefined ? "unknown"
        : st.distance_to_venue_m + " m" + (st.distance_is_straight_line_estimate ? " (straight line)" : "");
      var priceCls = st.price_status === "verified" ? "ok" : "neutral";
      return '<div class="card"><div class="row"><b>' + esc(st.name) + "</b></div>" +
        '<div class="row"><span class="badge ' + priceCls + '">price ' + esc(orUnknown(st.price_status)) + "</span>" +
        '<span class="badge neutral">availability ' + esc(orUnknown(st.availability)) + "</span>" + sourceBadge(st.source_mode) + "</div>" +
        '<div class="field"><b>Type:</b> ' + esc(orUnknown(st.lodging_type)) + "</div>" +
        '<div class="field"><b>Total:</b> ' + esc(st.total_price === null || st.total_price === undefined ? "unknown" :
          st.total_price + " " + (st.currency || "")) + "</div>" +
        '<div class="field"><b>Distance to venue:</b> ' + esc(dist) + "</div>" +
        '<div class="field"><b>Dates:</b> ' + esc(orUnknown(st.check_in)) + " to " + esc(orUnknown(st.check_out)) + "</div>" +
        (link ? '<div class="field"><a href="' + esc(link) + '" target="_blank" rel="noopener noreferrer">Book</a></div>' : "") +
        "</div>";
    }).join("") : '<p class="muted">No stay.</p>';
  }

  function markerColor(kind, planned) {
    if (kind === "conference") return "#ff7b72";
    if (kind === "stay") return "#bc8cff";
    return planned ? "#f0b429" : "#6e7681";
  }

  function routeKindLabel(polylines) {
    var kinds = {};
    (polylines || []).forEach(function (p) { if (p && p.kind) kinds[p.kind] = true; });
    if (kinds.straight_line_order_of_visits) return "straight lines, not routes";
    return Object.keys(kinds).join(", ");
  }

  function renderMap(m) {
    lastMapData = m;
    var el = $("map");
    var kindEl = $("map-kind");
    if (kindEl) {
      var label = routeKindLabel(m && m.polylines);
      kindEl.textContent = label;
      kindEl.className = label ? "badge neutral" : "hidden";
    }
    if (typeof L === "undefined") {
      el.innerHTML = '<p class="muted" style="padding:1rem">Leaflet not loaded. Points: ' +
        esc(((m && m.markers) || []).map(function (x) { return x.label; }).join(", ")) + "</p>";
      return;
    }
    if (!map) {
      map = L.map(el).setView([37.79, -122.42], 13);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, attribution: "&copy; OpenStreetMap contributors"
      }).addTo(map);
    }
    if (mapLayer) mapLayer.remove();
    mapLayer = L.layerGroup().addTo(map);
    var bounds = [];
    var dayColors = ["#58a6ff", "#3fb950", "#f0b429", "#ff7b72", "#bc8cff"];
    ((m && m.polylines) || []).forEach(function (p, idx) {
      if (!p.points || p.points.length < 2) return;
      L.polyline(p.points, { color: dayColors[idx % dayColors.length], weight: 4, opacity: 0.8, dashArray: "6 6" })
        .bindTooltip("Day " + esc(p.day) + (p.kind === "straight_line_order_of_visits" ? ", straight line" : "")).addTo(mapLayer);
    });
    ((m && m.markers) || []).forEach(function (mk) {
      if (typeof mk.lat !== "number" || typeof mk.lng !== "number") return;
      bounds.push([mk.lat, mk.lng]);
      L.circleMarker([mk.lat, mk.lng], {
        radius: mk.kind === "conference" ? 12 : 9, color: "#0d1117", weight: 2,
        fillColor: markerColor(mk.kind, mk.planned), fillOpacity: 0.95
      }).bindPopup("<b>" + esc(mk.label) + "</b><br>" + esc(mk.kind) +
        (mk.planned === false ? " (not planned)" : "") + "<br>precision: " + esc(orUnknown(mk.precision)))
        .addTo(mapLayer);
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30] });
  }

  function renderLegend(types) {
    $("graph-legend").innerHTML = types.map(function (t) {
      return '<span><span class="swatch" style="background:' + (TYPE_COLORS[t] || OTHER_COLOR) + '"></span>' + esc(t) + "</span>";
    }).join("");
  }

  function edgeDetail(e) {
    return "<b>" + esc(e.type) + "</b>: " + esc(e.source) + " to " + esc(e.target) +
      "<br>Evidence: " + esc(orUnknown(e.evidence_source)) + " | confidence " + esc(orUnknown(e.confidence)) +
      " | observed " + esc(orUnknown(e.observed_at));
  }

  function renderGraph(g) {
    var nodes = ((g && g.nodes) || []).slice(0, 400);
    var keep = {};
    nodes.forEach(function (n) { keep[n.id] = true; });
    var edges = ((g && g.edges) || []).filter(function (e) { return keep[e.source] && keep[e.target]; });
    var backend = $("graph-backend");
    backend.textContent = orUnknown(g && g.backend);
    backend.className = "badge " + (g && g.backend === "falkordb" ? "ok" : "neutral");
    var types = [];
    nodes.forEach(function (n) { if (types.indexOf(n.type) < 0) types.push(n.type); });
    renderLegend(types);

    if (typeof cytoscape === "undefined") {
      $("graph").classList.add("hidden");
      var fb = $("graph-fallback");
      fb.classList.remove("hidden");
      fb.innerHTML = '<p class="muted">cytoscape.js not loaded: plain list.</p><h3>Nodes (' + nodes.length + ")</h3><ul>" +
        nodes.map(function (n) {
          return "<li>" + esc(n.type) + ": " + esc(n.label) + " " + sourceBadge(n.source_mode) +
            (n.type === "Person" ? ' <button class="small" data-action="path" data-id="' + esc(n.id) + '">Path</button>' : "") + "</li>";
        }).join("") + "</ul><h3>Edges (" + edges.length + ")</h3><ul>" +
        edges.map(function (e) { return "<li>" + edgeDetail(e) + "</li>"; }).join("") + "</ul>";
      return;
    }

    var elements = nodes.map(function (n) {
      return { group: "nodes", data: { id: n.id, label: n.label, type: n.type, source_mode: n.source_mode,
        color: TYPE_COLORS[n.type] || OTHER_COLOR } };
    }).concat(edges.map(function (e) {
      return { group: "edges", data: { id: e.id, source: e.source, target: e.target, type: e.type,
        evidence_source: e.evidence_source, confidence: e.confidence, observed_at: e.observed_at } };
    }));

    if (cy) cy.destroy();
    cy = cytoscape({
      container: $("graph"),
      elements: elements,
      style: [
        { selector: "node", style: {
          "background-color": "data(color)", label: "data(label)", color: "#f0f3f6", "font-size": 13,
          "text-outline-color": "#0b0f14", "text-outline-width": 3, width: 26, height: 26,
          "text-valign": "bottom", "text-margin-y": 4, "text-max-width": 160, "text-wrap": "ellipsis"
        } },
        { selector: 'node[type = "User"]', style: { width: 44, height: 44, "font-size": 18, "font-weight": "bold" } },
        { selector: 'node[type = "Person"]', style: { width: 32, height: 32 } },
        { selector: "edge", style: {
          width: 1.5, "line-color": "#3a434e", "target-arrow-color": "#3a434e",
          "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.8
        } },
        { selector: ".dim", style: { opacity: 0.15 } },
        { selector: "node.path", style: { "border-width": 5, "border-color": "#ffffff", opacity: 1 } },
        { selector: "edge.path", style: { width: 6, "line-color": "#58a6ff", "target-arrow-color": "#58a6ff", opacity: 1,
          label: "data(type)", color: "#cfe5ff", "font-size": 12, "text-outline-color": "#0b0f14", "text-outline-width": 3 } },
        { selector: "edge.selected-edge", style: { width: 5, "line-color": "#f0b429", "target-arrow-color": "#f0b429" } }
      ],
      layout: COSE
    });

    cy.on("tap", "node", function (evt) {
      var d = evt.target.data();
      if (d.type === "Person") {
        highlightPath(d.id);
      } else {
        clearHighlight();
        $("graph-detail").innerHTML = "<b>" + esc(d.type) + "</b>: " + esc(d.label) + " " + sourceBadge(d.source_mode) +
          '<br><span class="mono">' + esc(d.id) + "</span>";
      }
    });
    cy.on("tap", "edge", function (evt) {
      cy.edges().removeClass("selected-edge");
      evt.target.addClass("selected-edge");
      $("graph-detail").innerHTML = edgeDetail(evt.target.data());
    });
    cy.on("tap", function (evt) {
      if (evt.target === cy) { clearHighlight(); $("graph-detail").textContent = "No selection."; }
    });
  }

  function clearHighlight() {
    if (!cy) return;
    cy.elements().removeClass("dim path selected-edge");
  }

  function highlightPath(personId) {
    api("/graph/path?person=" + encodeURIComponent(personId), null, "graph_path").then(function (res) {
      var nodeIds = res.node_ids || [];
      var edgeIds = res.edge_ids || [];
      var labels = (res.path || []).map(function (s) {
        return s.node ? esc(s.node.label || s.node.id) : s.edge ? '<span class="muted">' + esc(s.edge.type) + "</span>" : "";
      });
      $("graph-detail").innerHTML = "<b>Path (" + esc(res.hops) + " hops):</b> " + labels.join(" &rarr; ") +
        "<br>" + (res.path || []).filter(function (s) { return s.edge; }).map(function (s) { return edgeDetail(s.edge); }).join("<br>");
      if (cy) {
        cy.elements().removeClass("path selected-edge").addClass("dim");
        nodeIds.forEach(function (id) { cy.getElementById(id).removeClass("dim").addClass("path"); });
        edgeIds.forEach(function (id) { cy.getElementById(id).removeClass("dim").addClass("path"); });
      }
    }).catch(function (err) {
      showError("Path not found: " + err.message);
    });
  }

  function renderPeople(p) {
    var all = (p && p.items) || [];
    // Top 10 still to meet, then the people already met (they sink in the ranking but keep their follow-up).
    var items = all.filter(function (c) { return !c.met; }).slice(0, 10).concat(all.filter(function (c) { return c.met; }));
    $("people-cards").innerHTML = items.length ? items.map(function (c) {
      var o = c.opportunity || {};
      var person = c.person || {};
      var company = c.company || {};
      var presence = o.presence || "unknown";
      var presCls = presence === "confirmed" ? "confirmed" : presence === "probable" ? "probable" : "unknown";
      var pid = person.id || (o.person_ids && o.person_ids[0]) || "";
      return '<div class="card' + (c.met ? " is-met" : "") + '">' +
        '<div class="row"><b style="font-size:1.1rem">' + esc(person.name || o.title) + "</b>" +
        '<span class="score">' + esc(orUnknown(o.score)) + "</span></div>" +
        '<div class="row"><span class="badge ' + presCls + '">' + esc(presence) + "</span>" +
        (c.met ? '<span class="badge met">met</span>' : "") + sourceBadge(modeOfEvidence(o.evidence)) + "</div>" +
        '<div class="field"><b>Title:</b> ' + esc(orUnknown(person.title)) + "</div>" +
        '<div class="field"><b>Company:</b> ' + esc(orUnknown(company.name)) + "</div>" +
        '<div class="field"><b>Why:</b> ' + esc(orUnknown(o.rationale)) + "</div>" +
        '<div class="field"><b>Where:</b> ' + esc(orUnknown(o.where)) + "</div>" +
        '<div class="field"><b>Opener:</b> ' + esc(orUnknown(o.opener)) + "</div>" +
        (c.met_note ? '<div class="field"><b>Note:</b> ' + esc(c.met_note) + "</div>" : "") +
        (c.met ? '<div class="followup" id="followup-' + esc(pid) + '"></div>' : "") +
        '<div class="row">' + (c.met ? '<button class="small primary" data-action="followup" data-id="' + esc(pid) + '">Follow up</button>'
          : '<button class="small primary" data-action="met" data-id="' + esc(pid) + '">Met</button>') +
        '<button class="small" data-action="showpath" data-id="' + esc(pid) + '">Show path</button></div>' +
        "</div>";
    }).join("") : '<p class="muted">No people.</p>';
  }

  function modeOfEvidence(ev) {
    var modes = {};
    (ev || []).forEach(function (e) { if (e && e.source_mode) modes[e.source_mode] = true; });
    var l = Object.keys(modes);
    return l.length === 1 ? l[0] : l.length === 0 ? "unknown" : "mixed";
  }

  function renderDiff(res) {
    var d = res.diff || {};
    function section(name, cls, list, fmt) {
      return '<div class="diff-section ' + cls + '"><span class="tag">' + esc(name) + " (" + (list || []).length + "):</span>" +
        ((list || []).length ? "<ul>" + list.map(fmt).join("") + "</ul>" : '<span class="muted">none</span>') + "</div>";
    }
    $("diff-body").innerHTML = "<p><b>" + esc(res.scenario && res.scenario.label) + "</b></p>" +
      section("Added", "diff-added", d.added, function (x) { return "<li>" + esc(x.title || x.event_id) + "</li>"; }) +
      section("Removed", "diff-removed", d.removed, function (x) { return "<li>" + esc(x.title || x.event_id) + "</li>"; }) +
      section("Changed", "diff-changed", d.changed, function (x) {
        var b = x.before || {}, a = x.after || {};
        return "<li>" + esc(x.event_id) + ": " + esc(fmtTime(b.start_at)) + " (" + esc(b.status) + ") to " +
          esc(fmtTime(a.start_at)) + " (" + esc(a.status) + ")</li>";
      }) +
      section("Replanning", "diff-replan", res.replan, function (x) {
        var r = x.replacement, p = x.graph_path;
        return "<li><b>Removed:</b> " + esc(x.removed.title) +
          (r ? "<br><b>Replaced by:</b> " + esc(r.title) + " (" + esc(fmtTime(r.start_at)) + ")" : "") +
          "<br><b>Reason:</b> " + esc(x.reason) +
          (p ? "<br><b>Path:</b> " + esc(p.nodes.join(" > ")) + (p.explanation ? '<br><span class="muted">' + esc(p.explanation) + "</span>" : "") : "") +
          "</li>";
      }) + '<p class="muted small-text">Simulated change, not a real update of the source.</p>';
    $("diff-panel").classList.remove("hidden");
  }

  // Loading

  function settle(promise, label, render, errors) {
    return promise.then(function (data) {
      try { render(data); } catch (e) { errors.push(label + ": render " + e.message); }
    }).catch(function (e) { errors.push(label + ": " + e.message); });
  }

  function refreshAll() {
    var errors = [];
    return Promise.all([
      settle(api("/plan", null, "plan"), "plan", function (p) { renderGoals(p); renderNextActions(p); renderPlan(p); }, errors),
      settle(api("/roi", null, "roi"), "roi", renderRoi, errors),
      settle(api("/events", null, "events"), "events", renderEvents, errors),
      settle(api("/travel", null, "travel"), "travel", renderTravel, errors),
      settle(api("/stays", null, "stays"), "stays", renderStays, errors),
      settle(api("/travel/map", null, "map"), "map", renderMap, errors),
      settle(api("/graph", null, "graph"), "graph", renderGraph, errors),
      settle(api("/people?limit=100", null, "people"), "people", renderPeople, errors),
      settle(api("/scenarios", null, "scenarios"), "scenarios", renderScenarios, errors)
    ]).then(loadAgentsState).then(function () {
      if (errors.length) showError("Load error: " + errors.join(" | "));
    });
  }

  function renderScenarios(s) {
    var sel = $("scenario-select");
    var current = sel.value;
    var items = (s && s.items) || [];
    sel.innerHTML = items.map(function (it) {
      return '<option value="' + esc(it.id) + '">' + esc(it.label) + "</option>";
    }).join("");
    if (current && items.some(function (it) { return it.id === current; })) sel.value = current;
    else if (s && s.active) sel.value = s.active;
  }

  function withBusy(button, fn) {
    if (button) button.disabled = true;
    clearError();
    return Promise.resolve().then(fn).catch(function (e) {
      showError(e.message || String(e));
    }).then(function () {
      if (button) button.disabled = false;
    });
  }

  function mutate(path, body, key) {
    return api(path, { method: "POST", body: body }, key || "plan").then(function (res) {
      return refreshAll().then(function () { return res; });
    });
  }

  // Demo story: goal -> opportunities -> plan -> anti-FOMO -> change -> meeting

  var storyMap = null;
  var storyMapLayer = null;
  var storyTop = null;

  function pathHtml(steps) {
    var nodes = (steps || []).filter(function (s) { return s.node; }).map(function (s) {
      return '<span class="path-node t-' + esc(s.node.type || "Node") + '">' + esc(s.node.label || s.node.id) + "</span>";
    });
    return '<div class="path">' + nodes.join('<span class="path-arrow">&rarr;</span>') + "</div>";
  }

  function fmtMs(ms) {
    if (ms === null || ms === undefined) return "never";
    return fmtTime(new Date(Number(ms)).toISOString(), EVENT_TZ);
  }

  function renderAgentsState(res) {
    var box = $("agents-state");
    if (!box) return;
    if (!res || res.backend !== "falkordb") {
      $("agents-plan-version").textContent = "?";
      box.innerHTML = '<p class="muted">FalkorDB unreachable: no shared state.</p>';
      return;
    }
    var plan = res.plan || {};
    $("agents-plan-version").textContent = "v" + (plan.plan_version || 0);
    var rows = (res.agents || []).map(function (a) {
      return "<tr><td><b>" + esc(a.agent) + "</b></td><td>" + esc(a.writes) + "</td><td>" + esc(fmtMs(a.last_at_ms)) + "</td></tr>";
    }).join("");
    var open = res.browser_url && safeUrl(res.browser_url)
      ? '<a class="btn primary" target="_blank" rel="noopener" href="' + esc(safeUrl(res.browser_url)) + '">Show in FalkorDB Browser</a> '
      : "";
    box.innerHTML = '<table><thead><tr><th>Agent</th><th>Writes</th><th>Last (at_ms)</th></tr></thead><tbody>' +
      rows + "</tbody></table>" +
      '<p class="small-text">' + esc((plan.items || []).length) + " events in the plan (PLANS), " +
      esc((res.skips || []).length) + " skipped (SKIPS), " + esc((res.changes || []).length) + " changes (Change).</p>" +
      '<div class="cypher-panel">' + open +
      '<button data-action="copy-agents-cypher" class="small">Copy query</button>' +
      '<pre id="agents-cypher" class="cypher">' + esc(res.cypher) + "</pre></div>";
  }

  function loadAgentsState() {
    return api("/agents/state", null, "agents").then(renderAgentsState).catch(function () { renderAgentsState(null); });
  }

  function cypherPanel(res) {
    var open = res.browser_url && safeUrl(res.browser_url)
      ? '<a class="btn primary" target="_blank" rel="noopener" href="' + esc(safeUrl(res.browser_url)) + '">Show in FalkorDB Browser</a> '
      : "";
    return '<div class="cypher-panel">' + open +
      '<button data-action="copy-cypher" class="small">Copy query</button>' +
      '<pre id="story-cypher" class="cypher">' + esc(res.cypher) + "</pre></div>";
  }

  function renderStoryGoal(plan) {
    $("story-goal").textContent = (plan && plan.goal_text) || "";
    var storyGoals = (plan && plan.goals) || [];
    $("story-goals").innerHTML = (usesDefaultGoals(storyGoals) ? '<p class="muted">' + DEFAULT_GOALS_NOTE + "</p>" : "") +
      storyGoals.map(function (g) {
        return '<span class="chip">' + esc(g.description || g.id) + (g.priority ? " (" + esc(g.priority) + ")" : "") + "</span>";
      }).join("");
  }

  function renderStoryOpps(people) {
    var cards = ((people && people.items) || []).filter(function (c) { return c.person; }).slice(0, 3);
    storyTop = cards.length ? cards[0].person : null;
    $("story-opps").innerHTML = cards.map(function (c, i) {
      var p = c.person;
      return '<div class="opp"><div class="opp-name">' + (i + 1) + ". " + esc(p.name) +
        (p.title ? ' <span class="muted">' + esc(p.title) + "</span>" : "") + "</div>" +
        '<div id="story-path-' + i + '" class="muted">path...</div></div>';
    }).join("") || '<p class="muted">No people.</p>';
    return Promise.all(cards.map(function (c, i) {
      return api("/graph/path?person=" + encodeURIComponent(c.person.id), null, "graph_path").then(function (res) {
        $("story-path-" + i).innerHTML = pathHtml(res.path) +
          (res.explanation ? '<div class="explain">' + esc(res.explanation) + "</div>" : "") +
          '<div class="explain">source: ' + esc(res.backend || "graph") + " / " + esc(res.data_source) +
          (res.signature ? " / signature: " + esc(res.signature) : "") + "</div>" +
          (i === 0 && res.cypher ? cypherPanel(res) : "");
      }).catch(function () { $("story-path-" + i).textContent = "no path in the graph"; });
    }));
  }

  function renderStoryPlan(plan, mapData) {
    var days = ((plan && plan.plan && plan.plan.days) || []).filter(function (d) { return (d.items || []).length; });
    $("story-plan").innerHTML = days.map(function (d) {
      return '<div class="story-plan-day"><h3>' + esc(fmtDay(d.day)) + "</h3><ul>" + d.items.slice(0, 4).map(function (i) {
        return "<li><b>" + esc(fmtHour(i.start_at, i.timezone)) + "</b> " + esc(i.title) + "</li>";
      }).join("") + (d.items.length > 4 ? '<li class="muted">+ ' + (d.items.length - 4) + " more</li>" : "") + "</ul></div>";
    }).join("") || '<p class="muted">Empty plan.</p>';
    if (typeof L === "undefined") return;
    if (!storyMap) {
      storyMap = L.map($("story-map")).setView([37.79, -122.42], 13);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, attribution: "&copy; OpenStreetMap contributors"
      }).addTo(storyMap);
    }
    if (storyMapLayer) storyMapLayer.remove();
    storyMapLayer = L.layerGroup().addTo(storyMap);
    var bounds = [];
    ((mapData && mapData.markers) || []).forEach(function (mk) {
      if (mk.kind === "stay" || (mk.kind !== "conference" && !mk.planned)) return;
      if (typeof mk.lat !== "number" || typeof mk.lng !== "number") return;
      bounds.push([mk.lat, mk.lng]);
      L.circleMarker([mk.lat, mk.lng], {
        radius: mk.kind === "conference" ? 14 : 11, color: "#0d1117", weight: 2,
        fillColor: markerColor(mk.kind, true), fillOpacity: 0.95
      }).bindTooltip(esc(mk.label), { permanent: bounds.length <= 6, direction: "top" }).addTo(storyMapLayer);
    });
    setTimeout(function () {
      storyMap.invalidateSize();
      if (bounds.length) storyMap.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
    }, 50);
  }

  function renderStoryAntifomo(res) {
    var skips = (res && res.skips) || [];
    $("story-antifomo").innerHTML = skips.map(function (s) {
      return '<div class="skip"><div class="cat">' + esc(s.category_label) + "</div>" +
        "<div><b>Skipped:</b> " + esc(s.title) + " " + '<span class="muted">(' + esc(fmtTime(s.start_at, s.timezone)) + ")</span></div>" +
        '<div class="muted">' + esc(s.reason) + "</div>" +
        '<div class="gain">Gained: ' + esc(s.gain) + "</div></div>";
    }).join("") || '<p class="muted">No event skipped' + (res && res.computed_by ? "" : " (anti-FOMO agent unavailable)") + ".</p>";
  }

  function renderStoryDiff(res) {
    var replan = (res && res.replan) || [];
    var d = (res && res.diff) || {};
    var rows = replan.map(function (r) {
      var html = '<div class="diff-row removed"><span class="tag-r">REMOVED</span> ' + esc(r.removed.title) + "</div>";
      if (r.replacement) {
        html += '<div class="diff-row added"><span class="tag-a">ADDED</span> ' + esc(r.replacement.title) +
          ' <span class="muted">(' + esc(fmtTime(r.replacement.start_at)) + ")</span></div>";
      }
      html += '<div class="explain"><b>Reason:</b> ' + esc(r.reason) + "</div>";
      if (r.graph_path) {
        html += pathHtml(r.graph_path.nodes.map(function (n, i) {
          return { node: { label: n, type: i === r.graph_path.nodes.length - 1 ? "Person" : (i === 0 ? "Goal" : "Opportunity") } };
        }));
      }
      return html;
    });
    var added = (d.added || []).filter(function (a) {
      return !replan.some(function (r) { return r.replacement && r.replacement.event_id === a.event_id; });
    });
    rows = rows.concat(added.map(function (a) {
      return '<div class="diff-row added"><span class="tag-a">ADDED</span> ' + esc(a.title) + "</div>";
    }));
    $("story-diff").innerHTML = "<p><b>" + esc(res.scenario && res.scenario.label) + "</b></p>" + rows.join("") +
      '<p class="muted small-text">Simulated change, not a real update of the source.</p>';
  }

  function renderStoryMet(before, res, after) {
    var names = function (p) {
      return ((p && p.items) || []).filter(function (c) { return c.person; }).slice(0, 3)
        .map(function (c) { return esc(c.person.name); }).join(", ");
    };
    $("story-met").innerHTML = '<p class="met-ok">Meeting with ' + esc(res.person_name) + " recorded (" +
      esc(res.persisted === "falkordb" ? "FalkorDB" : "memory") + ")</p>" +
      "<p><b>Top 3 before:</b> " + names(before) + "</p><p><b>Top 3 after:</b> " + names(after) + "</p>";
  }

  function storyMetButton() {
    if (!storyTop) { $("story-met").innerHTML = '<p class="muted">No people.</p>'; return; }
    $("story-met").innerHTML = '<button id="story-met-btn" class="primary big-btn">I met ' +
      esc(storyTop.name) + "</button>";
  }

  function renderBrightData(res) {
    var u = (res && res.usage) || {}, ready = (res && res.ready) || {};
    function part(api, label) {
      return esc(label) + " " + esc(u[api] || 0) + (ready[api] ? "" : ' <span class="muted">(not configured)</span>');
    }
    $("bd-counter").innerHTML = "<b>Records collected via Bright Data: " + esc(u.total || 0) + "</b>" +
      ' <span class="bd-detail">' + part("datasets", "datasets") + " | " + part("web_unlocker", "Web Unlocker") +
      " | " + part("serp", "SERP API") + "</span>";
  }

  function loadStory() {
    api("/brightdata", null, null).then(renderBrightData).catch(function () {
      $("bd-counter").textContent = "Records collected via Bright Data: unavailable";
    });
    return Promise.all([api("/plan", null, "plan"), api("/travel/map", null, "map"), api("/people?limit=3", null, "people")])
      .then(function (r) {
        renderStoryGoal(r[0]);
        renderStoryPlan(r[0], r[1]);
        var opps = renderStoryOpps(r[2]);
        storyMetButton();
        var fomo = api("/antifomo", null, "antifomo").then(renderStoryAntifomo).then(loadAgentsState);
        return Promise.all([opps, fomo, refreshRoi()]);
      }).catch(function (e) { showError("Demo: " + e.message); });
  }

  function storySimulate() {
    return api("/scenarios", null, "scenarios").then(function (s) {
      var items = (s && s.items) || [];
      var pick = items.filter(function (it) { return /sold/i.test(it.id); })[0] || items[0];
      if (!pick) throw new Error("No scenario available.");
      return api("/simulate-change", { method: "POST", body: { scenario_id: pick.id } }, "plan");
    }).then(function (res) {
      renderStoryDiff(res);
      return api("/plan", null, "plan").then(function (plan) {
        return api("/travel/map", null, "map").then(function (m) { renderStoryPlan(plan, m); });
      }).then(loadAgentsState);
    });
  }

  function storyMet() {
    var person = storyTop;
    return api("/people?limit=3", null, "people").then(function (before) {
      return api("/met", { method: "POST", body: { person_id: person.id, note: "demo" } }, "plan").then(function (res) {
        res.person_name = person.name;
        return api("/people?limit=3", null, "people").then(function (after) { renderStoryMet(before, res, after); });
      });
    }).then(refreshRoi);
  }

  // Wiring

  function initTabs() {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (btn) {
      btn.addEventListener("click", function () { switchTab(btn.getAttribute("data-tab")); });
    });
  }

  function switchTab(name) {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (b) {
      b.classList.toggle("active", b.getAttribute("data-tab") === name);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".tab-panel"), function (p) {
      p.classList.toggle("active", p.id === "tab-" + name);
    });
    if (name === "story" && storyMap) setTimeout(function () { storyMap.invalidateSize(); }, 50);
    if (name === "travel" && map) {
      setTimeout(function () { map.invalidateSize(); if (lastMapData) renderMap(lastMapData); }, 50);
    }
    if (name === "graph" && cy) {
      setTimeout(function () {
        cy.resize();
        cy.layout(COSE).run();
        cy.fit(undefined, 20);
      }, 50);
    }
  }

  function onClick(e) {
    var btn = e.target.closest ? e.target.closest("button[data-action]") : null;
    if (!btn) return;
    var action = btn.getAttribute("data-action");
    var id = btn.getAttribute("data-id");
    if (action === "attended" || action === "skipped") {
      withBusy(btn, function () { return mutate("/" + action, { event_id: id }); });
    } else if (action === "accept") {
      withBusy(btn, function () {
        return api("/proposal/accept", { method: "POST", body: { proposal_id: id } }, "travel").then(renderTravel);
      });
    } else if (action === "met") {
      var note = window.prompt("Meeting note (optional):", "");
      if (note === null) return;
      withBusy(btn, function () { return mutate("/met", { person_id: id, note: note || null }); });
    } else if (action === "followup") {
      withBusy(btn, function () {
        return api("/followup?person=" + encodeURIComponent(id), {}, "people").then(function (d) {
          var box = $("followup-" + id);
          if (!box) return;
          var next = d.next_action || {};
          box.innerHTML = '<div class="field"><b>Draft (not sent):</b></div>' +
            '<pre class="followup-text">' + esc(d.message) + "</pre>" +
            '<div class="field"><b>Next:</b> ' + esc(next.label || "") +
            (next.url ? ' <a href="' + esc(next.url) + '" target="_blank" rel="noopener">' + esc(next.url) + "</a>" : "") +
            (next.due_at ? " (" + esc(String(next.due_at).slice(0, 10)) + ")" : "") + "</div>" +
            (d.warnings && d.warnings.length ? '<div class="field muted small-text">' + esc(d.warnings.join("; ")) + "</div>" : "") +
            '<button class="small" data-action="copy-followup" data-id="' + esc(id) + '">Copy</button>';
        });
      });
    } else if (action === "copy-followup") {
      var pre = document.querySelector("#followup-" + id + " .followup-text");
      if (pre && navigator.clipboard) navigator.clipboard.writeText(pre.textContent).then(function () { btn.textContent = "Copied"; });
    } else if (action === "copy-agents-cypher") {
      var q = $("agents-cypher") ? $("agents-cypher").textContent : "";
      if (navigator.clipboard) navigator.clipboard.writeText(q).then(function () { btn.textContent = "Copied"; });
    } else if (action === "copy-cypher") {
      var text = $("story-cypher") ? $("story-cypher").textContent : "";
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(function () { btn.textContent = "Copied"; });
    } else if (action === "showpath" || action === "path") {
      if (action === "showpath") switchTab("graph");
      setTimeout(function () { highlightPath(id); }, action === "showpath" ? 300 : 0);
    }
  }

  function init() {
    initTabs();
    document.addEventListener("click", onClick);

    $("btn-goal").addEventListener("click", function () {
      var text = $("goal-text").value.trim();
      if (!text) { showError("Empty goal."); return; }
      withBusy($("btn-goal"), function () { return mutate("/goal", { text: text }).then(loadStory); });
    });

    $("btn-simulate").addEventListener("click", function () {
      var id = $("scenario-select").value;
      if (!id) { showError("No scenario available."); return; }
      withBusy($("btn-simulate"), function () {
        return mutate("/simulate-change", { scenario_id: id }).then(renderDiff);
      });
    });

    $("btn-reset").addEventListener("click", function () {
      withBusy($("btn-reset"), function () {
        $("diff-panel").classList.add("hidden");
        $("story-diff").innerHTML = "";
        return mutate("/reset", {}).then(loadStory).then(function () {
          return api("/conference", null, "conference").then(function (c) {
            if (c && c.demo_goal_text) $("goal-text").value = c.demo_goal_text;
          });
        });
      });
    });

    $("story-simulate").addEventListener("click", function () {
      withBusy($("story-simulate"), storySimulate);
    });
    document.addEventListener("click", function (e) {
      if (e.target && e.target.id === "story-met-btn") withBusy(e.target, storyMet);
    });

    $("btn-close-diff").addEventListener("click", function () { $("diff-panel").classList.add("hidden"); });

    api("/conference", null, "conference").then(function (c) {
      if (c && c.demo_goal_text && !$("goal-text").value) $("goal-text").value = c.demo_goal_text;
      if (c && c.conference) {
        var conf = c.conference;
        $("conf-name").textContent = conf.name + " | " + orUnknown(conf.venue_name) + ", " + orUnknown(conf.city) +
          " | " + orUnknown(conf.start_date) + " to " + orUnknown(conf.end_date);
      }
    }).catch(function (e) { showError("Conference: " + e.message); });

    refreshAll().then(loadStory).then(function () {
      var tab = (window.location.hash || "").replace("#", "");
      if (document.getElementById("tab-" + tab)) switchTab(tab);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
