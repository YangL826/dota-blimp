# -*- coding: utf-8 -*-
"""阶段 1：死亡分析师。

用法：
  python analyst.py                  # 分析 deaths/ 下最新的 death 文件夹
  python analyst.py 203238_death      # 分析指定的文件夹
  python analyst.py --dry-run         # 冒烟测试：不调模型，只打印 system prompt 和工具列表

真正的 ReAct 循环在 runner.py 里，这里只是 thin wrapper：
选任务 → 选 prompt → 选工具集 → 交给 runner 跑。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from runner import run, pick_death
from tools import TOOL_SCHEMAS
from prompts import SYSTEM_PROMPT


def load_config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def main():
    cfg = load_config()

    if "--dry-run" in sys.argv:
        print("=== SYSTEM PROMPT ===")
        print(SYSTEM_PROMPT)
        print("\n=== 工具列表 ===")
        for t in TOOL_SCHEMAS:
            print(" -", t["function"]["name"], ":", t["function"]["description"])
        print("\n冒烟测试通过：prompt 和工具都已就绪，填好 config.json 的模型配置即可实战。")
        return

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    name, death_dir = pick_death(cfg["project_root"], args[0] if args else None)
    print(f"分析目标：{death_dir}")
    run(cfg, SYSTEM_PROMPT,
        f"请分析这次死亡：deaths/{name}/（里面有 log.csv 和截图）。按你的工作流来，最后用 write_report 存报告。",
        TOOL_SCHEMAS, report_key=name)


if __name__ == "__main__":
    main()
