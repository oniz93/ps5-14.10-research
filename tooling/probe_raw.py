import urllib.request, struct, sys
REC="https://pc.ps5.update.playstation.net/update/ps5/official/tJMRE80IbXnE9YuG0jzTXgKEjIMoabr6/image/2026_0928/rec_9f3a0b8811c00ab52b092d2e9f0f13dd4515f018361ff38e4be43fd8c18b21de/PS5UPDATE.PUP"
def rg(url,start,length):
    req=urllib.request.Request(url,headers={"Range":f"bytes={start}-{start+length-1}","User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=120) as r: return r.read()
buf=rg(REC,0,0x2000)
print("=== hexdump 0x000-0x110 ===")
for o in range(0,0x110,16):
    h=" ".join(f"{b:02x}" for b in buf[o:o+16])
    a="".join(chr(b) if 32<=b<127 else "." for b in buf[o:o+16])
    print(f"{o:04x}  {h}  |{a}|")
print()
print("=== ascii strings >=4 in first 0x2000 ===")
cur=b""; start=0
for i,b in enumerate(buf):
    if 32<=b<127: 
        if not cur: start=i
        cur+=bytes([b])
    else:
        if len(cur)>=4: print(f"  {start:#06x}  {cur.decode()}")
        cur=b""
if len(cur)>=4: print(f"  {start:#06x}  {cur.decode()}")
