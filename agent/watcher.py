# -*- coding: utf-8 -*-
"""阶段 0：death 文件夹监听打包。

只做一件事：盯着 <project_root>/deaths/，新的 death 文件夹写完后，
打成 zip 放到 agent/outbox/，方便拖进聊天框发给分析师。

关键细节：bot 是逐帧写入文件夹的（先建文件夹，再一张张写 jpg），
所以不能文件夹一出现就打包——要等它 N 秒没有新文件，才算写完（debounce）。
只读 deaths/，不碰项目其他任何东西。
"""
import json
import os
import time
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def load_config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def newest_mtime(folder):
    """文件夹里最新的文件修改时间，用来判断"写完了没"。"""
    latest = os.path.getmtime(folder)
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            p = os.path.join(root, fn)
            try:
                t = os.path.getmtime(p)
            except OSError:
                continue
            if t > latest:
                latest = t
    return latest


def zip_folder(src, dst_zip):
    with zipfile.ZipFile(dst_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(src):
            for fn in files:
                p = os.path.join(root, fn)
                arc = os.path.join(os.path.basename(src), os.path.relpath(p, src))
                z.write(p, arc)


def main():
    cfg = load_config()
    project = cfg["project_root"]
    deaths = os.path.join(project, "deaths")
    outbox = os.path.join(HERE, "outbox")
    os.makedirs(outbox, exist_ok=True)
    poll = cfg.get("watcher", {}).get("poll_sec", 2)
    debounce = cfg.get("watcher", {}).get("debounce_sec", 5)

    if not os.path.isdir(deaths):
        log(f"找不到 deaths 目录：{deaths}，请检查 config.json 里的 project_root")
        return

    log(f"开始监听 {deaths}（轮询 {poll}s，{debounce}s 无新文件视为写完）")
    log(f"zip 输出到 {outbox}")
    while True:
        try:
            names = sorted(os.listdir(deaths))
        except OSError as e:
            log(f"读取 deaths 失败：{e}")
            time.sleep(poll)
            continue
        for name in names:
            src = os.path.join(deaths, name)
            if not os.path.isdir(src):
                continue
            dst = os.path.join(outbox, name + ".zip")
            if os.path.exists(dst):
                continue  # 已处理过，幂等：重启也不会重复打包
            if time.time() - newest_mtime(src) < debounce:
                continue  # 还在写，下一轮再看
            try:
                zip_folder(src, dst)
                size_kb = os.path.getsize(dst) // 1024
                log(f"已打包 {name}.zip（{size_kb} KB），可拖进聊天框发送")
            except OSError as e:
                log(f"打包 {name} 失败：{e}（下一轮重试）")
        time.sleep(poll)


if __name__ == "__main__":
    main()
