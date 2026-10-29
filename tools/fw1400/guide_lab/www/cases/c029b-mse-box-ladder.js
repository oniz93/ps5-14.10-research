// c029b: same box ladder, fixed harness.
//
// Two bugs in c029, both mine: it used setImmediate (not guaranteed in a WebView) so a finishing case threw
// before the ladder advanced, and it only flushed at the next case's "pre" beacon, so any stall lost the
// results. Now every transition flushes immediately and advances with setTimeout.
(function () {
  function send(s) { try { navigator.sendBeacon('/beacon', 'c029b-' + s); } catch (e) {} }

  send('boot');
  if (typeof MediaSource === 'undefined') { send('no-MediaSource'); return; }
  var MIME = 'video/mp4; codecs="avc1.42E01E"';
  send('ms-' + (MediaSource.isTypeSupported(MIME) ? 'mp4-ok' : 'mp4-unsupported'));
  if (!MediaSource.isTypeSupported(MIME)) return;

  function u32(n) { return [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]; }
  function fourcc(s) { return [s.charCodeAt(0), s.charCodeAt(1), s.charCodeAt(2), s.charCodeAt(3)]; }
  function box(t, p) { return u32(8 + p.length).concat(fourcc(t), p); }
  function boxSized(size, t, p) { return u32(size).concat(fourcc(t), p); }

  var FTYP = box('ftyp', fourcc('isom').concat(u32(0x200)).concat(fourcc('isom')).concat(fourcc('mp41')));
  var cases = [
    ['A-ftyp',          FTYP],
    ['B-ftyp-moov',     FTYP.concat(box('moov', []))],
    ['C-size-zero',     boxSized(0, 'moov', [])],
    ['D-size-huge',     boxSized(0xFFFFFFFF, 'mvhd', [])],
    ['E-size-small',    boxSized(4, 'moov', [])],
    ['F-child-overrun', box('moov', boxSized(0x7FFFFFFF, 'trak', []))],
    ['G-deep-nest',     (function () { var b = box('moov', []); for (var i = 0; i < 12; i++) b = box('moov', b); return b; })()],
    ['H-truncated-hdr', u32(64).concat(fourcc('moo'))],
  ];

  var i = 0;
  function next() {
    if (i >= cases.length) { send('done-all'); return; }
    var name = cases[i][0], bytes = cases[i][1];
    i++;
    send('pre-' + name + '-len' + bytes.length);

    var done = false;
    function finish(tag) {
      if (done) return;
      done = true;
      send('post-' + name + (tag ? '-' + tag : ''));
      setTimeout(next, 60);
    }

    var ms, sb;
    try { ms = new MediaSource(); } catch (e) { finish('ms-threw:' + e.name); return; }
    var v = document.createElement('video');
    v.muted = true;
    v.src = URL.createObjectURL(ms);

    ms.addEventListener('sourceopen', function () {
      try { sb = ms.addSourceBuffer(MIME); } catch (e) { finish('addSB-threw:' + e.name); return; }
      sb.addEventListener('updateend', function () { finish('updateend'); });
      sb.addEventListener('error', function () { finish('sb-error'); });
      try { sb.appendBuffer(new Uint8Array(bytes).buffer); }
      catch (e) { finish('append-threw:' + e.name); return; }
      setTimeout(function () { finish('append-timeout'); }, 1200);
    });
    setTimeout(function () { finish('no-sourceopen'); }, 1500);
  }

  next();
})();
