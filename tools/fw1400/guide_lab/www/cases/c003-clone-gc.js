// Candidate: CloneSerializer/CloneDeserializer string and graph lifetime under GC pressure.
// Cycles plus repeated serialise/deserialise with allocation churn between them.
try {
  for (var k = 0; k < 150; k++) {
    var o = { a: new Array(512).fill(k), b: { n: k }, t: new TextDecoder().decode(new Uint8Array(64)) };
    o.self = o;
    o.back = { up: o };
    var c = structuredClone(o);
    if (c.self !== c) { }
    new Float64Array(1 << 19).fill(k);
  }
} catch (e) { }
