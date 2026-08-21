// Switches between the Graphs page's tabs (Bar / Scatter Plot / Head to
// Head). Each non-default tab's component is lazily initialized the first
// time its tab is opened, then never re-initialized on later switches --
// so a reader's axis/team selections survive flipping between tabs.
(function () {
  var tabs = [
    { btnId: 'tab-btn-bar', panelId: 'tab-panel-bar' },
    {
      btnId: 'tab-btn-scatter', panelId: 'tab-panel-scatter',
      init: function () {
        if (window.APSNCompare) window.APSNCompare.init(window.APSN_ACTIVE_BAR_STAT || null);
      },
    },
    {
      btnId: 'tab-btn-h2h', panelId: 'tab-panel-h2h',
      init: function () {
        if (window.APSNHeadToHead) window.APSNHeadToHead.init();
      },
    },
  ];

  var resolved = tabs.map(function (t) {
    return {
      btn: document.getElementById(t.btnId),
      panel: document.getElementById(t.panelId),
      init: t.init,
      initialized: false,
    };
  }).filter(function (t) { return t.btn && t.panel; });

  if (resolved.length < 2) return;

  function activate(target) {
    resolved.forEach(function (t) {
      var isActive = t === target;
      t.btn.classList.toggle('is-active', isActive);
      t.btn.setAttribute('aria-selected', String(isActive));
      t.panel.hidden = !isActive;
      if (isActive && !t.initialized && t.init) {
        t.initialized = true;
        t.init();
      }
    });
  }

  resolved.forEach(function (t) {
    t.btn.addEventListener('click', function () { activate(t); });
  });
})();
