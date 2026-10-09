# -*- coding: utf-8 -*-
"""
飞艇跳跃 录制器：录下你玩的画面和按键，给 Claude 分析用来写自动玩的程序
  F8  鼠标指向游戏窗口【左上角】按一下
  F9  鼠标指向游戏窗口【右下角】按一下（自动保存）
  F6  开始 / 停止录制（每秒约 15 帧，存到 frames 文件夹）
  F10 退出
"""
import ctypes, ctypes.wintypes as w, json, os, time, csv
import numpy as np, mss, keyboard, cv2

try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "config.json")
OUT = os.path.join(HERE, "frames"); os.makedirs(OUT, exist_ok=True)
cfg = {"left": 0, "top": 0, "right": 0, "bottom": 0}
if os.path.exists(CFG): cfg.update(json.load(open(CFG)))
st = {"rec": False, "quit": False, "t0": 0.0}

def cur():
    p = w.POINT(); ctypes.windll.user32.GetCursorPos(ctypes.byref(p)); return p.x, p.y
def save(): json.dump(cfg, open(CFG, "w"), indent=2)
def tl(): cfg["left"], cfg["top"] = cur(); save(); print("左上角", cfg["left"], cfg["top"])
def br(): cfg["right"], cfg["bottom"] = cur(); save(); print("右下角", cfg["right"], cfg["bottom"], "已保存")
def tog():
    if cfg["right"] <= cfg["left"]: print("先用 F8/F9 框游戏窗口"); return
    st["rec"] = not st["rec"]; st["t0"] = time.time()
    print("● 录制中" if st["rec"] else "■ 停止")
keyboard.add_hotkey("f8", tl); keyboard.add_hotkey("f9", br)
keyboard.add_hotkey("f6", tog); keyboard.add_hotkey("f10", lambda: st.update(quit=True))

logf = open(os.path.join(OUT, "keys.csv"), "a", newline="")
log = csv.writer(logf)
def on_key(e):
    if st["rec"] and e.name not in ("f6", "f8", "f9", "f10"):
        log.writerow([f"{time.time():.3f}", e.event_type, e.name]); logf.flush()
keyboard.hook(on_key)

print(__doc__)
n = 0
with (mss.MSS() if hasattr(mss, "MSS") else mss.mss()) as sct:
    while not st["quit"]:
        if not st["rec"]: time.sleep(0.05); continue
        t = time.time()
        mon = {"left": cfg["left"], "top": cfg["top"],
               "width": cfg["right"] - cfg["left"], "height": cfg["bottom"] - cfg["top"]}
        img = np.array(sct.grab(mon))[:, :, :3]
        cv2.imwrite(os.path.join(OUT, f"{t:.3f}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        n += 1
        if n % 50 == 0: print(f"已录 {n} 帧")
        time.sleep(max(0, 1/15 - (time.time() - t)))
print("退出，共录", n, "帧")
