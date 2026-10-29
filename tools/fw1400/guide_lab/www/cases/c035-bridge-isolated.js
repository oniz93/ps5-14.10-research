// c035: single-variable test - does _PS.postMessage('') alone cause memory exhaustion?
//
// c033 died right after pre-1-empty, but c029b had already leaked 16 MediaSource/video pairs with live object
// URLs, and the console has a history of LOW_MEMORY from exactly that. This run does nothing except the one
// call, so the code path and the leak are separated.
(function () {
  function send(s) { try { navigator.sendBeacon('/beacon', 'c035-' + String(s)); } catch (e) {} }
  send('boot');
  var P = (window._PS && window._PS.postMessage);
  if (typeof P !== 'function') { send('no-bridge'); return; }

  send('pre');
  var threw = '';
  try { P(''); } catch (e) { threw = e.name; }
  send('post happened' + (threw ? ' threw:' + threw : ''));
  setTimeout(function () { send('still-alive-3s'); }, 3000);
  setTimeout(function () { send('still-alive-8s'); }, 8000);
})();
