/* Progressive enhancement of the real search fields; no invented inventory. */
(function () {
  "use strict";
  var $ = function (id) {
    return document.getElementById(id);
  };
  var form = $("travel-research-form"),
    active = null,
    opener = null;
  var popup = document.createElement("div");
  popup.id = "travel-search-popover";
  popup.className = "travel-search-popover";
  popup.hidden = true;
  form.appendChild(popup);
  function flights() {
    return $("travel-flights-tab").getAttribute("aria-selected") === "true";
  }
  function oneWay() {
    return flights() && $("flight-type").value === "one_way";
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[c];
    });
  }
  function notify(input) {
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function positionPopup() {
    var box = opener.getBoundingClientRect(),
      root = form.getBoundingClientRect();
    var top = Math.max(
      12,
      Math.min(
        box.bottom + 10,
        innerHeight - popup.getBoundingClientRect().height - 12,
      ),
    );
    popup.style.top = top - root.top + "px";
  }
  function close(restore) {
    if (opener) {
      if (opener.type !== "date") opener.setAttribute("aria-expanded", "false");
      opener.removeAttribute("aria-activedescendant");
    }
    popup.hidden = true;
    active = null;
    if (restore && opener) opener.focus();
  }
  function open(kind, input, label) {
    close(false);
    active = kind;
    opener = input;
    popup.className = "travel-search-popover " + kind + "-popover";
    popup.setAttribute("role", kind === "places" ? "listbox" : "dialog");
    popup.setAttribute("aria-label", label);
    popup.hidden = false;
    if (input.type !== "date") input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-controls", popup.id);
    // Anchor using the real field; CSS caps width and handles mobile.
    var box = input.getBoundingClientRect(),
      root = form.getBoundingClientRect();
    popup.style.top = box.bottom - root.top + 12 + "px";
    popup.style.left =
      Math.max(
        0,
        Math.min(
          box.left - root.left,
          root.width - (kind === "dates" ? 688 : 360),
        ),
      ) + "px";
  }
  document.addEventListener("pointerdown", function (e) {
    if (
      !popup.hidden &&
      !popup.contains(e.target) &&
      !e.target.closest(
        ".travel-date-fields, .travel-party-field, .travel-route-fields",
      )
    )
      close(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !popup.hidden) {
      e.preventDefault();
      close(true);
    }
    if (e.key === "Tab" && active === "places") close(false);
  });
  form.addEventListener("submit", function () {
    close(false);
  });
  form.addEventListener("focusout", function () {
    // Tab remains free to leave this nonmodal picker.
    setTimeout(function () {
      if (
        !popup.hidden &&
        !popup.contains(document.activeElement) &&
        document.activeElement !== opener
      )
        close(false);
    }, 0);
  });
  document.addEventListener("travel:kindchange", function () {
    close(false);
    sync();
  });

  // The city expansions match the collector's supported airports. Individual
  // airports retain their IATA query; cities retain their supported city name.
  var cities = [
    [
      "New York",
      "NYC",
      [
        ["JFK", "John F. Kennedy International"],
        ["LGA", "LaGuardia"],
        ["EWR", "Newark Liberty International"],
      ],
    ],
    [
      "San Francisco",
      "SF",
      [
        ["SFO", "San Francisco International"],
        ["OAK", "Oakland International"],
      ],
    ],
    [
      "Paris",
      "PAR",
      [
        ["CDG", "Charles de Gaulle"],
        ["ORY", "Paris Orly"],
      ],
    ],
    [
      "London",
      "LON",
      [
        ["LHR", "London Heathrow"],
        ["LGW", "London Gatwick"],
      ],
    ],
    ["Los Angeles", "LA", [["LAX", "Los Angeles International"]]],
    ["Boston", "BOS", [["BOS", "Boston Logan International"]]],
    [
      "Washington",
      "DC",
      [
        ["DCA", "Reagan National"],
        ["IAD", "Dulles International"],
      ],
    ],
    [
      "Chicago",
      "CHI",
      [
        ["ORD", "O’Hare International"],
        ["MDW", "Chicago Midway"],
      ],
    ],
    ["Seattle", "SEA", [["SEA", "Seattle–Tacoma International"]]],
    ["Austin", "AUS", [["AUS", "Austin–Bergstrom International"]]],
    ["Miami", "MIA", [["MIA", "Miami International"]]],
    ["Atlanta", "ATL", [["ATL", "Hartsfield–Jackson Atlanta International"]]],
    ["Denver", "DEN", [["DEN", "Denver International"]]],
    [
      "Dallas",
      "DFW",
      [
        ["DFW", "Dallas Fort Worth International"],
        ["DAL", "Dallas Love Field"],
      ],
    ],
    [
      "Houston",
      "HOU",
      [
        ["IAH", "George Bush Intercontinental"],
        ["HOU", "William P. Hobby"],
      ],
    ],
    ["Philadelphia", "PHL", [["PHL", "Philadelphia International"]]],
    ["San Diego", "SAN", [["SAN", "San Diego International"]]],
    ["Las Vegas", "LAS", [["LAS", "Harry Reid International"]]],
    ["Toronto", "YYZ", [["YYZ", "Toronto Pearson International"]]],
    ["Amsterdam", "AMS", [["AMS", "Amsterdam Schiphol"]]],
    ["Berlin", "BER", [["BER", "Berlin Brandenburg"]]],
    ["Madrid", "MAD", [["MAD", "Adolfo Suárez Madrid–Barajas"]]],
    ["Lisbon", "LIS", [["LIS", "Humberto Delgado"]]],
    ["Dublin", "DUB", [["DUB", "Dublin Airport"]]],
  ];
  var placeOptions = [],
    placeIndex = -1;
  function places(input) {
    open("places", input, flights() ? "Cities and airports" : "Destinations");
    var term = input.value.trim().toLowerCase();
    placeOptions = [];
    cities.forEach(function (city) {
      var cityMatch =
        !term || (city[0] + " " + city[1]).toLowerCase().includes(term);
      if (
        cityMatch ||
        city[2].some(function (a) {
          return (a[0] + " " + a[1]).toLowerCase().includes(term);
        })
      ) {
        placeOptions.push({
          value: city[0],
          name: city[0],
          code: flights() ? city[1] : "",
          detail: flights()
            ? "City · " +
              city[2]
                .map(function (a) {
                  return a[0];
                })
                .join(", ")
            : "City",
        });
        if (flights())
          city[2].forEach(function (a) {
            if (cityMatch || (a[0] + " " + a[1]).toLowerCase().includes(term))
              placeOptions.push({
                value: a[0],
                name: a[1],
                code: a[0],
                detail: city[0] + " · Airport",
              });
          });
      }
    });
    placeOptions = placeOptions.slice(0, 9);
    placeIndex = -1;
    input.removeAttribute("aria-activedescendant");
    popup.innerHTML =
      '<p class="search-popover-caption">' +
      (term ? "Matching destinations" : "Popular destinations") +
      "</p>" +
      (placeOptions.length
        ? placeOptions
            .map(function (p, i) {
              return (
                '<button type="button" role="option" aria-selected="false" id="travel-place-option-' +
                i +
                '" data-place="' +
                i +
                '"><span><strong>' +
                esc(p.name) +
                "</strong><small>" +
                esc(p.detail) +
                "</small></span><b>" +
                esc(p.code) +
                "</b></button>"
              );
            })
            .join("")
        : '<p class="search-popover-empty">No suggestions. You can still enter a city or airport code.</p>');
    positionPopup();
    popup.querySelectorAll("[data-place]").forEach(function (button) {
      button.addEventListener("mousedown", function (e) {
        e.preventDefault();
      });
      button.onclick = function () {
        choosePlace(Number(button.dataset.place));
      };
    });
  }
  function choosePlace(i) {
    var input = opener;
    input.value = placeOptions[i].value;
    input.removeAttribute("aria-activedescendant");
    notify(input);
    close(false);
    if (input.id === "research-origin") {
      $("research-destination").focus();
      places($("research-destination"));
    } else {
      $("research-depart").focus();
      showDates($("research-depart"));
    }
  }
  ["research-origin", "research-destination"].forEach(function (id) {
    var input = $(id);
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.addEventListener("focus", function () {
      input.select();
      places(input);
    });
    input.addEventListener("click", function () {
      places(input);
    });
    input.addEventListener("input", function () {
      places(input);
    });
    input.addEventListener("keydown", function (e) {
      if (["ArrowDown", "ArrowUp"].includes(e.key)) {
        e.preventDefault();
        if (active !== "places" || opener !== input) places(input);
        if (!placeOptions.length) return;
        placeIndex =
          (placeIndex +
            (e.key === "ArrowDown" ? 1 : -1) +
            placeOptions.length) %
          placeOptions.length;
        popup.querySelectorAll("[data-place]").forEach(function (b, i) {
          b.setAttribute("aria-selected", String(i === placeIndex));
        });
        input.setAttribute(
          "aria-activedescendant",
          "travel-place-option-" + placeIndex,
        );
        $("travel-place-option-" + placeIndex).scrollIntoView({
          block: "nearest",
        });
      } else if (e.key === "Enter" && active === "places" && placeIndex >= 0) {
        e.preventDefault();
        choosePlace(placeIndex);
      }
    });
  });
  $("travel-swap-route").onclick = function () {
    var origin = $("research-origin"),
      destination = $("research-destination"),
      previous = origin.value;
    origin.value = destination.value;
    destination.value = previous;
    notify(origin);
    notify(destination);
    close(false);
  };

  function iso(date) {
    return (
      date.getFullYear() +
      "-" +
      String(date.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(date.getDate()).padStart(2, "0")
    );
  }
  function day(value) {
    return new Date(value + "T12:00:00");
  }
  function addDays(value, n) {
    var d = day(value);
    d.setDate(d.getDate() + n);
    return iso(d);
  }
  var today = iso(new Date()),
    month,
    picking = "start";
  function showDates(input) {
    open("dates", input, "Choose travel dates");
    picking =
      input.id === "research-return" && $("research-depart").value
        ? "end"
        : "start";
    var date = day(input.value && input.value >= today ? input.value : today);
    month = new Date(date.getFullYear(), date.getMonth(), 1, 12);
    drawCalendar();
  }
  function dateLabel(value) {
    return day(value).toLocaleDateString("en-US", {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  }
  function drawCalendar(focusDate) {
    var start = $("research-depart").value,
      end = oneWay() ? "" : $("research-return").value;
    var startName = flights() ? "departure" : "check-in",
      endName = flights() ? "return" : "check-out";
    popup.innerHTML =
      '<div class="search-popover-heading"><strong id="travel-calendar-prompt" aria-live="polite">Choose ' +
      (picking === "start" ? startName : endName) +
      ' date</strong><button type="button" data-close aria-label="Close date picker">×</button></div><div class="calendar-navigation"><button type="button" data-month="-1" aria-label="Previous month">‹</button><span>Exact dates</span><button type="button" data-month="1" aria-label="Next month">›</button></div><div class="travel-calendar-months">' +
      [0, 1]
        .map(function (offset) {
          var current = new Date(
              month.getFullYear(),
              month.getMonth() + offset,
              1,
              12,
            ),
            title = current.toLocaleDateString("en-US", {
              month: "long",
              year: "numeric",
            }),
            length = new Date(
              current.getFullYear(),
              current.getMonth() + 1,
              0,
            ).getDate();
          var html =
            '<section class="travel-calendar-month"><h3>' +
            title +
            '</h3><div class="calendar-weekdays" aria-hidden="true">' +
            ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
              .map(function (s) {
                return "<span>" + s + "</span>";
              })
              .join("") +
            '</div><div class="calendar-days" role="group" aria-label="' +
            title +
            '">';
          for (var empty = 0; empty < (current.getDay() + 6) % 7; empty++)
            html += "<span></span>";
          for (var n = 1; n <= length; n++) {
            var value = iso(
                new Date(current.getFullYear(), current.getMonth(), n, 12),
              ),
              selected = value === start || value === end,
              disabled = value < today || (picking === "end" && value <= start);
            html +=
              '<button type="button" data-date="' +
              value +
              '" aria-label="' +
              dateLabel(value) +
              '" aria-pressed="' +
              selected +
              '"' +
              (disabled ? " disabled" : "") +
              ' class="' +
              (selected ? "selected-date " : "") +
              (start && end && value > start && value < end ? "in-range" : "") +
              '" tabindex="' +
              (!disabled &&
              value ===
                (focusDate || (picking === "end" ? end : start) || today)
                ? "0"
                : "-1") +
              '">' +
              n +
              "</button>";
          }
          return html + "</div></section>";
        })
        .join("") +
      '</div><p class="calendar-range-summary">' +
      (start
        ? esc(
            day(start).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
            }),
          )
        : "Departure") +
      (oneWay()
        ? ""
        : " — " +
          (end
            ? esc(
                day(end).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                }),
              )
            : "Select return")) +
      "</p>";
    positionPopup();
    var previous = popup.querySelector('[data-month="-1"]');
    previous.disabled = iso(month).slice(0, 7) <= today.slice(0, 7);
    popup.querySelectorAll("[data-month]").forEach(function (b) {
      b.onclick = function () {
        month.setMonth(month.getMonth() + Number(b.dataset.month));
        drawCalendar();
      };
    });
    popup.querySelector("[data-close]").onclick = function () {
      close(true);
    };
    var enabled = Array.from(
      popup.querySelectorAll("[data-date]:not(:disabled)"),
    );
    if (
      !enabled.some(function (b) {
        return b.tabIndex === 0;
      }) &&
      enabled[0]
    )
      enabled[0].tabIndex = 0;
    enabled.forEach(function (b) {
      b.onclick = function () {
        if (picking === "start") {
          $("research-depart").value = b.dataset.date;
          if (!oneWay()) $("research-return").value = "";
          notify($("research-depart"));
          if (oneWay()) {
            close(false);
            $("research-adults").focus();
            return;
          }
          picking = "end";
          var nextDay = addDays(b.dataset.date, 1),
            nextDate = day(nextDay);
          var distance =
            (nextDate.getFullYear() - month.getFullYear()) * 12 +
            nextDate.getMonth() -
            month.getMonth();
          if (
            distance < 0 ||
            distance > 1 ||
            (distance > 0 && matchMedia("(max-width: 650px)").matches)
          )
            month = new Date(
              nextDate.getFullYear(),
              nextDate.getMonth(),
              1,
              12,
            );
          drawCalendar(nextDay);
          var next = popup.querySelector('[data-date="' + nextDay + '"]');
          if (next) next.focus();
        } else {
          $("research-return").value = b.dataset.date;
          notify($("research-return"));
          close(false);
          $("research-adults").focus();
        }
      };
      b.onkeydown = function (e) {
        var delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[
          e.key
        ];
        if (delta) {
          e.preventDefault();
          var target = addDays(b.dataset.date, delta);
          if (target < today || (picking === "end" && target <= start)) return;
          var date = day(target),
            monthsApart =
              (date.getFullYear() - month.getFullYear()) * 12 +
              date.getMonth() -
              month.getMonth();
          if (
            monthsApart < 0 ||
            (monthsApart > 0 && matchMedia("(max-width: 650px)").matches) ||
            monthsApart > 1
          )
            month = new Date(date.getFullYear(), date.getMonth(), 1, 12);
          drawCalendar(target);
          var next = popup.querySelector('[data-date="' + target + '"]');
          if (next) next.focus();
        }
      };
    });
  }
  ["research-depart", "research-return"].forEach(function (id) {
    var input = $(id);
    input.min = today;
    input.setAttribute("aria-haspopup", "dialog");
    input.addEventListener("click", function (e) {
      e.preventDefault();
      showDates(input);
    });
    input.addEventListener("keydown", function (e) {
      if (["Enter", " ", "ArrowDown"].includes(e.key)) {
        e.preventDefault();
        showDates(input);
        popup.querySelector('[data-date][tabindex="0"]')?.focus();
      }
    });
  });
  function party(input) {
    open(
      "party",
      input,
      flights() ? "Travelers and cabin" : "Guests and rooms",
    );
    drawParty();
  }
  function drawParty(focusId) {
    var names = flights() ? ["adults"] : ["adults", "rooms"];
    popup.innerHTML =
      '<div class="search-popover-heading"><strong>' +
      (flights() ? "Travelers and cabin" : "Guests and rooms") +
      '</strong><button type="button" data-close aria-label="Close traveler picker">×</button></div>' +
      names
        .map(function (name) {
          var value = Number($("research-" + name).value);
          return (
            '<div class="party-counter"><span><strong>' +
            (name === "adults" ? "Adults" : "Rooms") +
            "</strong><small>" +
            (name === "adults" ? "Age 18 and over" : "1–9 rooms") +
            '</small></span><div><button type="button" id="party-' +
            name +
            '-minus" data-counter="' +
            name +
            '" data-delta="-1" aria-label="Remove ' +
            (name === "adults" ? "adult" : "room") +
            '"' +
            (value <= 1 ? " disabled" : "") +
            '>−</button><output aria-live="polite">' +
            value +
            '</output><button type="button" id="party-' +
            name +
            '-plus" data-counter="' +
            name +
            '" data-delta="1" aria-label="Add ' +
            (name === "adults" ? "adult" : "room") +
            '"' +
            (value >= 9 ? " disabled" : "") +
            ">+</button></div></div>"
          );
        })
        .join("") +
      (flights()
        ? '<fieldset class="party-cabins"><legend>Cabin</legend>' +
          Array.from($("research-cabin").options)
            .map(function (o) {
              return (
                '<label><input type="radio" name="travel-cabin-choice" value="' +
                o.value +
                '"' +
                (o.selected ? " checked" : "") +
                ">" +
                o.text +
                "</label>"
              );
            })
            .join("") +
          "</fieldset>"
        : "") +
      '<button type="button" class="party-done">Done</button>';
    positionPopup();
    popup.querySelectorAll("[data-counter]").forEach(function (b) {
      b.onclick = function () {
        var select = $("research-" + b.dataset.counter);
        select.value = String(Number(select.value) + Number(b.dataset.delta));
        notify(select);
        drawParty(b.id);
      };
    });
    popup
      .querySelectorAll('[name="travel-cabin-choice"]')
      .forEach(function (radio) {
        radio.onchange = function () {
          $("research-cabin").value = radio.value;
          notify($("research-cabin"));
        };
      });
    popup.querySelector(".party-done").onclick = popup.querySelector(
      "[data-close]",
    ).onclick = function () {
      close(true);
    };
    if (focusId) {
      var focus = $(focusId);
      if (focus.disabled) focus = popup.querySelector(".party-done");
      focus.focus();
    }
  }
  ["research-adults", "research-cabin", "research-rooms"].forEach(
    function (id) {
      var input = $(id);
      input.setAttribute("aria-haspopup", "dialog");
      input.setAttribute("aria-expanded", "false");
      input.addEventListener("mousedown", function (e) {
        e.preventDefault();
        input.focus();
        party(input);
      });
      input.addEventListener("click", function (e) {
        e.preventDefault();
        if (active !== "party") party(input);
      });
      input.addEventListener("keydown", function (e) {
        if (["Enter", " ", "ArrowDown"].includes(e.key)) {
          e.preventDefault();
          party(input);
          popup.querySelector("[data-counter]:not(:disabled)").focus();
        }
      });
    },
  );
  function arrangeFilters() {
    var button = $("travel-mobile-filters");
    var target = matchMedia("(max-width: 650px)").matches
      ? document.querySelector(
          (flights() ? "#flight-results-panel" : "#stay-results-panel") +
            " .travel-sort-shortcuts",
        )
      : document.querySelector(".travel-filter-sidebar");
    if (button.parentElement !== target) target.prepend(button);
  }
  function sync() {
    arrangeFilters();
    $("travel-swap-route").hidden = !flights();
    $("research-adults-label").textContent = flights() ? "Travelers" : "Guests";
    document.querySelectorAll("[data-travel-sort]").forEach(function (b) {
      b.setAttribute(
        "aria-pressed",
        String(b.dataset.travelSort === $("flight-sort").value),
      );
    });
    document.querySelectorAll("[data-stay-sort]").forEach(function (b) {
      b.setAttribute(
        "aria-pressed",
        String(b.dataset.staySort === $("stay-sort").value),
      );
    });
  }
  document
    .querySelectorAll("[data-travel-sort], [data-stay-sort]")
    .forEach(function (b) {
      b.onclick = function () {
        var select = $(b.dataset.travelSort ? "flight-sort" : "stay-sort");
        select.value = b.dataset.travelSort || b.dataset.staySort;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        sync();
      };
    });
  $("flight-sort").addEventListener("change", sync);
  $("stay-sort").addEventListener("change", sync);
  $("flight-type").addEventListener("change", function () {
    close(false);
    sync();
  });
  $("travel-local-toggle").addEventListener("click", function () {
    close(false);
  });
  window.addEventListener("resize", function () {
    close(false);
    arrangeFilters();
  });
  sync();
})();
