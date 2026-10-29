// c030: enumerate the JS surface Sony exposes in the Guide WebView.
//
// The Guide is a WKWebView-class host. If Sony added a native bridge (window.webkit.messageHandlers on Apple
// ports, or their own global), that is a direct path into their code and far more valuable than fuzzing a
// closed demuxer. Also reports globals that are not standard, so anything PlayStation-specific shows up.
(function () {
  function send(s) { try { navigator.sendBeacon('/beacon', 'c030-' + s); } catch (e) {} }

  // globals that any WebKit build would have - anything outside this list is interesting
  var KNOWN = ('window self document navigator location history screen frames parent top opener closed length ' +
    'name status devicePixelRatio innerWidth innerHeight outerWidth outerHeight scrollX scrollY pageXOffset ' +
    'pageYOffset screenX screenY scrollTo scroll scrollBy moveTo moveBy resizeTo resizeBy getComputedStyle ' +
    'matchMedia requestAnimationFrame cancelAnimationFrame setTimeout clearTimeout setInterval clearInterval ' +
    'postMessage addEventListener removeEventListener dispatchEvent alert confirm prompt print open close stop ' +
    'focus blur atob btoa fetch queueMicrotask structuredClone reportError performance crypto caches indexedDB ' +
    'localStorage sessionStorage console customElements trustedTypes visualViewport CSS CSSStyleSheet ' +
    'CSSStyleDeclaration CSSRule CSSKeyframeRule origin isSecureContext crossOriginIsolated event ' +
    'WebSocket Worker SharedWorker MessageChannel MessagePort MessageEvent BroadcastChannel Blob File FileReader ' +
    'FormData Headers Request Response AbortController AbortSignal URL URLSearchParams TextEncoder TextDecoder ' +
    'ReadableStream WritableStream TransformStream ByteLengthQueuingStrategy CountQueuingStrategy ' +
    'CompressionStream DecompressionStream DOMException EventTarget Event CustomEvent ' +
    'Image Audio Option AudioContext OfflineAudioContext MediaSource SourceBuffer ManagedMediaSource ' +
    'MediaRecorder RTCPeerConnection SpeechSynthesis SpeechSynthesisUtterance Notification ' +
    'DOMParser XMLSerializer XMLHttpRequest ImageData ImageBitmap createImageBitmap Path2D CanvasGradient ' +
    'CanvasPattern WebGLRenderingContext WebGL2RenderingContext OffscreenCanvas ' +
    'Element Node Document HTMLDocument HTMLElement SVGElement Text Comment DocumentFragment ShadowRoot ' +
    'Range Selection CaretPosition DOMPoint DOMPointReadOnly DOMRect DOMRectReadOnly DOMQuad DOMMatrix ' +
    'MutationObserver IntersectionObserver ResizeObserver PerformanceObserver ReportingObserver ' +
    'FontFace FontFaceSet getSelection scrollbars showModalDialog find ' +
    'webkitRequestAnimationFrame webkitCancelAnimationFrame webkitCancelRequestAnimationFrame ' +
    'webkitURL webkitRTCPeerConnection webkitSpeechRecognition webkitSpeechSynthesis ' +
    'onload onerror onresize onscroll onfocus onblur onclick onkeydown onkeyup onpointerdown ' +
    'Gamepad GamepadButton GamepadEvent Navigator Screen Performance PerformanceEntry ' +
    'DataTransfer DataTransferItem DataTransferItemList DragEvent ClipboardEvent ' +
    'HTMLCanvasElement HTMLImageElement HTMLVideoElement HTMLMediaElement HTMLAudioElement ' +
    'HTMLInputElement HTMLFormElement HTMLIFrameElement HTMLScriptElement HTMLStyleElement ' +
    'HTMLAnchorElement HTMLAreaElement HTMLMapElement HTMLSlotElement HTMLTemplateElement ' +
    'CSSStyleRule CSSMediaRule CSSFontFaceRule CSSPageRule CSSSupportsRule CSSImportRule ' +
    'WebAssembly Intl Atomics SharedArrayBuffer ArrayBuffer DataView BigInt64Array BigUint64Array ' +
    'trustedTypes onmessage onmessageerror onunhandledrejection onrejectionhandled ' +
    'requestIdleCallback cancelIdleCallback scheduler').split(/\s+/);

  var known = Object.create(null);
  for (var k = 0; k < KNOWN.length; k++) known[KNOWN[k]] = 1;

  send('boot');

  var names = [];
  try { names = Object.getOwnPropertyNames(window); } catch (e) { send('enum-threw:' + e.name); return; }
  send('window-props=' + names.length);

  var odd = [];
  for (var i = 0; i < names.length; i++) {
    var n = names[i];
    if (n in known) continue;
    if (/^(on|webkit|moz|ms)/.test(n) && !/^webkit(?!Request|Cancel|URL|RTCPeer|Speech)/.test(n)) continue;
    var t = '?';
    try { t = typeof window[n]; } catch (e) { t = 'throws'; }
    odd.push(n + ':' + t);
    if (odd.length >= 40) break;
  }
  send('UNKNOWN[' + odd.length + '] ' + odd.join(' '));

  // the interesting part: a host bridge
  try {
    if (window.webkit) {
      send('webkit-keys ' + Object.getOwnPropertyNames(window.webkit).join(','));
      if (window.webkit.messageHandlers) {
        send('messageHandlers ' + Object.getOwnPropertyNames(window.webkit.messageHandlers).join(','));
      }
    } else send('no-window.webkit');
  } catch (e) { send('webkit-enum-threw:' + e.name); }

  send('done');
})();
