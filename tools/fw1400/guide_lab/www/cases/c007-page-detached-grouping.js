// Upstream reproducer for cc88e18743: "Null dereference in CSSParser::parsePageSelector() when
// inserting an @page rule into a detached grouping rule".
//
// Note how different this is from the obvious guess: it is NOT a constructable stylesheet. The @media
// rule is detached from its parent sheet and then has an @page inserted into it, so the parser walks a
// parent chain that no longer reaches a document. My earlier attempt (insertRule('@page') on a
// new CSSStyleSheet) exercised a different path and correctly survived.
var style = document.createElement('style');
style.textContent = '@media all {}';
document.head.appendChild(style);
var sheet = style.sheet;
if (sheet && sheet.cssRules.length) {
  var media = sheet.cssRules[0];
  sheet.deleteRule(0);                       // detach the grouping rule from the sheet
  try { media.insertRule('@page foo {}', 0); } catch (e) { }
  try { media.insertRule('@page foo:first {}', 0); } catch (e) { }
}
