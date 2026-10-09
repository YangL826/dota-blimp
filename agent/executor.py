# -*- coding: utf-8 -*-
"""阶段 2：接手工程师。

用法：
  python executor.py                  # 处理 deaths/ 下最新的 death 文件夹
  python executor.py 203238_death      # 处理指定的文件夹
  python executor.py --dry-run         # 冒烟测试：不调模型，只打印 system prompt 和工具列表

工作流：分析死因 → 改 analysis/work.py（自动备份）→ 过 py_compile →
跑 test_harness（errors: 0）→ 写报告。
不碰 blimp_bot.py：复制上线由外部自动 loop（loop.py）完成，
测试门通过后自动 promote + 重启 bot。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from runner import run, pick_death
from tools import EXECUTOR_SCHEMAS
from prompts import EXECUTOR_SYSTEM_PROMPT


def load_config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def main():
    cfg = load_config()

    if "--dry-run" in sys.argv:
        print("=== SYSTEM PROMPT ===")
        print(EXECUTOR_SYSTEM_PROMPT)
        print("\n=== 工具列表 ===")
        for t in EXECUTOR_SCHEMAS:
            print(" -", t["function"]["name"], ":", t["function"]["description"])
        print("\n冒烟测试通过：prompt 和工具都已就绪，填好 config.json 的模型配置即可实战。")
        return

    work = os.path.join(cfg["project_root"], "analysis", "work.py")
    if not os.path.isfile(work):
        raise SystemExit(f"找不到 analysis/work.py（{work}），先确认它存在且与 blimp_bot.py 一致")

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    name, death_dir = pick_death(cfg["project_root"], args[0] if args else None)
    print(f"处理目标：{death_dir}")
    print("工作副本：analysis/work.py（改完记得人工确认后用 run_promote.bat 上线）")
    run(cfg, EXECUTOR_SYSTEM_PROMPT,
        f"请接手这次死亡：deaths/{name}/（里面有 log.csv 和截图）。按你的工作流："
        f"先分析死因，再改 analysis/work.py，编译和回归测试通过后写报告。"
        f"记住：不要复制成 blimp_bot.py——测试通过后外部自动 loop 会负责上线，"
        f"你只管 work.py 和报告。",
        EXECUTOR_SCHEMAS, report_key=name)


if __name__ == "__main__":
    main()
