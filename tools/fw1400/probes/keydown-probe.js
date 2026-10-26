// Report keyboard events from inside the Guide WebView.
//
// The question this answers: does a key pressed on the Pi's HID gadget reach *the page*, not merely the
// console's shell? Beacons fire on both keydown and keyup, so the log distinguishes three outcomes that
// look identical on a screenshot:
//
//   * `loaded` and nothing else   -> the page ran, but the WebView never received a key
//   * `kd-...` with no `ku-...`   -> a press arrived and the release did not (a stuck modifier in disguise)
//   * paired kd/ku                -> the full path works: gadget -> console -> Guide shell -> page
//
// The last key is also painted at 20vmin so OCR can read it off the screen when the beacon POST cannot
// get through (the console's TLS trust for this lab is a separate problem from input).

(function () {
    var seq = 0;
    var out = document.createElement('div');
    out.style.cssText = 'position:fixed;left:0;top:0;right:0;bottom:0;background:#000;color:#0f0;' +
        'font:700 20vmin/1.05 monospace;display:flex;align-items:center;justify-content:center;' +
        'text-align:center;word-break:break-all;z-index:2147483647';
    out.textContent = 'WAITING FOR KEY';
    document.documentElement.appendChild(out);

    function beacon(tag) {
        try {
            navigator.sendBeacon('/beacon/' + encodeURIComponent(tag), '');
        } catch (e) {
            // A failed beacon must not stop the on-screen display: the screen is the fallback oracle.
        }
    }

    function label(e) {
        var k = e.key === undefined ? '?' : String(e.key);
        return k.replace(/[^A-Za-z0-9]/g, '_');
    }

    window.addEventListener('keydown', function (e) {
        seq += 1;
        out.textContent = (e.key || '?') + ' #' + seq;
        beacon('kd-' + seq + '-' + label(e) + '-c' + e.keyCode);
    }, true);

    window.addEventListener('keyup', function (e) {
        beacon('ku-' + seq + '-' + label(e) + '-c' + e.keyCode);
    }, true);

    // A page in a fresh WebView may not hold focus until it is interacted with; ask for it explicitly.
    window.addEventListener('load', function () { try { window.focus(); } catch (e) {} });
    try { window.focus(); } catch (e) {}

    beacon('keyprobe-loaded');
})();
