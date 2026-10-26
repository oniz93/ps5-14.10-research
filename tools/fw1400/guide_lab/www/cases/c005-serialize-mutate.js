// Candidate cfe38930db, second shape: mutate the graph mid-walk.
// A getter deletes and adds properties on the object being serialised, and pushes new strings into the
// pool after the serializer has already sized it.
var victim = { seed: 'seed-string' };
var added = 0;
Object.defineProperty(victim, 'mutator', {
  get: function () {
    for (var i = 0; i < 32; i++) { victim['late' + i] = 'late-string-' + i; added++; }
    delete victim.seed;
    return 'M';
  },
  enumerable: true
});
try { structuredClone(victim); } catch (e) { }
try { structuredClone(victim); } catch (e) { }
