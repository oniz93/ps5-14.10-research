// Probe P8: parser re-entry depth.  window.W() (index.html) writes an INLINE script that calls
// itself, so each link runs synchronously inside Document::write -> HTMLDocumentParser::insert ->
// pumpTokenizer -> HTMLScriptRunner::execute -> executePendingScriptAndDispatchEvent, and
// m_writeRecursionDepth accumulates one level per link.  Document::write drops the write once that
// depth passes cMaxWriteRecursionDepth = 21 (Document.cpp:385, :3445-3448), so the chain must stop
// there.  W1 measured the external-script variant: it does NOT nest (the parser pauses for the
// load and the script runs in a later task), so depth never accumulated and the chain reached 26.
if (ON('P8'))
  W();
