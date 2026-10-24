/* Source-backed comparisons; no fabricated photos, stars, prices or inclusions. */
(function () {
  "use strict";
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[c];
    });
  }
  function url(value) {
    try {
      var parsed = new URL(value);
      return ["http:", "https:"].includes(parsed.protocol) &&
        !parsed.username &&
        !parsed.password
        ? parsed.href
        : null;
    } catch (_) {
      return null;
    }
  }
  function date(value) {
    if (!value) return "Date unconfirmed";
    var parsed = new Date(value.slice(0, 10) + "T12:00:00Z");
    return isNaN(parsed)
      ? "Date unconfirmed"
      : parsed.toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          timeZone: "UTC",
        });
  }
  function money(value, currency) {
    if (value == null || !currency || !Number.isFinite(Number(value)))
      return "Price unavailable";
    try {
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: currency,
        maximumFractionDigits: 2,
      }).format(Number(value));
    } catch (_) {
      return esc(value) + " " + esc(currency);
    }
  }
  function clock(value) {
    return value ? esc(value.slice(11, 16)) : "—";
  }
  function zone(value) {
    return !value ? "" : value.endsWith("Z") ? "UTC" : "UTC" + value.slice(-6);
  }
  function duration(slice) {
    var segments = slice.segments || [],
      first = segments[0] || {},
      last = segments[segments.length - 1] || {};
    var minutes = slice.duration_minutes;
    if (minutes == null && first.departure_at && last.arrival_at)
      minutes =
        (new Date(last.arrival_at) - new Date(first.departure_at)) / 60000;
    if (minutes == null || !Number.isFinite(minutes) || minutes < 0)
      return "Duration unconfirmed";
    minutes = Math.round(minutes);
    return Math.floor(minutes / 60) + "h " + (minutes % 60) + "m";
  }
  function site(item) {
    var names = {
      booking: "Booking.com",
      airbnb: "Airbnb",
      google_hotels: "Google Hotels",
      google_flights: "Google Flights",
      expedia: "Expedia",
      hilton: "Hilton",
      marriott: "Marriott",
    };
    if (names[(item.source || {}).site]) return names[item.source.site];
    try {
      return new URL(item.booking_url).hostname.replace(/^www\./, "");
    } catch (_) {
      return "provider";
    }
  }
  function image(src, alt, klass, fallback) {
    src = url(src);
    // Keep the fallback visible while a remote source image is still loading.
    return (
      '<span class="' +
      klass +
      '"><span>' +
      esc(fallback) +
      "</span>" +
      (src
        ? '<img src="' +
          esc(src) +
          '" alt="' +
          esc(alt) +
          '" loading="lazy" referrerpolicy="no-referrer" onload="this.previousElementSibling.hidden=true" onerror="this.hidden=true">'
        : "") +
      "</span>"
    );
  }
  function sliceRow(slice, index, card) {
    var segments = slice.segments || [],
      first = segments[0] || {},
      last = segments[segments.length - 1] || {};
    var carrier = first.marketing_carrier || "Airline unconfirmed";
    var supplied = (card.airline_images || []).find(function (i) {
      return i.carrier === carrier;
    });
    var logo = supplied && supplied.url;
    // Local brand assets for known source IATA codes, separate from travel observations.
    if (
      !logo &&
      ["UA", "B6", "DL", "AA", "AS", "F9", "WN", "HA"].includes(carrier)
    )
      logo = location.origin + "/static/images/airlines/" + carrier + ".png";
    var stops = segments.length ? segments.length - 1 : null;
    var via = segments
      .slice(0, -1)
      .map(function (s) {
        return s.destination_iata;
      })
      .join(", ");
    var offset =
      first.departure_at && last.arrival_at
        ? Math.round(
            (new Date(last.arrival_at.slice(0, 10)) -
              new Date(first.departure_at.slice(0, 10))) /
              86400000,
          )
        : 0;
    var stopText =
      stops == null
        ? "Stops unconfirmed"
        : stops === 0
          ? "Nonstop"
          : stops +
            " stop" +
            (stops === 1 ? "" : "s") +
            (via ? " · " + via : "");
    return (
      '<div class="fare-slice"><div class="fare-airline">' +
      image(logo, carrier + " logo", "fare-logo", carrier) +
      "<span><strong>" +
      esc(carrier) +
      "</strong><small>" +
      esc(first.flight_number || "Flight number unconfirmed") +
      "</small></span></div>" +
      '<div class="fare-endpoint"><strong>' +
      clock(first.departure_at) +
      "</strong><span>" +
      esc(first.origin_iata || "—") +
      '</span></div><div class="fare-route"><span>' +
      esc(duration(slice)) +
      '</span><i aria-hidden="true"></i><span>' +
      esc(stopText) +
      "</span></div>" +
      '<div class="fare-endpoint fare-arrival"><strong>' +
      clock(last.arrival_at) +
      (offset > 0 ? "<sup>+" + offset + "</sup>" : "") +
      "</strong><span>" +
      esc(last.destination_iata || "—") +
      '</span></div><div class="fare-date"><span>' +
      esc(
        index === 0
          ? "Outbound"
          : index === 1
            ? "Return"
            : "Flight " + (index + 1),
      ) +
      " · " +
      esc(date(first.departure_at)) +
      "</span><small>Local times" +
      esc(
        first.departure_at ? " · " + zone(first.departure_at) : " unconfirmed",
      ) +
      esc(
        last.arrival_at && zone(last.arrival_at) !== zone(first.departure_at)
          ? " / " + zone(last.arrival_at)
          : "",
      ) +
      "</small></div></div>"
    );
  }
  function deal(link, label) {
    return (
      '<a class="offer-deal" href="' +
      esc(link) +
      '" target="_blank" rel="noopener noreferrer">' +
      esc(label) +
      '<span aria-hidden="true"> ↗</span></a>'
    );
  }
  function flight(flight, badge) {
    var card = flight.card_details || {},
      link = url(flight.booking_url),
      provider = site(flight);
    var roundTrip =
      flight.trip_type === "round_trip" ||
      flight.return_slice_collected === false;
    var bags = [];
    if (flight.carry_on_included != null)
      bags.push(
        flight.carry_on_included
          ? "Carry-on included"
          : "Carry-on not included",
      );
    if (flight.checked_bags_included != null)
      bags.push(
        flight.checked_bags_included +
          " checked bag" +
          (flight.checked_bags_included === 1 ? "" : "s"),
      );
    if (!bags.length) bags.push("Baggage unconfirmed");
    if (
      (flight.slices || []).some(function (s) {
        return s.self_transfer === true;
      })
    )
      bags.push("Self-transfer · separate tickets");
    var scope =
      flight.price_scope === "per_adult"
        ? "per adult"
        : flight.price_scope === "total_all_passengers"
          ? "all passengers"
          : "passenger scope unconfirmed";
    var label = roundTrip
      ? "Round-trip total"
      : flight.trip_type === "one_way"
        ? "One-way fare"
        : "Itinerary total";
    return (
      '<article class="travel-offer fare-card"><div class="fare-itinerary">' +
      (flight.slices || [])
        .map(function (s, i) {
          return sliceRow(s, i, card);
        })
        .join("") +
      (flight.return_slice_collected === false
        ? '<p class="fare-return-missing">Return times unavailable. Confirm both flights on the booking site.</p>'
        : "") +
      '<p class="fare-inclusions">' +
      esc(
        [card.cabin, card.fare_name].concat(bags).filter(Boolean).join(" · "),
      ) +
      '</p></div><div class="fare-price">' +
      (badge || "") +
      '<span class="offer-provider">' +
      esc(provider) +
      "</span><strong>" +
      money(flight.total_price, flight.currency) +
      "</strong><span>" +
      esc(label) +
      "</span><small>" +
      esc(scope) +
      "</small>" +
      (link
        ? deal(
            link,
            (flight.booking_url_type === "google_flights_search"
              ? "Check on "
              : "View deal on ") + provider,
          )
        : '<span class="offer-unconfirmed">Booking link unavailable</span>') +
      "<small>" + esc(flight.price_status === "indicative"
        ? "Estimated price · confirm on the booking site"
        : flight.price_status === "unavailable"
          ? "Unavailable for these dates"
          : "Price and availability may change") + "</small></div>" +
      "</article>"
    );
  }
  function stay(stay, badge) {
    var card = stay.card_details || {},
      link = url(stay.booking_url),
      provider = site(stay),
      venue = stay.venue || {};
    var nights =
      (new Date(stay.check_out) - new Date(stay.check_in)) / 86400000;
    var review =
      stay.rating != null && stay.rating_scale != null
        ? '<div class="stay-review"><span><strong>Guest rating</strong><small>' +
          esc(
            stay.rating_count == null
              ? "Review count unavailable"
              : Number(stay.rating_count).toLocaleString("en-US") + " reviews",
          ) +
          "</small></span><b>" +
          esc(stay.rating) +
          "<small>/" +
          esc(stay.rating_scale) +
          "</small></b></div>"
        : "";
    var stars =
      Number.isInteger(card.star_rating) &&
      card.star_rating >= 1 &&
      card.star_rating <= 5
        ? '<span class="stay-stars" role="img" aria-label="' +
          card.star_rating +
          '-star property">' +
          "★".repeat(card.star_rating) +
          "</span>"
        : "";
    var distance =
      stay.distance_to_venue_m == null
        ? ""
        : (stay.distance_to_venue_m / 1000).toFixed(1) +
          " km from conference" +
          (stay.distance_is_straight_line_estimate ? " · straight line" : "");
    var policies = [];
    if (stay.free_cancellation === true)
      policies.push(
        "Free cancellation" +
          (card.free_cancellation_until
            ? " until " + date(card.free_cancellation_until)
            : ""),
      );
    if (stay.free_cancellation === false) policies.push("No free cancellation");
    if (card.breakfast_included === true) policies.push("Breakfast included");
    if (card.no_prepayment === true) policies.push("No prepayment");
    var taxes =
      stay.includes_all_fees === true
        ? "Taxes and fees included"
        : stay.includes_all_fees === false
          ? "Additional taxes or fees apply"
          : "Taxes and fees unconfirmed";
    var price =
      stay.total_price != null
        ? money(stay.total_price, stay.currency)
        : stay.price_status === "indicative" && stay.nightly_avg != null
          ? "From " + money(stay.nightly_avg, stay.currency)
          : "Price unavailable";
    var unavailable =
      stay.availability === "unavailable" ||
      stay.price_status === "unavailable";
    return (
      '<article class="trip-stay stay-card">' +
      image(
        (card.image_urls || [])[0],
        stay.name,
        "stay-photo",
        "No photo supplied",
      ) +
      '<div class="stay-content"><span class="offer-provider">' +
      esc(provider) +
      " · " +
      esc(stay.lodging_type || "Stay") +
      "</span><h3>" +
      esc(stay.name) +
      "</h3>" +
      stars +
      '<p class="stay-location">' +
      esc(
        [venue.address || venue.city, distance].filter(Boolean).join(" · ") ||
          "Location unconfirmed",
      ) +
      "</p>" +
      ([card.room_type, card.bed_description].filter(Boolean).length
        ? '<p class="stay-room">' +
          esc(
            [card.room_type, card.bed_description].filter(Boolean).join(" · "),
          ) +
          "</p>"
        : "") +
      '<ul class="stay-amenities">' +
      (card.amenities || [])
        .slice(0, 3)
        .map(function (a) {
          return "<li>" + esc(a) + "</li>";
        })
        .join("") +
      "</ul>" +
      (policies.length
        ? '<p class="stay-policies">' + esc(policies.join(" · ")) + "</p>"
        : "") +
      '<p class="stay-dates">' +
      esc(date(stay.check_in)) +
      " – " +
      esc(date(stay.check_out)) +
      " · " +
      esc(nights) +
      " nights · " +
      esc(stay.adults) +
      " adult" +
      (stay.adults === 1 ? "" : "s") +
      " · " +
      esc(stay.rooms) +
      " room" +
      (stay.rooms === 1 ? "" : "s") +
      '</p></div><div class="stay-offer">' +
      review +
      '<div class="stay-price">' +
      (badge || "") +
      "<strong>" +
      price +
      "</strong><span>" +
      esc(
        stay.total_price != null
          ? "for " + nights + " nights"
          : stay.price_status === "indicative"
            ? "per night · indicative"
            : "for these dates",
      ) +
      "</span><small>" +
      esc(taxes) +
      "</small>" +
      (stay.total_price != null && stay.nightly_avg != null
        ? "<small>" +
          money(stay.nightly_avg, stay.currency) +
          " / night on average</small>"
        : "") +
      '<span class="offer-unconfirmed">' +
      esc(
        unavailable
          ? "Unavailable for these dates"
          : stay.price_status === "verified_bookable"
            ? "Availability was verified · recheck before booking"
            : "Availability needs checking",
      ) +
      "</span>" +
      (link
        ? deal(
            link,
            (unavailable ? "Check alternatives on " : "View deal on ") +
              provider,
          )
        : "<small>Booking link unavailable</small>") +
      '</div></div></article>'
    );
  }
  window.TravelCards = { flight: flight, stay: stay };
})();
