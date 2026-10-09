# -*- coding: utf-8 -*-
"""人工确认步骤（human-in-the-loop）：把 analysis/work.py 提升为 blimp_bot.py。

看完 executor 的报告、确认改动没问题后，运行这个脚本：
  备份旧 blimp_bot.py → blimp_bot.bak_<时间>.py，再把 work.py 复制过去。
bot 检测到 blimp_bot.py 更新会自动热更新并开下一局。
"""
import json
import os
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
project = cfg["project_root"]
src = os.path.join(project, "analysis", "work.py")
dst = os.path.join(project, "blimp_bot.py")

if not os.path.isfile(src):
    raise SystemExit(f"找不到 {src}")
if not os.path.isfile(dst):
    raise SystemExit(f"找不到 {dst}，不敢新建，先检查项目目录")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
bak = os.path.join(project, f"blimp_bot.bak_{stamp}.py")
shutil.copy2(dst, bak)
print(f"已备份旧版：{os.path.basename(bak)}")
shutil.copy2(src, dst)
print("已复制 analysis/work.py -> blimp_bot.py，bot 会热更新并开下一局。")
