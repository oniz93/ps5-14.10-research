# docs/112 — who takes the freed canvas context's slot?
#
# gdb Python: the dtor gives us the object address A (CanvasRenderingContext is the first base, and its dtor is
# the out-of-line one in CanvasRenderingContext.cpp), the free of A is confirmed at WTF::fastFree, and from then
# on every fastMalloc request in A's size class is logged with its return value (a FinishBreakpoint, because
# `finish` inside a breakpoint command list truncates the list on this gdb), plus a hardware write watchpoint on
# A reporting the first write after the free with its backtrace — i.e. the allocation that really owns the slot.
import gdb

A = None
alloc_hits = 0


def u64(expr):
    return int(gdb.parse_and_eval(expr))


def sizes():
    out = []
    for t in ("WebCore::CanvasRenderingContext2D", "WebCore::CachedImage", "WebCore::CachedResource",
              "WTF::StringImpl"):
        try:
            out.append("%s=%d" % (t.split("::")[-1], int(gdb.parse_and_eval("sizeof(%s)" % t))))
        except gdb.error:
            out.append("%s=?" % t.split("::")[-1])
    print("SIZES " + " ".join(out))


class Dtor(gdb.Breakpoint):
    def __init__(self):
        super().__init__("WebCore::CanvasRenderingContext::~CanvasRenderingContext()")

    def stop(self):
        global A
        A = u64("$rdi")
        gdb.execute("set $A = (unsigned long)0x%x" % A)
        print("CTXDTOR A=0x%x" % A)
        gdb.execute("bt 6")
        free_bp.enabled = True
        return False


class Free(gdb.Breakpoint):
    def __init__(self):
        super().__init__("WTF::fastFree")
        self.enabled = False

    def stop(self):
        p = u64("$rdi")
        if A is None or p != A:
            return False
        print("FREED-A ptr=0x%x" % p)
        gdb.execute("bt 5")
        self.enabled = False
        FreeReturn()
        return False


class FreeReturn(gdb.FinishBreakpoint):
    def __init__(self):
        super().__init__(internal=True)

    def stop(self):
        print("FREE-RETURNED")
        install_watch(A)
        alloc_bp.enabled = True
        return False


class Alloc(gdb.Breakpoint):
    def __init__(self):
        super().__init__("WTF::fastMalloc")
        self.enabled = False

    def stop(self):
        global alloc_hits
        sz = u64("$rdi")
        if not (700 <= sz <= 768):
            return False
        alloc_hits += 1
        if alloc_hits > 400:
            self.enabled = False
            return False
        AllocReturn(sz, alloc_hits)
        return False


class AllocReturn(gdb.FinishBreakpoint):
    def __init__(self, sz, n):
        self.sz = sz
        self.n = n
        super().__init__(internal=True)

    def stop(self):
        ret = u64("$rax")
        mark = "  <== A" if ret == A else ""
        print("ALLOC req=%d ret=0x%x n=%d%s" % (self.sz, ret, self.n, mark))
        if ret == A:
            gdb.execute("bt 8")
        return False


class Watch(gdb.Breakpoint):
    def __init__(self, addr):
        self.addr = addr
        super().__init__("*(unsigned long*)0x%x" % addr, gdb.BP_WATCHPOINT, gdb.WP_WRITE)

    def stop(self):
        try:
            val = u64("*(unsigned long*)0x%x" % self.addr) & 0xffffffffffffffff
        except gdb.error:
            val = -1
        print("WROTE-A addr=0x%x val=0x%x" % (self.addr, val))
        gdb.execute("bt 10")
        self.enabled = False
        return False


def install_watch(addr):
    Watch(addr)
    print("WATCH installed on 0x%x" % addr)


dtor_bp = Dtor()
free_bp = Free()
alloc_bp = Alloc()
sizes()
print("slotwatch armed: dtor=%s free=%s alloc=%s" % (dtor_bp.number, free_bp.number, alloc_bp.number))
