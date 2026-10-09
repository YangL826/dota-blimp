import csv,glob,numpy as np
from vt_eval import parse
W=572
over=[]
for f in sorted(glob.glob("../deaths/*_death/log.csv")):
    rows=[r for r in csv.DictReader(open(f)) if r.get('plats') is not None and r['px'] and r['act']!='dead']
    for i in range(2,len(rows)-2):
        y_prev=float(rows[i-1]['py']); y=float(rows[i]['py']); y_next=float(rows[i+1]['py'])
        # local max of screen y (lowest point) with clear falling before and rising after (no scroll during fall)
        if not (y>=y_prev and y>=y_next and y-float(rows[i-2]['py'])>15 and y-float(rows[i+2]['py'])>15): continue
        px=float(rows[i]['px'])
        pls=parse(rows[i]['plats'])
        cands=[]
        for x0,x1,top,k in pls:
            if not k or k[0] not in "gpb": continue
            if '~' in k or '!' in k or '^' in k: continue
            if -8 <= top - y <= 40:
                o=max(x0-px, px-x1, 0)
                # wrap
                o2=min(o, max(x0-(px+W), (px+W)-x1, 0), max(x0-(px-W), (px-W)-x1, 0))
                cands.append((o2, k, x0, x1, top))
        if cands:
            c=min(cands)
            over.append((c[0], c[1], c[2], c[3], c[4], px, y, f.split('/')[2]))
o=np.array([c[0] for c in over])
print("bounces", len(over), "overhang>0:", (o>0).sum())
print(sorted([round(c[0]) for c in over if c[0]>0])[-30:])
for c in sorted(over, key=lambda c:-c[0])[:12]: print(c)
