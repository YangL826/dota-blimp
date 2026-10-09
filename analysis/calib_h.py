import csv, glob, numpy as np
W=572  # wrap width (col[1]-col[0])
runs=[]
for f in sorted(glob.glob("deaths/*_death/log.csv")):
    rows=list(csv.DictReader(open(f)))
    if not rows or "plats" not in rows[0]: continue
    pts=[]
    for r in rows:
        if not r['px'] or r['act']=='dead': continue
        pts.append((float(r['t']), float(r['px']), r['act']))
    # find runs of same act (← or →) preceded by '·' or opposite, length>=8
    i=0
    while i < len(pts):
        a=pts[i][2]
        if a in ('←','→'):
            j=i
            while j+1<len(pts) and pts[j+1][2]==a and pts[j+1][0]-pts[j][0]<0.08: j+=1
            if j-i>=10:
                seq=pts[max(0,i-1):j+3]
                runs.append((a,seq))
            i=j+1
        else: i+=1
def unwrap(xs):
    out=[xs[0]]
    for x in xs[1:]:
        d=x-out[-1]
        d=(d+W/2)%W-W/2
        out.append(out[-1]+d)
    return np.array(out)
V=[]
for a,seq in runs:
    t=np.array([p[0] for p in seq]); x=unwrap([p[1] for p in seq])
    sgn=1 if a=='→' else -1
    t=t-t[1]
    # velocity by central diff
    v=np.gradient(x,t)*sgn
    V.append((t,v))
# aggregate velocity as function of time since key press
bins=np.arange(-0.05,0.6,0.033)
for b0 in bins:
    vals=[np.interp(b0,t,v) for t,v in V if t[0]<=b0<=t[-1]]
    if vals: print(f"t={b0:5.2f} n={len(vals):3d} v med={np.median(vals):6.0f}  p25={np.percentile(vals,25):6.0f} p75={np.percentile(vals,75):6.0f}")
# steady state
ss=[np.median(v[(t>0.35)]) for t,v in V if (t>0.35).sum()>3]
print("steady vmax median", np.median(ss), "n", len(ss), np.percentile(ss,[10,25,75,90]))
