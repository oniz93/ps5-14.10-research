import urllib.request
BASE="https://pc.ps5.update.playstation.net/update/ps5/official/tJMRE80IbXnE9YuG0jzTXgKEjIMoabr6/image/2026_0928"
REC=BASE+"/rec_9f3a0b8811c00ab52b092d2e9f0f13dd4515f018361ff38e4be43fd8c18b21de/PS5UPDATE.PUP"
SYS=BASE+"/sys_c17384946df6e5c85b2d72cbeee2057b165bf90279d9e2a86d527d0778cdaaf6/PS5UPDATE.PUP"
def rg(url,start,length):
    req=urllib.request.Request(url,headers={"Range":f"bytes={start}-{start+length-1}","User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=90) as r: return r.read()

print("=== SYS (update) header 0x00-0xA0 ===")
b=rg(SYS,0,0xA0)
for o in range(0,0xA0,16):
    h=" ".join(f"{x:02x}" for x in b[o:o+16])
    a="".join(chr(x) if 32<=x<127 else "." for x in b[o:o+16])
    print(f"{o:04x}  {h}  |{a}|")

print()
print("=== hunt for SLB2 magic in REC (4KiB windows, 8MiB stride to 96MiB) ===")
hits=0
for off in range(0, 96*2**20, 8*2**20):
    b=rg(REC,off,4096)
    i=b.find(b"SLB2")
    if i>=0:
        print(f"  SLB2 at {off+i:#012x} ({off+i:,})")
        hits+=1
    else:
        # report which candidate offsets we've now excluded
        pass
print(f"  -> {hits} hit(s) in coarse grid")

print()
print("=== targeted: around 0x2a4946 (the 0x10 field) ===")
for cand in (0x2a4946, 0x2a4946+0x30, 0x2a4900, 0x200000, 0x280000, 0x300000):
    b=rg(REC,cand,16)
    print(f"  @ {cand:#012x} ({cand:>10,})  {b.hex(' ')}  {'<-- SLB2!' if b[:4]==b'SLB2' else ''}")
