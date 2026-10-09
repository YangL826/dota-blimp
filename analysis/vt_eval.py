import sys,csv,glob,numpy as np
sys.path.insert(0,".")
import work as N, work_bak_2000 as O
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
def run(M, rows):
    vt=M.VTracker(); out=[]
    for r in rows:
        t=float(r['t']); p=(float(r['px']),float(r['py'])); pl=parse(r['plats'])
        out.append(vt.update(t,p,pl,1.0))
    return np.array(out)
errs={"old":[], "new":[]}
for f in sorted(glob.glob("../deaths/*_death/log.csv")):
    rows=[r for r in csv.DictReader(open(f)) if r.get('plats') is not None and r['px'] and r['act']!='dead']
    if len(rows)<50: continue
    vo=run(O,rows); vn=run(N,rows)
    vt=N.VTracker(); H=[]; T=[]
    for r in rows:
        t=float(r['t']); p=(float(r['px']),float(r['py'])); pl=parse(r['plats'])
        vt.update(t,p,pl,1.0); H.append(vt.total_scroll-p[1]); T.append(t)
    H=np.array(H); T=np.array(T)
    g=1182.0
    for i in range(4,len(rows)-4):
        tau=T[i-4:i+5]-T[i]; z=H[i-4:i+5]+0.5*g*tau**2
        A=np.vstack([tau,np.ones_like(tau)]).T
        sol=np.linalg.lstsq(A,z,rcond=None)[0]
        rms=np.sqrt(np.mean((A@sol-z)**2))
        if rms>3: continue
        vref=sol[0]
        errs["old"].append(vo[i]-vref); errs["new"].append(vn[i]-vref)
for k in errs:
    e=np.array(errs[k]); print(k, "n",len(e)," mean %.0f"%e.mean()," MAE %.0f"%np.abs(e).mean(), " p90 |e| %.0f"%np.percentile(np.abs(e),90), " p99 %.0f"%np.percentile(np.abs(e),99))
