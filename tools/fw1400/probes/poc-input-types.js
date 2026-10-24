// What form controls does this WebView actually support?
//
// The date-input probe showed `input.type = 'date'` behaving as a plain text field
// ("922012" typed straight through), which is what WebKit does when the type is not
// enabled: InputType::create() gates each type behind a runtime setting
// (Settings::inputTypeDateEnabled, inputTypeColorEnabled, …), and an unsupported type
// silently stays 'text'.
//
// So measure the surface instead of assuming it. Every input path that dispatches
// events from trusted input (choosers, sliders, pickers) is a reentrancy surface of the
// same class as the date-input UAF, and only the ones that survive this list are worth
// auditing.
(function () {
  var SENT = {};
  function B(tag) {
    if (SENT[tag]) return;
    SENT[tag] = 1;
    try { navigator.sendBeacon('/beacon/' + tag + '?t=' + Date.now()); } catch (e) {}
  }

  var types = ['text', 'date', 'time', 'datetime-local', 'month', 'week', 'color',
               'range', 'number', 'search', 'email', 'url', 'tel', 'file', 'checkbox', 'radio'];

  var supported = [];
  var unsupported = [];
  var rows = [];

  types.forEach(function (t) {
    var el = document.createElement('input');
    el.type = t;
    var actual = el.type;              // 'text' means the type was rejected
    (actual === t ? supported : unsupported).push(t + (actual === t ? '' : '->' + actual));
    rows.push('<tr><td style="padding:2px 12px">' + t + '</td><td>' + actual +
              '</td><td>' + (actual === t ? 'yes' : 'no') + '</td></tr>');
  });

  B('IF-SUPPORTED-' + supported.join('_').replace(/[^A-Za-z0-9_-]/g, ''));
  B('IF-REJECTED-' + unsupported.join('_').replace(/[^A-Za-z0-9_>-]/g, ''));
  B('IF-COUNTS-' + supported.length + 'of' + types.length);

  document.body.style.background = '#0b0b0b';
  document.body.style.color = '#eee';
  document.body.style.font = '20px/1.4 monospace';
  document.body.style.padding = '22px';
  document.body.innerHTML =
    '<h2 style="color:#7fd1ff;margin:0 0 12px">input types on this build</h2>' +
    '<table style="border-collapse:collapse">' +
    '<tr><th align="left">requested</th><th align="left">actual</th><th align="left">supported</th></tr>' +
    rows.join('') + '</table>' +
    '<p style="color:#8f8">' + supported.length + ' of ' + types.length + ' supported</p>';
})();
