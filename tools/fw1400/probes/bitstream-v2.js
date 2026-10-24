// Bitstream probe v2: the decode oracle is requestVideoFrameCallback, not the playing event.
//
// Round 3 reported deep=playing for sps_zero_bytes and sps_ff_bytes - cases where the only
// parameter sets in the file were replaced by all-zeroes or all-0xFF. That cannot have been a
// successful decode. The reason is that for MSE, loadedmetadata / canplay / playing are driven by
// the demuxer's track information from moov, which every mutation in this corpus left intact. The
// element happily "plays" with a buffer that no decoder could turn into a picture.
//
// A frame presented is the only honest signal that a decoder ran and produced output.
// requestVideoFrameCallback fires exactly then. The canvas sample is a fallback for engines
// without rVFC: draw the video and count non-background pixels.

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

  window.onerror = function (m) { fire('V-ONERROR-' + m); };

  var CASES = ["valid", "cfg_sps_count_31", "cfg_sps_len_zero", "cfg_sps_len_huge", "cfg_pps_count_255", "sps_profile_ff", "sps_level_ff", "sps_zero_bytes", "sps_ff_bytes", "pps_zero_bytes", "pps_id_31", "cfg_lengthsize_3of4", "nal_len_zero", "nal_len_huge", "nal_forbidden_bit", "nal_type_zero", "nal_type_31", "nal_zero_body", "nal_ff_body", "nal_startcode_injected", "nal_len_swallows_mdat", "au_truncated_at_last_nal"];
  var MEDIA = 'video/mp4; codecs="avc1.42E01E"';

  var hasRVFC = (typeof HTMLVideoElement !== 'undefined') &&
                ('requestVideoFrameCallback' in HTMLVideoElement.prototype);
  var canvas = document.createElement('canvas');
  canvas.width = 64; canvas.height = 48;
  var ctx = canvas.getContext('2d');

  fire('V-BOOT cases=' + CASES.length + ' rvfc=' + (hasRVFC ? 'yes' : 'no'));

  function runOne(name) {
    return new Promise(function (resolve) {
      fire('V-RUN-' + name);
      fetch('/mp4b/' + name + '.mp4', { cache: 'no-store' })
        .then(function (r) { return r.arrayBuffer(); })
        .then(function (buf) {
          var video = document.createElement('video');
          video.muted = true;
          video.setAttribute('playsinline', '');
          video.style.cssText = 'position:fixed;left:1px;top:1px;width:64px;height:48px;opacity:0.02';
          document.body.appendChild(video);

          var ms = new MediaSource();
          var url = URL.createObjectURL(ms);
          var done = false, frames = 0, deepest = 'none';

          function finish(tag) {
            if (done) return;
            done = true;
            var nonBlack = -1;
            try {
              ctx.drawImage(video, 0, 0, 64, 48);
              var px = ctx.getImageData(0, 0, 64, 48).data;
              nonBlack = 0;
              for (var i = 0; i < px.length; i += 4) if (px[i] || px[i + 1] || px[i + 2]) nonBlack += 1;
            } catch (e) {}
            fire(tag + '-' + name + '-frames=' + frames + '-nonblack=' + nonBlack + '-deep=' + deepest);
            try { video.removeAttribute('src'); video.load(); } catch (e) {}
            try { video.remove(); } catch (e) {}
            try { URL.revokeObjectURL(url); } catch (e) {}
            resolve();
          }

          var wd = setTimeout(function () { finish('V-TIMEOUT'); }, 6000);

          function onFrame() {
            frames += 1;
            if (frames < 6) { try { video.requestVideoFrameCallback(onFrame); } catch (e) {} }
          }

          video.addEventListener('error', function () { clearTimeout(wd); finish('V-VERR'); });
          video.addEventListener('loadedmetadata', function () { deepest = 'metadata'; });
          video.addEventListener('canplay', function () { if (deepest !== 'playing') deepest = 'canplay'; });
          video.addEventListener('playing', function () { deepest = 'playing'; });

          ms.addEventListener('sourceopen', function () {
            var sb;
            try { sb = ms.addSourceBuffer(MEDIA); }
            catch (e) { clearTimeout(wd); return finish('V-NOSB-' + e.name); }

            sb.addEventListener('updateend', function () {
              deepest = 'appended';
              if (hasRVFC) { try { video.requestVideoFrameCallback(onFrame); } catch (e) {} }
              var p = video.play();
              if (p && p.catch) p.catch(function () {});
              setTimeout(function () { try { video.currentTime = 0.1; } catch (e) {} }, 150);
              setTimeout(function () { clearTimeout(wd); finish('V-OK'); }, 2200);
            });
            sb.addEventListener('error', function () { clearTimeout(wd); finish('V-SBERR'); });

            try { sb.appendBuffer(buf); }
            catch (e) { clearTimeout(wd); finish('V-THREW-' + e.name); }
          });

          video.src = url;
        })
        .catch(function (e) { fire('V-FETCHFAIL-' + name + '-' + ((e && e.name) || 'x')); resolve(); });
    });
  }

  (function loop(i) {
    if (i >= CASES.length) { fire('V-DONE n=' + CASES.length); return; }
    runOne(CASES[i]).then(function () { setTimeout(function () { loop(i + 1); }, 120); });
  })(0);
})();
