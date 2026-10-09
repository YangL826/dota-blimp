# 检查按键是否生效：对每段连续按住同一方向 >=0.2s 的区间，比较实际横移和一阶模型预测
import csv, sys, numpy as np
W=572; V=470; tau=0.167
f=sys.argv[1]
rows=list(csv.DictReader(open(f)))
t=np.array([float(r['t']) for r in rows]); x=np.array([float(r['px']) for r in rows])
L=np.array([int(r['keyL']) for r in rows]); R=np.array([int(r['keyR']) for r in rows])
mode=[r['mode'] for r in rows]
xu=[x[0]]
for i in range(1,len(x)):
    d=(x[i]-x[i-1]+W/2)%W-W/2; xu.append(xu[-1]+d)
xu=np.array(xu)
u=np.where(R&(1-L),1,np.where(L&(1-R),-1,0))
i=1; bad=0; tot=0
t0=t[-1]
while i < len(t)-1:
    if u[i]!=0:
        j=i
        while j+1<len(t) and u[j+1]==u[i]: j+=1
        T=t[j]-t[i]
        if T>=0.2:
            v0=(xu[i]-xu[i-1])/max(t[i]-t[i-1],1e-3)
            pred=u[i]*V*T+(v0-u[i]*V)*tau*(1-np.exp(-T/tau))
            act=xu[j]-xu[i]
            tot+=1
            ok = act*u[i] > 0.4*pred*u[i] if pred*u[i]>20 else True
            if not ok:
                bad+=1
                print(f"{t[i]-t0:7.2f}s dir {'R' if u[i]>0 else 'L'} hold {T:.2f}s  v0 {v0:5.0f}  pred {pred:6.0f}  actual {act:6.0f}  modes {set(mode[i:j+1])}")
        i=j+1
    else: i+=1
print("segments",tot,"failed",bad)
