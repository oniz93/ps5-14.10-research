// c029: MSE appendBuffer with malformed ISO-BMFF boxes, aimed at Sony's closed demuxer.
//
// This is the one surface we cannot read: SourceBufferPrivatePlayStation.cpp:64 is just
//     m_playstation->append(data->data(), data->size());
// so everything that parses segment bytes happens inside Sony's media library. The console is the only oracle.
//
// Method: one append per case, a beacon before and after each. A crash kills the WebProcess, so the last
// "pre" beacon with no matching "post" identifies the case and the exact byte pattern that reached the parser.
// No case is expected to be safe or unsafe - the point is to learn where the parser stops validating.
(function () {
  var LOG = [];
  function note(s) { LOG.push(s); }
  function flush() { for (var i = 0; i < LOG.length; i++) { try { navigator.sendBeacon('/beacon', 'c029-' + LOG[i]); } catch (e) {} } }

  note('boot');

  // --- capability gate ---
  if (typeof MediaSource === 'undefined') { note('no-MediaSource'); flush(); return; }
  note('ms-' + (MediaSource.isTypeSupported('video/mp4; codecs="avc1.42E01E"') ? 'mp4-ok' : 'mp4-unsupported'));

  var MIME = 'video/mp4; codecs="avc1.42E01E"';
  if (!MediaSource.isTypeSupported(MIME)) { flush(); return; }

  // --- box builders -------------------------------------------------------
  function u32(n) { return [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]; }
  function fourcc(s) { return [s.charCodeAt(0), s.charCodeAt(1), s.charCodeAt(2), s.charCodeAt(3)]; }
  function box(type, payload) { return u32(8 + payload.length).concat(fourcc(type), payload); }
  function boxWithSize(size, type, payload) { return u32(size).concat(fourcc(type), payload); }

  var FTYP = box('ftyp', fourcc('isom').concat(u32(0x200)).concat(fourcc('isom')).concat(fourcc('mp41')));
  var MOOV_EMPTY = box('moov', []);

  // --- the ladder ---------------------------------------------------------
  var cases = [
    ['A-ftyp',          FTYP],                                  // control: a well-formed box
    ['B-ftyp-moov',     FTYP.concat(MOOV_EMPTY)],               // second box, zero payload
    ['C-size-zero',     boxWithSize(0, 'moov', [])],            // size 0 = "to end of file", invalid here
    ['D-size-huge',     boxWithSize(0xFFFFFFFF, 'mvhd', [])],   // claims 4 GB in a 16-byte buffer
    ['E-size-small',    boxWithSize(4, 'moov', [])],            // size smaller than the header itself
    ['F-child-overrun', box('moov', boxWithSize(0x7FFFFFFF, 'trak', []))],  // child claims more than parent
    ['G-deep-nest',     (function () {
                          var b = box('moov', []);
                          for (var i = 0; i < 12; i++) b = box('moov', b);
                          return b;
                        })()],
    ['H-truncated-hdr', u32(64).concat(fourcc('moo'))],         // header cut mid-fourcc
  ];

  // --- runner -------------------------------------------------------------
  var i = 0;

  function next() {
    if (i >= cases.length) { note('done-all'); flush(); return; }
    var name = cases[i][0], bytes = cases[i][1];
    i++;

    note('pre-' + name + '-len' + bytes.length);
    flush();                       // flush BEFORE the risky call: if the process dies, this is the marker

    var ms = new MediaSource();
    var v = document.createElement('video');
    v.muted = true;
    v.src = URL.createObjectURL(ms);

    var finished = false;
    function finish(tag) {
      if (finished) return;
      finished = true;
      note('post-' + name + (tag ? '-' + tag : ''));
      setImmediate(next);
    }

    ms.addEventListener('sourceopen', function () {
      var sb;
      try { sb = ms.addSourceBuffer(MIME); }
      catch (e) { finish('addSourceBuffer-threw:' + e.name); return; }

      var advanced = false;
      function after() {
        if (advanced) return;
        advanced = true;
        try { if (ms.readyState === 'open') ms.endOfStream(); } catch (e) {}
        finish('');
      }
      sb.addEventListener('updateend', after);
      sb.addEventListener('error', function () { after(); });

      try {
        sb.appendBuffer(new Uint8Array(bytes).buffer);
      } catch (e) {
        finish('append-threw:' + e.name);
        return;
      }
      // do not let a hung append stall the ladder
      setTimeout(function () { if (!advanced) { advanced = true; note('timeout-' + name); finish('timeout'); } }, 1500);
    });

    setTimeout(function () { if (!finished) finish('no-sourceopen'); }, 2500);
  }

  next();
})();
