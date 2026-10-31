#!/usr/bin/env python3
"""Classify the PS-only surface *outside* JavaScriptCore/WebCore (docs/107).

Same taxonomy as tools/ps-branch-classify.py (docs/106): impl / test / log /
stub / add / flag / dev.  The explicit table below holds every block that is
not a plain addition; the rules cover the rest, so a disagreement is a one-line
diff.  Reads data/ps-branches/blocks-outer.json and writes
data/ps-branches/verdicts-outer.json.
"""
import json, os, re, collections

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCKS = os.path.join(HERE, 'data/ps-branches/blocks-outer.json')
OUT = os.path.join(HERE, 'data/ps-branches/verdicts-outer.json')

E = {
 # ---------------- Source/WTF ----------------
 'Source/WTF/wtf/PageBlock.h:52': ('dev', 'mem',
   'CeilingOnPageSize 16 KB where every 4 KB port uses 4 KB: pageSize() is min(systemPageSize(), ceiling), '
   'so this *permits* a 16 KB page (the console value is unmeasured); pageSize() feeds isPageAligned and '
   'PageBlock::size in 27 files'),
 'Source/WTF/wtf/Threading.cpp:106': ('dev', 'mem',
   'JavaScript threads get a 512 KB stack; every other WTF thread falls through to '
   'DEFAULT_THREAD_STACK_SIZE_IN_KB, which PlatformPlayStation.cmake:44 sets to 64 on PS only (other ports: '
   'std::nullopt = the libc default, 8 MB on glibc)'),
 'Source/WTF/wtf/Assertions.cpp:342': ('dev', 'behav',
   'WTFCrash() is CRASH() (SIGTRAP inline asm) in NDEBUG on PS instead of WTFReportBacktrace + a 0xbbadbeef write'),
 'Source/WTF/wtf/Assertions.cpp:652': ('dev', 'behav',
   'the CRASH_WITH_INFO implementation with register dumps is compiled for PS as it is for Darwin '
   '(elsewhere every arity forwards to CRASH())'),
 'Source/WTF/wtf/Assertions.h:271': ('dev', 'behav',
   'CRASH() is a breakpoint trap (SIGTRAP) in NDEBUG on PS; on every non-Darwin port it is std::abort()'),
 'Source/WTF/wtf/Assertions.h:812': ('dev', 'behav',
   'CRASH_WITH_INFO calls callAssertReportFunction(__FILE__,__LINE__) first: Sony s assert reporter runs on '
   'every release assert'),
 'Source/WTF/wtf/DateMath.h:112': ('dev', 'behav',
   'maxUnixTime 4102444740 (12/31/2099) instead of 2145859200 (12/31/2037): Date can represent 62 more years'),
 'Source/WTF/wtf/DateMath.cpp:180': ('dev', 'behav',
   'the 2038 local-time-offset workaround is replaced by a PS body with a comment that DST may be wrong after 2038'),
 'Source/WTF/wtf/posix/ThreadingPOSIX.cpp:572': ('dev', 'inert',
   'Mutex::Mutex() is out-of-line (pthread_mutex_init + PTHREAD_MUTEX_NORMAL + pthread_mutex_setname_np); '
   'the type constant matches the shared initializer, the naming has no consequence'),
 'Source/WTF/wtf/PlatformEnable.h:891': ('dev', 'inert',
   'ENABLE_OPENTYPE_MATH 1 on PS (0 on GTK/WPE) — inert here because OptionsPlayStation.cmake:268 sets '
   'ENABLE_MATHML OFF, so no MathML layout reaches OpenTypeMathData'),
 'Source/WTF/wtf/PlatformHave.h:387': ('dev', 'inert',
   'HAVE_MEMMEM is not defined for PS (it is for every other non-Windows port): String::find/contains take the '
   'non-memmem path'),
 'Source/WTF/wtf/FileSystem.cpp:751': ('stub', '', 'deleteNonEmptyDirectory: PS body in playstation/FileSystemPlayStation.cpp'),
 'Source/WTF/wtf/FileSystem.cpp:835': ('stub', '', 'listDirectory: PS body in playstation/FileSystemPlayStation.cpp'),
 'Source/WTF/wtf/FileSystem.cpp:894': ('stub', '', 'createTemporaryDirectory: PS body in playstation/FileSystemPlayStation.cpp'),
 'Source/WTF/wtf/FileSystem.cpp:641': ('stub', '', 'moveFile: PS body in playstation/FileSystemPlayStation.cpp'),
 'Source/WTF/wtf/FileSystem.cpp:696': ('stub', '', 'volumeFreeSpace: PS body in playstation/FileSystemPlayStation.cpp'),
 'Source/WTF/wtf/FileSystem.cpp:826': ('stub', '', 'realPath: PS body in playstation/FileSystemPlayStation.cpp'),
 'Source/WTF/wtf/FileSystem.h:230': ('stub', '', 'createTemporaryDirectory declaration withheld for PS'),
 'Source/WTF/wtf/Assertions.cpp:126': ('add', '', 'setAssertReportFunction/callAssertReportFunction hook'),
 'Source/WTF/wtf/Assertions.h:766': ('add', '', 'AssertReportFunction typedef and declarations'),
 'Source/WTF/wtf/Assertions.h:190': ('add', '', 'LOG_CHANNEL_WEBKIT_SUBSYSTEM "SceNKWebKit"'),
 'Source/WTF/wtf/CurrentTime.cpp:269': ('add', '', 'clock_gettime_np(CLOCK_MONOTONIC)'),
 'Source/WTF/wtf/DataLog.cpp:151': ('add', '', 'DataLog writes to stdout'),
 'Source/WTF/wtf/DataLog.cpp:158': ('add', '', 'stdout is not set unbuffered'),
 'Source/WTF/wtf/NumberOfCores.cpp:50': ('add', '', 'getenv_np("WTF_numberOfProcessorCores")'),
 'Source/WTF/wtf/ThreadingPrimitives.h:77': ('add', '', 'Mutex() declared out-of-line'),
 'Source/WTF/wtf/PlatformEnable.h:94': ('add', '', 'includes wtf/PlatformEnablePlayStation.h'),
 'Source/WTF/wtf/PlatformEnable.h:899': ('add', '', 'ENABLE_KINETIC_SCROLLING also on PS (GTK already had it)'),
 'Source/WTF/wtf/PlatformEnablePlayStation.h:32': ('add', '', 'guard #error'),
 'Source/WTF/wtf/PlatformHave.h:119': ('add', '', 'HAVE_MISSING_STD_FILESYSTEM_PATH_CONSTRUCTOR'),
 # ---------------- Source/bmalloc ----------------
 'Source/bmalloc/bmalloc/BPlatform.h:360': ('dev', 'flag',
   'BUSE_PTHREAD_MUTEX 1 and BUSE_RELEASE_LARGE_FREE 0: the second one makes the PS purge path dead (see '
   'bmalloc.cpp:151), the first selects the pthread Mutex'),
 'Source/bmalloc/bmalloc/Environment.cpp:130': ('dev', 'mem',
   'isSanitizerEnabled() returns false on PS by compile-time exclusion; combined with computeIsDebugHeapEnabled() '
   '(:182) this is why the *oracle* runs bmalloc as a debug heap (malloc fill) and the console does not — an '
   'allocator mode difference, not a console behaviour'),
 'Source/bmalloc/bmalloc/BAssert.h:35': ('dev', 'behav',
   'in NDEBUG on PS BCRASH() is a breakpoint trap (SIGTRAP) where every other non-Darwin port writes 0xbbadbeef; '
   'BASSERT is unconditional, so bmalloc assertions stay live in a release build with a different crash signature'),
 'Source/bmalloc/bmalloc/BPlatform.h:341': ('flag', '',
   'BENABLE_LIBPAS 1 by default for PS/ADDRESS64, but OptionsPlayStation.cmake:284,286,741-742 forces '
   '-DBENABLE_LIBPAS=0, which is the build that ships (docs/106 §6.6) — so all 14 PAS_PLATFORM(PLAYSTATION) '
   'blocks below are unreachable'),
 'Source/bmalloc/bmalloc/Heap.cpp:138': ('add', '', 'Heap::releaseLargeFree -> m_largeFree.purge(); only caller is compiled out (BUSE_RELEASE_LARGE_FREE 0)'),
 'Source/bmalloc/bmalloc/Heap.h:91': ('add', '', 'declaration for the dead purge path'),
 'Source/bmalloc/bmalloc/LargeMap.cpp:91': ('add', '', 'LargeMap::purge(): decommits free large ranges; dead under BUSE_RELEASE_LARGE_FREE 0'),
 'Source/bmalloc/bmalloc/LargeMap.h:49': ('add', '', 'declaration for the dead purge path'),
 'Source/bmalloc/bmalloc/bmalloc.cpp:151': ('add', '', 'the purge call site, #if BPLATFORM(PLAYSTATION) && BUSE(RELEASE_LARGE_FREE) — both false in this build'),
 'Source/bmalloc/bmalloc/BVMTags.h:64': ('add', '', 'VM_TYPE_USER1..4 tags'),
 'Source/bmalloc/bmalloc/BVMTags.h:30': ('add', '', 'include <sys/mman.h>'),
 'Source/bmalloc/bmalloc/Scavenger.cpp:386': ('add', '', 'pthread_setname_np(name) — one-argument FreeBSD form'),
 'Source/bmalloc/bmalloc/Scavenger.cpp:43': ('add', '', 'include <pthread_np.h>'),
 'Source/bmalloc/bmalloc/Mutex.h:101': ('add', '', 'pthread_mutex_setname_np(&m_mutex, "SceNKBMalloc")'),
 'Source/bmalloc/bmalloc/Mutex.h:36': ('add', '', 'include <pthread_np.h>'),
 'Source/bmalloc/bmalloc/VMAllocate.h:135': ('add', '', 'MAT logging only (BENABLE(MAT) OFF)'),
 'Source/bmalloc/bmalloc/VMAllocate.h:154': ('add', '', 'MAT logging only'),
 'Source/bmalloc/bmalloc/VMAllocate.h:174': ('add', '', 'MAT logging only'),
 'Source/bmalloc/bmalloc/VMAllocate.h:233': ('add', '', 'MAT logging only'),
 'Source/bmalloc/bmalloc/VMAllocate.h:254': ('add', '', 'MAT logging only'),
 # ---------------- Source/WebKit ----------------
 'Source/WebKit/NetworkProcess/NetworkResourceLoader.cpp:989': ('dev', 'sec',
   'BrowsingContextGroupSwitchDecision is always StayInGroup: the COOP-driven process swap/isolation is '
   'disabled (single-WebProcess port, comment cites webkit.org/b/263185)'),
 'Source/WebKit/NetworkProcess/cache/NetworkCacheStorage.cpp:878': ('dev', 'mem',
   'shouldStoreBodyAsBlob() returns false: every cache body is written inline in the record file instead of as '
   'a separate blob, so the on-disk record is the container shared code uses for small bodies only'),
 'Source/WebKit/Platform/IPC/unix/ConnectionUnix.cpp:493': ('dev', 'behav',
   'the sendmsg loop is replaced by a partial-write walk over msg_iov with poll(POLLOUT) on EAGAIN/EMSGSIZE '
   '(Sony comment: sendmsg may fail with EMSGSIZE); the GLib write-monitor path is not built'),
 'Source/WebKit/Platform/IPC/unix/ConnectionUnix.cpp:364': ('dev', 'behav',
   'platformOpen spawns a SocketMonitor thread that calls readyReadHandler() from that thread (select() on one fd) instead of '
   'dispatching to m_connectionQueue'),
 'Source/WebKit/Platform/IPC/unix/ConnectionUnix.cpp:127': ('dev', 'mem',
   'platformInvalidate closes the descriptor (:113-116) *before* it detaches the monitor thread and before it sets '
   'm_socketDescriptor = -1 (:134), so the thread re-reads the closed fd in a hot select() loop and could select() '
   'a descriptor number the process has since reused'),
 'Source/WebKit/WebProcess/WebPage/WebPage.cpp:2189': ('dev', 'behav',
   'sendViewportAttributesChanged ignores <meta viewport>: attr.layoutSize = m_viewSize, attr.initialScale = -1 '
   'before contentFixedSize.scale(1 / attr.initialScale), i.e. the fixed visible content rect is built from '
   'scale(-1) — a negative-size IntRect — and every viewport change re-runs '
   'LocalFrameView::setFixedVisibleContentRect\'s size test (LocalFrameView.cpp:2800)'),
 'Source/WebKit/WebProcess/WebPage/WebPage.cpp:3383': ('dev', 'behav',
   'MouseReleased takes an extra EditorState round trip and re-sends EditorStateChanged after the release'),
 'Source/WebKit/WebProcess/WebPage/WebPage.cpp:4582': ('dev', 'behav',
   'PS is excluded from the block that forces acceleratedCompositingEnabled to true: a PS page can run with '
   'compositing off, where shared code refuses the configuration'),
 'Source/WebKit/Shared/CacheModel.cpp:141': ('dev', 'behav',
   'urlCacheDiskCapacity is a fixed 128 MB instead of the four-tier 20/30/40/75 MB computed from disk free space'),
 'Source/WebKit/UIProcess/WebProcessProxy.cpp:1945': ('dev', 'behav',
   'the responsiveness timer is only updated when state() != Terminated'),
 'Source/WebKit/UIProcess/CoordinatedGraphics/DrawingAreaProxyCoordinatedGraphics.cpp:200': ('dev', 'behav',
   'DisplayDidRefresh is sent even while m_isWaitingForDidUpdateGeometry is set'),
 'Source/WebKit/UIProcess/WebPageProxy.cpp:8542': ('dev', 'behav',
   'Accept/Convert/Cancel/TabJump key events go through KeyEventPlayStation with a caretOffset instead of the '
   'generic KeyEvent message'),
 'Source/WebKit/UIProcess/WebPageProxy.cpp:8486': ('dev', 'behav',
   'doneWithMouseUpEvent(handled) is called on every mouse-up'),
 'Source/WebKit/UIProcess/Network/NetworkProcessProxy.cpp:267': ('dev', 'behav',
   'getLaunchOptions RELEASE_ASSERTs that some WebProcessPool exists and takes allProcessPools()[0] (FIXME SUPER-4291)'),
 'Source/WebKit/UIProcess/API/C/WKPage.cpp:340': ('dev', 'behav',
   'every reload adds ReloadOption::ExpiredOnly, so a reload may serve an expired cache entry without revalidating'),
 'Source/WebKit/NetworkProcess/curl/NetworkDataTaskCurl.cpp:185': ('dev', 'sec',
   'a response Sony s WebSecurity library blocks is rewritten into a 302 to WebSecurity::getBlockPageUrl() before '
   'the client sees it'),
 'Source/WebKit/NetworkProcess/curl/NetworkDataTaskCurl.cpp:551': ('dev', 'behav',
   'a server-trust failure is reported as ResourceError::cancelledInServerTrustEvaluationError(challenge.error())'),
 'Source/WebKit/WebProcess/WebCoreSupport/WebLocalFrameLoaderClient.cpp:682': ('dev', 'behav',
   'dispatchDidFailProvisionalLoad loads a substitute HTML error document *inside* the failure dispatch (same-origin '
   'with the failing URL, error code + descriptions interpolated). FrameLoader.cpp:2649-2652 handles a load started by '
   'the delegate callback, and the only post-callback use of provisionalDocumentLoader is under ENABLE(CONTENT_FILTERING) '
   '(off), so the re-entrancy is guarded — recorded because it is the docs/65 shape'),
 'Source/WebKit/UIProcess/Launcher/ProcessLauncher.cpp:56': ('dev', 'inert',
   'when there is no client the PS branch closes the IPC identifier fd; Darwin releases the mach port instead — a fix, '
   'not a deviation'),
 'Source/WebKit/UIProcess/WebPreferences.cpp:243': ('stub', '', 'platformInitializeStore: PS body in UIProcess/neko/WebPreferencesPlayStation.cpp'),
 'Source/WebKit/Platform/IPC/unix/ConnectionUnix.cpp:55': ('add', '', 'SOCKET_TYPE SOCK_STREAM'),
 'Source/WebKit/Platform/IPC/unix/ConnectionUnix.cpp:58': ('add', '', 'SOCKET_TYPE SOCK_STREAM'),
 'Source/WebKit/Platform/IPC/Connection.h:616': ('add', '', 'm_socketMonitor member'),
 'Source/WebKit/NetworkProcess/cache/NetworkCacheStorage.cpp:367': ('add', '', 'recordsSize from real block-rounded file sizes'),
 'Source/WebKit/NetworkProcess/cache/NetworkCacheStorage.cpp:384': ('add', '', 'the estimateRecordsSize() shortcut is not taken'),
 'Source/WebKit/NetworkProcess/curl/NetworkDataTaskCurl.cpp:155': ('add', '', 'CurlTMServiceRequest for main resources'),
 'Source/WebKit/NetworkProcess/curl/NetworkDataTaskCurl.cpp:536': ('add', '', 'challenge.setIsForMainResource'),
 'Source/WebKit/Shared/NativeWebKeyboardEvent.h:81': ('add', '', 'WKKeyboardEvent constructor'),
 'Source/WebKit/Shared/NativeWebKeyboardEvent.h:99': ('add', '', 'nativeEvent() -> WKKeyboardEvent'),
 'Source/WebKit/Shared/NativeWebKeyboardEvent.h:117': ('add', '', 'WKKeyboardEvent member'),
 'Source/WebKit/Shared/WebKeyboardEvent.cpp:102': ('add', '', 'PS keyboard event constructor (no handledByInputMethod/commands)'),
 'Source/WebKit/Shared/WebKeyboardEvent.h:50': ('add', '', 'declaration'),
 'Source/WebKit/UIProcess/WebsiteData/WebsiteDataStore.cpp:2038': ('add', '', 'directory name "storage"'),
 'Source/WebKit/UIProcess/WebsiteData/WebsiteDataStore.cpp:2047': ('add', '', 'directory name "WebKitCache"'),
 'Source/WebKit/UIProcess/WebsiteData/WebsiteDataStore.cpp:2056': ('add', '', 'directory name "applications"'),
 'Source/WebKit/UIProcess/WebsiteData/WebsiteDataStore.cpp:2070': ('add', '', 'directory name "indexeddb"'),
 'Source/WebKit/UIProcess/WebsiteData/WebsiteDataStore.cpp:2081': ('add', '', 'directory name "serviceworkers"'),
 'Source/WebKit/UIProcess/WebsiteData/WebsiteDataStore.cpp:2090': ('add', '', 'directory name "websql"'),
 'Source/WebKit/UIProcess/WebsiteData/WebsiteDataStore.cpp:2113': ('add', '', 'directory name "local"'),
 'Source/WebKit/UIProcess/WebsiteData/WebsiteDataStore.cpp:2124': ('add', '', 'directory name "mediakeys"'),
 'Source/WebKit/UIProcess/WebsiteData/WebsiteDataStore.cpp:2149': ('add', '', 'directory name "itp"'),
}

def classify(r):
    key = f"{r['file']}:{r['line']}"
    if key in E:
        return E[key]
    if '/playstation/' in r['file'] or '/neko/' in r['file']:
        return ('impl', '', 'PS-only implementation file')
    code = [c for b in r['branches'] for c in b['code']]
    if code and code[0].startswith('#include'):
        return ('add', '', 'include only')
    return ('add', '', 'platform path/hook/field/method')

def main():
    rows = json.load(open(BLOCKS))
    out = []
    for r in rows:
        cat, kind, note = classify(r)
        r2 = dict(r); r2['category'] = cat; r2['kind'] = kind; r2['note'] = note
        out.append(r2)
    json.dump(out, open(OUT, 'w'), indent=1)
    c = collections.Counter(r['category'] for r in out)
    print('blocks', len(out), dict(c))
    print('by dir', dict(collections.Counter(r['file'].split('/')[1] for r in out)))
    print('dev kinds', dict(collections.Counter(r['kind'] for r in out if r['category'] == 'dev')))
    print('\n--- dev rows ---')
    for r in out:
        if r['category'] == 'dev':
            print(f"{r['file']}:{r['line']}  [{r['kind']}]  {r['note'][:110]}")
    print('\nunclassified explicit keys:', [k for k in E if k not in {f"{r['file']}:{r['line']}" for r in out}])

if __name__ == '__main__':
    main()
