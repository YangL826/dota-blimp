import csv,glob,numpy as np
from vt_eval import parse
W=572
res=[]
for f in sorted(glob.glob("../deaths/*_death/log.csv")):
    rows=[r for r in csv.DictReader(open(f)) if r.get('plats') is not None and r['px'] and r['act']!='dead']
    for i in range(3,len(rows)-2):
        # landing: py decreasing after increasing (screen y): use py and vy
        y0=float(rows[i-2]['py']); y1=float(rows[i]['py']); y2=float(rows[i+2]['py'])
        if not (y1-y0>8 and y1-y2>8): continue
        r=rows[i-2]
        if not r['tgt_x0']: continue
        x0=float(r['tgt_x0']); x1=float(r['tgt_x1']); k=r['tkind']; top=float(r['tgt_top'])
        px=float(rows[i]['px'])
        # landed on what? find plat with top near py within 15 px
        pls=parse(rows[i]['plats'])
        on=[q for q in pls if abs(q[2]-y1)<20 and q[0]-25<=px<=q[1]+25]
        c=(x0+x1)/2; off=(px-c+W/2)%W-W/2
        res.append((k, off, x1-x0, abs(top-y1)<25, f.split('/')[2]))
narrow=[r for r in res if r[0] and (r[0][0]=='p' or '~' in r[0] or r[0]=='j')]
wide=[r for r in res if r[0] and not (r[0][0]=='p' or '~' in r[0] or r[0]=='j')]
for name,L in (("narrow",narrow),("wide",wide)):
    L2=[r for r in L if r[3]]
    o=np.array([r[1] for r in L2]); w=np.array([r[2] for r in L2])
    if len(o)==0: continue
    print(name,"n",len(o),"|off| med %.1f p75 %.1f p90 %.1f"%(np.median(np.abs(o)),np.percentile(np.abs(o),75),np.percentile(np.abs(o),90)), " outside half-width:", int((np.abs(o)>w/2).sum()))
