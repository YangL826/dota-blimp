# 用死亡记录里某一帧的 plats/角色状态离线跑 choose，看新代码会选什么
import sys, os, types, csv, importlib.util
sys.modules["keyboard"] = types.ModuleType("keyboard")
ms = types.ModuleType("mss"); ms.MSS = object; sys.modules["mss"] = ms
src = sys.argv[1]; D = sys.argv[2]; tsel = [float(x) for x in sys.argv[3].split(",")]
spec = importlib.util.spec_from_file_location("W", src); W = importlib.util.module_from_spec(spec)
os.chdir(os.path.dirname(os.path.abspath(src)) + "/..") if src.startswith("analysis") else None
spec.loader.exec_module(W)
W.SCREEN["h"] = 934; W.SCREEN["sy"] = 563
col = (187, 759)
rows = list(csv.DictReader(open(D + "/log.csv")))
t0 = float(rows[-1]["t"])
def parse_plats(sx):
    out = []
    for it in sx.split("|"):
        if not it: continue
        a, b = it.split("@"); x0, x1 = a.split("-")[-2:] if a.count("-") == 1 else a.rsplit("-", 1)
        import re
        m = re.match(r"(-?\d+)([a-z~^!*]*)", b)
        out.append((int(x0), int(x1), int(m.group(1)), m.group(2) or "g"))
    return out
for ts in tsel:
    r = min(rows, key=lambda r: abs(float(r["t"]) - t0 - ts))
    plats = parse_plats(r["plats"])
    vy = float(r["vy"]); W.PHYS["vx"] = float(r["vx"])
    player = (int(r["px"]), int(r["py"]))
    W.SUPPORT[0] = None
    for vyv in (vy,):
        res = W.choose(player, vyv, plats, [], col, 1.0, None, False)
        print(f"{float(r['t'])-t0:6.2f} p={player} vy={vyv:.0f} sc={W.scroll_pred(player[1], vyv, 1182):.0f} -> {None if res is None else res[:4]}  DBG={sorted(W.DBG)[:5]}")
