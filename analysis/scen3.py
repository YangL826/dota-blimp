import sys, types, importlib.util
sys.modules["keyboard"] = types.ModuleType("keyboard")
ms = types.ModuleType("mss"); ms.MSS = object; sys.modules["mss"] = ms
spec = importlib.util.spec_from_file_location("W", sys.argv[1]); W = importlib.util.module_from_spec(spec); spec.loader.exec_module(W)
W.SCREEN["h"] = 934; W.SCREEN["sy"] = 563; W.PHYS["vmax"] = 485; W.PHYS["vx"] = -426
col = (187, 759)
W.SPIKES[:] = [(256, 282, 558), (640, 672, 674)]
plats = [(207,228,558,'g~'), (308,331,558,'g~'), (697,719,674,'g~'), (595,616,674,'g~')]
for vy in (218, 300):
    res = W.choose((350, 563), vy, plats, [], col, 1.0, None, False)
    print(vy, res[:5] if res else None, sorted(W.DBG))
for vy in (218, 300):
    res = W._choose((350, 563), vy, plats, [], col, 1.0, None, False, {}, False)
    print("tilde_ok", vy, res[:5] if res else None, sorted(W.DBG))
