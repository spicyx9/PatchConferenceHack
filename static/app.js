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

  function fmtTime(iso, tz) {
    if (!iso) return "heure unknown";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "heure unknown";
    try {
      return new Intl.DateTimeFormat("fr-FR", {
        timeZone: tz || EVENT_TZ, weekday: "short", day: "2-digit", month: "short",
        hour: "2-digit", minute: "2-digit"
      }).format(d);
    } catch (e) {
      return iso;
    }
  }

  function fmtHour(iso, tz) {
    if (!iso) return "?";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "?";
    try {
      return new Intl.DateTimeFormat("fr-FR", {
        timeZone: tz || EVENT_TZ, hour: "2-digit", minute: "2-digit"
      }).format(d);
    } catch (e) {
      return iso;
    }
  }

  function fmtDay(day) {
    if (!day) return "jour unknown";
    var d = new Date(day + "T12:00:00Z");
    if (isNaN(d.getTime())) return day;
    return new Intl.DateTimeFormat("fr-FR", {
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

  function updateGlobalBadges() {
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
    badge.title = "data_source agrege des dernieres reponses";

    var st = $("badge-status");
    st.className = "badge " + (worst || "neutral");
    st.textContent = (worst || "unknown").toUpperCase();

    $("collected-at").textContent = collected ? collected : "unknown";

    var wl = Object.keys(warnings).sort();
    $("warnings-count").textContent = String(wl.length);
    $("warnings-list").innerHTML = wl.map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("");
  }

  // Renderers

  function renderGoals(plan) {
    var goals = (plan && plan.goals) || [];
    $("goals-list").innerHTML = goals.length ? goals.map(function (g) {
      var w = typeof g.priority === "number" ? g.priority : null;
      var pct = w === null ? 0 : Math.round(w * 100);
      return '<div class="goal"><span class="weight">' + esc(w === null ? "unknown" : w.toFixed(2)) +
        '</span><span class="bar"><span style="width:' + pct + '%"></span></span><span>' +
        esc(g.description) + ' <span class="muted small-text">' + esc((g.target_roles || []).join(", ")) +
        "</span></span></div>";
    }).join("") : '<p class="muted">Aucun objectif reconnu.</p>';
    $("computed-by").textContent = plan ? "Calcule par: " + orUnknown(plan.computed_by) +
      (plan.scenario_id ? " | scenario actif: " + plan.scenario_id : "") : "";
  }

  function roiTile(name, value) {
    var unknown = value === null || value === undefined;
    return '<div class="roi-tile"><div class="value' + (unknown ? " unknown" : "") + '">' +
      esc(unknown ? "unknown" : value) + '</div><div class="name">' + esc(name) + "</div></div>";
  }

  function renderRoi(roi) {
    if (!roi) { $("roi-grid").innerHTML = '<p class="muted">ROI indisponible.</p>'; return; }
    $("roi-grid").innerHTML =
      roiTile("Depenses (USD)", roi.spend_usd === null || roi.spend_usd === undefined ? null : fmtUsd(roi.spend_usd)) +
      roiTile("Rencontres", roi.meetings) +
      roiTile("Contacts qualifies", roi.qualified_contacts) +
      roiTile("Opportunites (score >= 30)", roi.opportunities);
    $("roi-note").textContent = "Budget: " + fmtUsd(roi.budget_usd) + (roi.spend_note ? " | " + roi.spend_note : "");
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
        (who ? '<div class="muted small-text">Rencontrer: ' + esc(who) + "</div>" : "") + "</li>";
    }).join("") : '<li class="muted">Aucune action planifiee.</li>';
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
          (i.attended ? "Present" : "J'y vais") + "</button>" +
          '<button class="small" data-action="skipped" data-id="' + esc(i.event_id) + '">Passer</button>' +
          "</span></div>";
      }).join("") + "</div>";
    }).join("") : '<p class="muted">Aucun evenement planifie.</p>';

    var conflicts = (plan && plan.plan && plan.plan.conflicts) || [];
    $("conflicts").innerHTML = conflicts.length ? conflicts.map(function (c) {
      var miss = c.what_you_miss || [];
      return '<div class="conflict"><div><b>' + esc(fmtDay(c.day)) + ":</b> " + esc(c.verdict) + "</div>" +
        '<div class="small-text">Gagnant: ' + esc(c.winner && c.winner.title) + " | Perdant: " + esc(c.loser && c.loser.title) + "</div>" +
        "<div><b>Ce que tu rates:</b>" + (miss.length ? "<ul>" + miss.map(function (m) {
          return "<li>" + esc(m.name) + ' <span class="muted">(score ' + esc(m.score) + ")</span></li>";
        }).join("") + "</ul>" : ' <span class="muted">personne de ta liste</span>') + "</div></div>";
    }).join("") : '<p class="muted">Aucun conflit.</p>';

    var excluded = (plan && plan.plan && plan.plan.excluded) || [];
    $("excluded").innerHTML = excluded.length ? excluded.map(function (x) {
      return "<li>" + esc(x.title) + ' <span class="badge failed">' + esc(x.reason) + "</span></li>";
    }).join("") : '<li class="muted">Aucun.</li>';
  }

  function renderEvents(ev) {
    var items = (ev && ev.items) || [];
    $("events-list").innerHTML = items.length ? "<table><thead><tr><th>Quand (LA)</th><th>Titre</th><th>Type</th>" +
      "<th>Lieu</th><th>Statut</th><th>Score</th><th>Source</th></tr></thead><tbody>" + items.map(function (e) {
        var venue = e.venue && e.venue.name ? e.venue.name : null;
        var link = safeUrl(e.source_url) || safeUrl(e.registration_url);
        return "<tr><td>" + esc(fmtTime(e.start_at, e.timezone)) + "</td><td>" +
          (link ? '<a href="' + esc(link) + '" target="_blank" rel="noopener noreferrer">' + esc(e.title) + "</a>" : esc(e.title)) +
          (e.attended ? ' <span class="badge ok">present</span>' : "") +
          (e.skipped ? ' <span class="badge degraded">passe</span>' : "") +
          "</td><td>" + esc(e.event_type) + "</td><td>" + esc(orUnknown(venue)) + "</td><td>" + esc(orUnknown(e.status)) +
          "</td><td>" + esc(e.score) + "</td><td>" + sourceBadge(e.source_mode) + "</td></tr>";
      }).join("") + "</tbody></table>" : '<p class="muted">Aucun evenement.</p>';
  }

  function renderTravel(t) {
    if (!t) return;
    var legs = t.itinerary || [];
    $("itinerary").innerHTML = legs.length ? legs.map(function (l) {
      if (l.kind === "flight") {
        return "<li><b>Vol</b> " + esc(l.date) + ": " + esc(l.from) + " vers " + esc(l.to) +
          ' <span class="muted">depart ' + esc(orUnknown(l.departure_at)) + ", arrivee " + esc(orUnknown(l.arrival_at)) +
          ", compagnie " + esc(orUnknown(l.carrier)) + '</span> <span class="badge neutral">prix ' + esc(orUnknown(l.price_status)) +
          "</span> " + sourceBadge(l.source_mode) + "</li>";
      }
      return "<li><b>Hebergement</b> " + esc(l.name) + ' <span class="muted">' + esc(orUnknown(l.check_in)) + " au " +
        esc(orUnknown(l.check_out)) + '</span> <span class="badge neutral">prix ' + esc(orUnknown(l.price_status)) + "</span> " +
        sourceBadge(l.source_mode) + "</li>";
    }).join("") : '<li class="muted">Aucun trajet.</li>';

    var props = t.proposals || [];
    $("proposals").innerHTML = props.length ? props.map(function (p) {
      return '<div class="event-item"><span class="title">' + esc(p.text) +
        '<br><span class="muted small-text">' + esc(p.reason || "") + "</span></span>" +
        (p.accepted ? '<span class="badge ok">Acceptee</span>'
          : '<button class="small primary" data-action="accept" data-id="' + esc(p.id) + '">Accepter</button>') + "</div>";
    }).join("") : '<p class="muted">Aucune proposition.</p>';

    var b = t.budget || {};
    $("budget").innerHTML = "<table><tbody>" +
      "<tr><th>Budget</th><td>" + esc(fmtUsd(b.budget_usd)) + "</td></tr>" +
      "<tr><th>Vols</th><td>" + esc(fmtUsd(b.flights_usd)) + "</td></tr>" +
      "<tr><th>Hebergement</th><td>" + esc(fmtUsd(b.lodging_usd)) + "</td></tr>" +
      "<tr><th>Reste</th><td>" + esc(fmtUsd(b.remaining_usd)) + "</td></tr>" +
      "</tbody></table>" + (b.note ? '<p class="muted small-text">' + esc(b.note) + "</p>" : "");
  }

  function renderStays(s) {
    var items = (s && s.items) || [];
    $("stays").innerHTML = items.length ? items.map(function (st) {
      var link = safeUrl(st.booking_url);
      var dist = st.distance_to_venue_m === null || st.distance_to_venue_m === undefined ? "unknown"
        : st.distance_to_venue_m + " m" + (st.distance_is_straight_line_estimate ? " (vol d'oiseau)" : "");
      var priceCls = st.price_status === "verified" ? "ok" : "neutral";
      return '<div class="card"><div class="row"><b>' + esc(st.name) + "</b></div>" +
        '<div class="row"><span class="badge ' + priceCls + '">prix ' + esc(orUnknown(st.price_status)) + "</span>" +
        '<span class="badge neutral">dispo ' + esc(orUnknown(st.availability)) + "</span>" + sourceBadge(st.source_mode) + "</div>" +
        '<div class="field"><b>Type:</b> ' + esc(orUnknown(st.lodging_type)) + "</div>" +
        '<div class="field"><b>Total:</b> ' + esc(st.total_price === null || st.total_price === undefined ? "unknown" :
          st.total_price + " " + (st.currency || "")) + "</div>" +
        '<div class="field"><b>Distance au lieu:</b> ' + esc(dist) + "</div>" +
        '<div class="field"><b>Dates:</b> ' + esc(orUnknown(st.check_in)) + " au " + esc(orUnknown(st.check_out)) + "</div>" +
        (link ? '<div class="field"><a href="' + esc(link) + '" target="_blank" rel="noopener noreferrer">Reserver</a></div>' : "") +
        "</div>";
    }).join("") : '<p class="muted">Aucun hebergement.</p>';
  }

  function markerColor(kind, planned) {
    if (kind === "conference") return "#ff7b72";
    if (kind === "stay") return "#bc8cff";
    return planned ? "#f0b429" : "#6e7681";
  }

  function renderMap(m) {
    lastMapData = m;
    var el = $("map");
    if (typeof L === "undefined") {
      el.innerHTML = '<p class="muted" style="padding:1rem">Leaflet non charge. Points: ' +
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
        .bindTooltip("Jour " + esc(p.day)).addTo(mapLayer);
    });
    ((m && m.markers) || []).forEach(function (mk) {
      if (typeof mk.lat !== "number" || typeof mk.lng !== "number") return;
      bounds.push([mk.lat, mk.lng]);
      L.circleMarker([mk.lat, mk.lng], {
        radius: mk.kind === "conference" ? 12 : 9, color: "#0d1117", weight: 2,
        fillColor: markerColor(mk.kind, mk.planned), fillOpacity: 0.95
      }).bindPopup("<b>" + esc(mk.label) + "</b><br>" + esc(mk.kind) +
        (mk.planned === false ? " (non planifie)" : "") + "<br>precision: " + esc(orUnknown(mk.precision)))
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
    return "<b>" + esc(e.type) + "</b>: " + esc(e.source) + " vers " + esc(e.target) +
      "<br>Preuve: " + esc(orUnknown(e.evidence_source)) + " | confiance " + esc(orUnknown(e.confidence)) +
      " | observe le " + esc(orUnknown(e.observed_at));
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
      fb.innerHTML = '<p class="muted">cytoscape.js non charge: liste simple.</p><h3>Noeuds (' + nodes.length + ")</h3><ul>" +
        nodes.map(function (n) {
          return "<li>" + esc(n.type) + ": " + esc(n.label) + " " + sourceBadge(n.source_mode) +
            (n.type === "Person" ? ' <button class="small" data-action="path" data-id="' + esc(n.id) + '">Chemin</button>' : "") + "</li>";
        }).join("") + "</ul><h3>Liens (" + edges.length + ")</h3><ul>" +
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
      if (evt.target === cy) { clearHighlight(); $("graph-detail").textContent = "Aucune selection."; }
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
      $("graph-detail").innerHTML = "<b>Chemin (" + esc(res.hops) + " sauts):</b> " + labels.join(" &rarr; ") +
        "<br>" + (res.path || []).filter(function (s) { return s.edge; }).map(function (s) { return edgeDetail(s.edge); }).join("<br>");
      if (cy) {
        cy.elements().removeClass("path selected-edge").addClass("dim");
        nodeIds.forEach(function (id) { cy.getElementById(id).removeClass("dim").addClass("path"); });
        edgeIds.forEach(function (id) { cy.getElementById(id).removeClass("dim").addClass("path"); });
      }
    }).catch(function (err) {
      showError("Chemin introuvable: " + err.message);
    });
  }

  function renderPeople(p) {
    var items = (p && p.items) || [];
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
        (c.met ? '<span class="badge met">rencontre</span>' : "") + sourceBadge(modeOfEvidence(o.evidence)) + "</div>" +
        '<div class="field"><b>Titre:</b> ' + esc(orUnknown(person.title)) + "</div>" +
        '<div class="field"><b>Entreprise:</b> ' + esc(orUnknown(company.name)) + "</div>" +
        '<div class="field"><b>Pourquoi:</b> ' + esc(orUnknown(o.rationale)) + "</div>" +
        '<div class="field"><b>Ou:</b> ' + esc(orUnknown(o.where)) + "</div>" +
        '<div class="field"><b>Accroche:</b> ' + esc(orUnknown(o.opener)) + "</div>" +
        (c.met_note ? '<div class="field"><b>Note:</b> ' + esc(c.met_note) + "</div>" : "") +
        '<div class="row">' + (c.met ? "" : '<button class="small primary" data-action="met" data-id="' + esc(pid) + '">Rencontre</button>') +
        '<button class="small" data-action="showpath" data-id="' + esc(pid) + '">Voir le chemin</button></div>' +
        "</div>";
    }).join("") : '<p class="muted">Aucune personne.</p>';
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
        ((list || []).length ? "<ul>" + list.map(fmt).join("") + "</ul>" : '<span class="muted">aucun</span>') + "</div>";
    }
    $("diff-body").innerHTML = "<p><b>" + esc(res.scenario && res.scenario.label) + "</b></p>" +
      section("Ajoutes", "diff-added", d.added, function (x) { return "<li>" + esc(x.title || x.event_id) + "</li>"; }) +
      section("Retires", "diff-removed", d.removed, function (x) { return "<li>" + esc(x.title || x.event_id) + "</li>"; }) +
      section("Modifies", "diff-changed", d.changed, function (x) {
        var b = x.before || {}, a = x.after || {};
        return "<li>" + esc(x.event_id) + ": " + esc(fmtTime(b.start_at)) + " (" + esc(b.status) + ") vers " +
          esc(fmtTime(a.start_at)) + " (" + esc(a.status) + ")</li>";
      }) +
      section("Replanification", "diff-replan", res.replan, function (x) {
        var r = x.replacement, p = x.graph_path;
        return "<li><b>Retire :</b> " + esc(x.removed.title) +
          (r ? "<br><b>Remplace par :</b> " + esc(r.title) + " (" + esc(fmtTime(r.start_at)) + ")" : "") +
          "<br><b>Raison :</b> " + esc(x.reason) +
          (p ? "<br><b>Chemin :</b> " + esc(p.nodes.join(" > ")) + (p.explanation ? '<br><span class="muted">' + esc(p.explanation) + "</span>" : "") : "") +
          "</li>";
      }) + '<p class="muted small-text">Changement simule, pas une mise a jour reelle de la source.</p>';
    $("diff-panel").classList.remove("hidden");
  }

  // Loading

  function settle(promise, label, render, errors) {
    return promise.then(function (data) {
      try { render(data); } catch (e) { errors.push(label + ": rendu " + e.message); }
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
      settle(api("/people", null, "people"), "people", renderPeople, errors),
      settle(api("/scenarios", null, "scenarios"), "scenarios", renderScenarios, errors)
    ]).then(function () {
      if (errors.length) showError("Erreur de chargement: " + errors.join(" | "));
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
      var note = window.prompt("Note sur la rencontre (optionnel):", "");
      if (note === null) return;
      withBusy(btn, function () { return mutate("/met", { person_id: id, note: note || null }); });
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
      if (!text) { showError("Objectif vide."); return; }
      withBusy($("btn-goal"), function () { return mutate("/goal", { text: text }); });
    });

    $("btn-simulate").addEventListener("click", function () {
      var id = $("scenario-select").value;
      if (!id) { showError("Aucun scenario disponible."); return; }
      withBusy($("btn-simulate"), function () {
        return mutate("/simulate-change", { scenario_id: id }).then(renderDiff);
      });
    });

    $("btn-reset").addEventListener("click", function () {
      withBusy($("btn-reset"), function () {
        $("diff-panel").classList.add("hidden");
        return mutate("/reset", {}).then(function () {
          return api("/conference", null, "conference").then(function (c) {
            if (c && c.demo_goal_text) $("goal-text").value = c.demo_goal_text;
          });
        });
      });
    });

    $("btn-close-diff").addEventListener("click", function () { $("diff-panel").classList.add("hidden"); });

    api("/conference", null, "conference").then(function (c) {
      if (c && c.demo_goal_text && !$("goal-text").value) $("goal-text").value = c.demo_goal_text;
      if (c && c.conference) {
        var conf = c.conference;
        $("conf-name").textContent = conf.name + " | " + orUnknown(conf.venue_name) + ", " + orUnknown(conf.city) +
          " | " + orUnknown(conf.start_date) + " au " + orUnknown(conf.end_date);
      }
    }).catch(function (e) { showError("Conference: " + e.message); });

    refreshAll().then(function () {
      var tab = (window.location.hash || "").replace("#", "");
      if (document.getElementById("tab-" + tab)) switchTab(tab);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
