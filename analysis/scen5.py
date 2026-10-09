import sys, types, importlib.util
sys.modules["keyboard"] = types.ModuleType("keyboard")
ms = types.ModuleType("mss"); ms.MSS = object; sys.modules["mss"] = ms
spec = importlib.util.spec_from_file_location("W", sys.argv[1]); W = importlib.util.module_from_spec(spec); spec.loader.exec_module(W)
W.SCREEN["h"] = 934; W.SCREEN["sy"] = 563; W.PHYS["vmax"] = 485; W.PHYS["vx"] = 0
col = (187, 759)
en = [(474, 440, 72, 84, 'balloon'), (342, 266, 72, 84, 'balloon')]
plats = [(649, 748, 828, 'g'), (340, 374, 530, 'p'), (377, 413, 50, 'p'), (452, 496, 398, 'j'), (320, 364, 224, 'j')]
W.SUPPORT[0] = 828
for stuck in (False, True):
    res = W.choose((717, 828), 770, plats, en, col, 1.0, None, stuck)
    print("stuck", stuck, "->", None if res is None else (res[:4], round(res[4]), round(res[5]), [round(float(v),2) for v in res[6:9]]))
    print("   DBG", sorted(W.DBG))
ev = W.plan_eventual(plats, en, col, 1.0)
print("ev", {k: round(v) for k, v in ev.items()})
# after side bounce on pillar at ~590, x ~ 362 moving right
W.SUPPORT[0] = 590; W.PHYS["vx"] = 200
res = W.choose((362, 590), 770, plats, en, col, 1.0, None, False)
print("from pillar side ->", None if res is None else (res[:4], round(res[4])), sorted(W.DBG))
