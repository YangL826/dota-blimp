import sys,os,cv2,csv,numpy as np
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import work as B
D=sys.argv[1]; t_from=float(sys.argv[2]); t_to=float(sys.argv[3]); step=int(sys.argv[4]) if len(sys.argv)>4 else 1
fs=sorted(f for f in os.listdir(D) if f.endswith(".jpg")); t0=float(fs[-1][:-4])
rows={r[0]:r for r in csv.reader(open(D+"/log.csv",encoding="utf-8"))}
vt=B.VTracker(); prev=None; col=None; lastp=None
for i,f in enumerate(fs):
    t=float(f[:-4]); dt=t-t0
    im=cv2.imread(D+"/"+f)
    if col is None:
        col=B.find_column(cv2.cvtColor(im,cv2.COLOR_BGR2HSV)); s=(col[1]-col[0])/B.BASE_W
        B.PHYS["a"]=1900*s; B.PHYS["vmax"]=470*s
    p,pl,en=B.perceive(im,col,s)
    if p is None: continue
    vy=vt.update(t,p,pl,s)
    sp_=getattr(vt,"support",None); B.SUPPORT[0]=None if sp_ is None else sp_[0]+(getattr(vt,"total_scroll",0.0)-sp_[1])
    if lastp is not None and t-lastp[0]>0.004:
        d_=B.wrap_dx(lastp[1],p[0],col)
        if abs(d_)<80*s: B.PHYS["vx"]=0.6*B.PHYS["vx"]+0.4*d_/(t-lastp[0])
    lastp=(t,p[0])
    if not (t_from<=dt<=t_to) or i%step: continue
    tg=B.choose(p,vy,pl,en,col,s,prev); prev=tg
    r=rows.get(f[:-4])
    sup=B.SUPPORT[0]
    print(f"{dt:6.2f} p=({p[0]*2:.0f},{p[1]*2:.0f}) vy={vy/s:5.0f} sup={None if sup is None else round(sup*2)} -> {None if tg is None else (tg[0]*2,tg[1]*2,tg[2]*2,tg[3])}  real={'' if r is None else r[4]+'-'+r[5]+'@'+r[6]}")
    for c in sorted(B.DBG)[:4]:
        print(f"      cat{c[0]} {c[1]*2}-{c[2]*2}@{c[3]*2}{c[4]} dx={c[5]*2} reach={c[6]} bad={c[7]}")
