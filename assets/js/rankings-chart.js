// Sortable horizontal bar chart, driven entirely by the JSON file build.py
// exports alongside this page (one per week, same pinning rules as
// everything else -- see build_chart_export() in build.py). No server, no
// client-side data fetching beyond that one static file.
(function () {
  var canvas = document.getElementById('rankings-chart');
  var controlsEl = document.getElementById('chart-controls');
  if (!canvas || !controlsEl || typeof window.APSN_CHART_DATA_URL !== 'string') return;
  if (typeof Chart === 'undefined') return;

  // Presentation-only formatting for the raw value annotated on each bar
  // and shown in the tooltip -- mirrors build.py's RATING_FORMATS, kept
  // separate since that dict lives server-side in Python.
  var VALUE_FORMATS = {
    ap_rank: function (v) { return 'No. ' + v; },
    elo: function (v) { return Math.round(v).toString(); },
  };
  function formatValue(key, v) {
    return (VALUE_FORMATS[key] || function (n) { return n.toFixed(1); })(v);
  }

  fetch(window.APSN_CHART_DATA_URL)
    .then(function (res) { return res.json(); })
    .then(init)
    .catch(function (err) { console.error('[rankings-chart] failed to load chart data', err); });

  function init(data) {
    var stats = data.stats;
    var teams = data.teams;
    if (!stats.length || !teams.length) return;

    var logos = {};
    teams.forEach(function (t) {
      if (!t.logo_url) return;
      var img = new Image();
      img.onload = function () { chart.update(); };
      img.src = t.logo_url;
      logos[t.school] = img;
    });

    var style = getComputedStyle(document.body);
    var textColor = style.getPropertyValue('--text').trim() || '#1c1a16';
    var redColor = style.getPropertyValue('--red').trim() || '#cd242e';
    var fontFamily = "'Inter', -apple-system, BlinkMacSystemFont, sans-serif";

    // Draws each row's logo + school name in the reserved left gutter
    // (layout.padding.left, with the y-axis's own ticks turned off), plus
    // the true raw value just past the end of its bar -- so a rank-type
    // stat's bar can be drawn longer-is-better (see rowsForStat below)
    // without ever hiding the actual rank number from view.
    var labelsPlugin = {
      id: 'apsnLabels',
      afterDatasetsDraw: function (c) {
        var ctx = c.ctx;
        var meta = c.getDatasetMeta(0);
        var stat = c.$activeStat;
        ctx.save();
        meta.data.forEach(function (bar, i) {
          var row = c.$rows[i];
          var y = bar.y;
          var logoImg = logos[row.school];
          var logoSize = 22;
          if (logoImg && logoImg.complete && logoImg.naturalWidth) {
            ctx.drawImage(logoImg, 6, y - logoSize / 2, logoSize, logoSize);
          }
          ctx.fillStyle = textColor;
          ctx.font = "600 13px " + fontFamily;
          ctx.textBaseline = 'middle';
          ctx.textAlign = 'left';
          ctx.fillText(row.school, 6 + logoSize + 8, y);

          var rawValue = row.values[stat.key];
          ctx.font = "700 12px " + fontFamily;
          ctx.fillStyle = textColor;
          ctx.textAlign = 'left';
          ctx.fillText(formatValue(stat.key, rawValue), bar.x + 8, y);
        });
        ctx.restore();
      },
    };

    var chart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: { labels: [], datasets: [{ data: [], backgroundColor: redColor, borderRadius: 4, barPercentage: 0.7 }] },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { left: 150, right: 60, top: 8, bottom: 8 } },
        scales: {
          x: { display: false },
          y: {
            ticks: { display: false },
            grid: { display: false },
            border: { display: false },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (item) {
                var row = chart.$rows[item.dataIndex];
                var stat = chart.$activeStat;
                return row.school + ': ' + formatValue(stat.key, row.values[stat.key]);
              },
            },
          },
        },
        animation: { duration: 250 },
      },
      plugins: [labelsPlugin],
    });

    function rowsForStat(stat) {
      var rows = teams.filter(function (t) {
        var v = t.values[stat.key];
        return v !== null && v !== undefined;
      });
      rows.sort(function (a, b) {
        var av = a.values[stat.key], bv = b.values[stat.key];
        return stat.direction === 'asc' ? av - bv : bv - av;
      });
      return rows;
    }

    // Bar length always encodes "better = longer", regardless of whether
    // the underlying stat is rank-like (lower is better) or rating-like
    // (higher is better) -- the raw number is never altered, just drawn
    // via labelsPlugin above; only the bar's pixel length is transformed
    // for "asc" stats so the best team isn't stuck with the shortest bar.
    function barLengthsForStat(stat, rows) {
      if (stat.direction === 'desc') {
        return rows.map(function (r) { return r.values[stat.key]; });
      }
      var maxVal = rows.reduce(function (m, r) { return Math.max(m, r.values[stat.key]); }, 0);
      return rows.map(function (r) { return maxVal - r.values[stat.key] + 1; });
    }

    function selectStat(key) {
      var stat = stats.filter(function (s) { return s.key === key; })[0];
      var rows = rowsForStat(stat);

      chart.$activeStat = stat;
      chart.$rows = rows;
      chart.data.labels = rows.map(function (r) { return r.school; });
      chart.data.datasets[0].data = barLengthsForStat(stat, rows);
      chart.data.datasets[0].backgroundColor = rows.map(function (r) { return r.color || redColor; });
      canvas.parentElement.style.height = (rows.length * 34 + 40) + 'px';
      chart.update();

      Array.prototype.forEach.call(controlsEl.children, function (btn) {
        btn.classList.toggle('is-active', btn.dataset.statKey === key);
      });
    }

    stats.forEach(function (stat) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chart-stat-btn';
      btn.textContent = stat.label;
      btn.dataset.statKey = stat.key;
      btn.addEventListener('click', function () { selectStat(stat.key); });
      controlsEl.appendChild(btn);
    });

    var defaultKey = stats.some(function (s) { return s.key === 'fpi'; }) ? 'fpi' : stats[0].key;
    selectStat(defaultKey);
  }
})();
