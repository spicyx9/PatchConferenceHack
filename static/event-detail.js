(function () {
  "use strict";
  var events = [],
    opener,
    requestVersion = 0;
  document.addEventListener("conferge:events", function (event) {
    events = event.detail || [];
  });
  var dialog = document.createElement("dialog");
  dialog.id = "event-dialog";
  dialog.className = "event-dialog";
  dialog.setAttribute("aria-labelledby", "event-detail-title");
  dialog.innerHTML =
    '<div class="event-detail-ambient" aria-hidden="true"></div><button class="event-detail-close" aria-label="Close event details">×</button><div class="event-detail-layout"><div class="event-detail-copy"><span class="event-detail-eyebrow">AROUND YOUR CONFERENCE</span><h2 id="event-detail-title"></h2><p id="event-detail-host" class="event-detail-host"></p><div class="event-detail-facts"><div><svg class="icon"><use href="#i-calendar"/></svg><div><strong id="event-detail-date"></strong><span id="event-detail-time"></span></div></div><div><svg class="icon"><use href="#i-pin"/></svg><div><strong id="event-detail-venue"></strong><span id="event-detail-address"></span></div></div></div><p id="event-detail-status"></p><a id="event-detail-source" class="event-detail-cta" target="_blank" rel="noopener noreferrer">View event & registration</a><p id="event-detail-relation" class="event-detail-relation"></p></div><div id="event-detail-art" class="event-detail-art"></div><div id="event-detail-description" class="event-detail-description"></div></div>';
  document.body.appendChild(dialog);
  function field(id, value) {
    document.getElementById(id).textContent = value || "";
  }
  function url(value) {
    return typeof value === "string" && /^https?:\/\//i.test(value)
      ? value
      : null;
  }
  function show(event) {
    field("event-detail-title", event.title);
    field(
      "event-detail-host",
      (event.organizer_names || []).length
        ? "Hosted by " + event.organizer_names.join(" & ")
        : "",
    );
    var options = { timeZone: event.timezone || "America/Los_Angeles" };
    var date = event.start_at && new Date(event.start_at);
    field(
      "event-detail-date",
      date
        ? new Intl.DateTimeFormat(
            "en-US",
            Object.assign({}, options, {
              weekday: "long",
              month: "long",
              day: "numeric",
            }),
          ).format(date)
        : "Date to be announced",
    );
    field(
      "event-detail-time",
      date
        ? new Intl.DateTimeFormat(
            "en-US",
            Object.assign({}, options, {
              hour: "numeric",
              minute: "2-digit",
              timeZoneName: "short",
            }),
          ).format(date)
        : "",
    );
    field(
      "event-detail-venue",
      (event.venue && event.venue.name) || "Venue to be announced",
    );
    field("event-detail-address", event.venue && event.venue.address);
    field(
      "event-detail-status",
      { sold_out: "Sold out", cancelled: "Cancelled", postponed: "Postponed" }[
        event.status
      ],
    );
    field(
      "event-detail-relation",
      {
        official: "Part of the official conference program.",
        confirmed_side_event: "Confirmed conference side event.",
        candidate: "Conference connection awaiting confirmation.",
        unknown: "Listed nearby. Conference affiliation is unverified.",
        unrelated: "An independent event outside the conference.",
      }[event.conference_relation],
    );
    var description = event.description || "";
    if (/\[truncated(?: in fixture)?\]/i.test(description)) {
      description = description.split(/\s*\[truncated(?: in fixture)?\]/i)[0];
      var completeSentences = description.match(/[\s\S]*[.!?](?=\s|$)/);
      description = completeSentences ? completeSentences[0] : description;
    }
    field("event-detail-description", description);
    var source = document.getElementById("event-detail-source"),
      link = url(event.registration_url) || url(event.source_url);
    source.hidden = !link;
    if (link) source.href = link;
    else source.removeAttribute("href");
    var art = document.getElementById("event-detail-art"),
      cover = url(event.cover_url);
    art.replaceChildren();
    art.hidden = !cover;
    dialog.classList.toggle("has-artwork", Boolean(cover));
    if (cover) {
      var img = document.createElement("img");
      img.src = cover;
      img.alt = "Artwork for " + event.title;
      img.referrerPolicy = "no-referrer";
      img.addEventListener("error", function () {
        art.hidden = true;
        dialog.classList.remove("has-artwork");
      });
      art.appendChild(img);
      dialog.style.setProperty(
        "--event-image",
        "url(" + JSON.stringify(cover) + ")",
      );
    } else dialog.style.removeProperty("--event-image");
  }
  dialog
    .querySelector(".event-detail-close")
    .addEventListener("click", function () {
      dialog.close();
    });
  dialog.addEventListener("close", function () {
    requestVersion++;
    if (opener && opener.isConnected) opener.focus({ preventScroll: true });
  });
  document.addEventListener("click", async function (event) {
    var button = event.target.closest('button[data-action="event"]');
    if (!button) return;
    opener = button;
    var version = ++requestVersion,
      id = button.dataset.id;
    field("event-detail-title", "Loading event…");
    field("event-detail-host", "");
    dialog.showModal();
    try {
      if (!events.length) {
        var response = await fetch("/api/v1/events");
        if (!response.ok) throw new Error("Event unavailable");
        events = (await response.json()).items || [];
      }
      if (version !== requestVersion || !dialog.open) return;
      var item = events.find(function (entry) {
        return entry.id === id;
      });
      if (!item) throw new Error("Event unavailable");
      show(item);
    } catch (_) {
      if (version !== requestVersion || !dialog.open) return;
      field("event-detail-title", "This event couldn’t be loaded.");
      field("event-detail-host", "Close this window and try again.");
    }
  });
})();
