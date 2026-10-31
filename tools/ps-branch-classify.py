#!/usr/bin/env python3
"""Classify every PLATFORM(PLAYSTATION) block in the Sony drop.

Reads data/ps-branches/blocks.json (tools/platform-playstation-sweep.py) and
assigns each block one of:

  impl   PS-only platform implementation (file lives in a playstation/ dir)
  test   API test / memory tool, not shipped in the browser
  log    PS_LOG / debug print only
  stub   the shared definition is compiled out for PS because the port
         supplies its own elsewhere (named in the note)
  add    adds a platform path, hook, field, enum value, method or include
         without changing a decision shared code also makes
  flag   build/feature-flag default only
  dev    replaces shared logic — a different bound, operand, container,
         error path, virtuality or implementation — i.e. a deviation
         candidate.  `kind` narrows it: mem / sec / behavi.

Writes data/ps-branches/verdicts.json and prints counts plus the dev rows.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCKS = os.path.join(HERE, 'data/ps-branches/blocks.json')

# file:line -> (category, kind, note)
EXPLICIT = {
    # ---- JavaScriptCore ----
    'Source/JavaScriptCore/heap/BlockDirectory.cpp:63': ('dev', 'behav',
        'mincore paged-out statistic replaced by UNUSED_PARAM(stats)'),
    'Source/JavaScriptCore/llint/LLIntPCRanges.h:46': ('dev', 'behav',
        'isLLIntPC() returns false: VMTraps ignores a trap taken in LLInt code; profiling/asserts see no LLInt frame'),
    'Source/JavaScriptCore/runtime/JSDateMath.cpp:147': ('dev', 'behav',
        'ICU timezone offset replaced by WTF::calculateLocalTimeOffset()'),
    'Source/JavaScriptCore/runtime/JSDateMath.cpp:501': ('dev', 'behav',
        'timezone display names return the empty string'),
    'Source/JavaScriptCore/runtime/Options.cpp:452': ('dev', 'mem',
        'useConcurrentGC=false, but only inside #if ENABLE(MAT) (default OFF)'),
    'Source/JavaScriptCore/runtime/StructureID.h:50': ('dev', 'mem',
        'structure heap is 128 MB instead of 4 GB; structureIDMask = 0x07ffffff'),
    'Source/JavaScriptCore/runtime/VM.cpp:395': ('dev', 'mem',
        'Config::disableFreezingForTesting() at VM::finishInitialization'),
    'Source/JavaScriptCore/runtime/JSLock.cpp:160': ('add', '', 'CRASH() under Options::enableSingleThreadCheck() (default off)'),
    'Source/JavaScriptCore/API/tests/FunctionOverridesTest.cpp:44': ('test', '', 'script path /app0'),
    'Source/JavaScriptCore/API/tests/TypedArrayCTest.cpp:267': ('test', '', 'UINT_MAX typed-array allocation test skipped'),
    'Source/JavaScriptCore/API/tests/testapi.c:1409': ('test', '', 'testCAPIViaCpp skipped'),
    'Source/JavaScriptCore/API/tests/testapi.c:2018': ('test', '', 'script path /app0'),
    'Source/JavaScriptCore/API/tests/testapi.c:2126': ('test', '', 'testFunctionOverrides skipped'),
    'Source/JavaScriptCore/API/tests/testapi.c:2193': ('test', '', 'testExecutionTimeLimit skipped'),
    'Source/JavaScriptCore/testmem/testmem.cpp:38': ('test', '', 'showmap include'),
    'Source/JavaScriptCore/testmem/testmem.cpp:53': ('test', '', 'showmap footprint'),
    # ---- WebCore: deviations ----
    'Source/WebCore/Modules/mediasource/MediaSource.cpp:334': ('dev', 'behav',
        'currentTimeFudgeFactor 1/10 s instead of 2002/24000 s'),
    'Source/WebCore/Modules/mediasource/SourceBuffer.cpp:250': ('dev', 'behav',
        'monitorBufferingRate() not called on append'),
    'Source/WebCore/Modules/mediasource/SourceBuffer.cpp:628': ('dev', 'behav',
        'monitorBufferingRate() not called on append completion'),
    'Source/WebCore/dom/Document.cpp:7552': ('dev', 'behav',
        'extra `timestamp &&` guard: no user gesture in the first 5 s of uptime'),
    'Source/WebCore/editing/FrameSelection.cpp:1435': ('dev', 'behav',
        'caret does not move while caretIsVisible() is false'),
    'Source/WebCore/html/HTMLSelectElement.cpp:1325': ('dev', 'behav',
        'every mouse-driven updateSelectedState() is treated as ctrl-click (multi=true)'),
    'Source/WebCore/loader/DocumentLoader.cpp:2530': ('dev', 'inert',
        'static_cast removed, same addConsoleMessage call (CFI workaround)'),
    'Source/WebCore/page/csp/ContentSecurityPolicy.cpp:827': ('dev', 'sec',
        'AND inverted to OR: PS returns early where upstream downcasts; a downstream FIX'),
    'Source/WebCore/platform/ReferrerPolicy.h:50': ('dev', 'sec',
        'Default = NoReferrerWhenDowngrade instead of StrictOriginWhenCrossOrigin'),
    'Source/WebCore/platform/graphics/Font.cpp:606': ('dev', 'behav',
        'variation-selector test: FE0E accepted without a glyph, colour fonts refuse it'),
    'Source/WebCore/platform/graphics/WidthIterator.cpp:225': ('dev', 'behav',
        'no 0-glyph padding for non-BMP characters (glyph buffer shorter than the code-unit count)'),
    'Source/WebCore/platform/graphics/ImageSource.cpp:604': ('dev', 'behav',
        'size taken from the decoder when frames exist without contents; metadata cache not written'),
    'Source/WebCore/platform/graphics/MediaPlayer.cpp:1087': ('dev', 'behav',
        'setPresentationSize() forwards even when the size is unchanged'),
    'Source/WebCore/platform/graphics/SourceBufferPrivate.cpp:1114': ('dev', 'behav',
        'tweak-gated: `<` and frameEndTimestamp instead of `<=` and presentationTimestamp'),
    'Source/WebCore/platform/graphics/SourceBufferPrivate.cpp:1157': ('dev', 'behav',
        'tweak-gated extra erasure of samples sharing the last decode timestamp'),
    'Source/WebCore/platform/graphics/freetype/FontPlatformDataFreeType.cpp:127': ('dev', 'behav',
        'synthetic bold disabled'),
    'Source/WebCore/platform/graphics/freetype/FontPlatformDataFreeType.cpp:254': ('dev', 'behav',
        'font matrix built from FC_MATRIX instead of cairo_matrix_init(1,-yx,-xy,1,0,0)'),
    'Source/WebCore/platform/graphics/freetype/FontPlatformDataFreeType.cpp:274': ('dev', 'behav',
        'translates the matrix and resets the synthesized weight'),
    'Source/WebCore/platform/graphics/freetype/FontPlatformDataFreeType.cpp:287': ('dev', 'behav',
        'syntheticObliqueSkew constant -0x03a/0x100 instead of -tanf(14 deg)'),
    'Source/WebCore/platform/graphics/freetype/SimpleFontDataFreeType.cpp:137': ('dev', 'behav',
        'OS/2 winAscent/winDescent instead of typo metrics'),
    'Source/WebCore/platform/graphics/texmap/TextureMapper.cpp:36': ('dev', 'mem',
        'one BitmapTexture per acquire instead of the texture pool (no reuse)'),
    'Source/WebCore/platform/graphics/AudioTrackPrivate.h:61': ('dev', 'behav',
        'enabled() made virtual in the base class'),
    'Source/WebCore/platform/network/curl/CurlRequest.h:71': ('dev', 'behav',
        'resume()/cancel() made virtual'),
    'Source/WebCore/platform/network/curl/CurlRequest.h:90': ('dev', 'inert',
        'member section made protected instead of private'),
    'Source/WebCore/platform/network/curl/CurlRequest.cpp:467': ('dev', 'behav',
        'didReceiveResponse also invoked when WebSecurity::shouldBlock(status, connectCode)'),
    'Source/WebCore/platform/encryptedmedia/CDMInstance.h:82': ('dev', 'inert',
        'Playstation inserted MID-enum: Remote 3->4, Thunder 4->5 on PS'),
    'Source/WebCore/platform/graphics/PlatformDisplay.h:86': ('dev', 'inert',
        'PlayStation inserted before the USE(EGL) values: Surfaceless/GBM shift by one'),
    'Source/WebCore/platform/graphics/cairo/CairoOperations.cpp:906': ('dev', 'behav',
        'CAIRO_FILTER_BILINEAR where shared code uses CAIRO_FILTER_GOOD'),
    'Source/WebCore/platform/graphics/cairo/CairoOperations.cpp:913': ('dev', 'behav',
        'CAIRO_FILTER_BILINEAR where shared code uses CAIRO_FILTER_BEST'),
    'Source/WebCore/platform/WebCorePersistentCoders.cpp:468': ('dev', 'behav',
        'CertificateInfo codec gains hasPrivateKey/privateKey/privateKeyPassword'),
    'Source/WebCore/platform/WebCorePersistentCoders.cpp:499': ('dev', 'behav',
        'CertificateInfo decoder requires the three extra fields'),
    'Source/WebCore/rendering/RenderElement.cpp:1475': ('dev', 'mem',
        'canDestroyDecodedData() answers for paintsEntireContents() using fixedVisibleContentRect'),
    'Source/WebCore/rendering/RenderElement.h:369': ('dev', 'mem',
        'declares the PS canDestroyDecodedData() override (out-of-line)'),
    'Source/WebCore/rendering/RenderLayer.cpp:2129': ('dev', 'behav',
        'returns instead of ASSERT(parentLayer) when enclosingFilterRepaintLayer() is null'),
    'Source/WebCore/rendering/RenderLayer.cpp:5638': ('dev', 'behav',
        'sets RenderView::m_hasSoftwareFilters on every layer with filters'),
    # ---- WebCore: stubs (PS supplies the definition elsewhere) ----
    'Source/WebCore/platform/Widget.cpp:277': ('stub', '', 'Widget::~Widget/setFrameRect not the notImplemented stub'),
    'Source/WebCore/platform/encryptedmedia/CDMFactory.cpp:64': ('stub', '', 'platformRegisterFactories defined in playstation/eme/CDMFactoryPlayStation.cpp'),
    'Source/WebCore/platform/graphics/freetype/FontCacheFreeType.cpp:127': ('stub', '', 'systemFallbackForCharacters defined in playstation/FontCachePlayStation.cpp'),
    'Source/WebCore/platform/graphics/harfbuzz/FontDescriptionHarfBuzz.cpp:31': ('stub', '', 'effectiveFamilyCount/At defined in playstation/FontDescriptionPlayStation.cpp'),
    'Source/WebCore/page/EventHandler.cpp:5102': ('stub', '', 'tabsToAllFormControls defined in page/playstation/EventHandlerPlayStation.cpp'),
    # ---- WebCore: logs ----
    'Source/WebCore/Modules/mediasource/SourceBuffer.cpp:143': ('log', '', ''),
    'Source/WebCore/Modules/mediasource/SourceBuffer.cpp:186': ('log', '', ''),
    'Source/WebCore/Modules/mediasource/SourceBuffer.cpp:218': ('log', '', ''),
    'Source/WebCore/Modules/mediasource/SourceBuffer.cpp:246': ('log', '', ''),
    'Source/WebCore/Modules/mediasource/SourceBuffer.cpp:313': ('log', '', ''),
    'Source/WebCore/Modules/mediasource/SourceBuffer.cpp:539': ('log', '', ''),
    'Source/WebCore/Modules/mediasource/SourceBuffer.cpp:600': ('log', '', ''),
    'Source/WebCore/Modules/mediasource/SourceBuffer.cpp:633': ('log', '', ''),
    'Source/WebCore/platform/graphics/SourceBufferPrivate.cpp:475': ('log', '', ''),
    'Source/WebCore/platform/graphics/SourceBufferPrivate.cpp:510': ('log', '', ''),
    'Source/WebCore/platform/graphics/SourceBufferPrivate.cpp:574': ('log', '', ''),
    'Source/WebCore/platform/graphics/SourceBufferPrivate.cpp:583': ('log', '', ''),
    'Source/WebCore/platform/network/curl/CookieJarDB.cpp:541': ('log', '', 'logs the sqlite3 result on insert'),
}

# PS-only files (whole-file guard) are recognised by their directory.
def classify(r):
    key = f"{r['file']}:{r['line']}"
    if key in EXPLICIT:
        return EXPLICIT[key]
    if '/playstation/' in r['file'] or r['file'].startswith('Source/WebCore/platform/network/playstation/'):
        return ('impl', '', 'PS-only implementation file')
    code = []
    for b in r['branches']:
        code += b['code']
    if code and code[0].startswith('#include'):
        return ('add', '', 'include only')
    if code and re.match(r'PS_LOG|LOG\(', code[0]):
        return ('log', '', '')
    return ('add', '', 'platform path/hook/field')


def main():
    rows = json.load(open(BLOCKS))
    out = []
    for r in rows:
        cat, kind, note = classify(r)
        r2 = dict(r)
        r2['category'] = cat
        r2['kind'] = kind
        r2['note'] = note
        out.append(r2)
    with open(os.path.join(HERE, 'data/ps-branches/verdicts.json'), 'w') as f:
        json.dump(out, f, indent=1)
    import collections
    c = collections.Counter(r['category'] for r in out)
    print('blocks', len(out), dict(c))
    print('dev kinds', dict(collections.Counter(r['kind'] for r in out if r['category'] == 'dev')))
    print('\n--- dev rows ---')
    for r in out:
        if r['category'] == 'dev':
            print(f"{r['file']}:{r['line']}  [{r['kind']}]  {r['note']}")
    print('\n--- blocks with a non-PS alternative branch that are NOT dev ---')
    for r in out:
        if r['has_alt'] and r['category'] != 'dev':
            print(f"{r['file']}:{r['line']}  {r['category']}  {r['alt_conds']}")


if __name__ == '__main__':
    main()
