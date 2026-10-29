// c037: does the Guide shell register custom URI schemes, and does it act on them?
//
// A WKWebView host decides via a navigation policy delegate what to do with an unknown scheme. On consoles that
// delegate is often wired to native functionality, and the parsing on the other side is Sony's own code. Nothing
// in the drop describes it, so the only way to learn is to ask.
//
// Every probe runs inside a throwaway iframe so a handler that navigates cannot take the page with it, each is
// preceded by a beacon, and the whole set has a hard timeout. Top-level navigation is attempted last and only
// for a scheme that showed any sign of being handled.
(function () {
  function send(s) { try { navigator.sendBeacon('/beacon', 'c037-' + String(s)); } catch (e) {} }
  send('boot');

  var SCHEMES = ['ps5', 'playstation', 'ps', 'sce', 'sony', 'psn', 'store', 'guide', 'remoteplay', 'system'];
  var i = 0;
  var reacted = [];

  function probeScheme(name) {
    return new Promise(function (resolve) {
      send('pre-' + name);
      var done = false;
      var frame = document.createElement('iframe');
      frame.style.cssText = 'width:1px;height:1px;opacity:0.01';
      function finish(tag) {
        if (done) return;
        done = true;
        send('res-' + name + ':' + tag);
        try { frame.remove(); } catch (e) {}
        resolve();
      }
      frame.onload = function () { finish('load'); };
      frame.onerror = function () { finish('error'); };
      document.body.appendChild(frame);
      try { frame.src = name + '://probe'; }
      catch (e) { finish('assign-threw:' + e.name); }
      setTimeout(function () { finish('nocallback'); }, 900);
    });
  }

  function next() {
    if (i >= SCHEMES.length) {
      send('summary:' + (reacted.length ? reacted.join(',') : 'no-reactions'));
      send('done-all');
      return;
    }
    var s = SCHEMES[i++];
    probeScheme(s).then(function () { setTimeout(next, 120); });
  }

  // a page-driven anchor click is the other common path into the delegate
  function anchorProbe() {
    send('pre-anchor');
    try {
      var a = document.createElement('a');
      a.href = 'ps5://probe';
      document.body.appendChild(a);
      a.click();
      a.remove();
      send('res-anchor:clicked');
    } catch (e) { send('res-anchor:threw:' + e.name); }
  }

  next();
  setTimeout(anchorProbe, (SCHEMES.length + 1) * 1100);
})();
