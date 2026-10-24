// Are any automation/debug services listening on the console itself?
//
// The 14.x port is built with ENABLE_WEBDRIVER=ON (keyboard and mouse interactions
// explicitly enabled) and ENABLE_REMOTE_INSPECTOR=ON, which sets
// USE_INSPECTOR_SOCKET_SERVER=ON. If either is actually listening on a loopback port at
// runtime, programmable input and JS evaluation exist without any memory corruption -
// which matters a great deal for a bug that needs real key events.
//
// WebKit's own page is https, so this may be blocked as mixed content. WebKit treats
// loopback as potentially trustworthy, so it is worth measuring rather than assuming.
(function () {
  var SENT = {};
  function B(tag) {
    if (SENT[tag]) return;
    SENT[tag] = 1;
    try { navigator.sendBeacon('/beacon/' + tag + '?t=' + Date.now()); } catch (e) {}
  }

  function head(port, path) {
    var url = 'http://127.0.0.1:' + port + path;
    return new Promise(function (resolve) {
      var done = false;
      var timer = setTimeout(function () {
        if (!done) { done = true; resolve('timeout'); }
      }, 1200);
      fetch(url, { mode: 'cors', cache: 'no-store' })
        .then(function (r) {
          if (done) return;
          done = true; clearTimeout(timer);
          resolve('http' + r.status);
        })
        .catch(function (e) {
          if (done) return;
          done = true; clearTimeout(timer);
          resolve('err:' + (e && e.name ? e.name : 'fail'));
        });
    });
  }

  // WebDriver 9515 is the WebKit default; 4444 is Selenium; 9222/9223 are Chromium-style
  // inspector ports that some WebKit ports also use; 8090/8081 show up in embedder code.
  var targets = [
    [9515, '/status'], [9516, '/status'], [4444, '/status'],
    [9222, '/json/version'], [9223, '/json/version'],
    [8080, '/'], [3000, '/']
  ];

  B('LS-BOOT');

  var i = 0;
  function next() {
    if (i >= targets.length) { B('LS-DONE'); render('done - see beacons'); return; }
    var t = targets[i++];
    head(t[0], t[1]).then(function (res) {
      B('LS-' + t[0] + '-' + res.replace(/[^a-z0-9]/gi, ''));
      next();
    });
  }

  function render(msg) {
    document.body.style.background = '#111';
    document.body.style.color = '#eee';
    document.body.style.font = '22px/1.5 monospace';
    document.body.innerHTML = '<div style="padding:28px"><h2>local services</h2>'
      + '<p>' + msg + '</p></div>';
  }

  render('probing loopback ports…');
  setTimeout(next, 300);
})();
