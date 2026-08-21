// Switches between the Rankings (bar chart) and Compare (scatter) panels.
// The only coupling to either component: reads window.APSN_ACTIVE_BAR_STAT
// (kept up to date by rankings-chart.js) once, the first time Compare is
// opened, so its default axis pairing can follow whatever the bar chart
// was sorted by -- see rankings-compare.js's pickDefaultPair. After that
// first open, switching tabs never resets Compare's own selections.
(function () {
  var rankingsBtn = document.getElementById('tab-btn-rankings');
  var compareBtn = document.getElementById('tab-btn-compare');
  var rankingsPanel = document.getElementById('tab-panel-rankings');
  var comparePanel = document.getElementById('tab-panel-compare');
  if (!rankingsBtn || !compareBtn || !rankingsPanel || !comparePanel) return;

  var compareInitialized = false;

  function activate(showCompare) {
    rankingsBtn.classList.toggle('is-active', !showCompare);
    compareBtn.classList.toggle('is-active', showCompare);
    rankingsBtn.setAttribute('aria-selected', String(!showCompare));
    compareBtn.setAttribute('aria-selected', String(showCompare));
    rankingsPanel.hidden = showCompare;
    comparePanel.hidden = !showCompare;

    if (showCompare && !compareInitialized && window.APSNCompare) {
      compareInitialized = true;
      window.APSNCompare.init(window.APSN_ACTIVE_BAR_STAT || null);
    }
  }

  rankingsBtn.addEventListener('click', function () { activate(false); });
  compareBtn.addEventListener('click', function () { activate(true); });
})();
