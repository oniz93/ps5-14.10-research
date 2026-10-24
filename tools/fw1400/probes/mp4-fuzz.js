// MP4 box-mutation fuzz against Sony's proprietary MSE backend.
//
// The append *data* path is cleared (PSSourceBufferBackend::append copies - proven by
// mse-append-churn.js), but the backend still parses every byte a page gives it, and a valid
// fragmented MP4 produced a clean updateend on retail 14.10. That parser is in Sony's SDK and
// appears nowhere in the OSS drop, so nothing outside Sony has read it.
//
// Each case gets a FRESH video + MediaSource + SourceBuffer: a poisoned SourceBuffer after a
// malformed append would otherwise taint every later result, and this way a crash names exactly
// one input. Cost is roughly a second of sourceopen per case.
//
// Reading the result:
//   M-OK-<case>        parsed and produced updateend (or a benign error event)
//   M-ERR-<case>       appendBuffer threw synchronously (InvalidState / QuotaExceeded ...)
//   M-NOSB-<case>      addSourceBuffer or sourceopen failed - pipeline unusable for this case
//   silence after M-RUN-<case>  -> that case killed the WebProcess

(function () {
  'use strict';
  var BASE = 'https://manuals.playstation.net';
  var seq = 0;

  function fire(tag) {
    seq += 1;
    var url = BASE + '/beacon/' + ('000' + seq).slice(-4) + '-' + encodeURIComponent(tag);
    try {
      (navigator.sendBeacon && navigator.sendBeacon(url, '')) ||
        fetch(url, { method: 'POST', body: '', keepalive: true, mode: 'no-cors' }).catch(function () {});
    } catch (e) {}
    try { console.log(tag); } catch (e) {}
  }

  window.onerror = function (m) { fire('M-ONERROR-' + m); };

  var CASES = [
    'valid',
    'ftyp_size_zero', 'ftyp_size_one_lying_largesize', 'ftyp_size_lt_header',
    'ftyp_size_beyond_file', 'ftyp_type_swap',
    'moov_size_zero', 'moov_size_one_lying_largesize', 'moov_size_lt_header',
    'moov_size_beyond_file', 'moov_type_swap',
    'moof_size_zero', 'moof_size_one_lying_largesize', 'moof_size_lt_header',
    'moof_size_beyond_file', 'moof_type_swap',
    'mdat_size_zero', 'mdat_size_one_lying_largesize', 'mdat_size_lt_header',
    'mdat_size_beyond_file', 'mdat_type_swap',
    'mvhd_timescale_zero', 'mvhd_duration_huge', 'trak_type_swap',
    'tfhd_flags_all', 'trun_sample_count_huge', 'moov_nesting_64', 'moof_alias_moov_offset',
    'trunc_in_ftyp', 'trunc_in_moov', 'trunc_in_moof', 'trunc_in_mdat'
  ];

  var MEDIA = 'video/mp4; codecs="avc1.42E01E"';

  fire('M-BOOT cases=' + CASES.length +
       ' ms=' + (typeof MediaSource) +
       ' sb=' + (typeof SourceBuffer));

  if (typeof MediaSource === 'undefined') { fire('M-NOMEDIASOURCE'); return; }

  // One case = one fresh pipeline.
  function attempt(name, buf) {
    return new Promise(function (resolve) {
      var video = document.createElement('video');
      video.muted = true;
      video.setAttribute('playsinline', '');
      video.style.cssText = 'position:fixed;left:-2px;top:-2px;width:2px;height:2px;opacity:0.01';
      document.body.appendChild(video);

      var ms = new MediaSource();
      var url = URL.createObjectURL(ms);
      var settled = false;
      var watchdog = setTimeout(function () {
        if (!settled) { settled = true; fire('M-NOSB-' + name + '-sourceopen'); cleanup(); }
      }, 6000);

      function cleanup() {
        try { video.removeAttribute('src'); video.load(); } catch (e) {}
        try { video.remove(); } catch (e) {}
        try { URL.revokeObjectURL(url); } catch (e) {}
        resolve();
      }

      ms.addEventListener('sourceopen', function () {
        var sb;
        try {
          sb = ms.addSourceBuffer(MEDIA);
        } catch (e) {
          clearTimeout(watchdog);
          if (!settled) { settled = true; fire('M-NOSB-' + name + '-add-' + e.name); cleanup(); }
          return;
        }

        var done = false;
        function finish(tag) {
          if (done) return;
          done = true;
          clearTimeout(watchdog);
          fire(tag + '-' + name);
          setTimeout(cleanup, 20);
        }

        sb.addEventListener('updateend', function () { finish('M-OK'); });
        sb.addEventListener('error', function () { finish('M-EVENTERR'); });
        setTimeout(function () { finish('M-TIMEOUT'); }, 4000);

        try {
          sb.appendBuffer(buf);
        } catch (e) {
          finish('M-ERR-' + e.name);
        }
      });

      video.src = url;
    });
  }

  function run(i) {
    if (i >= CASES.length) { fire('M-DONE n=' + CASES.length); return; }
    var name = CASES[i];
    fire('M-RUN-' + name);
    fetch('/mp4/' + name + '.mp4', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('http' + r.status); return r.arrayBuffer(); })
      .then(function (buf) {
        fire('M-GOT-' + name + '-b' + buf.byteLength);
        return attempt(name, buf);
      })
      .catch(function (e) {
        fire('M-FETCHFAIL-' + name + '-' + ((e && e.name) || 'x'));
      })
      .then(function () {
        // small gap so the backend task queue drains before the next pipeline
        setTimeout(function () { run(i + 1); }, 120);
      });
  }

  setTimeout(function () { run(0); }, 300);
})();
