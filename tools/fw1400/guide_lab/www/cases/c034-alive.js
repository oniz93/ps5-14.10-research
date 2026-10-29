// c034: liveness ping. If the hot-reload poller is still running, this beacon arrives.
(function () {
  try { navigator.sendBeacon('/beacon', 'c034-alive'); } catch (e) {}
})();
