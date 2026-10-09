# -*- coding: utf-8 -*-
"""离线回归测试：用 frames/ 里的录像当“屏幕画面”跑一遍 blimp_bot.main()，检查有没有异常。
用法（在 dota_blimp 目录下）：
    python analysis/harness/test_harness.py                 # 测 blimp_bot.py
    python analysis/harness/test_harness.py analysis/work.py # 测工作副本
会把 bot 复制到临时目录里跑，不会污染真正的 deaths/、live/、scores.csv、bot_log.txt。
通过标准：输出 errors: 0（bot_log 里没有“出错”）。录像是固定画面，分数/行为本身没有参考意义。
"""
import sys, os, types, shutil, tempfile
import numpy as np, cv2

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FR = os.path.join(ROOT, "frames")
src = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "blimp_bot.py")
tmp = tempfile.mkdtemp(prefix="blimp_test_")
shutil.copy(src, os.path.join(tmp, "blimp_bot.py"))
shutil.copy(os.path.join(ROOT, "config.json"), tmp)
fs = sorted(f for f in os.listdir(FR) if f.endswith(".jpg"))[100:560]

hot = {}
kb = types.ModuleType("keyboard")
def _add_hotkey(k, f, *a, **kw):
    hot[k] = f
    if k == "f6":
        f()                       # 立即“按 F6”开始
kb.add_hotkey = _add_hotkey
sys.modules["keyboard"] = kb

class _Grab:
    def __init__(self): self.i = 0
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def grab(self, mon):
        self.i += 1
        if self.i <= len(fs):
            im = cv2.imread(os.path.join(FR, fs[self.i - 1]))
        else:
            im = np.zeros((938, 944, 3), np.uint8)   # 录像放完：黑屏 = 死亡
        if self.i > len(fs) + 60:
            hot["f10"]()                              # 退出
        return np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
ms = types.ModuleType("mss"); ms.MSS = _Grab
sys.modules["mss"] = ms

sys.path.insert(0, tmp); os.chdir(tmp)
sys.argv = ["blimp_bot.py"]
import blimp_bot as B
B.key_down = lambda k: None
B.key_up = lambda k: None
B.foreground_title = lambda: "Dota 2"
B.cfg.update({"left": 0, "top": 0, "right": 944, "bottom": 938})
B.main()

log = open(os.path.join(tmp, "bot_log.txt"), encoding="utf-8").read()
print("errors:", log.count("出错"))
for line in log.splitlines():
    if "出错" in line or "本局得分" in line:
        print(line)
print("临时目录:", tmp)
