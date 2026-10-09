# -*- coding: utf-8 -*-
"""阶段 1：死亡分析师 —— 第一个真正的 agent。

用法：
  python analyst.py                  # 分析 deaths/ 下最新的 death 文件夹
  python analyst.py 203238_death      # 分析指定的文件夹
  python analyst.py --dry-run         # 冒烟测试：不调模型，只打印 system prompt 和工具列表

这就是之前讲的 ReAct 循环的完整实现：
  组装上下文 → 调模型 → 有工具调用就执行、把结果塞回历史 → 没工具调用就结束。
运行时每一步都会打印出来，方便对照着学：它在想什么、调了什么工具、看到了什么。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from model_client import ModelClient
import tools
from tools import TOOL_SCHEMAS, execute
from prompts import SYSTEM_PROMPT


def load_config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def pick_death(project_root, name=None):
    deaths = os.path.join(project_root, "deaths")
    if not os.path.isdir(deaths):
        raise SystemExit(f"找不到 deaths 目录：{deaths}，检查 config.json 里的 project_root")
    if name:
        p = os.path.join(deaths, name)
        if not os.path.isdir(p):
            raise SystemExit(f"找不到 {p}")
        return name, p
    cands = [d for d in os.listdir(deaths)
             if os.path.isdir(os.path.join(deaths, d))]
    if not cands:
        raise SystemExit("deaths/ 是空的，先让 bot 跑出一局死亡再来")
    cands.sort(key=lambda d: os.path.getmtime(os.path.join(deaths, d)))
    return cands[-1], os.path.join(deaths, cands[-1])


def count_chars(messages):
    """估算历史长度。图片按 base64 实际长度计入——之前有个版本漏算了它，
    导致预算形同虚设，这也是要修的 bug 之一。"""
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            n += len(c)
        elif isinstance(c, list):
            for b in c:
                if b.get("type") == "text":
                    n += len(b.get("text", ""))
                elif b.get("type") == "image_url":
                    n += len(b["image_url"]["url"])
    return n


def trim_history(messages, budget):
    """上下文超预算时，丢掉最早的完整"回合"。

    一个"回合" = 一条 assistant 消息 + 它之后、下一条 assistant 消息之前的所有消息
    （tool 返回、穿插的 user 图片消息等）。整个回合要么全留、要么全删：
    如果只删 assistant 留下孤儿 tool 消息，接口会直接报 400
    （"tool message has no matching assistant message with tool_calls"）。
    system prompt 和最初的任务永远保留。
    """
    while len(messages) > 3 and count_chars(messages) > budget:
        j = 2
        while j < len(messages) and messages[j].get("role") != "assistant":
            j += 1
        if j >= len(messages):
            break
        k = j + 1
        while k < len(messages) and messages[k].get("role") != "assistant":
            k += 1
        del messages[j:k]
        print("  …历史太长，丢弃最早的一个回合…")


def to_tool_messages(call_id, result):
    """把工具结果转成消息列表。

    图片的特殊处理：实测发现某些 OpenAI 兼容接口不接受 tool 消息里的
    image_url（报 400），所以图片改走 user 通道——tool 消息里只留一句
    文字占位，图片紧跟在下一条 user 消息里。配对关系不受影响
    （每个 tool_call 照样有对应的 tool 消息）。
    """
    if isinstance(result, dict) and result.get("type") == "image":
        url = f"data:{result['mime']};base64,{result['b64']}"
        return [
            {"role": "tool", "tool_call_id": call_id,
             "content": f"[图片已加载：{result['path']}，见下一条消息]"},
            {"role": "user",
             "content": [{"type": "text", "text": f"截图：{result['path']}"},
                         {"type": "image_url", "image_url": {"url": url}}]},
        ]
    return [{"role": "tool", "tool_call_id": call_id, "content": str(result)}]


def main():
    cfg = load_config()
    project = cfg["project_root"]
    tools.init(project, HERE)

    if "--dry-run" in sys.argv:
        print("=== SYSTEM PROMPT ===")
        print(SYSTEM_PROMPT)
        print("\n=== 工具列表 ===")
        for t in TOOL_SCHEMAS:
            print(" -", t["function"]["name"], ":", t["function"]["description"])
        print("\n冒烟测试通过：prompt 和工具都已就绪，填好 config.json 的模型配置即可实战。")
        return

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    name, death_dir = pick_death(project, args[0] if args else None)
    print(f"分析目标：{death_dir}")

    mc = ModelClient(**cfg["model"])
    max_steps = cfg.get("analyst", {}).get("max_steps", 30)
    budget = cfg.get("analyst", {}).get("max_history_chars", 250000)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",
         "content": f"请分析这次死亡：deaths/{name}/（里面有 log.csv 和截图）。按你的工作流来，最后用 write_report 存报告。"},
    ]

    final_text = ""
    try:
        for step in range(1, max_steps + 1):
            trim_history(messages, budget)
            print(f"\n--- 步骤 {step}（历史约 {count_chars(messages)} 字符）---")
            text, calls = mc.chat(messages, tools=TOOL_SCHEMAS)
            if text:
                short = text[:300].replace("\n", " ")
                print("思考/回答：", short + ("…" if len(text) > 300 else ""))
            final_text = text
            assistant_msg = {"role": "assistant", "content": text or ""}
            if calls:
                assistant_msg["tool_calls"] = [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"],
                                  "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                    for c in calls]
            messages.append(assistant_msg)
            if not calls:
                print("模型没有再调工具，本轮结束。")
                break
            for c in calls:
                arg_preview = json.dumps(c["arguments"], ensure_ascii=False)[:120]
                print(f"调工具：{c['name']}({arg_preview})")
                t0 = time.time()
                result = execute(c["name"], c["arguments"])
                ms = int((time.time() - t0) * 1000)
                if isinstance(result, dict):
                    preview = "[图片]"
                else:
                    preview = str(result)[:200].replace("\n", " ")
                print(f"  返回（{ms}ms）：{preview}")
                messages.extend(to_tool_messages(c["id"], result))
        else:
            print(f"达到步数上限（{max_steps}），强制结束。")
    except Exception as e:
        print(f"\n模型调用失败：{e}")
        print("请检查 config.json 里 model.base_url / api_key / model 是否正确，")
        print("接口需要是 OpenAI-compatible 的 chat/completions。")
        raise SystemExit(1)

    # 兜底：如果模型忘了调 write_report，把它的最终结论也存一份，不丢东西
    reports = os.path.join(HERE, "reports")
    existing = set(os.listdir(reports)) if os.path.isdir(reports) else set()
    if not any(name in f for f in existing) and final_text:
        os.makedirs(reports, exist_ok=True)
        p = os.path.join(reports, f"{name}_report_unsaved.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(final_text)
        print(f"模型没有调用 write_report，已把它的最终结论存为 {p}")

    print("\n完成。报告在 agent/reports/ 目录下。")


if __name__ == "__main__":
    main()
