// Head to Head tab: pick any two Big Ten teams and get a card in the same
// visual language as a real matchup card (.game-card / .team / .team-logo
// etc., same CSS as templates/week.html), but built from season-long
// per-team stats rather than a real game's model predictions or market
// odds -- there often isn't a real scheduled game between the two teams
// picked, so there's nothing model/market to show. Independent component,
// same pattern as rankings-compare.js: fetches the shared JSON itself,
// lazily initialized by dashboard-tabs.js on first tab open.
(function () {
  var aSelect = document.getElementById('h2h-team-a-select');
  var bSelect = document.getElementById('h2h-team-b-select');
  var cardWrap = document.getElementById('h2h-card-wrap');
  var loadingEl = document.getElementById('h2h-loading');
  if (!aSelect || !bSelect || !cardWrap) return;

  // Same small presentation-only formatting duplicated in rankings-chart.js
  // and rankings-compare.js -- deliberately not shared, these components
  // are independent.
  function formatValue(key, v) {
    if (v === null || v === undefined) return '—';
    if (key === 'ap_rank') return 'No. ' + v;
    if (key === 'elo') return Math.round(v).toString();
    return v.toFixed(1);
  }

  var dataPromise = (typeof window.APSN_CHART_DATA_URL === 'string')
    ? fetch(window.APSN_CHART_DATA_URL).then(function (res) { return res.json(); })
    : Promise.reject(new Error('APSN_CHART_DATA_URL not set'));

  var state = { data: null };

  function populateSelect(select, selectedSchool) {
    select.innerHTML = '';
    state.data.teams.forEach(function (t) {
      var opt = document.createElement('option');
      opt.value = t.school;
      opt.textContent = t.school;
      if (t.school === selectedSchool) opt.selected = true;
      select.appendChild(opt);
    });
  }

  function teamBySchool(school) {
    return state.data.teams.filter(function (t) { return t.school === school; })[0];
  }

  function statRows(teamA, teamB) {
    var rows = [{ label: 'Record', a: teamA.record_display || '—', b: teamB.record_display || '—' }];
    state.data.stats.forEach(function (s) {
      rows.push({
        label: s.label,
        a: formatValue(s.key, teamA.values[s.key]),
        b: formatValue(s.key, teamB.values[s.key]),
      });
    });
    return rows;
  }

  function apBadge(team) {
    var rank = team.values.ap_rank;
    return rank ? '<span class="ap-rank-badge">' + rank + '</span>' : '';
  }

  function render() {
    var teamA = teamBySchool(aSelect.value);
    var teamB = teamBySchool(bSelect.value);

    if (!teamA || !teamB) return;

    if (teamA.school === teamB.school) {
      cardWrap.innerHTML = '<p class="compare-loading">Pick two different teams to compare.</p>';
      return;
    }

    var rows = statRows(teamA, teamB);
    var rowsHtml = rows.map(function (r) {
      return '<tr><td class="num tabular">' + r.a + '</td><th scope="row">' + r.label + '</th><td class="num tabular">' + r.b + '</td></tr>';
    }).join('');

    cardWrap.innerHTML =
      '<article class="game-card" style="--away-color:' + (teamA.color || 'var(--border)') + '; --home-color:' + (teamB.color || 'var(--border)') + ';">' +
        '<header class="game-card-header">' +
          '<div class="matchup">' +
            '<div class="team team-away">' +
              '<img class="team-logo" src="' + (teamA.logo_url || '') + '" alt="' + teamA.school + ' logo" loading="lazy">' +
              apBadge(teamA) +
              '<span class="team-name">' + teamA.school + '</span>' +
            '</div>' +
            '<span class="matchup-at">vs</span>' +
            '<div class="team team-home">' +
              '<img class="team-logo" src="' + (teamB.logo_url || '') + '" alt="' + teamB.school + ' logo" loading="lazy">' +
              apBadge(teamB) +
              '<span class="team-name">' + teamB.school + '</span>' +
            '</div>' +
          '</div>' +
          '<div class="game-meta"><span class="kickoff">Season-long comparison, not a scheduled game</span></div>' +
        '</header>' +
        '<div class="table-scroll">' +
          '<table class="model-table h2h-table">' +
            '<thead><tr><th scope="col" class="num">' + teamA.abbr + '</th><th scope="col">Stat</th><th scope="col" class="num">' + teamB.abbr + '</th></tr></thead>' +
            '<tbody>' + rowsHtml + '</tbody>' +
          '</table>' +
        '</div>' +
      '</article>';
  }

  aSelect.addEventListener('change', render);
  bSelect.addEventListener('change', render);

  function init() {
    dataPromise.then(function (data) {
      state.data = data;

      // Default to the top two teams by FPI (same "best first" ordering
      // the bar chart defaults to) so the card isn't blank on first open.
      var byFpi = data.teams.slice().sort(function (x, y) {
        var xv = x.values.fpi, yv = y.values.fpi;
        return (yv === null || yv === undefined ? -Infinity : yv) - (xv === null || xv === undefined ? -Infinity : xv);
      });
      var defaultA = byFpi[0] ? byFpi[0].school : data.teams[0].school;
      var defaultB = byFpi[1] ? byFpi[1].school : (data.teams[1] ? data.teams[1].school : defaultA);

      populateSelect(aSelect, defaultA);
      populateSelect(bSelect, defaultB);

      if (loadingEl) loadingEl.hidden = true;
      cardWrap.hidden = false;
      render();
    }).catch(function (err) {
      console.error('[rankings-h2h] failed to load chart data', err);
      if (loadingEl) loadingEl.textContent = 'Could not load team data.';
    });
  }

  window.APSNHeadToHead = { init: init };
})();
