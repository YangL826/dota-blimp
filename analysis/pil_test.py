import sys,os,glob,cv2,numpy as np
sys.path.insert(0,"."); import work as B
def new_pillars(hsv, col, s, pblob):
    lx, rx = col[0] - int(5*s), col[1] + int(8*s); top_cut=int(60*s)
    pil = cv2.inRange(hsv, (14, 85, 35), (46, 255, 215))
    pil[:top_cut] = 0; pil[:, :lx] = 0; pil[:, rx:] = 0
    if pblob is not None:
        x,y,w,h = pblob
        pil[max(0,y-int(8*s)):y+h+int(8*s), max(0,x-int(8*s)):x+w+int(8*s)] = 0
    pil = cv2.morphologyEx(pil, cv2.MORPH_CLOSE, np.ones((11, 5), np.uint8))
    B.ROI[0]=None
    out=[]; rej=[]
    for x, y, w, h, a in B.blobs(pil, int(250*s*s), half=True):
        if h >= 60*s and 12*s <= w <= 40*s and h > 2.2*w:
            out.append((x, y, w, h))
        elif h>=30*s: rej.append((x,y,w,h))
    return out, rej
files=sorted(glob.glob("raw*/*.png"))+sorted(glob.glob("../frames/*.jpg"))[::10]
for f in files:
    im=cv2.imread(f); hsv=cv2.cvtColor(im,cv2.COLOR_BGR2HSV); col=B.find_column(hsv)
    if col is None: continue
    s=(col[1]-col[0])/B.BASE_W
    B.SPIKE_MEM.clear(); B.PLAYER_LAST[0]=None
    p,pl,en=B.perceive(im,col,s)
    old=[q for q in pl if q[3]=="p"]
    # player orange blob
    m = cv2.inRange(hsv, (10, 140, 140), (25, 255, 255)); m[:int(60*s)]=0
    B.ROI[0]=None
    bs=B.blobs(m, int(40*s*s)); pb=None
    if p is not None and bs:
        pb=min(bs,key=lambda b: abs(b[0]+b[2]/2-p[0])+abs(b[1]+b[3]-(p[1]-28*s)))[:4]
    new,rej=new_pillars(hsv,col,s,pb)
    if old or new or rej:
        print(os.path.basename(f), "old:",[(a,c) for a,b,c,k in old], "new:",[(x,y,h) for x,y,w,h in new], "rej:",rej[:4], "player",pb)
