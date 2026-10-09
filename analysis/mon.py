# 实时监控：打印最近 30 秒的状态统计 + 生成最近画面拼图 analysis/mon_sheet.jpg
import csv, os, sys, time, numpy as np, cv2
R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
L = os.path.join(R, "live")
try:
    print("".join(open(os.path.join(L, "summary.txt"), encoding="utf-8").readlines()[-3:]).rstrip())
except Exception as e:
    print("no summary", e)
try:
    rows = list(csv.DictReader(open(os.path.join(L, "telemetry.csv"), encoding="utf-8")))
except Exception as e:
    rows = []; print("no telemetry", e)
if rows:
    t = np.array([float(r["t"]) for r in rows]); now = t[-1]
    m = t > now - 30
    rs = [r for r, k in zip(rows, m) if k]
    notg = sum(1 for r in rs if not r["tx0"]) / max(1, len(rs))
    dodge = sum(1 for r in rs if "躲" in r["mode"]) / max(1, len(rs))
    stuck = sum(1 for r in rs if r["stuck"] == "1") / max(1, len(rs))
    sc = [float(r["scroll"]) for r in rs]
    print(f"last30s: rows {len(rs)} climb {(sc[-1]-sc[0])/30:.0f}px/s  no-target {notg:.0%}  dodge {dodge:.0%}  stuck {stuck:.0%}  age {time.time()-now:.0f}s")
    kinds = {}
    for r in rs:
        k = (r["tkind"] or "-")[:2]; kinds[k] = kinds.get(k, 0) + 1
    print("target kinds:", dict(sorted(kinds.items(), key=lambda x: -x[1])))
    for r in rows[-4:]:
        print(r["t"][-7:], r["px"], r["py"], r["vy"], r["vx"], f"{r['tx0']}-{r['tx1']}@{r['ttop']}{r['tkind']}", r["tdx"], "L" if r["keyL"] == "1" else "", "R" if r["keyR"] == "1" else "", r["mode"], "|", r.get("cands", "")[:120])
F = os.path.join(L, "frames")
fs = sorted(os.listdir(F))[-int(sys.argv[1]) if len(sys.argv) > 1 else -12:]
ims = []
for f in fs:
    im = cv2.imread(os.path.join(F, f))
    if im is None: continue
    im = im[:, 80:400]
    cv2.putText(im, f[-9:-4], (5, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    ims.append(im)
if ims:
    while len(ims) % 6: ims.append(np.zeros_like(ims[0]))
    sheet = np.vstack([np.hstack(ims[i:i+6]) for i in range(0, len(ims), 6)])
    cv2.imwrite(os.path.join(R, "analysis", "mon_sheet.jpg"), cv2.resize(sheet, None, fx=0.6, fy=0.6))
