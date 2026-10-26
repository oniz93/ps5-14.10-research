// Candidate: @page rule inserted into a constructable (document-less) stylesheet.
// Targets CSSParser::parsePageSelector dereferencing state that only exists for a document-backed
// sheet. Throwing is a pass; taking the WebProcess down is the signal.
try {
  var sh = new CSSStyleSheet();
  for (var i = 0; i < 200; i++) {
    sh.insertRule('@page { margin: ' + (i % 5) + 'cm; }', sh.cssRules.length);
  }
  sh.replaceSync('@page { size: A4 } .x { color: red }');
} catch (e) { }
