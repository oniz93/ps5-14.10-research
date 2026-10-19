import urllib.request, struct, sys
BASE="https://pc.ps5.update.playstation.net/update/ps5/official/tJMRE80IbXnE9YuG0jzTXgKEjIMoabr6/image"
V = {
 "14.10": ("2026_0928", "c17384946df6e5c85b2d72cbeee2057b165bf90279d9e2a86d527d0778cdaaf6", 1261408256),
 "14.00": ("2026_0909", "1eb4b18451e0f064fc23b5bd4c95cae7f6489f9ad1148b5dfb0d66452a108ebc", 1260600832),
 "13.60": ("2026_0717", "767a94eac034d33907a6ff57af05bc30ce057258ad1cf4b5ffb75d5e21112561", 1247471104),
}
def rg(url,start,length):
    req=urllib.request.Request(url,headers={"Range":f"bytes={start}-{start+length-1}","User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=120) as r: return r.read(), r.status

for ver,(date,h,expect) in V.items():
    url=f"{BASE}/{date}/sys_{h}/PS5UPDATE.PUP"
    try:
        b,st=rg(url,0,0x40)
    except Exception as e:
        print(f"{ver}: FAILED {e}"); continue
    if b[:4]!=b"SLB2":
        print(f"{ver}: not SLB2 -> {b[:16].hex(' ')}"); continue
    ver_n,flags,count=struct.unpack_from("<III",b,0x04)
    total=struct.unpack_from("<Q",b,0x10)[0]
    eb,es,bk=struct.unpack_from("<III",b,0x20)[0],struct.unpack_from("<I",b,0x24)[0],0
    print(f"{ver}: v{ver_n} flags={flags:#010x} count={count} total={total:,} (~{total*512:,}) entry0 block={eb} size={es:,} ({es:#x})")
    # inner PUP header at 0x400
    ih,_=rg(url,0x400,16)
    magic=struct.unpack_from("<I",ih,0)[0]
    fmt=struct.unpack_from("<I",ih,4)[0]
    a=struct.unpack_from("<I",ih,8)[0]
    hsz,hsh=struct.unpack_from("<HH",ih,0x0C)
    print(f"      inner@0x400 magic={magic:#010x} fmt={fmt:#010x} f8={a} hdrsize={hsz:#x}({hsz}) hashtbl={hsh:#x}({hsh})")
