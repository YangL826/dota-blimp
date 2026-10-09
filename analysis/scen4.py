import sys, types, importlib.util
sys.modules["keyboard"] = types.ModuleType("keyboard")
ms = types.ModuleType("mss"); ms.MSS = object; sys.modules["mss"] = ms
spec = importlib.util.spec_from_file_location("W", sys.argv[1]); W = importlib.util.module_from_spec(spec); spec.loader.exec_module(W)
W.SCREEN["h"] = 934; W.SCREEN["sy"] = 563; W.PHYS["vmax"] = 485; W.PHYS["vx"] = 0
col = (187, 759)
plats = [(326,356,834,'p'), (217,246,542,'p'), (454,484,369,'p'), (197,226,196,'p'), (686,710,10,'p')]
for (px, fy, vy, stuck) in ((341, 834, 770, False), (341, 834, 770, True), (341, 700, 500, True), (300, 600, 150, True)):
    W.SUPPORT[0] = 834
    res = W.choose((px, fy), vy, plats, [], col, 1.0, None, stuck)
    print((px, fy, vy, stuck), "->", None if res is None else (res[:4], round(res[4]), round(res[5]), [round(v,2) for v in res[6:9]]))
    print("   DBG", sorted(W.DBG))
ev = W.plan_eventual(plats, [], col, 1.0)
print("ev", {k: round(v) for k, v in ev.items()})
