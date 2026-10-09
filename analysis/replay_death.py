import sys,os,cv2,csv,numpy as np
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import bb_dbg as B
D=sys.argv[1]; t_from=float(sys.argv[2]); t_to=float(sys.argv[3]); step=int(sys.argv[4]) if len(sys.argv)>4 else 1
fs=sorted(f for f in os.listdir(D) if f.endswith(".jpg")); t0=float(fs[-1][:-4])
rows={r[0]:r for r in csv.reader(open(D+"/log.csv",encoding="utf-8"))}
vt=B.VTracker(); prev=None; col=None
B.PHYS["a"]=1900*0.4975; B.PHYS["vmax"]=396*0.4975
lastp=None
for i,f in enumerate(fs):
    t=float(f[:-4]); dt=t-t0
    im=cv2.imread(D+"/"+f)
    if col is None:
        col=B.find_column(cv2.cvtColor(im,cv2.COLOR_BGR2HSV)); s=(col[1]-col[0])/B.BASE_W
        B.PHYS["a"]=1900*s; B.PHYS["vmax"]=396*s
    p,pl,en=B.perceive(im,col,s)
    if p is None: continue
    vy=vt.update(t,p,pl,s)
    if lastp is not None and t-lastp[0]>0.004:
        d_=B.wrap_dx(lastp[1],p[0],col)
        if abs(d_)<80*s: B.PHYS["vx"]=0.6*B.PHYS["vx"]+0.4*d_/(t-lastp[0])
    lastp=(t,p[0])
    if not (t_from<=dt<=t_to) or i%step: continue
    B.DBG.clear(); tg=B.choose(p,vy,pl,en,col,s,prev); prev=tg
    r=rows.get(f[:-4])
    print(f"{dt:6.2f} p=({p[0]*2:.0f},{p[1]*2:.0f}) vy={vy/s:5.0f} vx={B.PHYS['vx']/s:5.0f} real_tgt={'' if r is None else r[4]+'-'+r[5]+'@'+r[6]+' '+r[8]}")
    print("      en:",[(int(e[0]*2),int(e[1]*2),int(e[2]*2),int(e[3]*2),e[4]) for e in en])
    for k,c in sorted(B.DBG, key=lambda z: z[0])[:5]:
        x0,x1,top,kind,dx,tt,reach,bad,sev,ev=c
        print(f"      key=({k[0]},{float(k[1]):7.1f}) plat={x0*2}-{x1*2}@{top*2}{kind} dx={dx*2} t={tt} reach={reach} bad={bad} sev={sev} ev={ev*2}")
    if not B.DBG: print("      (no candidates)", [f"{k}@{a*2}-{b*2},{tt*2}" for a,b,tt,k in pl])
