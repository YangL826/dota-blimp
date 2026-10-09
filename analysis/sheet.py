import cv2,os,numpy as np,sys
D=sys.argv[1]; secs=float(sys.argv[2]) if len(sys.argv)>2 else 4.0; step=int(sys.argv[3]) if len(sys.argv)>3 else 4
fs=sorted(f for f in os.listdir(D) if f.endswith(".jpg")); t0=float(fs[-1][:-4])
sel=[f for f in fs if float(f[:-4])-t0>-secs][::step]
ims=[cv2.putText(cv2.imread(D+"/"+f)[:, 80:400],f"{float(f[:-4])-t0:.2f}",(5,20),0,0.6,(0,0,255),2) for f in sel]
while len(ims)%8: ims.append(np.zeros_like(ims[0]))
sheet=np.vstack([np.hstack(ims[i:i+8]) for i in range(0,len(ims),8)])
cv2.imwrite("analysis/cur_sheet.jpg",cv2.resize(sheet,None,fx=0.55,fy=0.55))
import csv
rows=list(csv.reader(open(D+"/log.csv")))[1:]
for r in rows[-int(secs*15)::3]:
    print(f"{float(r[0])-t0:6.2f} p=({r[1]},{r[2]}) vy={r[3]} tgt={r[4]}-{r[5]}@{r[6]} dx={r[7]} {r[8]} en={r[10]}")
