import csv, glob, numpy as np, sys
def parse(pl):
    out=[]
    for it in pl.split("|"):
        if not it: continue
        try:
            xs, rest = it.split("@"); x0, x1 = xs.split("-")
            i=0
            while i < len(rest) and (rest[i].isdigit() or rest[i]=='-'): i+=1
            out.append((int(x0), int(x1), int(rest[:i]), rest[i:]))
        except Exception: pass
    return out
res_g=[]; res_v=[]; res_H=[]; res_T=[]
for f in sorted(glob.glob("deaths/*_death/log.csv")):
    rows=list(csv.DictReader(open(f)))
    if not rows or "plats" not in rows[0]: continue
    T=[];W=[]
    cum=0; prev=None
    for r in rows:
        if not r['px'] or r['act']=='dead': prev=None; continue
        t=float(r['t']); py=float(r['py']); pl=parse(r['plats'])
        if prev is not None:
            t0,py0,pl0=prev
            ds=[]
            for x0,x1,top,k in pl:
                if not k or k[0] in "bcj": continue
                c=[top-q[2] for q in pl0 if q[3]==k and abs(q[0]-x0)<=3 and abs((q[1]-q[0])-(x1-x0))<=4 and -4<=top-q[2]<=250]
                if c: ds.append(min(c))
            sc=float(np.median(ds)) if ds else 0.0
            if t-t0>0.2:  # gap
                T.append(None); W.append(None)
            cum+=max(sc,0)
        prev=(t,py,pl)
        T.append(t); W.append(cum-py)
    # split segments
    segs=[]; cur=[]
    for t,w in zip(T,W):
        if t is None:
            if cur: segs.append(cur); cur=[]
        else: cur.append((t,w))
    if cur: segs.append(cur)
    for seg in segs:
        if len(seg)<20: continue
        t=np.array([a for a,b in seg]); w=np.array([b for a,b in seg])
        # smooth velocity sign: find local minima (bounces): w[i] <= neighbors within +-2 and then rises >40
        n=len(w); mins=[]
        for i in range(2,n-2):
            if w[i]==min(w[max(0,i-3):i+4]) and (max(w[i:i+12])-w[i])>60 and (max(w[max(0,i-12):i+1])-w[i])>30:
                if not mins or i-mins[-1]>5: mins.append(i)
        for a,b in zip(mins[:-1],mins[1:]):
            tt=t[a:b+1]; ww=w[a:b+1]
            if len(tt)<15 or tt[-1]-tt[0]>2.0: continue
            # fit interior
            ti=tt[2:-2]-tt[0]; wi=ww[2:-2]
            c=np.polyfit(ti,wi,2)
            fit=np.polyval(c,ti); err=np.sqrt(np.mean((fit-wi)**2))
            if err>8: continue
            g=-2*c[0]; v0=c[1]; H=ww.max()-ww[0]; Tf=tt[-1]-tt[0]
            res_g.append(g); res_v.append(v0); res_H.append(H); res_T.append(Tf)
res_g=np.array(res_g); res_v=np.array(res_v); res_H=np.array(res_H)
print("n jumps", len(res_g))
print("g  pct 10/25/50/75/90:", np.percentile(res_g,[10,25,50,75,90]).round(0))
print("v0 pct:", np.percentile(res_v,[10,25,50,75,90]).round(0))
print("H  pct:", np.percentile(res_H,[10,25,50,75,90]).round(0))
m=(res_H>200)&(res_H<300)
print("normal jumps n",m.sum()," g med",np.median(res_g[m]).round(0)," v0 med",np.median(res_v[m]).round(0)," H med",np.median(res_H[m]).round(0), "v0^2/2g", np.median(res_v[m]**2/(2*res_g[m])).round(0))
