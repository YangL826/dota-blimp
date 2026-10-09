import sys, os, cv2, numpy as np, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import blimp_bot as B
D=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"frames")
fs=sorted(f for f in os.listdir(D) if f.endswith(".jpg"))
keys=[(float(a),b,c) for a,b,c in csv.reader(open(D+"/keys.csv"))]
def keystate(t):
    st={"left":False,"right":False}
    for a,b,c in keys:
        if a>t: break
        st[c]= (b=="down")
    return "R" if st["right"] else ("L" if st["left"] else "-")
vt=B.VTracker(); col=None; prev=None; agree=n=0
for i,f in enumerate(fs[30:700]):
    t=float(f[:-4]); img=cv2.imread(D+"/"+f)
    if col is None: col=B.find_column(cv2.cvtColor(img,cv2.COLOR_BGR2HSV)); s=(col[1]-col[0])/B.BASE_W; print("col",col,"s",s)
    pl,plats,en=B.perceive(img,col,s)
    if pl is None: print(i,"no player"); vt.reset(); continue
    vy=vt.update(t,pl,plats,s)
    tg=B.choose(pl,vy,plats,en,col,s,prev); prev=tg
    d="-" if tg is None else ("R" if tg[4]>12*s else ("L" if tg[4]<-12*s else "-"))
    u=keystate(t); n+=1; agree+= (d==u)
    if i%5==0: print(f"{i:3d} p=({pl[0]:.0f},{pl[1]:.0f}) vy={vy:6.0f} plats={len(plats):2d} en={len(en)} tgt={None if tg is None else (tg[0],tg[2],tg[3],round(tg[4]))} bot={d} user={u}")
print("agree",agree/n)
