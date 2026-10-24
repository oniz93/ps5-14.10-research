// Capability map for the Sony-specific surfaces found by reading the shipped source.
//
// Everything below is a gate, not an attack. Each result decides whether an entire
// Sony-authored code path (never reviewed outside Sony, with no upstream fix to diff) is
// reachable from the Guide WebView at all:
//
//   media  -> MediaPlayerPrivatePlayStation.cpp (1249 lines), SourceBufferPrivatePlayStation,
//             MediaSamplePrivatePlayStation. The last one hands `append(data->data(),
//             data->size())` - a raw pointer into a SharedBuffer - to an opaque backend that
//             reports completion asynchronously, so a freed-buffer read is possible.
//   eme    -> CDMInstanceSessionPlayStation + CDMUtilPlayStation (Sony copyright 2019).
//             Note its callback queues are FIFO by position, not by request, so out-of-order
//             completion binds a result to the wrong request.
//   fonts  -> FontCachePlayStation / SystemFontDatabasePlayStation, plus FreeType/HarfBuzz.
//             No OpenTypeSanitizer exists in this tree, so bytes may reach FreeType raw.
//   xml    -> XMLDocumentParserLibxml2 -> Sony's system libxml2.
//   canvas -> the only channel that returns attacker-visible bytes from decoder output, i.e.
//             the exfiltration half of any exploit chain.
//
// Run it once. The beacon log is the record; the page prints the same lines.

(function () {
  const out = (s) => {
    try {
      let el = document.getElementById('log');
      if (!el) {
        el = document.createElement('pre');
        el.id = 'log';
        el.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;background:#000;color:#0f0;font:12px monospace;margin:0;padding:6px';
        (document.body || document.documentElement).appendChild(el);
      }
      el.textContent += s + '\n';
    } catch (e) {}
  };
  const fire = (tag) => {
    try { navigator.sendBeacon('/beacon/' + encodeURIComponent(tag), ''); } catch (e) {}
    out(tag);
  };

  fire('CAP-BOOT');

  // ---- media: does MSE exist, and which codecs will it accept? -------------------------
  fire('CAP-MediSource=' + (typeof MediaSource));
  fire('CAP-SourceBuffer=' + (typeof SourceBuffer));
  if (typeof MediaSource !== 'undefined') {
    const codecs = [
      'video/mp4; codecs="avc1.42E01E"',
      'audio/mp4; codecs="mp4a.40.2"',
      'video/webm; codecs="vp8"',
      'video/mp4; codecs="hvc1.1.6.L93.B0"'
    ];
    for (const c of codecs) {
      try {
        const ok = MediaSource.isTypeSupported(c);
        fire('CAP-MS-' + c.split(';')[0].split('/')[1] + '-' + (ok ? 'yes' : 'no'));
      } catch (e) {
        fire('CAP-MS-threw-' + e.name);
      }
    }
    // Can we actually get a SourceBuffer? That is the object that reaches Sony's append path.
    try {
      const ms = new MediaSource();
      const url = URL.createObjectURL(ms);
      const v = document.createElement('video');
      v.src = url;
      v.style.cssText = 'position:fixed;left:-9999px';
      document.body.appendChild(v);
      ms.addEventListener('sourceopen', function () {
        let sb = null;
        try {
          sb = ms.addSourceBuffer('video/mp4; codecs="avc1.42E01E"');
        } catch (e) {
          fire('CAP-SB-threw-' + e.name);
        }
        fire('CAP-SB=' + (sb ? 'yes' : 'no'));
        if (sb) {
          // Reachability of the raw-pointer append, without yet relying on freed memory:
          // a well-formed ftyp box is enough for the backend to start a parser.
          try {
            const box = new Uint8Array([
              0, 0, 0, 24, 0x66, 0x74, 0x79, 0x70, 0x69, 0x73, 0x6f, 0x6d,
              0, 0, 2, 0, 0x69, 0x73, 0x6f, 0x6d, 0x69, 0x73, 0x6f, 0x32
            ]);
            sb.appendBuffer(box);
            fire('CAP-APPEND-issued');
          } catch (e) {
            fire('CAP-APPEND-threw-' + e.name);
          }
        }
      });
      setTimeout(function () { fire('CAP-MSE-timeout-no-sourceopen'); }, 1500);
    } catch (e) {
      fire('CAP-MSE-threw-' + e.name);
    }
  }

  // ---- EME: Sony's 2019 CDM glue -------------------------------------------------------
  fire('CAP-requestMediaKeySystemAccess=' + (typeof navigator.requestMediaKeySystemAccess));
  if (typeof navigator.requestMediaKeySystemAccess === 'function') {
    const ks = ['com.widevine.alpha', 'com.microsoft.playready', 'org.w3.clearkey'];
    ks.forEach(function (name) {
      try {
        navigator.requestMediaKeySystemAccess(name, [{
          initDataTypes: ['cenc'],
          videoCapabilities: [{ contentType: 'video/mp4; codecs="avc1.42E01E"' }]
        }]).then(function (a) {
          fire('CAP-KS-' + name.split('.').pop() + '=yes');
        }, function (e) {
          fire('CAP-KS-' + name.split('.').pop() + '=no:' + e.name);
        });
      } catch (e) {
        fire('CAP-KS-' + name.split('.').pop() + '=threw');
      }
    });
  }

  // ---- fonts: raw bytes into FreeType/HarfBuzz ----------------------------------------
  fire('CAP-FontFace=' + (typeof FontFace));
  fire('CAP-document.fonts=' + (document.fonts ? 'yes' : 'no'));
  fire('CAP-woff2=' + (function () {
    try {
      const f = new FontFace('probe', 'url(data:font/woff2;base64,d09GMgABAAAAAA)');
      document.fonts.add(f);
      return 'accepted';
    } catch (e) { return 'threw'; }
  })());

  // ---- libxml2 path --------------------------------------------------------------------
  try {
    const d = new DOMParser().parseFromString('<a><b/></a>', 'application/xml');
    fire('CAP-DOMParser-xml=' + (d.documentElement ? d.documentElement.nodeName : 'null'));
  } catch (e) {
    fire('CAP-DOMParser-xml-threw-' + e.name);
  }

  // ---- the leak / exfiltration channel -------------------------------------------------
  try {
    const c = document.createElement('canvas');
    c.width = 8; c.height = 8;
    const ctx = c.getContext('2d');
    const img = ctx.getImageData(0, 0, 8, 8);
    fire('CAP-getImageData=' + (img.data.length === 256 ? 'ok' : 'odd'));
    // out-of-bounds request: upstream zero-fills, but this is the check that matters
    const oob = ctx.getImageData(-16, -16, 64, 64);
    let nonZero = 0;
    for (let i = 0; i < oob.data.length; i++) if (oob.data[i] !== 0) nonZero++;
    fire('CAP-OOB-imageData-nonzero=' + nonZero);
  } catch (e) {
    fire('CAP-canvas-threw-' + e.name);
  }

  // ---- chain enablers ------------------------------------------------------------------
  fire('CAP-ResizableArrayBuffer=' + (function () {
    try { new ArrayBuffer(16, { maxByteLength: 64 }); return 'yes'; } catch (e) { return 'no'; }
  })());

  fire('CAP-DONE');
})();
