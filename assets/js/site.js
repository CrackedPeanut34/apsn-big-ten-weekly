// Progressive enhancement only: flags .table-scroll containers that
// actually overflow, so CSS can show an edge fade. No effect if this
// script fails to load -- the table is still fully usable via native
// horizontal scroll.
(function () {
  var containers = document.querySelectorAll('.table-scroll');
  containers.forEach(function (el) {
    function update() {
      el.classList.toggle('has-overflow', el.scrollWidth > el.clientWidth + 1);
    }
    update();
    window.addEventListener('resize', update);
  });
})();

// Team filter: clicking a team logo shows only that team's game cards.
// Clicking the already-active chip resets the filter (shows everything).
// Pure client-side -- no navigation, no separate page, no "all" button.
(function () {
  var bar = document.querySelector('.team-filter');
  if (!bar) return;
  var chips = bar.querySelectorAll('.team-filter-chip');
  var cards = document.querySelectorAll('.game-card');

  function applyFilter(team) {
    cards.forEach(function (card) {
      var teams = (card.dataset.teams || '').split('|');
      var match = !team || teams.indexOf(team) !== -1;
      card.classList.toggle('is-filtered-out', !match);
    });
  }

  chips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      var wasActive = chip.classList.contains('is-active');
      chips.forEach(function (c) { c.classList.remove('is-active'); });
      if (wasActive) {
        applyFilter(null);
      } else {
        chip.classList.add('is-active');
        applyFilter(chip.dataset.teamFilter);
      }
    });
  });
})();

// Rankings table: click a column header to sort by it, click again to flip
// direction. Blank cells (a source that hasn't rated that team yet) always
// sort to the bottom, regardless of direction. The "school" column sorts
// alphabetically; every other column sorts numerically on its data-value.
(function () {
  var table = document.getElementById('rankings-table');
  if (!table) return;
  var headers = table.querySelectorAll('th[data-sort-key]');
  var tbody = table.querySelector('tbody');

  headers.forEach(function (th) {
    th.addEventListener('click', function (event) {
      if (event.target.closest('a')) return;  // let glossary links navigate normally

      var key = th.dataset.sortKey;
      var isText = key === 'school';
      var dir = th.classList.contains('sorted-asc') ? 'desc' : 'asc';

      headers.forEach(function (h) { h.classList.remove('sorted-asc', 'sorted-desc'); });
      th.classList.add(dir === 'asc' ? 'sorted-asc' : 'sorted-desc');

      var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
      rows.sort(function (a, b) {
        var cellA = a.querySelector('[data-sort-cell="' + key + '"]');
        var cellB = b.querySelector('[data-sort-cell="' + key + '"]');

        if (isText) {
          var textA = cellA.textContent.trim();
          var textB = cellB.textContent.trim();
          return dir === 'asc' ? textA.localeCompare(textB) : textB.localeCompare(textA);
        }

        var valA = cellA.dataset.value;
        var valB = cellB.dataset.value;
        if (!valA && !valB) return 0;
        if (!valA) return 1;
        if (!valB) return -1;
        var numA = parseFloat(valA);
        var numB = parseFloat(valB);
        return dir === 'asc' ? numA - numB : numB - numA;
      });

      rows.forEach(function (row) { tbody.appendChild(row); });
    });
  });
})();
