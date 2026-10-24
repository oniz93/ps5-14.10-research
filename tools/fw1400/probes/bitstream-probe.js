// H.264 bitstream probe: mutates the codec layer, not the container.
//
// Round 2 closed the box parser: 32 structural mutations, nine of them reaching deep=playing
// with the demuxer and decoder actually running. Untouched is the codec layer - the avcC
// configuration record (SPS/PPS, parsed at init) and the length-prefixed NAL units in mdat.
// Those reach a different parser, and a hostile SPS is the classic way to make a decoder
// allocate by numbers it was told but never validated.
//
// Every case is played and seeked, and the beacon records the deepest event reached so that
// "accepted and stalled" cannot be mistaken for "decoded".

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

  window.onerror = function (m) { fire('B-ONERROR-' + m); };

  var CASES = ["valid", "cfg_sps_count_31", "cfg_sps_len_zero", "cfg_sps_len_huge", "cfg_pps_count_255", "sps_profile_ff", "sps_level_ff", "sps_zero_bytes", "sps_ff_bytes", "pps_zero_bytes", "pps_id_31", "cfg_lengthsize_3of4", "nal_len_zero", "nal_len_huge", "nal_forbidden_bit", "nal_type_zero", "nal_type_31", "nal_zero_body", "nal_ff_body", "nal_startcode_injected", "nal_len_swallows_mdat", "au_truncated_at_last_nal"];
  var MEDIA = 'video/mp4; codecs="avc1.42E01E"';

  fire('B-BOOT cases=' + CASES.length + ' ms=' + (typeof MediaSource));

  if (typeof MediaSource === 'undefined') { fire('B-NOMEDIASOURCE'); return; }

  function runOne(name) {
    return new Promise(function (resolve) {
      fire('B-RUN-' + name);
      fetch('/mp4b/' + name + '.mp4', { cache: 'no-store' })
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
          var wd = setTimeout(finish.bind(null, 'B-TIMEOUT'), 7000);

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

          video.addEventListener('error', function () { finish('B-VERR'); });
          video.addEventListener('loadedmetadata', function () { deepest = 'metadata'; });
          video.addEventListener('loadeddata', function () { deepest = 'data'; });
          video.addEventListener('canplay', function () { if (deepest !== 'playing') deepest = 'canplay'; });
          video.addEventListener('timeupdate', function () { if (deepest !== 'playing') deepest = 'timeupdate'; });
          video.addEventListener('playing', function () { deepest = 'playing'; });

          ms.addEventListener('sourceopen', function () {
            var sb;
            try { sb = ms.addSourceBuffer(MEDIA); }
            catch (e) { return finish('B-NOSB-' + e.name); }

            sb.addEventListener('updateend', function () {
              deepest = 'appended';
              fire('B-APP-' + name);
              var p = video.play();
              if (p && p.catch) p.catch(function () {});
              setTimeout(function () { try { video.currentTime = 0.15; } catch (e) {} }, 120);
              setTimeout(function () { finish('B-OK'); }, 1600);
            });
            sb.addEventListener('error', function () { finish('B-SBERR'); });

            try { sb.appendBuffer(buf); }
            catch (e) { finish('B-THREW-' + e.name); }
          });

          video.src = url;
        })
        .catch(function (e) {
          fire('B-FETCHFAIL-' + name + '-' + ((e && e.name) || 'x'));
          resolve();
        });
    });
  }

  (function loop(i) {
    if (i >= CASES.length) { fire('B-DONE n=' + CASES.length); return; }
    runOne(CASES[i]).then(function () { setTimeout(function () { loop(i + 1); }, 120); });
  })(0);
})();
