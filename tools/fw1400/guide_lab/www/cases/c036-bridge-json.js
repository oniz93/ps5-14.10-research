// c036: single variable - does a well-formed JSON message return, or does any call block?
// c035 established that _PS.postMessage('') never returns. This asks whether the bridge works at all.
(function () {
  function send(s) { try { navigator.sendBeacon('/beacon', 'c036-' + String(s)); } catch (e) {} }
  send('boot');
  var P = window._PS && window._PS.postMessage;
  if (typeof P !== 'function') { send('no-bridge'); return; }
  send('pre');
  var r, threw = '';
  try { r = P('{"type":"ping"}'); } catch (e) { threw = e.name; }
  send('post' + (threw ? ' threw:' + threw : ' ret=' + typeof r));
  setTimeout(function () { send('alive-3s'); }, 3000);
})();
