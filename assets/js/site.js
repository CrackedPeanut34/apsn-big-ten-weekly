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
