# -*- coding: utf-8 -*-
"""全自动死亡循环控制器（auto-loop）。

流程：
  盯 deaths/ → 新死亡 → 跑 executor 分析修 → 查改动 → 独立过测试门 →
  promote 上线 → git 提交+push → 重启 bot → 下一局。

三道熔断（触发后停机+告警，等人工）：
  1. 测试门失败：executor 改了代码但 test_harness errors != 0 → 不上线，直接停。
  2. 连续无产出：executor 连续 N 次死亡没改代码 → 停。
  3. 分数大跌：promote 后连续 2 局分数 < 基线 50% → 自动回滚到上一版本，停。

每次 promote 自动 git commit + push（push 失败只记日志，不停机）。
平时只记日志（agent/loop_log.txt）；熔断时写 agent/loop_ALERT.txt + 蜂鸣 + 停机。

用法：双击 agent/run_loop.bat（或 python -u loop.py）。
停止：关窗口或 Ctrl+C。
冒烟：python loop.py --dry-run（只检查配置和环境，不启动 bot）。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DEFAULTS = {
    "poll_sec": 5,               # 轮询 deaths/ 的间隔（秒）
    "debounce_sec": 10,          # 文件夹 N 秒无新文件视为写完
    "executor_timeout_sec": 3600,  # executor 单次上限（秒）
    "max_no_change_streak": 3,   # 连续几次"有报告但无改动"后停机
    "max_fail_streak": 2,        # 连续几次"崩溃/超时/无报告"后停机
    "score_drop_ratio": 0.5,     # 分数 < 基线*此比例 视为大跌
    "score_watch_games": 2,      # promote 后观察几局
    "auto_push": True,           # promote 后自动 git push
}

STATE_FILE = os.path.join(HERE, "loop_state.json")
LOG_FILE = os.path.join(HERE, "loop_log.txt")
ALERT_FILE = os.path.join(HERE, "loop_ALERT.txt")
BOT_LOG = os.path.join(HERE, "loop_bot.log")

PROJECT = None
LOOP_CFG = None


# ---------- 基础 ----------

def load_config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_state():
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                st = json.load(f)
            # 缺字段就补默认值（兼容老 state）
            for k, v in {"seen_deaths": [], "no_change_streak": 0,
                         "fail_streak": 0, "bad_games": 0, "score_watch": 0,
                         "watch_scores": [], "last_promote_commit": None,
                         "baseline": None, "games": 0, "bot_pid": None}.items():
                st.setdefault(k, v)
            return st
        except Exception as e:
            log(f"[!] loop_state.json 读失败（{e}），用空状态重建")
    return {"seen_deaths": [], "no_change_streak": 0, "fail_streak": 0,
            "bad_games": 0, "score_watch": 0, "watch_scores": [],
            "last_promote_commit": None, "baseline": None, "games": 0,
            "bot_pid": None}


def save_state(st):
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        log(f"[!] 状态保存失败：{e}")


def pause_if_console():
    if sys.stdout.isatty():
        try:
            input("按回车退出…")
        except EOFError:
            pass


# ---------- 告警与熔断 ----------

def alert(reason, bot_proc):
    msg = (f"熔断停机：{reason}\n"
           f"时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n"
           f"处理：bot 已停止。请看 agent/loop_log.txt、"
           f"agent/loop_executor_*.log 和测试日志，人工确认后重新双击 run_loop.bat。")
    try:
        with open(ALERT_FILE, "w", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass
    print("\n" + "=" * 60, flush=True)
    print("[!] 熔断停机：" + reason, flush=True)
    print(f"[!] 告警已写入 {os.path.basename(ALERT_FILE)}，请人工处理。", flush=True)
    print("=" * 60 + "\n", flush=True)
    log(f"[ALERT] {reason}")
    try:
        import winsound
        for _ in range(3):
            winsound.Beep(880, 400)
            time.sleep(0.25)
    except Exception:
        pass
    stop_bot(bot_proc)
    pause_if_console()
    sys.exit(2)


# ---------- bot 进程管理 ----------

def bot_running():
    """wmic 查有没有 blimp_bot.py 在跑（防双开）。True/False/None(查不到)。"""
    try:
        proc = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'",
             "get", "commandline", "/format:csv"],
            capture_output=True, text=True, errors="replace",
            stdin=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return "blimp_bot.py" in (proc.stdout or "")


def start_bot():
    log("启动 bot…")
    try:
        with open(BOT_LOG, "a", encoding="utf-8") as lf:
            lf.write(f"\n===== bot 启动 {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            lf.flush()
            proc = subprocess.Popen(
                [sys.executable, "blimp_bot.py", "--auto"],
                cwd=PROJECT, stdin=subprocess.DEVNULL,
                stdout=lf, stderr=subprocess.STDOUT)
    except OSError as e:
        log(f"[!] bot 启动失败：{e}")
        return None
    time.sleep(3)
    if proc.poll() is not None:
        log(f"[!] bot 启动后立刻退出（rc={proc.returncode}），检查 blimp_bot.py")
        return None
    log(f"[OK] bot 已启动（pid={proc.pid}），输出记到 {os.path.basename(BOT_LOG)}")
    return proc


def stop_bot(proc):
    if proc is None:
        return
    if proc.poll() is None:
        log("停止 bot…")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
        log("[OK] bot 已停止")


def restart_bot_for_next_game(st, bot):
    """处理完一次死亡后重启 bot，开始下一局。返回新进程（失败则熔断）。"""
    stop_bot(bot)
    log("上一局处理完毕，重启 bot 开始下一局…")
    new_bot = start_bot()
    if new_bot is None:
        save_state(st)
        alert("bot 重启失败，下一局无法开始", None)
    st["bot_pid"] = new_bot.pid
    save_state(st)
    return new_bot


# ---------- 死亡检测 ----------

def newest_mtime(folder):
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


def find_ready_deaths(seen, debounce_sec):
    """deaths/ 里没见过、且已写完（debounce 秒无新文件）的文件夹，按时间排序。"""
    deaths = os.path.join(PROJECT, "deaths")
    if not os.path.isdir(deaths):
        return []
    cands = []
    for name in os.listdir(deaths):
        if name in seen:
            continue
        src = os.path.join(deaths, name)
        if not os.path.isdir(src):
            continue
        if time.time() - newest_mtime(src) < debounce_sec:
            continue
        cands.append(name)
    cands.sort(key=lambda n: os.path.getmtime(os.path.join(deaths, n)))
    return cands


# ---------- 分数 ----------

def read_score_rows(limit=100000):
    """读 scores.csv，返回 [(时间戳字符串, 分数)]（时间顺序）。"""
    p = os.path.join(PROJECT, "scores.csv")
    rows = []
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ts, _, sc = line.rpartition(",")
                try:
                    rows.append((ts.strip(), int(sc.strip())))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows[-limit:]


def score_for_death(death, timeout=60):
    """按时间匹配本局分数。death 形如 '032155_death'（HHMMSS）。"""
    m = re.match(r"(\d{2})(\d{2})(\d{2})", death)
    if not m:
        return None
    hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        return None
    target = hh * 3600 + mm * 60 + ss
    t0 = time.time()
    while time.time() - t0 < timeout:
        for ts, sc in reversed(read_score_rows()):
            try:
                hh, mm, ss = int(ts[11:13]), int(ts[14:16]), int(ts[17:19])
            except (ValueError, IndexError):
                continue
            diff = abs((hh * 3600 + mm * 60 + ss) - target)
            diff = min(diff, 86400 - diff)  # 跨午夜
            if diff <= 180:
                return sc
        time.sleep(3)
    return None


# ---------- executor ----------

def work_hash():
    p = os.path.join(PROJECT, "analysis", "work.py")
    h = hashlib.sha1()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def reports_snapshot():
    d = os.path.join(HERE, "reports")
    snap = {}
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith(".md"):
                p = os.path.join(d, f)
                try:
                    snap[f] = (os.path.getmtime(p), os.path.getsize(p))
                except OSError:
                    pass
    return snap


def run_executor(death_name, timeout_sec):
    """跑 executor，输出重定向到日志文件。返回 (returncode, timed_out)。"""
    log_path = os.path.join(HERE, f"loop_executor_{death_name}.log")
    log(f"启动 executor 分析 {death_name}（日志：{os.path.basename(log_path)}）")
    try:
        lf = open(log_path, "w", encoding="utf-8")
    except OSError as e:
        log(f"[!] 打不开 executor 日志：{e}")
        return None, False
    with lf:
        lf.write(f"=== executor {death_name} started {datetime.now()} ===\n")
        lf.flush()
        try:
            proc = subprocess.Popen(
                [sys.executable, "executor.py", death_name],
                cwd=HERE, stdout=lf, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL)
        except OSError as e:
            lf.write(f"启动失败：{e}\n")
            return None, False
        try:
            rc = proc.wait(timeout=timeout_sec)
            lf.write(f"=== exited rc={rc} ===\n")
            return rc, False
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
            lf.write(f"=== 超时（>{timeout_sec}s）已终止 ===\n")
            return None, True


def run_test_gate(timeout_sec=600):
    """独立跑测试门（不信任 executor 的自报）。返回 (passed, errors, tail)。"""
    cmd = [sys.executable, "analysis/harness/test_harness.py", "analysis/work.py"]
    try:
        proc = subprocess.run(cmd, cwd=PROJECT, capture_output=True,
                              text=True, errors="replace",
                              stdin=subprocess.DEVNULL, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        return False, -1, "测试门超时"
    except OSError as e:
        return False, -1, f"测试门启动失败：{e}"
    out = (proc.stdout or "") + (proc.stderr or "")
    errors = None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("errors:"):
            try:
                errors = int(s.split(":", 1)[1].strip())
            except ValueError:
                pass
    tail = out[-2000:] if len(out) > 2000 else out
    passed = (proc.returncode == 0 and errors == 0)
    return passed, errors, tail


# ---------- promote + git ----------

def do_promote():
    """调 promote.py：备份 + 复制 work.py -> blimp_bot.py。返回 (ok, output)。"""
    try:
        proc = subprocess.run(
            [sys.executable, "promote.py"], cwd=HERE,
            capture_output=True, text=True, errors="replace",
            stdin=subprocess.DEVNULL, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "promote 超时"
    except OSError as e:
        return False, f"promote 启动失败：{e}"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()[-500:]


def git(*args, timeout=60):
    try:
        proc = subprocess.run(
            ["git"] + list(args), cwd=PROJECT,
            capture_output=True, text=True, errors="replace",
            stdin=subprocess.DEVNULL, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()[-1000:]


def git_commit_push(message):
    ok, out = git("add", "analysis/work.py", "blimp_bot.py")
    if not ok:
        return False, f"git add 失败：{out}", None
    ok, out = git("commit", "-m", message)
    if not ok:
        if "nothing to commit" in out:
            return True, "没有新改动可提交", None
        return False, f"git commit 失败：{out}", None
    ok2, hout = git("rev-parse", "HEAD")
    full = hout.strip() if ok2 else ""
    if LOOP_CFG["auto_push"]:
        okp, pout = git("push", timeout=120)
        if not okp:
            log(f"[!] git push 失败（仅记日志，不停机）：{pout[:200]}")
        else:
            log("[OK] 已 push 到 GitHub")
    return True, full[:8] if full else "?", full or None


def rollback(st, bot):
    """分数大跌：回滚 work.py + blimp_bot.py 到上次 promote 之前，然后停机告警。"""
    chash = st.get("last_promote_commit")
    log(f"[!] 触发分数熔断，准备回滚（回滚点：{chash})")
    if chash:
        ok, out = git("rev-parse", chash + "^")
        parent = out.strip() if ok else ""
        if parent:
            okc, outc = git("checkout", parent, "--",
                            "analysis/work.py", "blimp_bot.py")
            if okc:
                git("add", "analysis/work.py", "blimp_bot.py")
                git("commit", "-m",
                    f"[auto-loop] 回滚：promote 后分数大跌，回到 {parent[:8]}")
                if LOOP_CFG["auto_push"]:
                    git("push", timeout=120)
                log(f"[OK] 已回滚到 {parent[:8]}")
                st["last_promote_commit"] = None
            else:
                log(f"[!] 回滚失败：{outc[:200]}")
        else:
            log("[!] 找不到回滚点")
    else:
        log("[!] 没有 promote 记录，无法回滚")
    save_state(st)
    alert("promote 后分数大跌，已回滚到上一版本。请人工检查死因和修复。", bot)


# ---------- 处理一次死亡 ----------

def handle_death(death, st, bot):
    log("-" * 60)
    log(f"新死亡：{death}，开始自动处理（第 {st['games'] + 1} 局）")
    st["games"] += 1

    # 1) 本局分数 + 分数熔断器（只在 promote 后的观察期内）
    score = score_for_death(death)
    if score is not None:
        log(f"本局得分：{score}")
    else:
        log("[!] 没匹配到本局分数，跳过分数检查")
    if score is not None and st["baseline"] and st["score_watch"] > 0:
        st["score_watch"] -= 1
        st["watch_scores"].append(score)
        if score < st["baseline"] * LOOP_CFG["score_drop_ratio"]:
            st["bad_games"] += 1
            log(f"[!] 分数大跌（{score} < 基线 {st['baseline']} x "
                f"{LOOP_CFG['score_drop_ratio']}），连续 {st['bad_games']} 局")
        else:
            st["bad_games"] = 0
            log(f"[OK] 分数正常（{score}），观察期还剩 {st['score_watch']} 局")
        if st["bad_games"] >= LOOP_CFG["score_watch_games"]:
            save_state(st)
            rollback(st, bot)  # 不返回：内部 alert 退出
        elif st["score_watch"] == 0:
            ws = sorted(st["watch_scores"])
            med = ws[len(ws) // 2]
            if med > st["baseline"]:
                log(f"[OK] 观察期通过，基线 {st['baseline']} → {med}")
                st["baseline"] = med
            st["watch_scores"] = []
    save_state(st)

    # 2) 跑 executor
    before_reports = reports_snapshot()
    try:
        h_before = work_hash()
    except OSError as e:
        save_state(st)
        alert(f"读不到 analysis/work.py：{e}", bot)
    rc, timed_out = run_executor(death, LOOP_CFG["executor_timeout_sec"])
    try:
        h_after = work_hash()
    except OSError as e:
        save_state(st)
        alert(f"executor 跑完后读不到 analysis/work.py：{e}", bot)
    changed = (h_before != h_after)
    after_reports = reports_snapshot()
    report_written = any(
        f not in before_reports or before_reports[f] != after_reports[f]
        for f in after_reports)
    log(f"executor 结束：rc={rc} 超时={timed_out} 改动={changed} 报告={report_written}")

    # 3) 崩溃 / 超时
    if timed_out or rc != 0:
        st["fail_streak"] += 1
        save_state(st)
        log(f"[!] executor 异常（rc={rc} 超时={timed_out}），"
            f"连续失败 {st['fail_streak']} 次")
        if st["fail_streak"] >= LOOP_CFG["max_fail_streak"]:
            alert(f"executor 连续 {st['fail_streak']} 次异常退出，"
                  f"日志见 loop_executor_{death}.log", bot)
        return restart_bot_for_next_game(st, bot)

    # 4) 有改动 → 独立过测试门 → promote → 提交 → 重启
    if changed:
        st["fail_streak"] = 0
        log("检测到代码改动，独立过测试门…")
        passed, errors, tail = run_test_gate()
        if not passed:
            tp = os.path.join(HERE, f"loop_testfail_{death}.log")
            try:
                with open(tp, "w", encoding="utf-8") as f:
                    f.write(tail)
            except OSError:
                pass
            save_state(st)
            alert(f"测试门失败（errors={errors}），已阻止上线。"
                  f"测试输出：{os.path.basename(tp)}", bot)
        log("[OK] 测试门通过（errors: 0）")
        ok, pout = do_promote()
        if not ok:
            save_state(st)
            alert(f"promote 失败：{pout}", bot)
        log(f"[OK] 已上线：{pout[:120]}")
        okc, short, full = git_commit_push(
            f"[auto-loop] {death}: 自动修复已上线（测试 errors: 0）")
        if not okc:
            save_state(st)
            alert(f"git 提交失败：{short}", bot)
        log(f"[OK] 已提交 {short}")
        st["last_promote_commit"] = full
        st["no_change_streak"] = 0
        st["bad_games"] = 0
        st["score_watch"] = LOOP_CFG["score_watch_games"]
        st["watch_scores"] = []
        save_state(st)
        stop_bot(bot)
        bot = start_bot()
        if bot is None:
            alert("promote 后 bot 重启失败", None)
        st["bot_pid"] = bot.pid
        log(f"[OK] bot 已重启，新代码生效。观察接下来 {st['score_watch']} 局。")
        return bot

    # 5) 无改动
    if report_written:
        st["no_change_streak"] += 1
        st["fail_streak"] = 0
        save_state(st)
        log(f"executor 有报告但无改动（连续 {st['no_change_streak']} 次）")
        if st["no_change_streak"] >= LOOP_CFG["max_no_change_streak"]:
            alert(f"连续 {st['no_change_streak']} 次死亡无改动，需要人工看死因", bot)
    else:
        st["fail_streak"] += 1
        save_state(st)
        log(f"[!] executor 无改动也无报告，连续失败 {st['fail_streak']} 次")
        if st["fail_streak"] >= LOOP_CFG["max_fail_streak"]:
            alert(f"executor 连续 {st['fail_streak']} 次无产出", bot)
    return restart_bot_for_next_game(st, bot)


# ---------- 主循环 ----------

def dry_run():
    """冒烟检查：配置、环境、关键文件，不启动 bot。"""
    print("=== auto-loop 干跑检查 ===")
    cfg = load_config()
    project = cfg["project_root"]
    print(f"[OK] config.json 可读，project_root={project}")
    for p, what in [
            (os.path.join(project, "deaths"), "deaths/ 目录"),
            (os.path.join(project, "analysis", "work.py"), "analysis/work.py"),
            (os.path.join(project, "blimp_bot.py"), "blimp_bot.py"),
            (os.path.join(project, "analysis", "harness", "test_harness.py"),
             "test_harness.py"),
            (os.path.join(HERE, "executor.py"), "executor.py"),
            (os.path.join(HERE, "promote.py"), "promote.py")]:
        print(("[OK] " if os.path.exists(p) else "[x] 缺失：") + what)
    lc = dict(DEFAULTS)
    lc.update(cfg.get("loop", {}))
    print(f"[OK] loop 配置：{json.dumps(lc, ensure_ascii=False)}")
    ok, out = git("rev-parse", "--is-inside-work-tree")
    print(("[OK] git 可用" if ok else "[x] git 不可用：" + out[:100]))
    rows = read_score_rows(5)
    print(f"[OK] scores.csv 最近 {len(rows)} 行可读" if rows else "[!] scores.csv 为空或缺失")
    print("干跑完成：以上全 [OK] 即可双击 run_loop.bat 启动。")


def main():
    global PROJECT, LOOP_CFG
    cfg = load_config()
    PROJECT = cfg["project_root"]
    LOOP_CFG = dict(DEFAULTS)
    LOOP_CFG.update(cfg.get("loop", {}))

    log("=" * 60)
    log("全自动死亡循环启动")
    log(f"项目：{PROJECT}")
    log(f"熔断：无改动x{LOOP_CFG['max_no_change_streak']} / "
        f"失败x{LOOP_CFG['max_fail_streak']} / "
        f"大跌<{int(LOOP_CFG['score_drop_ratio'] * 100)}%基线")
    log("=" * 60)

    st = load_state()

    # 基线分数：历史最后 5 局的中位数（只升不降，删 loop_state.json 可重置）
    if st.get("baseline") is None:
        hist = [sc for _, sc in read_score_rows(5)]
        if hist:
            s = sorted(hist)
            st["baseline"] = s[len(s) // 2]
            log(f"分数基线：{st['baseline']}（最近 {len(hist)} 局中位数）")
        else:
            log("[!] scores.csv 为空，分数熔断器暂不启用")
        save_state(st)
    else:
        log(f"分数基线：{st['baseline']}（沿用上次）")

    # 历史死亡：只记不处理
    deaths_dir = os.path.join(PROJECT, "deaths")
    existing = set()
    if os.path.isdir(deaths_dir):
        existing = {d for d in os.listdir(deaths_dir)
                    if os.path.isdir(os.path.join(deaths_dir, d))}
    new_hist = [d for d in existing if d not in st["seen_deaths"]]
    if new_hist:
        log(f"忽略 {len(new_hist)} 个历史死亡记录（loop 启动前已存在）")
    st["seen_deaths"] = sorted(set(st["seen_deaths"]) | existing)
    save_state(st)

    # 启动时 work.py/blimp_bot.py 有未提交改动？先 checkpoint，保证回滚基线干净
    ok, out = git("status", "--porcelain", "analysis/work.py", "blimp_bot.py")
    if ok and out.strip():
        log(f"[!] 启动时有未提交改动，先 checkpoint：\n{out.strip()[:300]}")
        git("add", "analysis/work.py", "blimp_bot.py")
        git("commit", "-m", "[auto-loop] 接管：启动时的未提交改动（checkpoint）")

    # 防双开
    r = bot_running()
    if r is True:
        alert("检测到 blimp_bot.py 已在运行（防双开）。请先关掉旧 bot 再启动 loop。",
              None)
    elif r is None:
        log("[!] 查不到进程列表（wmic 不可用），跳过防双开检查")
    if st.get("bot_pid"):
        log(f"[!] 上次运行的 bot 进程 pid={st['bot_pid']} 可能还残留；"
            f"如重启后行为异常，请在任务管理器里确认旧 python.exe 已结束")
        st["bot_pid"] = None
        save_state(st)

    bot = start_bot()
    if bot is None:
        alert("bot 启动失败，请检查 blimp_bot.py", None)
    st["bot_pid"] = bot.pid
    save_state(st)

    log("进入主循环。停止：关窗口或 Ctrl+C。")
    try:
        while True:
            if bot.poll() is not None:
                log(f"[!] bot 进程退出（rc={bot.returncode}），重启…")
                bot = start_bot()
                if bot is None:
                    alert("bot 反复启动失败", bot)
            ready = find_ready_deaths(set(st["seen_deaths"]),
                                      LOOP_CFG["debounce_sec"])
            if ready:
                death = ready[0]  # 一次处理一个最老的
                st["seen_deaths"].append(death)
                save_state(st)
                bot = handle_death(death, st, bot)
                # handle_death 内部熔断会直接 alert 退出；正常返回新的 bot 进程
            time.sleep(LOOP_CFG["poll_sec"])
    except KeyboardInterrupt:
        log("收到 Ctrl+C，停止…")
    finally:
        stop_bot(bot)
        save_state(st)
        log("loop 已退出")
        pause_if_console()


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        # dry-run 不需要 PROJECT 全局：临时设一下
        cfg = load_config()
        PROJECT = cfg["project_root"]
        LOOP_CFG = dict(DEFAULTS)
        LOOP_CFG.update(cfg.get("loop", {}))
        dry_run()
    else:
        main()
