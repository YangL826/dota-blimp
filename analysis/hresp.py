import csv,glob,numpy as np
W=572
tau=0.167; V=470
res=[]
for f in sorted(glob.glob("deaths/*_death/log.csv")):
    rows=[r for r in csv.DictReader(open(f)) if r['px'] and r['act']!='dead']
    if len(rows)<30: continue
    t=np.array([float(r['t']) for r in rows]); x=np.array([float(r['px']) for r in rows]); y=np.array([float(r['py']) for r in rows])
    vy=np.array([float(r['vy']) for r in rows])
    a=[r['act'][:1] for r in rows]
    xu=[x[0]]
    for i in range(1,len(x)):
        d=(x[i]-x[i-1]+W/2)%W-W/2; xu.append(xu[-1]+d)
    xu=np.array(xu)
    # windows of 6 frames with constant key
    for i in range(1,len(t)-7):
        k=a[i]
        if k not in '←→·': continue
        if not all(a[j]==k for j in range(i,i+6)): continue
        if t[i+6]-t[i]>0.25: continue
        u={'←':-1,'→':1,'·':0}[k]
        # initial velocity from previous frames
        v0=(xu[i]-xu[i-1])/(t[i]-t[i-1]) if t[i]-t[i-1]>0 else 0
        # model prediction of displacement over window
        T=t[i+6]-t[i]
        pred = u*V*T + (v0-u*V)*tau*(1-np.exp(-T/tau))
        act_d = xu[i+6]-xu[i]
        res.append((u, v0, pred, act_d, vy[i], y[i], f.split('/')[1], t[i]))
res=np.array([(r[0],r[1],r[2],r[3],r[4],r[5]) for r in res])
for u in (-1,0,1):
    m=res[:,0]==u
    e=res[m,3]-res[m,2]
    print("u",u,"n",m.sum(),"err mean %.1f MAE %.1f"%(e.mean(),np.abs(e).mean()))
# by vertical phase for held keys
held=res[:,0]!=0
for name,mm in (("rising vy>300",res[:,4]>300),("apex |vy|<300",np.abs(res[:,4])<=300),("falling vy<-300",res[:,4]<-300),("at scroll line py<570",res[:,5]<570)):
    m=held&mm
    e=(res[m,3]-res[m,2])*res[m,0]
    print(name,"n",m.sum()," signed err (pos=more than model) mean %.1f  med %.1f"%(e.mean(),np.median(e)))

# fit V,tau per phase
import itertools
R=[]
for f in sorted(glob.glob("deaths/*_death/log.csv")):
    rows=[r for r in csv.DictReader(open(f)) if r['px'] and r['act']!='dead']
    if len(rows)<30: continue
    t=np.array([float(r['t']) for r in rows]); x=np.array([float(r['px']) for r in rows])
    vy=np.array([float(r['vy']) for r in rows]); a=[r['act'][:1] for r in rows]
    xu=[x[0]]
    for i in range(1,len(x)):
        d=(x[i]-x[i-1]+W/2)%W-W/2; xu.append(xu[-1]+d)
    xu=np.array(xu)
    for i in range(1,len(t)-7):
        k=a[i]
        if k not in '←→': continue
        if not all(a[j]==k for j in range(i,i+6)): continue
        if t[i+6]-t[i]>0.25 or t[i]-t[i-1]>0.06: continue
        u={'←':-1,'→':1}[k]
        v0=(xu[i]-xu[i-1])/(t[i]-t[i-1])
        R.append((u,v0,t[i+6]-t[i],xu[i+6]-xu[i],vy[i]))
R=np.array(R)
def err(Vv,tt,sel):
    u,v0,T,d=R[sel,0],R[sel,1],R[sel,2],R[sel,3]
    pred=u*Vv*T+(v0-u*Vv)*tt*(1-np.exp(-T/tt))
    return np.mean(np.abs(pred-d))
for name,sel in (("all",np.ones(len(R),bool)),("rising",R[:,4]>300),("apex",np.abs(R[:,4])<=300),("falling",R[:,4]<-300)):
    best=min(((err(Vv,tt,sel),Vv,tt) for Vv in range(250,651,25) for tt in (0.08,0.1,0.12,0.14,0.167,0.2,0.25,0.3,0.4)))
    print(name, sel.sum(), "best MAE %.1f V %d tau %.3f"%best, " (default model MAE %.1f)"%err(470,0.167,sel))
