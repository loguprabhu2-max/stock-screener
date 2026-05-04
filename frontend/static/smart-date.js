/* Smart date pickers using Flatpickr.
   Highlights dates that have data (dark) and disables dates without data.
   Submit value is YYYY-MM-DD; user sees DD MM YYYY.

   Two functions:
     initSmartDates(screenerType)         - first init for a page
     reloadSmartDates(screenerType)       - re-init for a different screener
                                            (used by Data Management when
                                            the table dropdown changes)
*/

(function () {
    var pickers = []; // tracks current flatpickr instances so we can destroy them

    function buildOptions(data) {
        var availableDates = data.dates || [];
        var availableSet = new Set(availableDates);

        return {
            dateFormat: "Y-m-d",
            altInput: true,
            altFormat: "d m Y",
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
    }

    function fallbackOptions() {
        return {
            dateFormat: "Y-m-d",
            altInput: true,
            altFormat: "d m Y",
            disableMobile: true,
        };
    }

    function destroyAll() {
        pickers.forEach(function (p) {
            try { p.destroy(); } catch (e) {}
        });
        pickers = [];
    }

    function applyOptions(options) {
        destroyAll();
        var inputs = document.querySelectorAll("input.smart-date");
        inputs.forEach(function (el) {
            pickers.push(flatpickr(el, options));
        });
    }

    function load(screenerType) {
        if (typeof flatpickr === "undefined") {
            console.warn("Flatpickr not loaded");
            return;
        }
        fetch("/api/available-dates/" + screenerType)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                applyOptions(buildOptions(data));
            })
            .catch(function (err) {
                console.error("Could not load available dates:", err);
                applyOptions(fallbackOptions());
            });
    }

    // Expose to global scope
    window.initSmartDates = load;
    window.reloadSmartDates = load;
})();
