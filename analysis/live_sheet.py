import cv2, os, sys, csv, numpy as np, time
L = "live"; F = os.path.join(L, "frames")
n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
fs = sorted(os.listdir(F))[-n:]
if fs:
    t0 = float(fs[-1][:-4])
    ims = []
    for f in fs:
        im = cv2.imread(os.path.join(F, f))
        if im is None: continue
        im = im[:, 80:400]
        ims.append(cv2.putText(im, f"{float(f[:-4]) - t0:.1f}", (5, 20), 0, 0.6, (0, 0, 255), 2))
    while len(ims) % 8: ims.append(np.zeros_like(ims[0]))
    sheet = np.vstack([np.hstack(ims[i:i + 8]) for i in range(0, len(ims), 8)])
    cv2.imwrite("analysis/live_sheet.jpg", cv2.resize(sheet, None, fx=0.55, fy=0.55))
rows = list(csv.reader(open(os.path.join(L, "telemetry.csv"), encoding="utf-8")))[1:]
if rows:
    tl = float(rows[-1][0])
    print("telemetry age", round(time.time() - tl, 1), "s, rows", len(rows))
    last = [r for r in rows if tl - float(r[0]) < n * 0.5]
    for r in last[::max(1, len(last) // 40)]:
        print(f"{float(r[0]) - tl:6.2f} p=({r[1]},{r[2]}) vy={r[3]} vx={r[4]} tgt={r[5]}-{r[6]}@{r[7]}{r[8]} dx={r[9]} ev={r[10]} L{r[11]}R{r[12]} {r[13]} n={r[14]} en={r[15]} st={r[16]}")
print(open(os.path.join(L, "summary.txt"), encoding="utf-8").read().splitlines()[-4:] if os.path.exists(os.path.join(L, "summary.txt")) else "no summary")
