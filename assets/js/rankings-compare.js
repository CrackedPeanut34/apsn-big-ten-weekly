// Compare tab: Plotly scatter plot, reads the same JSON the bar chart uses
// (rankings-chart.js). Independent component on purpose -- it only shares
// the data file and the page shell, not code, with the bar chart, so
// either can change without touching the other. Lazily initialized by
// dashboard-tabs.js the first time the Compare tab is opened (exposed as
// window.APSNCompare.init), so nothing here runs until a reader asks for
// it -- but the JSON fetch itself starts eagerly at load time so there's
// no visible delay on first switch.
(function () {
  var xSelect = document.getElementById('compare-x-select');
  var ySelect = document.getElementById('compare-y-select');
  var scatterOuter = document.getElementById('compare-scatter-outer');
  var plotDiv = document.getElementById('compare-scatter');
  var logoLayer = document.getElementById('compare-logo-layer');
  var markerButtons = document.querySelectorAll('.marker-mode-btn');
  var loadingEl = document.getElementById('compare-loading');
  if (!xSelect || !ySelect || !plotDiv || !logoLayer || typeof Plotly === 'undefined') return;

  // Same small presentation-only formatting duplicated in rankings-chart.js
  // -- deliberately not shared, these two charts are independent.
  function formatValue(key, v) {
    if (v === null || v === undefined) return '—';
    if (key === 'ap_rank') return 'No. ' + v;
    if (key === 'elo') return Math.round(v).toString();
    return v.toFixed(1);
  }

  // Sensible pairing when arriving from a Rankings-tab sort other than the
  // SP+/FPI default -- e.g. sorting the bar chart by SRS and switching to
  // Compare pairs SRS against SP+ rather than resetting to the flat default.
  var PAIR_DEFAULTS = { ap_rank: 'fpi', sp_plus: 'fpi', fpi: 'sp_plus', srs: 'sp_plus', elo: 'fpi' };

  var LOGO_PX = 34;
  var LOGO_PX_SHRUNK = 20;
  var PROXIMITY_PX = 30;

  var dataPromise = (typeof window.APSN_CHART_DATA_URL === 'string')
    ? fetch(window.APSN_CHART_DATA_URL).then(function (res) { return res.json(); })
    : Promise.reject(new Error('APSN_CHART_DATA_URL not set'));

  var state = { data: null, xKey: null, yKey: null, markerMode: 'logo' };
  var plotted = false;
  var resizeTimer = null;

  function statByKey(key) {
    return state.data.stats.filter(function (s) { return s.key === key; })[0];
  }

  function populateSelect(select, selectedKey) {
    select.innerHTML = '';
    state.data.stats.forEach(function (s) {
      var opt = document.createElement('option');
      opt.value = s.key;
      opt.textContent = s.label;
      if (s.key === selectedKey) opt.selected = true;
      select.appendChild(opt);
    });
  }

  function pickDefaultPair(hintKey) {
    var keys = state.data.stats.map(function (s) { return s.key; });
    if (hintKey && keys.indexOf(hintKey) !== -1) {
      var paired = PAIR_DEFAULTS[hintKey];
      if (paired && paired !== hintKey && keys.indexOf(paired) !== -1) return [hintKey, paired];
    }
    if (keys.indexOf('sp_plus') !== -1 && keys.indexOf('fpi') !== -1) return ['sp_plus', 'fpi'];
    return [keys[0], keys[1] || keys[0]];
  }

  // "Better" always reads up/right, regardless of whether the stat is a
  // rank (1 is best) or a rating (higher is best) -- reversing the range
  // for rank-type stats does this without ever altering the plotted value.
  function axisRange(stat, vals) {
    var min = Math.min.apply(null, vals);
    var max = Math.max.apply(null, vals);
    var pad = (max - min) * 0.15 || 1;
    var range = [min - pad, max + pad];
    if (stat.direction === 'asc') range.reverse();
    return range;
  }

  function axisTitle(stat) {
    var direction = stat.direction === 'asc' ? '← lower is better' : 'higher is better →';
    return stat.label + '  <span style="font-size:11px;color:#655f54;">(' + direction + ')</span>';
  }

  function currentPoints() {
    return state.data.teams.filter(function (t) {
      var xv = t.values[state.xKey], yv = t.values[state.yKey];
      return xv !== null && xv !== undefined && yv !== null && yv !== undefined;
    });
  }

  function render() {
    var xStat = statByKey(state.xKey);
    var yStat = statByKey(state.yKey);
    var points = currentPoints();
    var xVals = points.map(function (t) { return t.values[state.xKey]; });
    var yVals = points.map(function (t) { return t.values[state.yKey]; });
    var isLogoMode = state.markerMode === 'logo';

    var hoverText = points.map(function (t) {
      return '<b>' + t.school + '</b><br>' + xStat.label + ': ' + formatValue(state.xKey, t.values[state.xKey]) +
        '<br>' + yStat.label + ': ' + formatValue(state.yKey, t.values[state.yKey]) + '<extra></extra>';
    });

    var trace = {
      x: xVals,
      y: yVals,
      type: 'scatter',
      mode: isLogoMode ? 'markers' : 'markers+text',
      text: isLogoMode ? undefined : points.map(function (t) { return t.abbr; }),
      textposition: 'top center',
      textfont: { family: "'Inter', sans-serif", size: 11, color: '#1c1a16' },
      hovertemplate: hoverText,
      marker: isLogoMode
        ? { size: LOGO_PX, opacity: 0 }
        : { size: 12, color: points.map(function (t) { return t.color || '#cd242e'; }), line: { width: 1, color: 'rgba(0,0,0,0.3)' } },
    };

    var layout = {
      margin: { l: 60, r: 30, t: 20, b: 60 },
      xaxis: {
        title: { text: axisTitle(xStat) },
        range: axisRange(xStat, xVals),
        zeroline: false,
        gridcolor: 'rgba(0,0,0,0.07)',
        tickfont: { family: "'Inter', sans-serif", color: '#57524a' },
      },
      yaxis: {
        title: { text: axisTitle(yStat) },
        range: axisRange(yStat, yVals),
        zeroline: false,
        gridcolor: 'rgba(0,0,0,0.07)',
        tickfont: { family: "'Inter', sans-serif", color: '#57524a' },
      },
      font: { family: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif" },
      plot_bgcolor: 'rgba(0,0,0,0)',
      paper_bgcolor: 'rgba(0,0,0,0)',
      showlegend: false,
      hoverlabel: { bgcolor: '#1c1a16', font: { family: "'Inter', sans-serif" } },
    };

    Plotly.react(plotDiv, [trace], layout, { displayModeBar: false, responsive: true }).then(function () {
      if (isLogoMode) {
        renderLogoImages(points);
      } else {
        logoLayer.innerHTML = '';
      }
      if (!plotted) {
        plotted = true;
        plotDiv.on('plotly_relayout', function () {
          if (state.markerMode === 'logo') renderLogoImages(currentPoints());
        });
        window.addEventListener('resize', function () {
          clearTimeout(resizeTimer);
          resizeTimer = setTimeout(function () {
            if (state.markerMode === 'logo') renderLogoImages(currentPoints());
          }, 150);
        });
      }
    });
  }

  // Logo markers are plain <img> elements absolutely positioned on top of
  // the Plotly SVG (see .compare-logo-layer in site.css -- CORS is why,
  // not styling). Also does the proximity check here, since it already
  // has each point's real pixel position: a point with 2+ neighbors within
  // PROXIMITY_PX of it (itself + 2 = a cluster of 3+) gets its logo
  // shrunk. O(n^2) over <=18 teams, trivial -- not a full label-placement
  // solve.
  function renderLogoImages(points) {
    var xa = plotDiv._fullLayout.xaxis;
    var ya = plotDiv._fullLayout.yaxis;
    if (!xa || !ya) return;

    var xOffset = xa._offset || 0;
    var yOffset = ya._offset || 0;
    var pixelPositions = points.map(function (t) {
      return { x: xOffset + xa.d2p(t.values[state.xKey]), y: yOffset + ya.d2p(t.values[state.yKey]) };
    });

    var pixelSizes = pixelPositions.map(function (p, i) {
      var neighbors = 0;
      for (var j = 0; j < pixelPositions.length; j++) {
        if (j === i) continue;
        var dx = pixelPositions[j].x - p.x, dy = pixelPositions[j].y - p.y;
        if (Math.sqrt(dx * dx + dy * dy) <= PROXIMITY_PX) {
          neighbors++;
          if (neighbors >= 2) break;
        }
      }
      return neighbors >= 2 ? LOGO_PX_SHRUNK : LOGO_PX;
    });

    logoLayer.innerHTML = '';
    var fragment = document.createDocumentFragment();
    points.forEach(function (t, i) {
      if (!t.logo_url) return;
      var size = pixelSizes[i];
      var img = document.createElement('img');
      img.src = t.logo_url;
      img.alt = '';
      img.width = size;
      img.height = size;
      img.style.left = (pixelPositions[i].x - size / 2) + 'px';
      img.style.top = (pixelPositions[i].y - size / 2) + 'px';
      img.style.width = size + 'px';
      img.style.height = size + 'px';
      fragment.appendChild(img);
    });
    logoLayer.appendChild(fragment);
  }

  xSelect.addEventListener('change', function () {
    state.xKey = xSelect.value;
    render();
  });
  ySelect.addEventListener('change', function () {
    state.yKey = ySelect.value;
    render();
  });
  Array.prototype.forEach.call(markerButtons, function (btn) {
    btn.addEventListener('click', function () {
      if (btn.classList.contains('is-active')) return;
      state.markerMode = btn.dataset.markerMode;
      Array.prototype.forEach.call(markerButtons, function (b) { b.classList.toggle('is-active', b === btn); });
      render();
    });
  });

  function init(hintKey) {
    dataPromise.then(function (data) {
      state.data = data;
      var pair = pickDefaultPair(hintKey);
      state.xKey = pair[0];
      state.yKey = pair[1];
      populateSelect(xSelect, state.xKey);
      populateSelect(ySelect, state.yKey);
      if (loadingEl) loadingEl.hidden = true;
      scatterOuter.hidden = false;
      render();
    }).catch(function (err) {
      console.error('[rankings-compare] failed to load chart data', err);
      if (loadingEl) loadingEl.textContent = 'Could not load chart data.';
    });
  }

  window.APSNCompare = { init: init };
})();
