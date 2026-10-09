import cv2,os,numpy as np,sys,csv
# usage: multi_sheet.py out.jpg secs n deathdir1 deathdir2 ...
out=sys.argv[1]; secs=float(sys.argv[2]); n=int(sys.argv[3]); dirs=sys.argv[4:]
rows=[]
for D in dirs:
    fs=sorted(f for f in os.listdir(D) if f.endswith(".jpg")); t0=float(fs[-1][:-4])
    sel=[f for f in fs if float(f[:-4])-t0>-secs]
    idx=np.linspace(0,len(sel)-1,n).astype(int)
    ims=[]
    for i in idx:
        f=sel[i]; im=cv2.imread(D+"/"+f)[:, 80:400]
        ims.append(cv2.putText(im,f"{float(f[:-4])-t0:.1f}",(5,20),0,0.6,(0,0,255),2))
    row=np.hstack(ims)
    row=cv2.putText(row,os.path.basename(D),(5,460),0,0.7,(0,255,0),2)
    rows.append(row)
sheet=np.vstack(rows)
cv2.imwrite(out,cv2.resize(sheet,None,fx=0.5,fy=0.5),[cv2.IMWRITE_JPEG_QUALITY,85])
print(sheet.shape)
