// Combined round 2: fonts with real glyph rendering, and MP4 with the pipeline actually driven.
//
// Round 1 was clean but shallow, and the logs said so:
//   * every font reported w150 because the base font is NotoSansLepcha and the probe rendered
//     Latin text, so the system font was substituted and no glyph outlines were ever parsed.
//     Face creation was exercised (that is where the four rejections came from), not glyf/fpgm/prep.
//   * every MP4 reported updateend, which means the bytes were accepted, not demuxed - nothing
//     ever played the media, so the box parser was barely driven.
//
// Round 2 fixes both: Lepcha codepoints force the real outlines through FreeType's glyph loader
// and hinting interpreter, and each MP4 case is played and seeked so the demuxer runs.

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

  window.onerror = function (m) { fire('X-ONERROR-' + m); };

  var FONTS = ["valid", "hdmx_numrecords_huge", "hdmx_sizedevice_zero", "hdmx_count_times_size_overflow", "maxp_numglyphs_huge", "maxp_numglyphs_zero", "loca_short", "loca_empty", "loca_offsets_past_glyf", "glyf_glyph_span_huge", "cmap_subtable_offset_oob", "cmap_format4_segcount_huge", "head_unitsperem_zero", "head_magic_bad", "head_locformat_bad", "name_count_huge", "post_numglyphs_huge", "fpgm_inflated", "prep_huge", "dirent_numtables_huge", "dirent_numtables_zero", "dirent_offset_overflow", "dirent_length_huge", "dirent_overlap", "trunc_8", "trunc_header", "trunc_half", "trunc_tail"];
  var MP4S  = ["valid", "ftyp_size_zero", "ftyp_size_one_lying_largesize", "ftyp_size_lt_header", "ftyp_size_beyond_file", "ftyp_type_swap", "moov_size_zero", "moov_size_one_lying_largesize", "moov_size_lt_header", "moov_size_beyond_file", "moov_type_swap", "moof_size_zero", "moof_size_one_lying_largesize", "moof_size_lt_header", "moof_size_beyond_file", "moof_type_swap", "mdat_size_zero", "mdat_size_one_lying_largesize", "mdat_size_lt_header", "mdat_size_beyond_file", "mdat_type_swap", "mvhd_timescale_zero", "mvhd_duration_huge", "trak_type_swap", "tfhd_flags_all", "trun_sample_count_huge", "moov_nesting_64", "moof_alias_moov_offset", "trunc_in_ftyp", "trunc_in_moov", "trunc_in_moof", "trunc_in_mdat"];

  // Lepcha block: this base font actually contains these, so the outlines get parsed.
  var LEPCHA = '\u1C00\u1C01\u1C02\u1C03\u1C04\u1C05\u1C06\u1C07';

  var canvas = document.createElement('canvas');
  canvas.width = 260; canvas.height = 64;
  var ctx = canvas.getContext('2d');

  function measure(text, family, px) {
    var s = document.createElement('span');
    s.style.cssText = 'position:fixed;left:-4px;top:-4px;white-space:pre;font-size:' + px +
                      'px;font-family:' + (family ? '"' + family + '"' : 'monospace');
    s.textContent = text;
    document.body.appendChild(s);
    var w = s.offsetWidth;
    s.remove();
    return w;
  }

  fire('X-BOOT fonts=' + FONTS.length + ' mp4=' + MP4S.length);

  // ---------------------------------------------------------------- fonts
  var fallbackLepcha = measure(LEPCHA, null, 28);
  fire('X-FALLBACK-LEPCHA-w' + fallbackLepcha);

  function runFont(name, i) {
    var family = 'x_' + name;
    fire('F2-RUN-' + name);
    return fetch('/fonts/' + name + '.ttf', { cache: 'no-store' }).then(function (r) {
      return r.arrayBuffer();
    }).then(function (buf) {
      var face = new FontFace(family, buf);
      return face.load().then(function (loaded) {
        document.fonts.add(loaded);
        var registered = document.fonts.check('28px "' + family + '"');

        // Real outlines: layout, canvas raster, and a readback.
        var wLep = measure(LEPCHA, family, 28);
        try {
          ctx.clearRect(0, 0, 260, 64);
          ctx.font = '28px "' + family + '"';
          ctx.fillStyle = '#fff';
          ctx.fillText(LEPCHA, 2, 40);
          ctx.getImageData(0, 0, 260, 64);
        } catch (e) { fire('F2-CANVAS-THREW-' + name + '-' + e.name); }

        // applied=yes means the width differs from the monospace fallback, i.e. the font's own
        // outlines/metrics were used rather than a substitute.
        var applied = (wLep !== fallbackLepcha) ? 'yes' : 'same';
        fire('F2-OK-' + name + '-reg' + (registered ? 1 : 0) + '-applied' + applied + '-w' + wLep);
      }, function (err) {
        fire('F2-REJ-' + name + '-' + ((err && err.name) || 'unknown'));
      });
    }).catch(function (e) {
      fire('F2-FETCHFAIL-' + name + '-' + ((e && e.name) || 'x'));
    });
  }

  // ---------------------------------------------------------------- mp4
  var MEDIA = 'video/mp4; codecs="avc1.42E01E"';

  function runMp4(name) {
    return new Promise(function (resolve) {
      fire('M2-RUN-' + name);
      fetch('/mp4/' + name + '.mp4', { cache: 'no-store' })
        .then(function (r) { return r.arrayBuffer(); })
        .then(function (buf) {
          var video = document.createElement('video');
          video.muted = true;
          video.setAttribute('playsinline', '');
          video.style.cssText = 'position:fixed;left:-2px;top:-2px;width:2px;height:2px;opacity:0.01';
          document.body.appendChild(video);

          var ms = new MediaSource();
          var url = URL.createObjectURL(ms);
          var done = false;
          var deepest = 'none';
          var wd = setTimeout(finish.bind(null, 'M2-TIMEOUT'), 7000);

          function finish(tag) {
            if (done) return;
            done = true;
            clearTimeout(wd);
            fire(tag + '-' + name + '-deep=' + deepest);
            try { video.removeAttribute('src'); video.load(); } catch (e) {}
            try { video.remove(); } catch (e) {}
            try { URL.revokeObjectURL(url); } catch (e) {}
            resolve();
          }

          video.addEventListener('error', function () { finish('M2-VERR'); });
          video.addEventListener('loadedmetadata', function () { deepest = 'metadata'; });
          video.addEventListener('loadeddata', function () { deepest = 'data'; });
          video.addEventListener('canplay', function () { deepest = 'canplay'; });
          video.addEventListener('timeupdate', function () { if (deepest !== 'playing') deepest = 'timeupdate'; });
          video.addEventListener('playing', function () { deepest = 'playing'; });

          ms.addEventListener('sourceopen', function () {
            var sb;
            try { sb = ms.addSourceBuffer(MEDIA); }
            catch (e) { return finish('M2-NOSB-' + e.name); }

            sb.addEventListener('updateend', function () {
              // The append was accepted. Now force the demuxer: play, then seek into the sample.
              deepest = 'appended';
              fire('M2-APP-' + name);
              var p = video.play();
              if (p && p.catch) p.catch(function () {});
              setTimeout(function () {
                try { video.currentTime = 0.15; } catch (e) {}
              }, 150);
              // finish() is armed by the watchdog, or fires earlier on error
              setTimeout(function () { finish('M2-OK'); }, 1800);
            });
            sb.addEventListener('error', function () { finish('M2-SBERR'); });

            try { sb.appendBuffer(buf); }
            catch (e) { finish('M2-THREW-' + e.name); }
          });

          video.src = url;
        })
        .catch(function (e) { fire('M2-FETCHFAIL-' + name + '-' + ((e && e.name) || 'x')); resolve(); });
    });
  }

  // ---------------------------------------------------------------- driver
  function fontsLoop(i) {
    if (i >= FONTS.length) { fire('F2-DONE'); mp4Loop(0); return; }
    runFont(FONTS[i], i).then(function () { setTimeout(function () { fontsLoop(i + 1); }, 50); });
  }
  function mp4Loop(i) {
    if (i >= MP4S.length) { fire('X-DONE'); return; }
    runMp4(MP4S[i]).then(function () { setTimeout(function () { mp4Loop(i + 1); }, 100); });
  }

  setTimeout(function () { fontsLoop(0); }, 250);
})();
