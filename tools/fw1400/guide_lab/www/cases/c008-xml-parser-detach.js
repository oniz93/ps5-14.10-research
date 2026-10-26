// Upstream reproducer for 479cba7de8: "ASAN_ILL | XMLDocumentParser::detach; Document::removedLastRef".
//
// The upstream test calls the shell's gc(); a page cannot, so allocation pressure stands in for it.
// The payload is the exact one from the test - an XML document whose root is renamed to <glypRef>
// (sic) with an xlink:href, then replaced via innerHTML.
try {
  var doc = new DOMParser().parseFromString(
    "<svg xmlns='http://www.w3.org/2000/svg'><glypRef xlink:href='#foo' ></svg>", "application/xml");
  doc.documentElement.innerHTML = "foo";
  for (var i = 0; i < 40; i++) { var a = new Array(4000).fill(i); }
} catch (e) { }
