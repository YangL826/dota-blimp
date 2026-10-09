# -*- coding: utf-8 -*-
"""工具层：模型能用的「手脚」。

对照之前讲的设计原则：
  1. 每个工具功能单一、行为确定；
  2. 所有读路径被钉死在项目目录内（_safe 防越界）；
  3. 写操作只有一个出口：write_report，且只能写到 agent/reports/。
     ——这就是"最小权限"护栏的实例：分析师阶段不需要改代码，
       所以干脆不给它写代码的工具。

TOOL_SCHEMAS 是给模型看的"说明书"（OpenAI function calling 格式），
TOOL_FUNCS 是真正执行的函数，两边通过名字对应。
"""
import base64
import os

PROJECT_ROOT = None
AGENT_DIR = None
_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
# 单次工具返回进历史的上限：超过就截断，防止一个 7 万字的 log.csv
# 一次塞爆上下文（实测中这曾导致历史压缩把证据全删光、模型"失忆"重来）。
MAX_RESULT_CHARS = 15000


def init(project_root, agent_dir):
    global PROJECT_ROOT, AGENT_DIR
    PROJECT_ROOT = os.path.abspath(project_root)
    AGENT_DIR = os.path.abspath(agent_dir)


def _safe(path, base):
    """把传入的路径钉死在 base 目录内，越界就抛错。"""
    p = os.path.abspath(os.path.join(base, path or ""))
    if p != base and not p.startswith(base + os.sep):
        raise ValueError(f"路径越界，已拒绝：{path}")
    return p


# ---------- 工具实现 ----------

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
    """读一张图。返回 dict，analyst.py 会把它拼成多模态消息发给模型。"""
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
    """唯一的写出口：把 Markdown 报告写到 agent/reports/。"""
    name = os.path.basename(filename or "")
    if not name.endswith(".md"):
        return "文件名必须以 .md 结尾"
    reports = os.path.join(AGENT_DIR, "reports")
    os.makedirs(reports, exist_ok=True)
    p = os.path.join(reports, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return f"报告已保存：{p}"


TOOL_FUNCS = {
    "read_file": do_read_file,
    "read_file_tail": do_read_file_tail,
    "list_dir": do_list_dir,
    "read_image": do_read_image,
    "write_report": do_write_report,
}


# ---------- 给模型看的工具说明书 ----------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "从头读取项目目录内的文本文件，如 HANDOFF.md、代码。超长会自动截断。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "相对项目根目录的路径，如 'HANDOFF.md'"},
                    "max_chars": {"type": "integer", "description": "最多读多少字符，默认 20000"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_tail",
            "description": "读取文本文件的尾部。看 log.csv 时优先用它：死亡的结局在最后，先看尾部定位异常帧最划算。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "相对项目根目录的路径，如 'deaths/203238_death/log.csv'"},
                    "tail_chars": {"type": "integer", "description": "读最后多少字符，默认 8000"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出项目目录内某个文件夹的内容。先看结构、再决定读哪个文件时用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对项目根目录的路径，默认为根目录"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_image",
            "description": "查看一张 death 截图（jpg/png），直接看图分析敌人和平台位置。一次看一张，只挑关键帧看。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "相对项目根目录的图片路径，如 'deaths/203238_death/123.456.jpg'"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_report",
            "description": "把最终的死亡分析报告（Markdown 中文）保存到 agent/reports/。分析完成后必须调用一次。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string",
                                 "description": "文件名，如 '203238_death_report.md'，必须 .md 结尾"},
                    "content": {"type": "string", "description": "报告正文（Markdown，中文）"},
                },
                "required": ["filename", "content"],
            },
        },
    },
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
