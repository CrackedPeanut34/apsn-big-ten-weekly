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
// Clicking the already-active chip (or "All teams") resets the filter.
// Pure client-side -- no navigation, no separate page.
(function () {
  var bar = document.querySelector('.team-filter');
  if (!bar) return;
  var chips = bar.querySelectorAll('.team-filter-chip');
  var cards = document.querySelectorAll('.game-card');

  function applyFilter(team) {
    cards.forEach(function (card) {
      var teams = (card.dataset.teams || '').split('|');
      var match = team === 'all' || teams.indexOf(team) !== -1;
      card.classList.toggle('is-filtered-out', !match);
    });
  }

  chips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      var wasActive = chip.classList.contains('is-active');
      var team = chip.dataset.teamFilter;
      var nextTeam = (wasActive && team !== 'all') ? 'all' : team;
      chips.forEach(function (c) { c.classList.remove('is-active'); });
      bar.querySelector('[data-team-filter="' + nextTeam + '"]').classList.add('is-active');
      applyFilter(nextTeam);
    });
  });
})();
