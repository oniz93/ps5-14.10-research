// Candidate: refcount/ownership churn on grouping rules (@media) via insert/delete.
try {
  var s2 = new CSSStyleSheet();
  for (var j = 0; j < 400; j++) {
    var at = s2.insertRule('@media screen { .a' + j + ' { color: red } }', s2.cssRules.length);
    s2.insertRule('.b' + j + ' { color: blue }', at + 1);
    s2.deleteRule(at);
  }
} catch (e) { }
