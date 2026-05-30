// Simple table sorter for tables with class "sortable".
// Click a header to sort ascending; click again for descending.
(function () {
    function getCellValue(tr, idx) {
        var cell = tr.children[idx];
        return cell ? cell.innerText.trim() : "";
    }
    function comparer(idx, asc) {
        return function (a, b) {
            var v1 = getCellValue(asc ? a : b, idx);
            var v2 = getCellValue(asc ? b : a, idx);
            // Strip % sign, commas
            var n1 = parseFloat(v1.replace(/[%,]/g, ""));
            var n2 = parseFloat(v2.replace(/[%,]/g, ""));
            if (!isNaN(n1) && !isNaN(n2)) return n1 - n2;
            return v1.localeCompare(v2);
        };
    }
    document.querySelectorAll("table.sortable th").forEach(function (th) {
        th.style.cursor = "pointer";
        th.addEventListener("click", function () {
            var table = th.closest("table");
            var tbody = table.querySelector("tbody");
            var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
            var asc = !(th.dataset.asc === "true");
            // Reset others
            table.querySelectorAll("th").forEach(function (h) {
                h.dataset.asc = "";
                h.classList.remove("sort-asc", "sort-desc");
            });
            th.dataset.asc = asc ? "true" : "false";
            th.classList.add(asc ? "sort-asc" : "sort-desc");
            Array.from(tbody.querySelectorAll("tr"))
                .sort(comparer(idx, asc))
                .forEach(function (tr) { tbody.appendChild(tr); });
        });
    });
})();
