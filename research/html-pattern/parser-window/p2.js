// Probe P2: the load-callback script window.  Runs from HTMLDocumentParser::notifyFinished ->
// executeScriptsWaitingForLoad -> executeParsingBlockingScripts -> executePendingScriptAndDispatchEvent.
// The nested beacon must land between "P2 enter" and "P2 wrote" if the parse really re-enters.
B('P2 enter');
try {
  document.write('<script>B("P2 nested exec")<\/script>');
  B('P2 wrote');
} catch (e) { B('P2 threw ' + e.name); }
B('P2 exit');
