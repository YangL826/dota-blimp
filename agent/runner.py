# -*- coding: utf-8 -*-
"""ReAct 循环：阶段 1（分析师）和阶段 2（执行者）共用的"发动机"。

analyst.py 和 executor.py 只是 thin wrapper：换 system prompt、换任务描述、
换工具列表，循环本身是同一套——这就是之前讲的"agent 内核只有一个 loop"。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from model_client import ModelClient
import tools
from tools import execute


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
    """估算历史长度。图片按 base64 实际长度计入——漏算它曾导致预算形同虚设。"""
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
    如果只删 assistant 留下孤儿 tool 消息，接口会直接报 400。
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

    图片的特殊处理：某些 OpenAI 兼容接口不接受 tool 消息里的 image_url（报 400），
    所以图片改走 user 通道——tool 消息里只留一句文字占位，图片紧跟在下一条
    user 消息里。配对关系不受影响（每个 tool_call 照样有对应的 tool 消息）。
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


def _pause_if_console():
    """防闪退：双击 bat 运行时等用户按回车；输出被重定向到文件时不等待
    （否则窗口会像卡住一样停在那里等一个看不见的按键）。"""
    if sys.stdout.isatty():
        try:
            input("按回车退出…")
        except EOFError:
            pass


def run(cfg, system_prompt, task_message, schemas, report_key=""):
    """跑一轮 ReAct。cfg 里没有 executor 小节时，沿用 analyst 的 limits。"""
    agent_dir = os.path.dirname(os.path.abspath(__file__))
    project = cfg["project_root"]
    tools.init(project, agent_dir)
    tools.clear_notes()  # 每轮清空工作笔记本

    mc = ModelClient(**cfg["model"])
    limits = cfg.get("executor", cfg.get("analyst", {}))
    max_steps = limits.get("max_steps", 30)
    budget = limits.get("max_history_chars", 250000)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task_message},
    ]

    final_text = ""
    trace = []  # 每步一句话摘要：崩溃时存成 partial 报告，分析过程不丢
    call_counts = {}   # (工具名, 参数JSON) -> 累计次数：抓"非连续"的重复调用
    warned_sigs = set()  # 已经提醒过的签名，不重复提醒
    try:
        for step in range(1, max_steps + 1):
            trim_history(messages, budget)
            print(f"\n--- 步骤 {step}（历史约 {count_chars(messages)} 字符）---")
            text, calls = mc.chat(messages, tools=schemas)
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
                # 循环熔断器：同一个工具+同样参数累计调 4 次还没进展，说明在打转
                sig = (c["name"], json.dumps(c["arguments"], sort_keys=True,
                                            ensure_ascii=False))
                call_counts[sig] = call_counts.get(sig, 0) + 1
                if call_counts[sig] == 4 and sig not in warned_sigs:
                    warned_sigs.add(sig)
                    print("  ⚠ 重复调用 4 次，注入提醒")
                    messages.append({
                        "role": "user",
                        "content": (f"⚠ 重复调用提醒：你已经用完全相同的参数调用了 {c['name']} 共 4 次，"
                                    "返回的内容没有变化，你正在原地打转。立刻用 read_notes 查看笔记本里"
                                    "已确认的事实，然后换思路推进（读代码找逻辑、看别的证据、收敛写报告）。"
                                    "不要再重复这次调用。")})
            trace.append(
                "### 步骤 %d\n%s\n工具：%s\n" % (
                    step, (text or "")[:400],
                    ", ".join(c["name"] for c in calls) if calls else "无"))
        else:
            print(f"达到步数上限（{max_steps}），强制结束。")
    except Exception as e:
        print(f"\n模型调用失败：{e}")
        if report_key and trace:
            try:
                reports = os.path.join(agent_dir, "reports")
                os.makedirs(reports, exist_ok=True)
                p = os.path.join(reports, f"{report_key}_report_PARTIAL.md")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(f"# {report_key} —— 中断时的分析（partial，修复未完成）\n\n")
                    f.write(f"中断原因：{e}\n\n已完成 {len(trace)} 步。\n\n")
                    f.write("\n".join(trace))
                    if final_text:
                        f.write(f"\n\n## 最后的模型输出\n\n{final_text}\n")
                print(f"已把中断前的分析存为 {p}")
            except Exception as se:
                print(f"（partial 报告保存失败：{se}）")
        print("请检查 config.json 里 model.base_url / api_key / model 是否正确，")
        print("接口需要是 OpenAI-compatible 的 chat/completions。")
        _pause_if_console()
        raise SystemExit(1)

    # 兜底：如果模型忘了调 write_report，把最后的输出和步骤回放也存一份，不丢东西
    if report_key:
        reports = os.path.join(agent_dir, "reports")
        existing = set(os.listdir(reports)) if os.path.isdir(reports) else set()
        if not any(report_key in f for f in existing) and (final_text or trace):
            os.makedirs(reports, exist_ok=True)
            p = os.path.join(reports, f"{report_key}_report_unsaved.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# {report_key} —— 未正常结束时的抢救记录\n\n")
                if final_text:
                    f.write(f"## 模型最后的输出\n\n{final_text}\n\n")
                if trace:
                    f.write("## 步骤回放（每步摘要）\n\n" + "\n".join(trace) + "\n")
            print(f"模型没有调用 write_report，已把抢救记录存为 {p}")

    print("\n完成。报告在 agent/reports/ 目录下。")
    _pause_if_console()
