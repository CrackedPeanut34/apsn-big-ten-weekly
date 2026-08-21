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

  // Crude, deliberately unbranded win-probability estimate: same shape as
  // the rest of the site's margin -> win-prob conversion (normal CDF, see
  // conversions.py's win_prob_from_margin/WIN_PROB_SIGMA), just run
  // client-side on the two teams' power ratings with no home-field term --
  // there's no real home team in a hypothetical pairing. Explicitly a
  // rough estimate, not one of the site's tracked prediction sources.
  var WIN_PROB_SIGMA = 16;

  function normalCdf(x) {
    var t = 1 / (1 + 0.2316419 * Math.abs(x));
    var d = 0.3989423 * Math.exp((-x * x) / 2);
    var prob = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
    return x > 0 ? 1 - prob : prob;
  }

  function estimatedWinProb(teamA, teamB) {
    var a = teamA.values.fpi, b = teamB.values.fpi;
    if (a === null || a === undefined || b === null || b === undefined) return null;
    return normalCdf((a - b) / WIN_PROB_SIGMA);
  }

  // A stat's "winner" for the highlight -- ties and missing values on
  // either side show no highlight rather than guessing.
  function statWinner(row) {
    if (row.aValue === null || row.aValue === undefined) return null;
    if (row.bValue === null || row.bValue === undefined) return null;
    if (row.aValue === row.bValue) return null;
    var aBetter = row.direction === 'asc' ? row.aValue < row.bValue : row.aValue > row.bValue;
    return aBetter ? 'a' : 'b';
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
    var rows = [{
      label: 'Record',
      a: teamA.record_display || '—', b: teamB.record_display || '—',
      aValue: teamA.record_value, bValue: teamB.record_value, direction: 'desc',
    }];
    state.data.stats.forEach(function (s) {
      rows.push({
        label: s.label,
        a: formatValue(s.key, teamA.values[s.key]),
        b: formatValue(s.key, teamB.values[s.key]),
        aValue: teamA.values[s.key], bValue: teamB.values[s.key], direction: s.direction,
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
      var w = statWinner(r);
      var aCls = 'num tabular' + (w === 'a' ? ' h2h-better' : '');
      var bCls = 'num tabular' + (w === 'b' ? ' h2h-better' : '');
      return '<tr><td class="' + aCls + '">' + r.a + '</td><th scope="row">' + r.label + '</th><td class="' + bCls + '">' + r.b + '</td></tr>';
    }).join('');

    var winProbA = estimatedWinProb(teamA, teamB);
    var winProbHtml = '';
    if (winProbA !== null) {
      var pctA = Math.round(winProbA * 100);
      var pctB = 100 - pctA;
      winProbHtml =
        '<div class="h2h-winprob">' +
          '<div class="h2h-winprob-row">' +
            '<span class="h2h-winprob-pct">' + pctA + '%</span>' +
            '<span class="h2h-winprob-label">Estimated win probability</span>' +
            '<span class="h2h-winprob-pct">' + pctB + '%</span>' +
          '</div>' +
          '<div class="h2h-winprob-bar"><span class="h2h-winprob-fill" style="width:' + pctA + '%;"></span></div>' +
        '</div>';
    }

    cardWrap.innerHTML =
      '<article class="game-card" style="--away-color:' + (teamA.color || 'var(--border)') + '; --home-color:' + (teamB.color || 'var(--border)') + ';">' +
        '<header class="game-card-header">' +
          '<div class="matchup">' +
            '<div class="team team-away">' +
              '<img class="team-logo" src="' + (teamA.logo_url || '') + '" alt="' + teamA.school + ' logo" loading="lazy">' +
              apBadge(teamA) +
              '<span class="team-name">' + teamA.school + '</span>' +
            '</div>' +
            '<span class="matchup-at h2h-vs">vs</span>' +
            '<div class="team team-home">' +
              '<img class="team-logo" src="' + (teamB.logo_url || '') + '" alt="' + teamB.school + ' logo" loading="lazy">' +
              apBadge(teamB) +
              '<span class="team-name">' + teamB.school + '</span>' +
            '</div>' +
          '</div>' +
          '<div class="game-meta"><span class="kickoff">Season-long comparison, not a scheduled game</span></div>' +
        '</header>' +
        winProbHtml +
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
