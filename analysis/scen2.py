# 用死亡记录里的半分辨率帧（放大 2 倍）离线跑 perceive + choose
import sys, os, types, glob, importlib.util, cv2, numpy as np
sys.modules["keyboard"] = types.ModuleType("keyboard")
ms = types.ModuleType("mss"); ms.MSS = object; sys.modules["mss"] = ms
src = sys.argv[1]; D = sys.argv[2]; tsel = [float(x) for x in sys.argv[3].split(",")]
desp = len(sys.argv) > 4 and sys.argv[4] == "1"
spec = importlib.util.spec_from_file_location("W", src); W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)
fs = sorted(glob.glob(D + "/*.jpg")); tl = float(os.path.basename(fs[-1])[:-4])
for ts in tsel:
    f = min(fs, key=lambda f: abs(float(os.path.basename(f)[:-4]) - tl - ts))
    img = cv2.resize(cv2.imread(f), None, fx=2, fy=2)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    col = W.find_column(hsv)
    s = 1.0
    player, plats, enemies = W.perceive(img, col, s)
    W.SCREEN["h"] = img.shape[0]; W.SCREEN["sy"] = 563; W.PHYS["vmax"] = 485
    if os.environ.get("SUP"): W.SUPPORT[0] = float(os.environ["SUP"]); W.STUCK_SOFT[0] = True
    W.DESPERATE[0] = float(os.environ.get("DS", "12")) if desp else 0.0
    print(f"{ts:.2f} col={col} player={player}\n plats={plats}\n enemies={enemies}\n CUT_SRC={[c[:4] for c in W.CUT_SRC]}")
    if desp: print(" escape_parts:", W.escape_parts(s))
    pl_over = os.environ.get("PL")
    if pl_over:
        player = tuple(float(v) for v in pl_over.split(","))
    vys = [float(v) for v in os.environ.get("VY", "700,-300").split(",")]
    for vy in vys:
        res = W.choose(player, vy, plats, enemies, col, s, None, os.environ.get("STUCK","1")=="1")
        print(f"  vy={vy} stuck -> {None if res is None else (res[:5], [round(v,1) for v in res[6:9]])}  DBG={sorted(W.DBG)[:6]}")
