# -*- coding: utf-8 -*-
"""工具层：模型能用的「手脚」。

对照之前讲的设计原则：
  1. 每个工具功能单一、行为确定；
  2. 所有路径被钉死在项目目录内（_safe 防越界）；
  3. 最小权限：分析师阶段只有读 + 写报告；阶段 2 才多给
     write_file / edit_file / run_command，且每个都有自己的护栏：
     写文件只能写 analysis/work.py（自动备份），跑命令只有两条白名单。

TOOL_SCHEMAS 是分析师的工具集；EXECUTOR_SCHEMAS 在此基础上加了
写和执行，是阶段 2 的工具集。两边通过名字对应到 TOOL_FUNCS。
"""
import base64
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime

PROJECT_ROOT = None
AGENT_DIR = None
_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
# 单次工具返回进历史的上限：超过就截断，防止某次返回把上下文撑爆。
MAX_RESULT_CHARS = 15000
# 写文件的白名单：只能动这一个文件
WRITABLE = {"analysis/work.py"}
# 工作笔记本：每轮运行时 runner 会清空，模型用 write_note/read_notes 读写。
# 它是独立文件，不会被 trim_history 裁掉——专治"失忆循环"。
NOTES_FILE = None
NOTES_MAX_CHARS = 20000


def init(project_root, agent_dir):
    global PROJECT_ROOT, AGENT_DIR, NOTES_FILE
    PROJECT_ROOT = os.path.abspath(project_root)
    AGENT_DIR = os.path.abspath(agent_dir)
    NOTES_FILE = os.path.join(AGENT_DIR, "working", "notes.md")


def clear_notes():
    """每轮运行开始时清空笔记本。"""
    if NOTES_FILE:
        os.makedirs(os.path.dirname(NOTES_FILE), exist_ok=True)
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            f.write("")


def _safe(path, base):
    """把传入的路径钉死在 base 目录内，越界就抛错。"""
    p = os.path.abspath(os.path.join(base, path or ""))
    if p != base and not p.startswith(base + os.sep):
        raise ValueError(f"路径越界，已拒绝：{path}")
    return p


def _norm(p):
    return (p or "").replace("\\", "/").lstrip("/")


def _backup(path):
    """写文件前的自动备份，沿用项目里 .bak 的习惯。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + f".bak_{stamp}"
    shutil.copy2(path, bak)
    return bak


# ---------- 只读工具（阶段 1 就有） ----------

def do_read_file(path, max_chars=20000):
    p = _safe(path, PROJECT_ROOT)
    if not os.path.isfile(p):
        return f"文件不存在：{path}"
    with open(p, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if len(text) > max_chars:
        text = (text[:max_chars]
                + f"\n…（太长已截断，全文 {len(text)} 字符，可用 read_file_tail 看尾部，或调小 max_chars 分段读）")
    return text


def do_read_file_tail(path, tail_chars=8000):
    """读文本文件的尾部。log.csv 这种"结局在最后"的文件，先看尾部定位异常帧最划算。"""
    p = _safe(path, PROJECT_ROOT)
    if not os.path.isfile(p):
        return f"文件不存在：{path}"
    with open(p, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if len(text) > tail_chars:
        return (f"（全文 {len(text)} 字符，以下是最后 {tail_chars} 字符；"
                f"要看前面用 read_file 分段读）\n" + text[-tail_chars:])
    return text


def do_list_dir(path=""):
    p = _safe(path, PROJECT_ROOT)
    if not os.path.isdir(p):
        return f"目录不存在：{path}"
    lines = []
    for name in sorted(os.listdir(p)):
        fp = os.path.join(p, name)
        if os.path.isdir(fp):
            lines.append(f"[目录] {name}")
        else:
            lines.append(f"[文件] {os.path.getsize(fp) // 1024}KB {name}")
    return "\n".join(lines) or "（空目录）"


def do_read_image(path):
    """读一张图。返回 dict，runner.py 会把它拼成多模态消息发给模型。"""
    p = _safe(path, PROJECT_ROOT)
    ext = os.path.splitext(p)[1].lower()
    if ext not in _IMAGE_EXTS:
        return f"不是支持的图片格式（jpg/png）：{path}"
    if not os.path.isfile(p):
        return f"文件不存在：{path}"
    if os.path.getsize(p) > 3 * 1024 * 1024:
        return f"图片太大（>3MB），跳过：{path}"
    mime = "image/png" if ext == ".png" else "image/jpeg"
    with open(p, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return {"type": "image", "mime": mime, "b64": b64, "path": path}


def do_write_report(filename, content):
    """唯一的报告出口：把 Markdown 报告写到 agent/reports/。"""
    name = os.path.basename(filename or "")
    if not name.endswith(".md"):
        return "文件名必须以 .md 结尾"
    reports = os.path.join(AGENT_DIR, "reports")
    os.makedirs(reports, exist_ok=True)
    p = os.path.join(reports, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return f"报告已保存：{p}"


def _safe_key(key):
    return (key or "").strip().replace("\n", " ")[:60] or "未命名"


def do_write_note(key, content):
    """工作笔记本：记下已确认的事实（读过的文件、关键证据、死因假设、当前计划）。
    同一个 key 重复写会覆盖旧内容。笔记本是独立文件，不会被历史裁剪丢掉。"""
    if NOTES_FILE is None:
        return "笔记本还没初始化（runner 会在每轮开始时准备好）"
    key = _safe_key(key)
    content = (content or "").strip()
    if not content:
        return "拒绝：内容为空，不记"
    os.makedirs(os.path.dirname(NOTES_FILE), exist_ok=True)
    old = ""
    if os.path.isfile(NOTES_FILE):
        with open(NOTES_FILE, encoding="utf-8", errors="replace") as f:
            old = f.read()
    entry = f"## {key}\n{content}\n"
    pattern = re.compile(r"^## " + re.escape(key) + r"\s*\n(.*?)(?=^## |\Z)",
                         re.M | re.S)
    if pattern.search(old):
        new = pattern.sub(entry, old)
    else:
        new = old + ("\n" if old and not old.endswith("\n") else "") + entry
    if len(new) > NOTES_MAX_CHARS:
        return (f"拒绝：笔记本已满（{len(new)}>{NOTES_MAX_CHARS} 字）。"
                "用更短的话重写旧笔记，或精简后再记。")
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        f.write(new)
    return f"已记入笔记本：{key}（{len(content)} 字）"


def do_read_notes():
    """读工作笔记本。读文件/图片之前先查它——记过的东西不许重复读。"""
    if NOTES_FILE is None or not os.path.isfile(NOTES_FILE):
        return "（笔记本是空的，还没记任何东西）"
    with open(NOTES_FILE, encoding="utf-8", errors="replace") as f:
        text = f.read().strip()
    return text or "（笔记本是空的，还没记任何东西）"


# ---------- 阶段 2 新增：受控的写与执行 ----------

def do_write_file(path, content):
    """全量写文件。只能写 analysis/work.py；写入前自动备份旧版本。
    大重构才用，平时小改用 edit_file。"""
    norm = _norm(path)
    if norm not in WRITABLE:
        return f"拒绝：只能写 {sorted(WRITABLE)}，你给了 {path}"
    if not content or not content.strip():
        return "拒绝：内容为空，不写"
    p = _safe(norm, PROJECT_ROOT)
    bak_msg = "（原文件不存在，直接新建）"
    if os.path.exists(p):
        bak_msg = f"旧版本已备份为 {os.path.basename(_backup(p))}"
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return f"已写入 {norm}（{len(content)} 字符）。{bak_msg}"


def do_edit_file(path, old_text, new_text):
    """精准改文件：把 old_text 精确替换成 new_text（外科手术式）。
    old_text 必须在文件中恰好出现一次——找不到或出现多次都拒绝，
    防止改错地方。这是平时改代码的首选，比全量 write_file 安全得多。"""
    norm = _norm(path)
    if norm not in WRITABLE:
        return f"拒绝：只能改 {sorted(WRITABLE)}，你给了 {path}"
    if not old_text:
        return "拒绝：old_text 为空"
    p = _safe(norm, PROJECT_ROOT)
    if not os.path.isfile(p):
        return f"文件不存在：{path}"
    with open(p, encoding="utf-8") as f:
        text = f.read()
    count = text.count(old_text)
    if count == 0:
        return "拒绝：old_text 在文件中找不到（可能代码和你读到的不一致，先重读再改）"
    if count > 1:
        return f"拒绝：old_text 出现了 {count} 次，有歧义。请加长上下文让它唯一。"
    bak = os.path.basename(_backup(p))
    text = text.replace(old_text, new_text, 1)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return f"已替换 1 处，旧版本备份为 {bak}。"


def _allowed_command(cmd):
    c = _norm(cmd)
    return (c.startswith("python -m py_compile analysis/work.py")
            or c.startswith("python analysis/harness/test_harness.py"))


def do_run_command(cmd, timeout_sec=600):
    """跑命令。白名单只有两条（测试门）：
      python -m py_compile analysis/work.py
      python analysis/harness/test_harness.py analysis/work.py
    其他一律拒绝。用 shell=False 执行，拼在后面的恶意串只会被当成普通参数。"""
    if not _allowed_command(cmd):
        return ("拒绝：只能跑以下两条命令：\n"
                "  python -m py_compile analysis/work.py\n"
                "  python analysis/harness/test_harness.py analysis/work.py")
    exe = sys.executable  # 就是跑 analyst/executor 的那个 venv python
    parts = shlex.split(_norm(cmd))
    parts[0] = exe
    try:
        proc = subprocess.run(parts, cwd=PROJECT_ROOT, capture_output=True,
                              text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        return f"超时（>{timeout_sec}s）已终止。测试太久多半是卡住了，检查改动。"
    out = (proc.stdout or "") + (proc.stderr or "")
    if len(out) > 8000:
        out = out[:2000] + "\n…（中间省略）…\n" + out[-6000:]
    return f"退出码：{proc.returncode}\n{out or '（无输出）'}"


TOOL_FUNCS = {
    "read_file": do_read_file,
    "read_file_tail": do_read_file_tail,
    "list_dir": do_list_dir,
    "read_image": do_read_image,
    "write_report": do_write_report,
    "write_note": do_write_note,
    "read_notes": do_read_notes,
    "write_file": do_write_file,
    "edit_file": do_edit_file,
    "run_command": do_run_command,
}


# ---------- 给模型看的工具说明书 ----------

def _schema(name, description, props, required):
    return {"type": "function",
            "function": {"name": name, "description": description,
                         "parameters": {"type": "object",
                                        "properties": props,
                                        "required": required}}}


TOOL_SCHEMAS = [
    _schema("read_file", "从头读取项目目录内的文本文件，如 HANDOFF.md、代码。超长会自动截断。",
            {"path": {"type": "string", "description": "相对项目根目录的路径，如 'HANDOFF.md'"},
             "max_chars": {"type": "integer", "description": "最多读多少字符，默认 20000"}},
            ["path"]),
    _schema("read_file_tail", "读取文本文件的尾部。看 log.csv 时优先用它：死亡的结局在最后，先看尾部定位异常帧最划算。",
            {"path": {"type": "string", "description": "相对项目根目录的路径，如 'deaths/203238_death/log.csv'"},
             "tail_chars": {"type": "integer", "description": "读最后多少字符，默认 8000"}},
            ["path"]),
    _schema("list_dir", "列出项目目录内某个文件夹的内容。先看结构、再决定读哪个文件时用。",
            {"path": {"type": "string", "description": "相对项目根目录的路径，默认为根目录"}},
            []),
    _schema("read_image", "查看一张 death 截图（jpg/png），直接看图分析敌人和平台位置。一次看一张，只挑关键帧看。",
            {"path": {"type": "string", "description": "相对项目根目录的图片路径，如 'deaths/203238_death/123.456.jpg'"}},
            ["path"]),
    _schema("write_note", "工作笔记本：把已确认的事实立刻记下来（读过的文件清单、关键证据、死因假设、当前计划），防止历史被裁剪后失忆。调 read_file/read_image 前先用 read_notes 查，记过的东西不许重复读。同一个 key 重复写会覆盖旧内容。",
            {"key": {"type": "string", "description": "短标题，如 '已读文件'、'死因假设'、'计划'"},
             "content": {"type": "string", "description": "要记的内容，简明扼要"}},
            ["key", "content"]),
    _schema("read_notes", "读工作笔记本。每次读文件/图片/列目录之前先读它——已经记下来的东西不许再读一遍。",
            {},
            []),
    _schema("write_report", "把最终报告（Markdown 中文）保存到 agent/reports/。任务完成前必须调用一次。",
            {"filename": {"type": "string", "description": "文件名，如 '203238_death_report.md'，必须 .md 结尾"},
             "content": {"type": "string", "description": "报告正文（Markdown，中文）"}},
            ["filename", "content"]),
]

EXECUTOR_SCHEMAS = TOOL_SCHEMAS + [
    _schema("write_file", "全量写文件。只能写 analysis/work.py，写入前自动备份。大重构才用，平时小改用 edit_file。",
            {"path": {"type": "string", "description": "只能是 'analysis/work.py'"},
             "content": {"type": "string", "description": "文件完整新内容"}},
            ["path", "content"]),
    _schema("edit_file", "精准改文件：把 old_text 精确替换成 new_text。old_text 必须在文件中恰好出现一次。平时改代码的首选。",
            {"path": {"type": "string", "description": "只能是 'analysis/work.py'"},
             "old_text": {"type": "string", "description": "要被替换的原文（从文件中原样复制，含缩进）"},
             "new_text": {"type": "string", "description": "替换成的新代码"}},
            ["path", "old_text", "new_text"]),
    _schema("run_command", "跑测试命令。白名单只有两条：编译检查和回归测试，其他一律会被拒绝。",
            {"cmd": {"type": "string",
                     "description": "只能是 'python -m py_compile analysis/work.py' 或 'python analysis/harness/test_harness.py analysis/work.py'"},
             "timeout_sec": {"type": "integer", "description": "超时秒数，默认 600"}},
            ["cmd"]),
]


def execute(name, args):
    """执行工具：名字不对 / 参数不对 / 执行抛错，都转成文字返回给模型，
    而不是让整个程序崩掉——这就是之前讲的"工具层容错"。

    另外：单次返回超过 MAX_RESULT_CHARS 就截断，这是"上下文预算"的
    最后一道闸——防止某次返回太大把历史撑爆。
    """
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        return f"没有这个工具：{name}。可用工具：{', '.join(TOOL_FUNCS)}"
    try:
        result = fn(**(args or {}))
    except TypeError as e:
        return f"参数错误：{e}。请对照工具说明重新传参。"
    except Exception as e:
        return f"工具执行出错：{e}"
    if isinstance(result, str) and len(result) > MAX_RESULT_CHARS:
        result = (result[:MAX_RESULT_CHARS]
                  + f"\n…（单次返回超 {MAX_RESULT_CHARS} 字已截断，原文 {len(result)} 字；"
                    f"请用更小的 max_chars/tail_chars 分段读取）")
    return result
