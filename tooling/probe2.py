import urllib.request, struct
BASE="https://pc.ps5.update.playstation.net/update/ps5/official/tJMRE80IbXnE9YuG0jzTXgKEjIMoabr6/image/2026_0928"
REC=BASE+"/rec_9f3a0b8811c00ab52b092d2e9f0f13dd4515f018361ff38e4be43fd8c18b21de/PS5UPDATE.PUP"
SYS=BASE+"/sys_c17384946df6e5c85b2d72cbeee2057b165bf90279d9e2a86d527d0778cdaaf6/PS5UPDATE.PUP"

def head(url):
    req=urllib.request.Request(url,method="HEAD",headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=60) as r:
        return {k.lower():v for k,v in r.headers.items()}

def rg(url,start,length):
    req=urllib.request.Request(url,headers={"Range":f"bytes={start}-{start+length-1}","User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=120) as r: return r.read(), r.status

for label,u in (("REC",REC),("SYS",SYS)):
    h=head(u)
    cl=h.get("content-length")
    print(f"{label}: content-length={cl}  ({int(cl)/2**20:.2f} MiB)" if cl else f"{label}: no length")
    print(f"     accept-ranges={h.get('accept-ranges')}  content-type={h.get('content-type')}")
print()

print("=== probe hypothetical data offsets in REC for SLB2 magic ===")
for cand in (0x200, 0x1000, 0x2597c8, 0x962FAB5, 0x2597C8+0x962FAB5):
    try:
        b,st=rg(REC,cand,32)
        tag = "  <<< SLB2!" if b[:4]==b"SLB2" else ""
        print(f"  @ {cand:#012x} ({cand:>12,}) [{st}] {b[:32].hex(' ')}{tag}")
    except Exception as e:
        print(f"  @ {cand:#012x} error: {e}")

print()
print("=== REC header region 0x100 .. 0x400 ===")
b,_=rg(REC,0x100,0x300)
for o in range(0,0x300,16):
    h=" ".join(f"{x:02x}" for x in b[o:o+16])
    a="".join(chr(x) if 32<=x<127 else "." for x in b[o:o+16])
    print(f"{0x100+o:04x}  {h}  |{a}|")

print()
print("=== is the header region long? scan 0x1000/0x10000/0x40000/0x100000 for ascii ===")
for off in (0x1000, 0x10000, 0x40000, 0x100000):
    b,_=rg(REC,off,256)
    nz=sum(1 for x in b if x!=0)
    print(f"  @ {off:#09x}  nonzero={nz}/256  first16={b[:16].hex(' ')}")
