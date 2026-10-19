import urllib.request, struct
BASE="https://pc.ps5.update.playstation.net/update/ps5/official/tJMRE80IbXnE9YuG0jzTXgKEjIMoabr6/image/2026_0928"
REC=BASE+"/rec_9f3a0b8811c00ab52b092d2e9f0f13dd4515f018361ff38e4be43fd8c18b21de/PS5UPDATE.PUP"
SYS=BASE+"/sys_c17384946df6e5c85b2d72cbeee2057b165bf90279d9e2a86d527d0778cdaaf6/PS5UPDATE.PUP"
def rg(url,start,length):
    req=urllib.request.Request(url,headers={"Range":f"bytes={start}-{start+length-1}","User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=120) as r: return r.read()

for label,u in (("SYSTEM",SYS),("RECOVERY",REC)):
    b=rg(u,0x400,0x400)
    print(f"===== {label} @0x400 =====")
    magic=struct.unpack_from("<I",b,0)[0]
    print(f"  magic @0x400 : {magic:#010x}   {'MATCH 0xEEF51454' if magic==0xEEF51454 else 'no match'}")
    for o in range(0,0x100,16):
        h=" ".join(f"{x:02x}" for x in b[o:o+16])
        a="".join(chr(x) if 32<=x<127 else "." for x in b[o:o+16])
        print(f"  {0x400+o:04x}  {h}  |{a}|")
    # how far does low-entropy plaintext extend?
    print("  --- entropy by 256B block ---")
    import math
    for blk in range(0,0x400,256):
        seg=b[blk:blk+256]
        if not seg: break
        c={}
        for x in seg: c[x]=c.get(x,0)+1
        H=-sum((n/len(seg))*math.log2(n/len(seg)) for n in c.values())
        print(f"    {0x400+blk:#06x}  entropy {H:.3f}")
    print()
