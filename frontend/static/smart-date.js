/* Smart date pickers using Flatpickr.
   Highlights dates that have data (dark) and disables dates without data.
   Submit value is YYYY-MM-DD; user sees DD MM YYYY. */

function initSmartDates(screenerType) {
    if (typeof flatpickr === "undefined") {
        console.warn("Flatpickr not loaded");
        return;
    }

    fetch("/api/available-dates/" + screenerType)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var availableDates = data.dates || [];
            var availableSet = new Set(availableDates);

            var commonOptions = {
                dateFormat: "Y-m-d",   // value sent to server
                altInput: true,
                altFormat: "d m Y",    // shown to user
                allowInput: false,
                minDate: data.range && data.range.min ? data.range.min : null,
                maxDate: data.range && data.range.max ? data.range.max : null,
                disableMobile: true,
                onDayCreate: function (dObj, dStr, fp, dayElem) {
                    var d = dayElem.dateObj;
                    var iso = d.getFullYear() + "-" +
                              String(d.getMonth() + 1).padStart(2, "0") + "-" +
                              String(d.getDate()).padStart(2, "0");
                    if (availableSet.has(iso)) {
                        dayElem.classList.add("has-data");
                    } else {
                        dayElem.classList.add("no-data");
                    }
                },
            };

            var inputs = document.querySelectorAll("input.smart-date");
            inputs.forEach(function (el) {
                flatpickr(el, commonOptions);
            });
        })
        .catch(function (err) {
            console.error("Could not load available dates:", err);
            // Fallback: still let user pick any date
            document.querySelectorAll("input.smart-date").forEach(function (el) {
                flatpickr(el, {
                    dateFormat: "Y-m-d",
                    altInput: true,
                    altFormat: "d m Y",
                    disableMobile: true,
                });
            });
        });
}
