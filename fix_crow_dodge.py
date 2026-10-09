# -*- coding: utf-8 -*-
"""乌鸦躲避抖动修复：给躲避方向加迟滞。

死因（203238_death）：work.py 的躲避逻辑每帧按敌人相对位置的符号决定方向
（threat>=0 往左躲，否则往右躲），没有任何记忆。乌鸦贴脸时识别框抖动 ±10px
会让符号来回翻，bot 就原地 →躲/←躲 横跳，哪边也没躲开，被乌鸦追上侧面撞死。

修法：DODGE_DIR 记住当前躲避方向；已在躲时，威胁没明显跑到另一侧
（|edx| < 45px）就不换方向。刺的躲避（每帧按几何重算）不受影响。

用法：把本文件放到 F:\\claude memory\\dota_blimp\\ 下运行：
    ..\\dota_automaton\\.venv\\Scripts\\python.exe fix_crow_dodge.py
脚本会自动备份 analysis/work.py，改完跑 py_compile 验证。
看完 diff 没问题后，用 run_promote.bat 上线。
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "analysis", "work.py")


def main():
    with open(WORK, encoding="utf-8") as f:
        src = f.read()

    # 0. 备份
    bak = WORK + ".bak_crowdodge"
    shutil.copyfile(WORK, bak)
    print(f"已备份：{bak}")

    # 1. 模块级状态：躲避方向记忆（跟 STUCK_SOFT 同一风格）
    a1 = "STUCK_SOFT = [False]"
    assert src.count(a1) == 1, "锚点1（STUCK_SOFT）不唯一或找不到，中止，未改任何东西"
    src = src.replace(
        a1,
        a1 + "\nDODGE_DIR = [0] # 躲避方向迟滞：+1=往左躲，-1=往右躲，0=没在躲（防乌鸦贴脸时方向抖动）",
        1,
    )
    print("1/4 状态变量 DODGE_DIR 已加")

    # 2. threat 初始化处加 ethreat（锚点全局唯一，已验证）
    m = re.search(r"(?m)^([ ]*)threat = None[ ]*$", src)
    assert m, "锚点2（threat = None）找不到，中止，未改任何东西"
    ind = m.group(1)
    src = src[: m.end()] + f"\n{ind}ethreat = None # 敌人威胁（带符号的横向距离），单独记以便做方向迟滞" + src[m.end():]
    print("2/4 ethreat 初始化已加")

    # 3. 威胁选择时同步跟踪 ethreat
    m = re.search(
        r"(?m)^([ ]*)if threat is None or abs\(edx\) < abs\(threat\): threat = edx[ ]*$",
        src,
    )
    assert m, "锚点3（威胁选择）找不到，中止，未改任何东西"
    ind = m.group(1)
    src = src[: m.end()] + f"\n{ind}if ethreat is None or abs(edx) < abs(ethreat): ethreat = edx" + src[m.end():]
    print("3/4 ethreat 跟踪已加")

    # 4. 在躲避分支 `if threat is not None:` 之前插入方向迟滞
    #    （不碰原分支，只前置改写 threat；无论原分支是何种合法布局都适用）
    idx = src.find('mode = "躲"')
    assert idx != -1, "锚点4（mode 躲避）找不到，中止，未改任何东西"
    m = None
    for pm in re.finditer(r'(?m)^([ ]*)if threat is not None:', src):
        if pm.start() < idx:
            m = pm  # 取 mode = "躲" 之前最近的一个
    assert m, "锚点4（if threat is not None）找不到，中止，未改任何东西"
    assert idx - m.end() < 200, "锚点4（分支不连续），中止，未改任何东西"
    ind = m.group(1)
    hyst = (
        f"{ind}if ethreat is not None:\n"
        f"{ind}    # 敌人躲避方向迟滞：已在躲且威胁没明显换边时，保持原方向\n"
        f"{ind}    # （乌鸦贴脸时识别抖动会让 edx 符号来回翻，不加迟滞就原地抖、被追上）\n"
        f"{ind}    dodge_want = 1 if ethreat >= 0 else -1\n"
        f"{ind}    if DODGE_DIR[0] != 0 and dodge_want != DODGE_DIR[0] and abs(ethreat) < 45*s:\n"
        f"{ind}        dodge_want = DODGE_DIR[0]\n"
        f"{ind}    DODGE_DIR[0] = dodge_want\n"
        f"{ind}    threat = float(dodge_want)  # 沿用下面 threat>=0 往左躲的约定\n"
        f"{ind}else:\n"
        f"{ind}    DODGE_DIR[0] = 0\n"
    )
    src = src[: m.start()] + hyst + src[m.start():]
    print("4/4 方向迟滞逻辑已加")

    with open(WORK, "w", encoding="utf-8") as f:
        f.write(src)

    # 5. 编译验证
    import py_compile

    py_compile.compile(WORK, doraise=True)
    print("py_compile 通过 ✓")
    print("改完。检查 diff：git diff analysis/work.py")
    print("没问题就双击 run_promote.bat 上线，bot 热更新后开下一局。")


if __name__ == "__main__":
    main()
