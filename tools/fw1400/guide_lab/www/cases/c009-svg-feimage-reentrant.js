// Upstream reproducer for 5b3364fd97: "Revert 312304@main, which used a stale HashMap iterator in
// LegacyRenderSVGResourceFilter::applyResource". The test is plain markup that says "PASS if it does
// not crash": an feImage referencing a group that itself contains filtered rects, so resolving the
// filter re-enters the resource map while it is being mutated.
var holder = document.createElement('div');
holder.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300">'
  + '<defs><filter id="f"><feImage href="#target"></feImage><feDiffuseLighting></feDiffuseLighting></filter>'
  + '<g id="target">'
  + '<rect x="0" y="0" width="40" height="40" filter="url(#f)"/>'
  + '<rect x="50" y="0" width="40" height="40" filter="url(#f)"/>'
  + '<rect x="100" y="0" width="40" height="40" filter="url(#f)"/>'
  + '<rect x="0" y="50" width="40" height="40" filter="url(#f)"/>'
  + '<rect x="50" y="50" width="40" height="40" filter="url(#f)"/>'
  + '</g></defs>'
  + '<rect x="0" y="0" width="100" height="100" filter="url(#f)"/></svg>';
document.body.appendChild(holder);
// Force layout/paint of the filters, then drop the subtree while the resource map is still warm.
for (var k = 0; k < 20; k++) { holder.getBoundingClientRect(); }
document.body.removeChild(holder);
