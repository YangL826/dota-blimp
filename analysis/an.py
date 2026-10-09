import cv2, numpy as np, os, json
fs=sorted(f for f in os.listdir("frames") if f.endswith(".jpg"))
def player(hsv):
    m=cv2.inRange(hsv,(10,140,140),(25,255,255)); m[:60]=0; m[:, :180]=0; m[:, 765:]=0
    n,l,st,c=cv2.connectedComponentsWithStats(m)
    if n<2: return None
    i=1+np.argmax(st[1:,4]); return float(c[i][0]),float(st[i,1]+st[i,3])
def plats(hsv):
    g=cv2.inRange(hsv,(42,90,80),(52,170,170))
    n,l,st,c=cv2.connectedComponentsWithStats(g); return [(int(st[i,0]),int(st[i,1]),int(st[i,2])) for i in range(1,n) if st[i,2]>60 and 6<st[i,3]<30]
rows=[]; prev=None; cum=0
for f in fs[30:400]:
    hsv=cv2.cvtColor(cv2.imread("frames/"+f),cv2.COLOR_BGR2HSV)
    p=player(hsv); pl=plats(hsv); t=float(f[:-4])
    sc=0
    if prev:
        ds=[]
        for x,y,w in pl:
            c=[y-py for px,py,pw in prev if abs(px-x)<=2 and abs(pw-w)<=3 and -5<=y-py<=200]
            if c: ds.append(min(c))
        sc=float(np.median(ds)) if ds else 0
    cum+=sc; prev=pl
    rows.append((t,p,sc,cum))
json.dump(rows,open("analysis/track.json","w"))
for t,p,sc,cum in rows[:200]:
    if p: print(f"{t-rows[0][0]:6.3f} x={p[0]:6.1f} feet={p[1]:6.1f} scroll={sc:5.1f} worldH={cum-p[1]:7.1f}")
