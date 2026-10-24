// Trigger search for the stale UnresolvedForwardReference in YarrPattern::quantifyAtom.
//
// The claim under test: atomNamedBackReference() appends to m_forwardReferencesInLookbehind
// UNCONDITIONALLY, while the other two append sites require parenthesisMatchDirection() ==
// Backward. Sony's fix pops the reference only when direction is Backward. So in a FORWARD
// context, a named forward reference quantified {0} removes the term but leaves the vector
// entry pointing at the removed index; a later lookbehind close walks the vector and
// dereferences term() -> m_terms[stale index].
//
// Each case is printed before it runs so ASAN output can be attributed.

const cases = [
  ['A', String.raw`^\k<a>{0}(?<a>x)(?<=y)`],
  ['B', String.raw`^(?:\k<a>{0})(?<a>x)(?<=y)`],
  ['C', String.raw`\k<a>{0}(?<a>x)(?<=(?<=y))`],
  ['D', String.raw`(?<a>x)\k<a>{0}(?<=y)`],
  ['E', String.raw`\k<a>{0}(?<a>x)(?<b>y)(?<=z)`],
  ['F', String.raw`(?:\k<a>{0})(?<a>x)(?<=(?:y))`],
  ['G', String.raw`(?<=\k<a>{0})(?<a>x)`],
  ['H', String.raw`\k<a>{0}{0}(?<a>x)(?<=y)`],
];

for (const [name, src] of cases) {
  print('CASE ' + name + ' : ' + src);
  try {
    const re = new RegExp(src);
    print('  compiled ok, flags=' + re.flags);
    try { print('  test="xy" -> ' + re.test('xy')); } catch (e) { print('  test threw ' + e.name); }
  } catch (e) {
    print('  threw ' + e.name + ': ' + e.message);
  }
}
print('DONE');
