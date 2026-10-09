# -*- coding: utf-8 -*-
"""
Dota 2 暗黑狂欢「飞艇跳跃」自动玩
原理：截游戏画面 -> 找角色(橙色)、平台(绿/蓝/白云) -> 预测落点 -> 按住 ←/→ 移过去；头顶有敌人就按 ↑ 扔飞刀

热键：
  F8  鼠标指向游戏窗口【左上角】按一下
  F9  鼠标指向游戏窗口【右下角】按一下（自动保存）
  F6  开始 / 暂停（开局后按）
  F7  开/关 自动射击敌人
  F11 保存当前画面+识别结果到 debug.png
  F12 保存最近约 8 秒画面到 deaths 文件夹（死亡时会自动保存）
  F10 退出
"""
import ctypes, json, os, time, sys
import numpy as np, cv2

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")
DEFAULT = {"left": 0, "top": 0, "right": 0, "bottom": 0,
           "shoot": True,
           "deadzone": 6,       # 离目标水平距离小于这个像素就松手（基准尺寸下）
           "hspeed": 400,       # 角色水平速度 px/s（基准尺寸，偏保守）
           "gravity": 1182,     # 重力 px/s²（基准尺寸；用 24 次完整跳跃拟合抛物线实测）
           "jump_v": 778,
           "htau": 0.167,       # 横向速度的一阶响应时间常数（按住/松开/反向都符合 dv/dt=(u·vmax-v)/τ，从日志拟合）
           "latency": 0.03,     # 按键生效延迟（秒）
           "reach_vfrac": 0.9,  # 判断“够得着”时按最大速度的这个比例算（留余量）
           "timescale": 1.0}    # 如果用了 host_timescale 0.5 减速，这里也改成 0.5       # 起跳速度 px/s（基准尺寸）
cfg = dict(DEFAULT)
if os.path.exists(CFG_PATH):
    cfg.update(json.load(open(CFG_PATH, encoding="utf-8")))

BASE_W = 572.0   # 录像里角色左右穿屏的宽度，用来按窗口大小缩放所有参数

# ---------------- 识别 ----------------
def find_column(hsv):
    """找两条米色边框，返回 (穿屏左边界, 穿屏右边界, 内框左, 内框右)"""
    h = hsv.shape[0]
    m = cv2.inRange(hsv[int(h*0.1):int(h*0.85)], (14, 55, 150), (20, 90, 200))
    frac = m.mean(0) / 255.0
    xs = np.where(frac > 0.5)[0]
    if len(xs) < 10:
        return None
    # 分成两段
    gaps = np.where(np.diff(xs) > 20)[0]
    if len(gaps) == 0:
        return None
    L0, L1 = xs[0], xs[gaps[0]]
    R0, R1 = xs[gaps[-1] + 1], xs[-1]
    return int(L0 + 1), int(R1 - 2), int(L1), int(R0)

ROI = [None]   # 本帧只在游戏区里找连通块（快很多）

def find_spike(band_v, s):
    """在平台顶上方那一条（V 通道）里找刺：黑色描边的一小簇。
    先去掉每列最底下连着的黑色（那是平台自己的上描边），再找“每列至少 2 个黑点”的最长一段连续列。"""
    blk = band_v < 30
    h = blk.shape[0]
    if h == 0:
        return None
    rev = blk[::-1]
    allblk = rev.all(axis=0)
    run = np.where(allblk, h, np.argmin(rev, axis=0))      # 每列底部连续黑色的长度
    rows = np.arange(h)[:, None]
    blk = blk & (rows < (h - run)[None, :])
    good = blk.sum(0) >= 2
    # 找最长的一段（允许中间断开 3 列以内）
    best = None; start = None; last = None
    for i, g in enumerate(good):
        if g:
            if start is None or i - last > 4:
                if start is not None and (best is None or last - start > best[1] - best[0]):
                    best = (start, last)
                start = i
            last = i
    if start is not None and (best is None or last - start > best[1] - best[0]):
        best = (start, last)
    if best is None:
        return None
    n_good = int(good[best[0]:best[1] + 1].sum())
    if n_good >= max(4, int(10*s)) and best[1] - best[0] <= 60*s:
        # 刺有一定高度：簇里要有离平台顶 12px 以上的黑点（平台两头的尖角很矮，排除掉）
        hi_rows = blk[:max(1, h - int(12*s)), best[0]:best[1] + 1]
        if hi_rows.any():
            return best
    return None

def blobs(mask, min_area=20, half=False):
    """连通块。只在游戏区 ROI 内算；half=True 时隔点取样（大物体用，快 4 倍）"""
    if ROI[0] is not None:
        x0, y0, x1, y1 = ROI[0]
        sub = mask[y0:y1, x0:x1]
    else:
        x0 = y0 = 0; sub = mask
    k = 2 if half else 1
    if half:
        sub = sub[::2, ::2]
    sub = np.ascontiguousarray(sub)
    n, _, st, c = cv2.connectedComponentsWithStats(sub)
    out = []
    for i in range(1, n):
        a = int(st[i, 4]) * k * k
        if a >= min_area:
            out.append((int(st[i, 0]) * k + x0, int(st[i, 1]) * k + y0, int(st[i, 2]) * k, int(st[i, 3]) * k, a))
    return out

SPIKE_MEM = []
UPS = []
STUCK_SOFT = [False]
DODGE_DIR = [0] # 躲避方向迟滞：+1=往左躲，-1=往右躲，0=没在躲（防乌鸦贴脸时方向抖动）
SUPPORT = [None]   # 上次起跳的平台顶（当前屏幕坐标）
DBG = []          # 本帧所有候选落点（写进死亡记录，方便事后分析）
PLAYER_LAST = [None]   # 上一帧角色位置（连续跟踪用）
PLAT_V = {}      # 移动平台（蓝色/云）的横向速度估计
PHYS = {"vx": 0.0, "a": None, "vmax": None}   # 角色横向速度、加速度、最大速度（在线估计，单位按当前画面像素）
SPIKES = []      # 本帧所有尖刺 (x0, x1, 平台顶)
SEG_PARENT = {}  # 带刺平台切出来的落脚段 -> 整块平台的 (x0, x1)（预测移动平台碰边反弹要用整块的宽度）

def perceive(img, col, s):
    """返回 player(x, feet_y) 或 None, platforms[(x0,x1,top,kind)], enemies[(cx,cy,w,h)]"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, W = hsv.shape[:2]
    lx, rx = col[0] - int(5*s), col[1] + int(8*s)
    top_cut = int(60*s)
    ROI[0] = (max(0, int(lx) - 2), max(0, top_cut), min(hsv.shape[1], int(rx) + 2), hsv.shape[0])

    # 角色：橙色盔甲
    m = cv2.inRange(hsv, (10, 140, 140), (25, 255, 255))
    m[:top_cut] = 0; m[:, :lx] = 0; m[:, rx:] = 0
    bs = [b for b in blobs(m, int(40*s*s))]
    player = None; pbox = None
    if bs:
        # 连续性：优先选离上一帧角色最近的橙色块（穿框时角色被切成两半，面积会变小，不能只挑最大的）
        last = PLAYER_LAST[0]
        big = max(b[4] for b in bs)
        cand = [b for b in bs if b[4] >= 0.25 * big] if last is None else bs
        def dist_(b):
            cx_, cy_ = b[0] + b[2]/2.0, b[1] + b[3]
            if last is None:
                return -b[4]
            ddx = abs(wrap_dx(last[0], cx_, col)) if col else abs(cx_ - last[0])
            return ddx + abs(cy_ - last[1]) - 0.3 * b[4] / s
        x, y, w, h, a = min(cand, key=dist_)
        if last is not None and a < 80*s*s:
            # 太小的块只在离上一帧很近时才认（防止把别的橙色小东西当成角色）
            if abs(wrap_dx(last[0], x + w/2.0, col)) + abs(y + h - last[1]) > 120*s:
                x, y, w, h, a = max(bs, key=lambda b: b[4])
                if a < 80*s*s:
                    x = None
        if x is not None:
            player = (x + w/2.0, float(y + h))
            pbox = (int(x), int(y), int(w), int(h))
    PLAYER_LAST[0] = player if player is not None else PLAYER_LAST[0]

    plats, enemies = [], []
    PILLARS.clear()
    green = cv2.inRange(hsv, (42, 90, 80), (52, 170, 170))
    blue = cv2.inRange(hsv, (100, 130, 170), (108, 200, 230))
    cloud = cv2.inRange(hsv, (0, 0, 205), (179, 45, 255))
    red = cv2.inRange(hsv, (0, 140, 80), (8, 255, 230)) | cv2.inRange(hsv, (163, 130, 70), (179, 255, 235))
    boxes = []
    for kind, mk in (("g", green), ("b", blue), ("c", cloud)):
        mk[:top_cut] = 0; mk[:, :lx] = 0; mk[:, rx:] = 0
        pieces = []
        for x, y, w, h, a in blobs(mk, int(15*s*s)):
            if 3*s < h < 30*s and w >= 8*s and w > 1.2*h and not (kind in ("g", "b") and h >= 35*s):
                pieces.append([x, x + w, y])
                continue
            if kind in ("g", "b") and h >= 35*s and w >= 30*s:
                inner_red = int((red[y + int(h*0.15):y + int(h*0.85), x + int(w*0.15):x + int(w*0.85)] > 0).sum())
                if h > 2.0*w and inner_red > 30*s*s:
                    # 弹簧柱：又高又窄、带红色标记的柱子，侧面碰到/踩顶都会往上弹——不是尖刺箱！
                    # 不进 enemies（否则 bot 会躲它）；记到 PILLARS 供脱困时主动去蹭；
                    # 同时进 boxes，让小丑识别跳过柱身上的红色标记（否则误报小丑）。
                    PILLARS.append((x, x + w, y, y + h))
                    boxes.append((x, y, w, h))
                    continue
                boxes.append((x, y, w, h))
                if inner_red > 30*s*s:
                    # 红叉箱子：顶上有刺，哪个方向都不能碰，也不能踩
                    y_top = y - 0.45*h; hh = h + 0.45*h
                    enemies.append((x + w/2.0, y_top + hh/2.0, w + 10*s, hh, "xbox"))
                else:
                    # 小丑机关盒：绿盒子上面还顶着小丑的头，判定范围往上扩
                    y_top = y - 0.9*h; hh = h + 0.9*h
                    enemies.append((x + w/2.0, y_top + hh/2.0, w, hh, "jester"))
        # 同一高度、挨得很近的几段拼成一块平台；中间的缺口通常是尖刺（或角色挡住）
        pieces.sort(key=lambda q: (round(q[2] / (4*s)), q[0]))
        used = [False]*len(pieces)
        for i_, pc in enumerate(pieces):
            if used[i_]: continue
            group = [pc]; used[i_] = True
            for j_ in range(i_ + 1, len(pieces)):
                q = pieces[j_]
                if not used[j_] and abs(q[2] - pc[2]) <= 4*s and q[0] - max(g_[1] for g_ in group) <= 30*s and q[0] >= min(g_[0] for g_ in group) - 30*s:
                    group.append(q); used[j_] = True
            group.sort()
            gx0, gx1 = group[0][0], max(g_[1] for g_ in group)
            gtop = min(g_[2] for g_ in group)
            if gx1 - gx0 <= 45*s:
                continue
            if len(group) == 1:
                plats.append((gx0, gx1, gtop, kind))
            else:
                gaps = [(group[k_][1], group[k_ + 1][0]) for k_ in range(len(group) - 1) if group[k_ + 1][0] > group[k_][1] + 13*s]
                # 平台两头的螺栓孔（窄缺口）不是刺；角色挡住造成的缺口也不算
                if player is not None:
                    gaps = [g_ for g_ in gaps if not (g_[0] - 25*s < player[0] < g_[1] + 25*s and gtop - 60*s < player[1] < gtop + 30*s)]
                if not gaps:
                    plats.append((gx0, gx1, gtop, kind))
                else:
                    plats.append((gx0, gx1, gtop, kind + "#" + ";".join(f"{a_}:{b_}" for a_, b_ in gaps)))
    # 乌鸦：深褐色的一大块（面积远大于角色身上的深色部分）
    brown = cv2.inRange(hsv, (3, 90, 18), (28, 255, 85))
    brown[:top_cut] = 0; brown[:, :int(col[2])] = 0; brown[:, int(col[3]):] = 0   # 只看游戏区内（墙外是木头，颜色像乌鸦）
    if player is not None:                                  # 角色身上的棕色部分不算
        bx0_ = int(max(0, player[0] - 34*s)); bx1_ = int(player[0] + 34*s)
        by0_ = int(max(0, player[1] - 45*s)); by1_ = int(player[1] + 32*s)
        brown[by0_:by1_, bx0_:bx1_] = 0
    brown = cv2.morphologyEx(brown, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    for x, y, w, h, a in blobs(brown, int(1500*s*s), half=True):
        if w >= 70*s and h >= 45*s:
            enemies.append((x + w/2.0, y + h/2.0, w + 10*s, h + 10*s, "crow"))
    # 小丑（红帽子）：不管有没有绿盒子，都按红帽子定位整个小丑
    red[:top_cut] = 0; red[:, :lx] = 0; red[:, rx:] = 0
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    for x, y, w, h, a in blobs(red, int(150*s*s), half=True):
        if w >= 16*s and h >= 10*s and w < 90*s:
            cx = x + w/2.0
            if any(e[4] == "jester" and abs(e[0] - cx) < 50*s and abs((e[1] - e[3]/2) - y) < 60*s for e in enemies):
                continue   # 已经被绿盒子那套识别覆盖了
            if any(bx - 5*s < cx < bx + bw + 5*s and by - 5*s < y < by + bh for bx, by, bw, bh in boxes):
                continue   # 箱子里的红叉，不是小丑
            if a > 900*s*s and h > 30*s:
                enemies.append((cx, y + h/2.0, w + 12*s, h + 12*s, "balloon"))   # 红气球
            else:
                enemies.append((cx, y + 32*s, 82*s, 80*s, "clown"))

    # 蓝色/青色气球：比蓝平台暗、形状接近圆形
    bball = cv2.inRange(hsv, (80, 120, 55), (125, 255, 168))
    bball[:top_cut] = 0; bball[:, :lx] = 0; bball[:, rx:] = 0
    bball = cv2.morphologyEx(bball, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    for x, y, w, h, a in blobs(bball, int(500*s*s), half=True):
        if 40*s <= w <= 110*s and 40*s <= h <= 120*s and 0.6 < w / max(h, 1) < 1.5 and a > 0.35 * w * h:
            cx, cy = x + w/2.0, y + h/2.0
            if player and abs(cx - player[0]) < 40*s and -70*s < cy - player[1] < 10*s:
                continue                                   # 角色自己身上的蓝色
            enemies.append((cx, cy, w + 12*s, h + 12*s, "balloon"))

    # 气球（橄榄黄、会把人推开）：当敌人躲，但不打
    yel = cv2.inRange(hsv, (24, 130, 60), (34, 255, 230)) | cv2.inRange(hsv, (125, 80, 40), (165, 255, 230))
    yel[:top_cut] = 0; yel[:, :lx] = 0; yel[:, rx:] = 0
    for x, y, w, h, a in blobs(yel, int(500*s*s), half=True):
        if w >= 30*s and h >= 30*s:
            enemies.append((x + w/2.0, y + h/2.0, w + 10*s, h + 10*s, "balloon"))

    # 平台上面有什么：尖刺(灰色金属+深色描边) / 道具(弹簧绿、火箭橙)
    bgv = float(np.median(hsv[top_cut:int(H*0.8), col[2]+10:col[3]-10, 2]))
    now = time.time()
    SPIKE_MEM[:] = [m for m in SPIKE_MEM if now - m[3] < 3.0][-200:]
    marked = []
    SPIKES.clear(); SEG_PARENT.clear()
    for (x0, x1, top, kind) in plats:
        gap_spike = None
        if "#" in kind:
            kind, gs_ = kind.split("#")
            gl = [tuple(int(v) for v in g_.split(":")) for g_ in gs_.split(";")]
            gap_spike = (min(a_ for a_, b_ in gl) - x0, max(b_ for a_, b_ in gl) - x0)
        y0 = max(0, int(top - 46*s)); y1 = max(0, int(top - 5*s))
        # 记忆匹配：绿平台不会横向移动，相机滚动只改变 y，所以按横向位置+宽度配对；移动平台按宽度+大致高度
        if kind[0] == "b":
            mem = [m for m in SPIKE_MEM if abs(m[1] - top) < 60*s and abs(m[2] - (x1 - x0)) < 8*s and abs(m[0] - (x0 + x1)/2) < 120*s and now - m[3] < 0.6]
        else:
            mem = [m for m in SPIKE_MEM if abs(m[2] - (x1 - x0)) < 8*s and abs(m[0] - (x0 + x1)/2) < 6*s]
        spike = None                                          # 尖刺占的横向范围（相对平台左端）
        blocked = y1 <= y0
        # 角色的身体（盔甲下沿往上 45px、往下 35px，左右 ±38px）挡在平台顶上方那一条里吗
        near_p = bool(player and x0 - 60*s < player[0] < x1 + 60*s and player[1] + 35*s > top - 26*s and player[1] - 45*s < top)
        if not blocked:
            reg = hsv[y0:y1, max(0, x0):x1]
            H_, S_, V_ = reg[..., 0], reg[..., 1], reg[..., 2]
            pmask = np.ones(reg.shape[1], dtype=bool)
            if near_p:                                         # 角色挡住的那几列不看，其余照样检查
                c0 = int(player[0] - 30*s) - max(0, x0); c1 = int(player[0] + 30*s) - max(0, x0)
                pmask[max(0, c0):max(0, c1)] = False
            green = ((H_ >= 38) & (H_ <= 80) & (S_ > 150) & (V_ > 140))[:, pmask].sum()
            orange = ((H_ >= 5) & (H_ <= 22) & (S_ > 120) & (V_ > 110))[:, pmask].sum()
            thr = 25 * s * s
            if green > thr or orange > thr:
                kind = kind + "*"                                  # 有道具：优先去
            else:
                # 刺：紧贴平台顶、黑色描边的一小簇（宽度有限）。只看平台顶上方一窄条，
                # 这样上面另一块平台的描边、深色背景都不会被误认成刺
                hb = int(round(24*s)); gb = max(1, int(round(2*s)))
                ext = 20*s                                          # 刺可能挂在平台两头外面一点（平台两头的尖角靠高度条件排除）
                bx0 = int(max(col[0] + 4*s, x0 - ext)); bx1 = int(min(col[1] - 4*s, x1 + ext))   # 平台/刺可以伸进米色边框里
                band = hsv[max(0, top - hb):max(0, top - gb), max(0, bx0):max(0, bx1), 2]
                if band.size:
                    if near_p:                             # 角色身上的黑描边不能当成刺：把角色那几列盖掉再找
                        bb_ = band.copy()
                        c0 = int(player[0] - 38*s) - bx0; c1 = int(player[0] + 38*s) - bx0
                        bb_[:, max(0, c0):max(0, c1)] = 255
                        sp_ = find_spike(bb_, s)
                    else:
                        sp_ = find_spike(band, s)
                    if sp_ is not None:
                        spike = (int(sp_[0] + bx0 - x0), int(sp_[1] + bx0 - x0))   # 相对平台左端（可能是负数）
                        SPIKE_MEM.append(((x0 + x1)/2, top, x1 - x0, now, spike))

        if spike is None and mem:
            spike = mem[-1][4]                                 # 被挡住时沿用 1.5 秒内的记忆
        if gap_spike is not None:
            spike = gap_spike if spike is None else (min(spike[0], gap_spike[0]), max(spike[1], gap_spike[1]))
            SPIKE_MEM.append(((x0 + x1)/2, top, x1 - x0, now, spike))
        if spike is None:
            marked.append((x0, x1, top, kind)); continue
        # 尖刺只占平台的一段：把两边没刺的部分留下来当落脚点
        pad = (22*s) if kind[0] == "b" else (15*s)   # 刺边缘到脚的安全距离；移动平台上的刺会跟着动，留宽一点
        SPIKES.append((x0 + spike[0], x0 + spike[1], top))
        segs = [(x0, int(x0 + spike[0] - pad)), (int(x0 + spike[1] + pad), x1)]
        segs = [(a_, b_) for a_, b_ in segs if b_ - a_ >= 12*s]
        if segs:
            for a_, b_ in segs:
                marked.append((a_, b_, top, kind + "~"))
                SEG_PARENT[(a_, b_, top, kind + "~")] = (x0, x1)
        else:
            marked.append((x0, x1, top, kind + "!"))
    plats = marked

    # 小丑机关盒的头顶可以踩，当成可落脚点
    for e in enemies:
        if len(e) > 4 and e[4] in ("jester", "clown", "balloon"):
            ex, ey, ew, eh = e[:4]
            half = min(ew/2 - 4*s, 22*s)       # 只把头顶正中间一段当落脚点，边上容易擦到身体
            plats.append((int(ex - half), int(ex + half), int(ey - eh/2), "j"))

    # 竖着的柱子（细长：两头绿色、中间金色箭头）：顶端可以当小落脚点。
    # 金色箭头和角色盔甲同色，所以先把角色盔甲那一块挖掉；两头必须有绿色（排除边框木纹）
    pil = cv2.inRange(hsv, (14, 85, 35), (46, 255, 215))
    pil[:top_cut] = 0; pil[:, :lx] = 0; pil[:, rx:] = 0
    if pbox is not None:
        bx_, by_, bw_, bh_ = pbox; e_ = int(8*s)
        pil[max(0, by_ - e_):by_ + bh_ + e_, max(0, bx_ - e_):bx_ + bw_ + e_] = 0
    pil = cv2.morphologyEx(pil, cv2.MORPH_CLOSE, np.ones((11, 5), np.uint8))
    for x, y, w, h, a in blobs(pil, int(250*s*s), half=True):
        if h >= 60*s and 12*s <= w <= 40*s and h > 2.2*w:
            if pbox is not None and x < bx_ + bw_ + 2*e_ and x + w > bx_ - 2*e_ and by_ - 2*e_ <= y <= by_ + bh_ + 2*e_:
                continue          # 柱子顶端被挖掉的角色区域切了：顶的位置不准，交给平台记忆
            sub = hsv[y:y + h, x:x + w]
            gr = (sub[..., 0] >= 34) & (sub[..., 0] <= 48) & (sub[..., 1] >= 90) & (sub[..., 2] >= 80) & (sub[..., 2] <= 175)
            if gr.mean() < 0.10 or (y > top_cut + 3*s and gr[:max(1, int(h*0.3))].mean() < 0.2):
                continue
            plats.append((x - int(4*s), x + w + int(4*s), y, "p"))

    # 去掉角色自己身上的蓝色被当成敌人
    if player:
        enemies = [e for e in enemies if not (len(e) > 4 and e[4] in ("jester", "xbox") and abs(e[0]-player[0]) < 40*s and abs(e[1]-(player[1]-15*s)) < 40*s)]
    enemies = [tuple(e[:4]) + ((e[4],) if len(e) > 4 else ("enemy",)) for e in enemies]
    # 头顶一跳高度内有敌人的平台：只把敌人正下方那一段切掉，剩下够宽的部分照样能踩（标 ^）
    ts_ = cfg.get("timescale", 1.0)
    H_ = (cfg["jump_v"] * s * ts_) ** 2 / (2 * cfg["gravity"] * s * ts_ * ts_) + 80*s   # 跳到最高点时头顶（脚底往上约 75px）能碰到的高度
    cut = []
    for (x0, x1, top, kind) in plats:
        if kind == "j":
            cut.append((x0, x1, top, kind)); continue
        pieces = [(x0, x1)]
        for e in enemies:
            ebot = e[1] + e[3]/2
            if not (top - H_ < ebot < top + 5*s):
                continue
            b0, b1 = e[0] - e[2]/2 - 38*s, e[0] + e[2]/2 + 38*s     # 角色身体半宽约 35px（实测被小丑判定碰到时离识别框只有几个像素）
            nxt = []
            for a_, b_ in pieces:
                if b_ <= b0 or a_ >= b1:
                    nxt.append((a_, b_)); continue
                if a_ < b0: nxt.append((a_, b0))
                if b_ > b1: nxt.append((b1, b_))
            pieces = nxt
        if pieces == [(x0, x1)]:
            cut.append((x0, x1, top, kind))
        else:
            for a_, b_ in pieces:
                if b_ - a_ >= 16*s:
                    cut.append((int(a_), int(b_), top, kind + "^"))
            # 被切掉的那段（敌人正下方）：落上去会弹起来撞到敌人 → 和尖刺一样当危险区（路过时不能落在上面）
            pos_ = x0
            for a_, b_ in sorted(pieces):
                if a_ > pos_ + 1:
                    SPIKES.append((int(pos_), int(a_), top))
                pos_ = max(pos_, b_)
            if x1 > pos_ + 1:
                SPIKES.append((int(pos_), int(x1), top))
    plats = cut
    # 识别到的是橙色盔甲的下沿；实测真正的脚底还要再往下约 28 像素（录像里落地瞬间盔甲下沿比平台顶高 28px）
    if player is not None:
        player = (player[0], player[1] + cfg.get("foot_offset", 28) * s)
    return player, plats, enemies

# ---------------- 决策 ----------------
def wrap_dx(px, tx, col):
    """角色到目标的最短水平位移（考虑左右穿屏）"""
    Wd = col[1] - col[0]
    d = tx - px
    if d > Wd/2: d -= Wd
    if d < -Wd/2: d += Wd
    return d

def span_dx(px, x0, x1, col, margin):
    """到平台可站立区间的最短位移；已经在上面返回 0"""
    a, b = x0 + margin, x1 - margin
    if a > b: a = b = (x0 + x1) / 2
    if a <= px <= b: return 0.0
    d1, d2 = wrap_dx(px, a, col), wrap_dx(px, b, col)
    return d1 if abs(d1) < abs(d2) else d2

def time_to_cover(dx, v0, tau, vmax):
    """一直朝 dx 方向按住键，多久能横移 dx。横向运动是一阶系统：dv/dt = (vmax - v)/τ
    x(t) = vmax·t + (v0 - vmax)·τ·(1 - e^(-t/τ))，用牛顿法解 x(t)=|dx|（从右侧逼近，单调收敛）"""
    D = abs(dx)
    if D < 1e-6:
        return 0.0
    u = v0 * (1.0 if dx > 0 else -1.0)            # 朝目标方向的初速度（负=正往反方向跑）
    tau = max(tau, 1e-3)
    t = D / vmax + tau * max(0.0, 1.0 - u / vmax)
    for _ in range(12):
        e = np.exp(-t / tau)
        x = vmax * t + (u - vmax) * tau * (1.0 - e)
        dxdt = vmax + (u - vmax) * e
        nt = t - (x - D) / max(dxdt, 1e-3)
        if nt < 0.0:
            nt = 0.0
        if abs(nt - t) < 1e-4:
            t = nt; break
        t = nt
    return t

def reflect_move(x0, x1, v, t, lo, hi):
    """移动平台 t 秒后的位置：在 [lo, hi] 之间来回走、碰边反弹（不会穿框）"""
    w = x1 - x0
    span = (hi - w) - lo
    if span <= 0:
        return x0, x1
    p = min(max(x0 - lo, 0.0), span) + v * t
    period = 2.0 * span
    p = p % period
    if p > span:
        p = period - p
    return lo + p, lo + p + w

def span_gap(a0, a1, b0, b1, col):
    """两段横向区间之间的最短距离（考虑左右穿框）；重叠返回 0"""
    W = col[1] - col[0]
    best = 1e9
    for sh in (-W, 0.0, W):
        c0, c1 = b0 + sh, b1 + sh
        if c1 >= a0 and c0 <= a1:
            return 0.0
        g_ = c0 - a1 if c0 > a1 else a0 - c1
        best = min(best, g_)
    return best

def node_danger(x0, x1, top, kind, enemies, s, jump_h):
    """这块落脚点本身危不危险：上方一跳高度内有敌人、敌人就站在上面、带刺的移动平台"""
    if "!" in kind:
        return True
    if kind[0] == "b" and "~" in kind:
        return True
    for e in enemies:
        if kind == "j":
            continue
        if (e[0] + e[2]/2 > x0 - 6*s) and (e[0] - e[2]/2 < x1 + 6*s) and top - jump_h < e[1] + e[3]/2 < top + 5*s:
            return True
    return False

def plan_eventual(plats, enemies, col, s, depth=5, allow_risky=True):
    """全局规划：把画面里所有安全的落脚点连成图（横向按穿框后的最短距离算），
    往后看几跳，算出从每个落脚点出发最终能爬到多高（返回 dict: 平台 -> 能到达的最高平台顶 y，越小越高）"""
    ts = cfg.get("timescale", 1.0)
    g = cfg["gravity"] * s * ts * ts
    vj = cfg["jump_v"] * s * ts
    H = vj * vj / (2 * g)
    tau_ = cfg.get("htau", 0.167); vm_ = (PHYS["vmax"] or 470*s) * cfg.get("reach_vfrac", 0.9)
    nodes = [p for p in plats if not node_danger(p[0], p[1], p[2], p[3], enemies, s, H + 80*s)
             and (allow_risky or "~" not in p[3])]
    n = len(nodes)
    best = {}
    for p in nodes:
        bonus = 350*s if "*" in p[3] else 0.0          # 弹簧/火箭：能弹得高很多
        best[p] = p[2] - bonus
    succ = {p: [] for p in nodes}
    for p in nodes:
        Hp = H * (2.2 if "*" in p[3] else 1.0)
        vjp = np.sqrt(2 * g * Hp)
        for q in nodes:
            if q is p:
                continue
            dy = p[2] - q[2]                               # q 比 p 高多少
            need_clear = 35*s if q[3] == "j" else 10*s     # 踩敌人头要先高过它
            if dy > Hp - need_clear or dy < -Hp:
                continue
            tq = (vjp + np.sqrt(max(0.0, vjp * vjp - 2 * g * dy))) / g
            m_ = 6*s
            gap = span_gap(p[0] + m_, p[1] - m_, q[0] + m_, q[1] - m_, col)
            if time_to_cover(gap, 0.0, tau_, vm_) <= tq - 0.1:
                succ[p].append(q)
    for _ in range(depth):
        changed = False
        for p in nodes:
            for q in succ[p]:
                if best[q] < best[p] - 0.5:
                    best[p] = best[q]; changed = True
        if not changed:
            break
    return best

def choose(player, vy_up, plats, enemies, col, s, prev_target, stuck=False):
    """先按“带刺平台算危险”选；如果干净的选择里没有一个能（不碰刺地）爬得比起跳平台更高，
    而带刺平台没刺的那段能往上走，就不再把带刺算危险，重新选一次（避免在底下干净平台上原地弹）"""
    try:
        ev_any = plan_eventual(plats, enemies, col, s)
        ev_safe = plan_eventual(plats, enemies, col, s, allow_risky=False)
    except Exception:
        ev_any, ev_safe = {}, {}
    res = _choose(player, vy_up, plats, enemies, col, s, prev_target, stuck, ev_any, True)
    if stuck or not any("~" in q[3] for q in plats):
        return res
    ref = SUPPORT[0] if SUPPORT[0] is not None else player[1]
    clean_ok = [c for c in CANDS if c["reach"] and not c["bad"] and "~" not in c["kind"]
                and ev_safe.get(c["plat"], c["plat"][2]) < ref - 30*s]
    risky_up = [c for c in CANDS if c["reach"] and "~" in c["kind"] and not c["severe"]
                and ev_any.get(c["plat"], c["plat"][2]) < ref - 30*s]
    if not clean_ok and risky_up:
        res2 = _choose(player, vy_up, plats, enemies, col, s, prev_target, stuck, ev_any, False, ref)
        if res2 is not None:
            res = res2
    return res

CANDS = []
PILLARS = []   # 弹簧柱 [(x0, x1, y_top, y_bottom)]，脱困时主动去蹭

def _choose(player, vy_up, plats, enemies, col, s, prev_target, stuck, eventual, tilde_bad, up_ref=None):
    """vy_up: 世界坐标向上速度(px/s，正=上升)。返回 (目标x或None, 目标平台)"""
    px, fy = player
    ts = cfg.get("timescale", 1.0)
    g = cfg["gravity"] * s * ts * ts
    hs = cfg["hspeed"] * s * ts
    margin = 10 * s
    Wd_ = col[1] - col[0]
    best, best_key = None, None
    stick, stick_key = None, None
    DBG.clear(); UPS.clear(); CANDS.clear()
    for (x0, x1, top, kind) in plats:
        if "!" in kind:
            continue                       # 有尖刺
        if up_ref is not None and top >= up_ref - 20*s:
            continue                       # 第二轮：只考虑比起跳平台高的
        if kind == "j" and vy_up <= 0 and fy > top - 40*s and abs(wrap_dx(px, (x0 + x1) / 2, col)) > (x1 - x0) / 2:
            continue                       # 已经在往下落、离它头顶很近却还没对准：来不及了，不踩
        j_below = kind == "j" and fy > top - 8*s
        if j_below and not (vy_up > 0 and fy - vy_up*vy_up/(2*g) < top - 35*s):
            continue                       # 踩敌人只能从头顶落下；人在下面、又跳不过它头顶时不以它为目标
        d = fy - top                       # 平台在脚上方多少（负=在下面）
        if vy_up > 0:
            if vy_up*vy_up < 2*g*(d + 8*s):    # 跳不到这个高度（脚要高出平台顶一点才落得上去）
                continue
            t = (vy_up + np.sqrt(max(0.0, vy_up*vy_up - 2*g*d))) / g
        else:
            if d > -4*s:                   # 下落中只能落到脚下面的平台
                continue
            t = (vy_up + np.sqrt(vy_up*vy_up - 2*g*d)) / g
        # 移动平台：按落地时它会移到的位置来瞄
        vxp = PLAT_V.get((x0, x1, top, kind), 0.0)
        if vxp:
            tt_ = min(t, 1.2)
            # 移动平台碰到左右边界会反弹（不穿框）：按整块平台的宽度算反弹，带刺平台的落脚段跟着整块平移
            pp0, pp1 = SEG_PARENT.get((x0, x1, top, kind), (x0, x1))
            np0, np1 = reflect_move(pp0, pp1, vxp, tt_, col[0], col[1])
            x0m, x1m = x0 + (np0 - pp0), x1 + (np0 - pp0)
        else:
            x0m, x1m = x0, x1
        narrow_k = ("~" in kind) or kind[0] == "p" or kind == "j"
        # 贴着左右边界的平台：落点离边界留出余量（站在边界上会来回穿框）
        x0e = max(x0m, col[0] + 14*s) if x0m < col[0] + 14*s < x1m else x0m
        x1e = min(x1m, col[1] - 14*s) if x0m < col[1] - 14*s < x1m else x1m
        m_k = (x1e - x0e) * 0.5 - 1 if narrow_k else min(margin, (x1e - x0e) * 0.25)
        dx = span_dx(px, x0e, x1e, col, m_k)   # 窄落脚点瞄正中间
        # 落脚区间（相对角色的横向坐标，考虑穿框），给控制器用
        a_r, b_r = x0e + m_k, x1e - m_k
        if a_r > b_r: a_r = b_r = (x0e + x1e) / 2
        hw_r = (b_r - a_r) / 2; c_rel = wrap_dx(px, (a_r + b_r) / 2, col)
        if dx > 0 and c_rel + hw_r < 0: c_rel += Wd_
        elif dx < 0 and c_rel - hw_r > 0: c_rel -= Wd_
        ra_, rb_ = c_rel - hw_r, c_rel + hw_r
        if j_below:
            # 还在它下面：先待在它身体外侧往上跳，脚高过它头顶后再横移过去踩
            sides = [wrap_dx(px, x0 - 55*s, col), wrap_dx(px, x1 + 55*s, col)]
            dx = min(sides, key=abs)
            ra_ = rb_ = dx
        bad = any(x0 - 20*s < e[0] < x1 + 20*s and top - 90*s < e[1] < top + 5*s for e in enemies)
        severe = bad                       # 敌人就站在这块平台上：比别的危险选项更糟
        # 从这块平台弹起来会直接撞上它头顶的敌人（敌人在一跳高度以内、横向又重叠）：危险
        if not bad and kind != "j":
            jump_h = (cfg["jump_v"] * s * ts) ** 2 / (2 * g) + 80*s
            for e in enemies:
                if (e[0] + e[2]/2 > x0 - 6*s) and (e[0] - e[2]/2 < x1 + 6*s) and top - jump_h < e[1] + e[3]/2 < top + 5*s:
                    bad = True; break
        # 落到目标的路上会先经过别的带刺平台：横向路线跨过刺的位置就不行
        if not bad:
            v0_ = PHYS["vx"]; Vm_ = PHYS["vmax"] or 470*s; tau_ = cfg.get("htau", 0.167)
            for sx0, sx1, stop in SPIKES:
                if fy - 5*s < stop < top - 3*s:
                    # 下落经过这个刺/危险平台的高度时人在哪：按一阶模型朝目标按住（离得很近就滑行），考虑穿框
                    ds_ = fy - stop
                    disc = vy_up*vy_up - 2*g*ds_
                    if disc < 0:
                        continue
                    tc = (vy_up + np.sqrt(disc)) / g
                    u_ = float(np.sign(dx)) if abs(dx) > 30*s else 0.0
                    disp = u_*Vm_*tc + (v0_ - u_*Vm_)*tau_*(1.0 - np.exp(-tc/tau_))
                    if u_ != 0 and disp*u_ > abs(dx):
                        disp = dx
                    xc = col[0] + ((px + disp - col[0]) % Wd_)
                    if sx0 - 26*s < xc < sx1 + 26*s:      # 脚的判定比盔甲中心宽（实测踩到平台边外 26px 也能弹起）
                        bad = True; break
        # 去目标的横向路线（从现在高度到目标高度之间）上有敌人挡着：不去
        if not bad and kind != "j":
            tx = px + dx
            if col[0] <= tx <= col[1]:
                lo_, hi_ = min(px, tx) - 20*s, max(px, tx) + 20*s
                apex_y = fy - max(vy_up, 0.0) ** 2 / (2 * g)          # 还在往上冲：路线会先经过最高点
                ylo, yhi = min(apex_y - 50*s, fy - 60*s, top - 60*s), max(fy, top)
                for e in enemies:
                    if e[0] + e[2]/2 > lo_ and e[0] - e[2]/2 < hi_ and e[1] + e[3]/2 > ylo and e[1] - e[3]/2 < yhi:
                        bad = True; break
        # 落到这块平台的路上会擦过敌人的侧面（敌人比平台高、横向又挨着）也不去
        if not bad and kind != "j":
            for e in enemies:
                etop_, ebot_ = e[1] - e[3]/2, e[1] + e[3]/2
                # 按实际要落的那一段算（落点区间 ± 身体半宽 20px），不是整块平台
                near = (a_r - 38*s < e[0] + e[2]/2) and (e[0] - e[2]/2 < b_r + 38*s)
                if near and etop_ < top - 5*s and ebot_ > min(fy, top) - 40*s:
                    bad = True; break
        if "~" in kind and tilde_bad:
            bad = True                     # 带刺平台（只剩刺旁边一小段）：落点要求太准，没有干净平台时才去
        if stuck:
            if top > fy - 20*s and eventual.get((x0, x1, top, kind), top) > fy - 20*s:
                continue                   # 卡住时只考虑更高的、或能通往更高处的平台
            if "~" in kind and not severe:
                bad = False                # 卡住时允许去带刺平台没刺的那一段
        vm_ = PHYS["vmax"] or 470*s
        slack = min(1.0, cfg.get("reach_vfrac", 0.9) + (0.07 if stuck else 0.0))
        need = time_to_cover(dx, PHYS["vx"], cfg.get("htau", 0.167), vm_ * slack)
        reach = need <= max(t - 0.06, 0.0)
        slack_t = t - 0.06 - need                              # 时间余量（秒）
        risk_ = max(0.0, 0.15 - slack_t) * 800*s if reach else 0.0   # 时间卡得太紧也算风险
        deficit = need - t                                     # 够不着时还差多少秒（越小越有希望）
        narrow = max(0.0, 45*s - (x1 - x0)) * 2.0            # 落脚区太窄扣分
        ev_ = eventual.get((x0, x1, top, kind), top)       # 从这里出发最终能爬到的高度（全局规划）
        sticky = prev_target is not None and abs(prev_target[2] - top) < 30*s and abs(prev_target[0] - x0) < 15*s
        # 同一块带刺平台的另一侧：不要在左右两段之间来回换（最容易换着换着踩到中间的刺）
        flip = prev_target is not None and not sticky and abs(prev_target[2] - top) < 10*s and \
            ("~" in kind or "~" in prev_target[3]) and abs(prev_target[0] - x0) < 160*s
        # 能稳稳到达的优先；越高越好，但横移越远扣分越多；当前目标加分，避免来回改主意
        if vy_up <= 0:
            # 正在往下落：够得着但有点危险的，强过够不着的（够不着基本就是摔死）
            cat = (0 if not bad else 1) if reach else (2 + (2 if bad else 0))
        else:
            cat = (0 if reach else 1) + (2 if bad else 0)
        key = (cat + (4 if severe else 0),     # 有危险的只在实在没得选时才去
               ((ev_ + 0.5 * (top - ev_)) - ((150*s if vy_up > 0 else 30*s) if "*" in kind else 0) + ((120*s if tilde_bad else 30*s) if "~" in kind else 0) + (260*s if kind[0] == "b" and "~" in kind else 0) + narrow + (0.15 if stuck else 0.25)*abs(dx) + risk_ - (0 if stuck else ((120*s if "~" in kind else 60*s) if sticky else 0)) + (150*s if flip else 0)) if reach else deficit)
        DBG.append((key[0], int(x0), int(x1), int(top), kind, int(dx), int(reach), int(bad)))
        CANDS.append({"plat": (x0, x1, top, kind), "kind": kind, "reach": bool(reach), "bad": bool(bad), "severe": bool(severe)})
        cand_ = (x0, x1, top, kind, dx, ev_, ra_, rb_, t)
        if reach and not severe and (not bad or "~" in kind):
            UPS.append(((1 if bad else 0, key[1]), cand_))
        if best_key is None or key < best_key:
            best_key, best = key, cand_
        if sticky and (stick_key is None or key < stick_key):
            stick_key, stick = key, cand_
    # 卡住保护（只在 2 秒多没往上爬时）：最好的选择只是落回起跳平台或更低，
    # 而有更高的平台够得着（哪怕带刺、只剩没刺的那段）→ 去更高的那块
    sup = SUPPORT[0]
    if STUCK_SOFT[0] and best is not None and vy_up > 0 and sup is not None and best[2] >= sup - 20*s:
        up = [c for c in UPS if c[1][2] < sup - 30*s]
        if up:
            k_, c_ = min(up, key=lambda z: z[0])
            return c_
    # 原地再弹一次（目标就是刚起跳的那块）= 白白浪费一跳：有够得着、不危险、明显更高的平台，而且分数差得不多 → 去更高的
    if best is not None and vy_up > 0 and sup is not None and abs(best[2] - sup) < 25*s:
        up = [c for c in UPS if c[0][0] == 0 and c[1][2] < sup - 40*s]
        if up:
            k_, c_ = min(up, key=lambda z: z[0])
            if k_[1] <= best_key[1] + 90*s:
                return c_
    # 认准目标：当前目标还够得着、也没变危险，就不换（除非新目标明显更好）；往下落时更不换
    if stick is not None and best is not None:
        if stick_key[0] <= best_key[0] and (vy_up <= 0 or stick_key[1] <= best_key[1] + (400*s if DODGE_DIR[0] != 0 else 150*s)):
            return stick
    return best

class VTracker:
    """估计角色在世界坐标里的竖直速度（正=上升）。相机上移时平台会整体下移，用平台匹配算出滚屏量。
    速度：用“已知重力”的抛物线拟合最近几帧的世界高度（几乎没有滞后、也抗噪）；刚弹起的一两帧用起跳速度模型"""
    def __init__(self):
        self.prev = None; self.hist = []; self.total_scroll = 0.0; self.samp = []; self.t_bounce = None
    def update(self, t, player, plats, s):
        self.s = s
        if self.prev is None:
            self.prev = (t, player[1], plats); self.samp = [(t, self.total_scroll - player[1])]
            return 0.0
        t0, fy0, pl0 = self.prev
        dt = t - t0
        if dt < 0.004:
            self.last_scroll = 0.0
            return self.value()
        ds = []
        for x0, x1, top, k in plats:
            if k[0] == "j":   # 小丑头不稳定，不参与
                continue
            tol = 15*s if k[0] in "bc" else 3*s       # 蓝色/云会左右动：横向放宽，竖直方向和别的平台一样滚
            c = [top - q[2] for q in pl0 if q[3] == k and abs(q[0] - x0) <= tol and abs((q[1]-q[0]) - (x1-x0)) <= 4*s and -4*s <= top - q[2] <= 250*s]
            if c: ds.append(min(c))
        if not ds and abs(player[1] - fy0) < 2*s and dt < 0.3:
            self.last_scroll = 0.0            # 认不出滚屏量、角色又停在滚屏线上：这一帧不可信，跳过（滚屏量下一帧一起算）
            return self.value()
        scroll = float(np.median(ds)) if ds else 0.0
        self.total_scroll += max(scroll, 0.0)
        self.last_scroll = scroll
        same = scroll == 0.0 and abs(player[1] - fy0) < 0.5
        if not same:   # 跳过重复帧
            vy = (scroll - (player[1] - fy0)) / dt
            h = self.total_scroll - player[1]
            # 弹起：之前在下落（中间可能夹一帧刚好接触平台、速度≈0），现在明显在往上冲
            if self.hist and min(self.hist[-2:]) < -40*s and vy > 300*s and (self.t_bounce is None or t0 - self.t_bounce > 0.25):
                self.t_bounce = t0
                # 起跳平台高度 = 弹起前后最低的那一帧（中间可能夹着接触帧）；存成（屏幕y, 当时的累计滚屏）
                h_lo = min([q[1] for q in self.samp[-3:]] + [self.total_scroll - fy0])
                self.support = (self.total_scroll - h_lo, self.total_scroll)
                self.samp = []                     # 弹起前的点不在这条抛物线上，全部丢掉
            self.samp.append((t, h)); self.samp = self.samp[-8:]
            self.hist.append(vy); self.hist = self.hist[-3:]
            self.prev = (t, player[1], plats)
        return self.value()
    def fit(self):
        """已知重力的抛物线拟合：h(τ) = h0 + v·τ - g/2·τ²（τ=相对最新一帧的时间），返回 (v, 残差)"""
        sm = self.samp
        if len(sm) < 3:
            return None, None
        tn = sm[-1][0]
        pts = [(a - tn, b) for a, b in sm[-6:] if tn - a <= 0.25]
        if len(pts) < 3:
            return None, None
        ts_ = cfg.get("timescale", 1.0); s_ = getattr(self, "s", 1.0)
        g = cfg["gravity"] * s_ * ts_ * ts_
        tau = np.array([p[0] for p in pts]); z = np.array([p[1] for p in pts]) + 0.5 * g * tau * tau
        tm, zm = tau.mean(), z.mean()
        den = float(((tau - tm) ** 2).sum())
        if den < 1e-9:
            return None, None
        v = float(((tau - tm) * (z - zm)).sum() / den)
        res = float(np.sqrt(np.mean((zm + v * (tau - tm) - z) ** 2)))
        return v, res
    def value(self):
        ts = cfg.get("timescale", 1.0); s_ = getattr(self, "s", 1.0)
        v_fit, res = self.fit()
        v = float(np.median(self.hist)) if self.hist else 0.0
        if v_fit is not None:
            v = v_fit
        # 刚弹起：拟合点还少（或噪声大），和物理模型（起跳速度 - g·t）平均；弹簧/火箭时拟合明显更大，用拟合
        t_b = self.t_bounce
        if t_b is not None and self.prev is not None:
            dtb = self.prev[0] - t_b
            if 0 <= dtb < 0.25:
                v_model = cfg["jump_v"] * s_ * ts - cfg["gravity"] * s_ * ts * ts * dtb
                if v_fit is None:
                    v = max(v, v_model)
                elif abs(v_fit - v_model) < 150*s_:
                    w_ = min(1.0, dtb / 0.25)
                    v = w_ * v_fit + (1 - w_) * v_model
        return v
    def reset(self):
        self.prev = None; self.hist = []; self.samp = []      # total_scroll 不清零：短暂认不出角色时进度不能丢

_OCR = []
def read_score(small_img):
    """从缓存画面(半分辨率)顶部读分数"""
    try:
        if not _OCR:
            from rapidocr_onnxruntime import RapidOCR
            _OCR.append(RapidOCR())
        h, w = small_img.shape[:2]
        crop = small_img[0:int(h*0.06), int(w*0.3):int(w*0.7)]
        crop = cv2.resize(crop, None, fx=3, fy=3)
        res, _ = _OCR[0](crop)
        ds = ["".join(ch for ch in text if ch.isdigit()) for box, text, sc in (res or [])]
        ds = [d for d in ds if d]
        if ds: return int(max(ds, key=len))
    except Exception as e:
        return f"err:{e}"
    return ""

def foreground_title():
    """当前最前面窗口的标题"""
    try:
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        return b.value
    except Exception:
        return None

# ---------------- 键盘（扫描码 SendInput，游戏更容易收到） ----------------
SCAN = {"a": (0x1E, False), "d": (0x20, False), "w": (0x11, False),
        "left": (0x4B, True), "right": (0x4D, True), "up": (0x48, True), "space": (0x39, False)}

def _send_scan(key, up):
    import ctypes.wintypes as wt
    PUL = ctypes.POINTER(ctypes.c_ulong)
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", PUL)]
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", PUL)]
    class _I(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]
    class INPUT(ctypes.Structure):
        _fields_ = [("type", wt.DWORD), ("ii", _I)]
    sc, ext = SCAN[key]
    flags = 0x0008 | (0x0002 if up else 0) | (0x0001 if ext else 0)   # SCANCODE | KEYUP | EXTENDED
    inp = INPUT(type=1, ii=_I(ki=KEYBDINPUT(0, sc, flags, 0, None)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

def key_down(k): _send_scan(k, False)
def key_up(k): _send_scan(k, True)
def key_tap(k): key_down(k); time.sleep(0.03); key_up(k)
PENDING_UP = {}
def key_tap_async(k, now):
    """不阻塞的点按：先按下，0.03 秒后由主循环松开（避免主循环停顿）"""
    if k in PENDING_UP:
        return
    key_down(k); PENDING_UP[k] = now + 0.03
def flush_taps(now):
    for k_ in [k_ for k_, tu in PENDING_UP.items() if now >= tu]:
        key_up(k_); PENDING_UP.pop(k_, None)

# ---------------- 后台写盘（写图片/遥测不能卡住主循环） ----------------
import threading, queue
IOQ = queue.Queue(maxsize=64)
def _io_worker():
    while True:
        job = IOQ.get()
        try:
            job()
        except Exception:
            pass
threading.Thread(target=_io_worker, daemon=True).start()
def io_submit(fn):
    try:
        IOQ.put_nowait(fn)
    except queue.Full:
        pass

# ---------------- 主循环 ----------------
def main():
    import mss, keyboard
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception: pass
    import ctypes.wintypes as wt

    def save(): json.dump(cfg, open(CFG_PATH, "w", encoding="utf-8"), indent=2)
    def cursor():
        p = wt.POINT(); ctypes.windll.user32.GetCursorPos(ctypes.byref(p)); return p.x, p.y
    AUTO = "--auto" in sys.argv
    st = {"run": False, "quit": False, "dump": False, "reload": False}
    my_mtime = os.path.getmtime(os.path.abspath(__file__))
    auto_start = time.time() + 3.0 if AUTO else None
    if AUTO:
        print("自动模式：3 秒后开始，请切到游戏窗口。死了会停下等 Claude 分析改进，改完自动重启开下一局")
    def tl(): cfg["left"], cfg["top"] = cursor(); save(); print("左上角", cfg["left"], cfg["top"])
    def br(): cfg["right"], cfg["bottom"] = cursor(); save(); print("右下角", cfg["right"], cfg["bottom"], "已保存")
    def tog():
        st["run"] = not st["run"]; print("[>] 运行（按键 A/D 移动, W 射击）" if st["run"] else "[||] 暂停")
        if not st["run"]: release_all()
    def tshoot(): cfg["shoot"] = not cfg["shoot"]; save(); print("自动射击:", "开" if cfg["shoot"] else "关")
    keyboard.add_hotkey("f8", tl); keyboard.add_hotkey("f9", br); keyboard.add_hotkey("f6", tog)
    keyboard.add_hotkey("f7", tshoot); keyboard.add_hotkey("f10", lambda: st.update(quit=True))
    keyboard.add_hotkey("f11", lambda: st.update(dump=True))
    keyboard.add_hotkey("f12", lambda: st.update(save=True))

    K = {"left": cfg.get("key_left", "a"), "right": cfg.get("key_right", "d"), "up": cfg.get("key_shoot", "w")}
    held = {"left": False, "right": False}
    held_since = {"left": None, "right": None}
    def hold(k, on):
        if held[k] != on:
            (key_down if on else key_up)(K[k]); held[k] = on
            held_since[k] = time.time() if on else None
    def release_all():
        hold("left", False); hold("right", False)

    print(__doc__)
    col = None; s = 1.0
    vt = VTracker()
    LIVE = os.path.join(HERE, "live"); LIVE_F = os.path.join(LIVE, "frames")
    os.makedirs(LIVE_F, exist_ok=True)
    tele = []                       # 最近约 60 秒的逐帧记录
    tele_flush = [time.time(), 0.0] # [上次写盘时间, 上次存抽样画面时间]
    def live_flush(now, tele):
        try:
            with open(os.path.join(LIVE, "telemetry.csv"), "w", encoding="utf-8") as tf:
                tf.write("t,px,py,vy,vx,tx0,tx1,ttop,tkind,tdx,teve,keyL,keyR,mode,nplat,nen,stuck,scroll,cands\n")
                for r in tele:
                    tf.write(",".join(str(v) for v in r) + "\n")
            # 删掉 70 秒前的抽样画面
            for fn in os.listdir(LIVE_F):
                try:
                    if now - float(fn[:-4]) > 70: os.remove(os.path.join(LIVE_F, fn))
                except (ValueError, OSError):
                    pass
            # 汇总指标
            rec = [r for r in tele if now - r[0] < 30]
            if len(rec) > 30:
                dur = rec[-1][0] - rec[0][0]
                climb = (rec[-1][17] - rec[0][17]) / max(dur, 1e-3)
                flips = sum(1 for a_, b_ in zip(rec[:-1], rec[1:]) if (a_[11], a_[12]) != (b_[11], b_[12]) and (b_[11] or b_[12]) and (a_[11] or a_[12]))
                presses = sum(1 for a_, b_ in zip(rec[:-1], rec[1:]) if not (a_[11] or a_[12]) and (b_[11] or b_[12]))
                def _sw(a_, b_):
                    if (a_[5] == "") != (b_[5] == ""): return True
                    if a_[5] == "": return False
                    return a_[8] != b_[8] or abs(float(a_[5]) - float(b_[5])) > 15 or abs(float(b_[7]) - float(a_[7]) - (b_[17] - a_[17])) > 15
                tswitch = sum(1 for a_, b_ in zip(rec[:-1], rec[1:]) if _sw(a_, b_))
                dodge = sum(1 for r in rec if "躲" in str(r[13])) / len(rec)
                stuckp = sum(1 for r in rec if r[16]) / len(rec)
                wraps = sum(1 for a_, b_ in zip(rec[:-1], rec[1:]) if abs(b_[1] - a_[1]) > 250)
                with open(os.path.join(LIVE, "summary.txt"), "a", encoding="utf-8") as sf_:
                    sf_.write(f"{time.strftime('%H:%M:%S')} 30s: 爬升{climb:5.0f}px/s 左右直接反向{flips/dur:4.1f}/s 按键次数{presses/dur:4.1f}/s 换目标{tswitch/dur:4.1f}/s 躲避占比{dodge:4.0%} 卡住占比{stuckp:4.0%} 穿框{wraps}次 fps{len(rec)/dur:3.0f}\n")
        except Exception as e_:
            log(f"live 写盘出错 {e_}")
    buf = []; seen_t = 0
    vy_last, tgt_last, act_last = [0.0], [None], ["·"]
    prog = [0.0, time.time(), False]
    prev_en = [None, 0.0]
    pvx = [0.0, None]
    fg = [True, 0.0, "", 0.0]   # [游戏在前台, 上次检查时间, 前台标题, 上次提示时间]
    plat_mem = []
    spk_prev = [None, 0.0]
    pl_prev = [None, 0.0, {}]
    raw_dump = [0.0]     # 角色横向速度、上一帧(t, x)   # [上次有进展时的累计滚屏, 时间, 是否已提示]
    def dump_buf(tag):
        d = os.path.join(HERE, "deaths", time.strftime("%H%M%S") + "_" + tag); os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "log.csv"), "w", encoding="utf-8") as lf:
            lf.write("t,px,py,vy,tgt_x0,tgt_x1,tgt_top,tgt_dx,act,n_plat,enemies,tkind,vx,plats,cands\n")
            for item in buf:
                bt, sm, pl, pls, ens, vy_, tg_, ac_ = item[:8]
                extra = item[8] if len(item) > 8 else ("", 0, "")
                cv2.imwrite(os.path.join(d, f"{bt:.3f}.jpg"), sm, [cv2.IMWRITE_JPEG_QUALITY, 92])
                tgs = ",".join(str(round(float(v))) for v in (tg_[0], tg_[1], tg_[2], tg_[4])) if tg_ else ",,,"
                pls_s = "|".join(f"{int(q[0])}-{int(q[1])}@{int(q[2])}{q[3]}" for q in pls)
                lf.write(f"{bt:.3f},{pl[0]:.0f},{pl[1]:.0f},{vy_:.0f},{tgs},{ac_},{len(pls)},{';'.join(f'{e[0]:.0f}/{e[1]:.0f}/{e[4] if len(e) > 4 else chr(63)}' for e in ens)},"
                         f"{tg_[3] if tg_ else ''},{extra[1]},{pls_s},{extra[2]}\n")
        log(f"已保存最近 {len(buf)} 帧到 {d}"); buf.clear()
    lp_ = os.path.join(HERE, "bot_log.txt")
    try:
        if os.path.exists(lp_) and os.path.getsize(lp_) > 3_000_000:
            os.replace(lp_, os.path.join(HERE, "bot_log_old.txt"))
    except OSError:
        pass
    logf = open(lp_, "a", encoding="utf-8")
    logf.write("\n===== " + time.strftime("%Y-%m-%d %H:%M:%S") + " 启动 =====\n")
    last_log = 0.0
    def log(msg):
        print(msg); logf.write(time.strftime("%H:%M:%S ") + msg + "\n"); logf.flush()
    prev_target = None
    last_shot = 0.0
    fps_t, fps_n = time.time(), 0
    with (mss.MSS() if hasattr(mss, "MSS") else mss.mss()) as sct:
        last_mcheck = 0.0; dead_since = None; last_space = 0.0; ever_alive = False
        while not st["quit"]:
          try:
            now_ = time.time()
            if auto_start and now_ > auto_start:
                st["run"] = True; auto_start = None; log("[>] 自动开始")
            if now_ - last_mcheck > 2.0:
                last_mcheck = now_
                try:
                    if os.path.getmtime(os.path.abspath(__file__)) > my_mtime + 0.5:
                        dead_long = dead_since is not None and now_ - dead_since > 1.5
                        stuck_long = now_ - prog[1] > 30.0          # 卡了半分钟没进展：直接换新版本接着打
                        if dead_long or not ever_alive or stuck_long:
                            log("检测到程序更新，重启…"); st["reload"] = True; st["quit"] = True; continue
                        elif not st.get("pending"):
                            st["pending"] = True; log("检测到新版本：这一局结束后生效")
                except OSError:
                    pass
            if not st["run"] and not st["dump"]:
                time.sleep(0.03); vt.reset(); continue
            mon = {"left": cfg["left"], "top": cfg["top"],
                   "width": cfg["right"] - cfg["left"], "height": cfg["bottom"] - cfg["top"]}
            if mon["width"] <= 0:
                print("先用 F8/F9 框住游戏窗口"); st["run"] = False; continue
            t = time.time()
            img = np.ascontiguousarray(np.array(sct.grab(mon))[:, :, :3])
            flush_taps(t)
            # 游戏窗口必须在最前面：否则按键会打到别的窗口里，游戏还可能“卡住”某个方向键
            if t - fg[1] > 0.4:
                fg[1] = t
                title = foreground_title()
                fg[0] = (title is None) or ("dota" in title.lower())
                fg[2] = title or ""
            if not fg[0]:
                release_all(); flush_taps(1e18)
                if t - fg[3] > 5:
                    fg[3] = t; log(f"[!] 游戏窗口不在最前面（当前：{fg[2][:30]}），暂停操作，等你点回游戏窗口")
                time.sleep(0.1); continue
            hsv = None
            if col is None or fps_n % 60 == 0:
                c = find_column(cv2.cvtColor(img, cv2.COLOR_BGR2HSV))
                if c: col = c; s = (col[1] - col[0]) / BASE_W
            if col is None:
                if t - last_log > 5.0:
                    log("没找到游戏画面（米色边框）——游戏窗口被挡住了，或 F8/F9 区域不对"); last_log = t
                    cv2.imwrite(os.path.join(HERE, "nogame.jpg"), cv2.resize(img, None, fx=0.5, fy=0.5))
                # 结算画面会挡住边框：自动模式下照样按空格开局
                flag = os.path.join(HERE, "continue.flag")
                if AUTO and ((not ever_alive) or os.path.exists(flag)) and t - last_space > 3.0:
                    if os.path.exists(flag):
                        try: os.remove(flag)
                        except OSError: pass
                        ever_alive = False
                    key_tap("space"); last_space = t; log("按空格开局")
                elif AUTO and ever_alive and t - last_log > 10.0:
                    log("[||] 已死亡，等待 Claude 分析改进…"); last_log = t
                release_all(); time.sleep(0.5)
                if st["dump"]: cv2.imwrite(os.path.join(HERE, "debug.png"), img); st["dump"] = False
                continue
            player, plats, enemies = perceive(img, col, s)

            if st["dump"]:
                dbg = img.copy()
                for x0, x1, top, k in plats: cv2.rectangle(dbg, (x0, top), (x1, top+8), (0,255,255), 2)
                for e in enemies: cv2.circle(dbg, (int(e[0]), int(e[1])), int(max(e[2], e[3])/2), (0,0,255), 2)
                if player: cv2.circle(dbg, (int(player[0]), int(player[1])), 8, (255,0,255), -1)
                cv2.line(dbg, (col[0], 0), (col[0], dbg.shape[0]), (255,0,0), 1); cv2.line(dbg, (col[1], 0), (col[1], dbg.shape[0]), (255,0,0), 1)
                cv2.imwrite(os.path.join(HERE, "debug.png"), dbg); print("已保存 debug.png", "角色:", player, "平台:", len(plats), "敌人:", len(enemies))
                st["dump"] = False
                if not st["run"]: continue

            # 录像缓存（最近约 8 秒），死亡时自动存
            alive = player is not None and len(plats) >= 3
            if alive:
                small = cv2.resize(img, None, fx=0.5, fy=0.5)
                cands_s = "|".join(f"{c[0]}:{c[1]}-{c[2]}@{c[3]}{c[4]}:dx{c[5]}:r{c[6]}b{c[7]}" for c in sorted(DBG)[:6])
                buf.append((t, small, player, list(plats), list(enemies), vy_last[0], tgt_last[0], act_last[0], ("", int(PHYS["vx"]), cands_s)))
                if len(buf) > 240: buf.pop(0)
                seen_t = t
            elif buf and seen_t and t - seen_t > 0.8 and len(buf) < 30:
                buf.clear(); seen_t = 0            # 只活了不到 2 秒（开局过场等），不算一局
            elif buf and seen_t and t - seen_t > 0.8:
                # 结算画面也存几帧，方便看死因
                buf.append((t, cv2.resize(img, None, fx=0.5, fy=0.5), player or (0, 0), list(plats), list(enemies), 0, None, "dead"))
                score = read_score(buf[-2][1] if len(buf) > 1 else buf[-1][1])
                with open(os.path.join(HERE, "scores.csv"), "a", encoding="utf-8") as sf:
                    sf.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{score}\n")
                log(f"本局得分：{score}")
                dump_buf("death"); seen_t = 0
            if alive:
                dead_since = None; ever_alive = True
            else:
                dead_since = dead_since or t
                # 自动模式：死了先停下等分析。只有两种情况才按空格开下一局：
                #   1) 刚启动（含改完代码自动重启后），还没开局
                #   2) Claude 分析完觉得不用改代码，放了 continue.flag
                flag = os.path.join(HERE, "continue.flag")
                go = (not ever_alive) or os.path.exists(flag)
                if AUTO and go and t - dead_since > 3.0 and t - last_space > 3.0:
                    if os.path.exists(flag):
                        try: os.remove(flag)
                        except OSError: pass
                        ever_alive = False
                    key_tap("space"); last_space = t; log("按空格开局")
                elif AUTO and ever_alive and t - last_log > 10.0:
                    log("[||] 已死亡，等待 Claude 分析改进…"); last_log = t
            if st.get("save"):
                dump_buf("manual"); st["save"] = False

            if not alive:
                if t - last_log > 1.0:
                    log(f"找不到角色 | 平台 {len(plats)} | 区域 {img.shape[1]}x{img.shape[0]} 边框 {col}"); last_log = t
                    try: cv2.imwrite(os.path.join(HERE, "nogame.jpg"), cv2.resize(img, None, fx=0.5, fy=0.5))
                    except Exception: pass
                release_all(); vt.reset(); prog[0], prog[1] = 0.0, time.time(); time.sleep(0.01); continue

            vy_up = vt.update(t, player, plats, s)
            sp_ = getattr(vt, "support", None)
            SUPPORT[0] = None if sp_ is None else sp_[0] + (getattr(vt, "total_scroll", 0.0) - sp_[1])
            # 移动平台（蓝色、云）测速：和上一帧配对
            sc1 = getattr(vt, "last_scroll", 0.0)
            newv = {}
            if pl_prev[0] is not None and t - pl_prev[1] < 0.3:
                dtp = max(t - pl_prev[1], 1e-3)
                for p_ in plats:
                    if p_[3][0] not in "bc":
                        continue
                    cands = [q for q in pl_prev[0] if q[3][0] == p_[3][0] and abs(q[2] + sc1 - p_[2]) < 6*s
                             and abs((q[1] - q[0]) - (p_[1] - p_[0])) < 10*s and abs(q[0] - p_[0]) < 40*s]
                    if cands:
                        q = min(cands, key=lambda q: abs(q[0] - p_[0]))
                        raw_v = (p_[0] - q[0]) / dtp
                        old_v = pl_prev[2].get(q, raw_v)
                        newv[p_] = 0.6 * old_v + 0.4 * raw_v
            pl_prev[0], pl_prev[1], pl_prev[2] = list(plats), t, newv
            PLAT_V.clear(); PLAT_V.update({k_: v_ for k_, v_ in newv.items() if abs(v_) > 20*s})
            # 移动平台上的刺：估计速度，把它 0.5 秒内会扫过的范围都当成危险区
            sc0 = getattr(vt, "last_scroll", 0.0)
            ext = []
            for sx0, sx1, stop in SPIKES:
                vx_ = 0.0
                if spk_prev[0] is not None and t - spk_prev[1] < 0.3:
                    c_ = [q for q in spk_prev[0] if abs(q[2] + sc0 - stop) < 6*s and abs((q[1]-q[0]) - (sx1-sx0)) < 8*s and abs(q[0] - sx0) < 60*s]
                    if c_:
                        q = min(c_, key=lambda q: abs(q[0] - sx0))
                        vx_ = (sx0 - q[0]) / max(t - spk_prev[1], 1e-3)
                if abs(vx_) > 30*s:
                    ext.append((min(sx0, sx0 + vx_*0.5) - 6*s, max(sx1, sx1 + vx_*0.5) + 6*s, stop))
                else:
                    ext.append((sx0, sx1, stop))
            spk_prev[0], spk_prev[1] = list(SPIKES), t
            SPIKES[:] = ext
            # 平台记忆：角色站上去时会挡住平台（尤其竖柱子），短时间内用上一帧的位置补回来
            sc_ = getattr(vt, "last_scroll", 0.0)
            kept = []
            for (mx0, mx1, mtop, mk, mt) in plat_mem:
                ntop = mtop + sc_
                if t - mt > (1.0 if mk[0] == "p" else 0.6) or mk[0] not in "gp":
                    continue
                if any(abs(q[2] - ntop) < 8*s and q[0] < mx1 and q[1] > mx0 for q in plats):
                    continue
                # 柱子：画面里时有时无（被角色挡住、颜色闪烁），1 秒内都用记忆补回来
                if mk[0] == "p" or (abs((mx0 + mx1)/2 - player[0]) < 120*s and -60*s < ntop - player[1] < 160*s):
                    kept.append((mx0, mx1, ntop, mk, mt))
            plat_mem[:] = kept + [(q[0], q[1], q[2], q[3], t) for q in plats]
            plats = plats + [(q[0], q[1], int(q[2]), q[3]) for q in kept]
            if pvx[1] is not None and t - pvx[1][0] > 0.004:
                dxp = wrap_dx(pvx[1][1], player[0], col)
                if abs(dxp) < 80*s:
                    dt_ = t - pvx[1][0]
                    v_ = dxp / dt_
                    v_old = pvx[0]
                    # 一阶模型预测 + 测量修正（比单纯平滑滞后小）：上一帧按的键在这段时间里起作用
                    u_ = 1 if held["right"] and not held["left"] else (-1 if held["left"] and not held["right"] else 0)
                    Vm_ = PHYS["vmax"] or 470*s; tau_ = cfg.get("htau", 0.167)
                    e_ = np.exp(-dt_ / tau_)
                    v_end = u_*Vm_ + (pvx[0] - u_*Vm_) * e_
                    v_avg = u_*Vm_ + (pvx[0] - u_*Vm_) * tau_ / dt_ * (1 - e_)
                    pvx[0] = v_end + 0.5 * (v_ - v_avg)
                    # 在线估计横向加速度/最大速度（不同高度段手感可能不一样）
                    dirn = 1 if held["right"] and not held["left"] else (-1 if held["left"] and not held["right"] else 0)
                    hk = "right" if dirn > 0 else "left"
                    if dirn != 0 and held_since[hk] is not None:
                        hold_t = t - held_since[hk]
                        if 0.06 < hold_t < 0.5 and abs(pvx[0]) < 0.8 * (PHYS["vmax"] or 450*s):
                            a_obs = (pvx[0] - v_old) * dirn / (t - pvx[1][0])
                            if a_obs > 0:
                                a_obs = max(1000*s, min(4000*s, a_obs))   # 合理范围内（之前测到的异常值其实是按键没进游戏）
                                PHYS["a"] = a_obs if PHYS["a"] is None else 0.85*PHYS["a"] + 0.15*a_obs
                        if hold_t > 0.45 and v_ * dirn > 0:
                            vm_obs = max(350*s, min(600*s, abs(v_)))
                            PHYS["vmax"] = vm_obs if PHYS["vmax"] is None else 0.9*PHYS["vmax"] + 0.1*vm_obs
            pvx[1] = (t, player[0])
            PHYS["vx"] = pvx[0]
            dirn_ = 1 if held["right"] and not held["left"] else (-1 if held["left"] and not held["right"] else 0)
            hk_ = "right" if dirn_ > 0 else "left"
            if dirn_ and held_since[hk_] is not None and t - held_since[hk_] > 0.5 and pvx[0] * dirn_ < -150*s:
                if t - fg[3] > 5:
                    fg[3] = t; log("[!] 按住的方向和实际移动相反：按键可能没进游戏（窗口焦点？）")

            # 敌人速度预测（小丑会跟着移动平台走、乌鸦会飞）：用 0.3 秒后的位置一起判断
            moving = []; moving_long = []
            if prev_en[0] is not None and t - prev_en[1] < 0.3:
                for e in enemies:
                    cands = [q for q in prev_en[0] if q[4] == e[4] and abs(q[0] - e[0]) < 80*s and abs(q[1] - e[1]) < 80*s]
                    if cands:
                        q = min(cands, key=lambda q: abs(q[0] - e[0]) + abs(q[1] - e[1]))
                        vx = max(-600*s, min(600*s, (e[0] - q[0]) / max(t - prev_en[1], 1e-3)))
                        if abs(vx) > 40*s:
                            moving.append((e[0] + vx*0.3, e[1], e[2] + abs(vx)*0.15, e[3], e[4]))
                            # 选目标用更长的预测：0.8 秒内它会扫过的整段范围
                            moving_long.append((e[0] + vx*0.4, e[1], e[2] + abs(vx)*0.8, e[3] + 20*s, e[4]))
            prev_en[0], prev_en[1] = list(enemies), t
            ts_now = getattr(vt, "total_scroll", 0.0)
            if ts_now - prog[0] > 40*s:
                prog[0], prog[1] = ts_now, t
            stuck = t - prog[1] > 3.0
            STUCK_SOFT[0] = t - prog[1] > 2.0
            if stuck and not prog[2]:
                log("[!] 3 秒没往上爬，进入脱困模式"); prog[2] = True
            if not stuck: prog[2] = False
            if prev_target is not None:      # 相机滚动后，上一帧目标的 y 要跟着平移才能对上
                prev_target = (prev_target[0], prev_target[1], prev_target[2] + getattr(vt, "last_scroll", 0.0)) + tuple(prev_target[3:])
            tgt = choose(player, vy_up, plats, enemies + moving_long, col, s, None if stuck else prev_target, stuck)
            if stuck and tgt is None:
                # 脱困时第一轮(stuck=True)已过滤掉自身/更低平台, 若无更高可达则保持 None
                # 进入"寻"模式(向最近平台靠), 不再回退到 stuck=False 重选回原地
                # (041603: 回退会选回 298-350@829 原地空跳 7.6 秒直至偏出踩空)
                tgt = None
            # 躲避：不能从下面/侧面碰到敌人；从上往下踩没事
            g_px = cfg["gravity"] * s * cfg.get("timescale", 1.0) ** 2
            ptop, pbot = player[1] - 68*s, player[1]          # 整个身体：脚底往上约 68px
            threat = None
            ethreat = None # 敌人威胁（带符号的横向距离），单独记以便做方向迟滞
            for ex, ey, ew, eh, et in enemies + moving:
                edx = wrap_dx(player[0], ex, col)
                if abs(edx) > ew/2 + 45*s:
                    continue
                etop, ebot = ey - eh/2, ey + eh/2
                if et != "xbox" and vy_up <= 0 and pbot <= etop + 12*s:
                    continue                                  # 正在往下落、脚在它上面：可以踩
                side = pbot > etop + 12*s and ptop < ebot + 10*s
                rise = vy_up > 0 and ebot <= ptop and (ptop - ebot) < min(vy_up*vy_up/(2*g_px), 320*s) + 25*s
                if rise and not side and cfg["shoot"] and et in ("clown", "jester", "crow") and (ptop - ebot) > 90*s \
                        and abs(edx) < ew/2 + 15*s:
                    # 正上方、还有一段距离：不躲，直接扔飞刀把它打掉
                    if t - last_shot > 0.2:
                        key_tap_async(K["up"], t); last_shot = t
                    continue
                if side or rise:
                    if threat is None or abs(edx) < abs(threat): threat = edx
                    if ethreat is None or abs(edx) < abs(ethreat): ethreat = edx
            # 正在往下落，脚下不远处就是刺：往离刺远的一边躲
            if threat is None and vy_up <= 0:
                g_e = cfg["gravity"] * s * cfg.get("timescale", 1.0) ** 2
                tau_e = cfg.get("htau", 0.167)
                for sx0, sx1, stop in SPIKES:
                    d_e = stop - player[1]
                    if 0 <= d_e < 130*s:
                        # 按现在的速度滑过去，落到这个高度时会在哪；脚的判定半宽约 26px
                        t_e = (vy_up + np.sqrt(vy_up*vy_up + 2*g_e*d_e)) / g_e
                        xp_e = player[0] + PHYS["vx"] * tau_e * (1.0 - np.exp(-t_e / tau_e))
                        lo_e, hi_e = sx0 - 26*s, sx1 + 26*s
                        if lo_e < xp_e < hi_e:
                            threat = 1.0 if (xp_e - lo_e) < (hi_e - xp_e) else -1.0   # threat>=0 往左躲：离左边出口近就往左
                            break
            mode = ""
            if ethreat is not None:
                # 敌人躲避方向迟滞：已在躲且威胁没明显换边时，保持原方向
                # （乌鸦贴脸时识别抖动会让 edx 符号来回翻，不加迟滞就原地抖、被追上）
                dodge_want = 1 if ethreat >= 0 else -1
                if DODGE_DIR[0] != 0 and dodge_want != DODGE_DIR[0] and abs(ethreat) < 45*s:
                    dodge_want = DODGE_DIR[0]
                DODGE_DIR[0] = dodge_want
                threat = float(dodge_want)  # 沿用下面 threat>=0 往左躲的约定
            else:
                DODGE_DIR[0] = 0
            if threat is not None:
                mode = "躲"
                if threat >= 0: hold("right", False); hold("left", True)
                else: hold("left", False); hold("right", True)
            elif stuck and PILLARS:
                # 脱困：主动去蹭最近弹簧柱的侧面（碰到就往上弹），打破原地弹跳死循环。
                # 躲避（threat）分支在前，优先级不变；弹起开始爬升后 stuck 自动解除。
                _pl0, _pl1 = min(PILLARS, key=lambda p: abs(wrap_dx(player[0], (p[0] + p[1]) / 2, col)))[:2]
                _pdx = wrap_dx(player[0], (_pl0 + _pl1) / 2, col)
                mode = "柱"
                if _pdx > 30 * s:
                    hold("left", False); hold("right", True)
                elif _pdx < -30 * s:
                    hold("right", False); hold("left", True)
                else:
                    release_all()
            elif tgt is None:
                _fb = [p for p in plats if "!" not in p[3]] or plats
                if _fb:
                    # 无候选兜底：一般是掉到所有平台下方（下落时脚上方平台全被过滤）。
                    # release_all 等于松手等死；改为朝最近平台的横向位置靠拢——
                    # 万一中途弹起（复跳/弹簧），横向已对准才有机会落回去。
                    # 躲避（threat）分支在前，这里只处理无威胁 + 无目标的情况。
                    _fx0, _fx1 = min(_fb, key=lambda p: abs(wrap_dx(player[0], (p[0] + p[1]) / 2, col)))[:2]
                    _fdx = wrap_dx(player[0], (_fx0 + _fx1) / 2, col)
                    mode = "寻"
                    if _fdx > 30 * s:
                        hold("left", False); hold("right", True)
                    elif _fdx < -30 * s:
                        hold("right", False); hold("left", True)
                    else:
                        release_all()
                else:
                    release_all()
            else:
                prev_target = tgt
                # 横向是一阶系统：现在松手，落地那一刻会滑到哪？落在落脚区间里就松手，不够就按住，冲过头就反向
                vx_ = PHYS["vx"]; tau_ = cfg.get("htau", 0.167); L_ = cfg.get("latency", 0.03)
                if len(tgt) >= 9:
                    ra_, rb_, Tl_ = tgt[6], tgt[7], tgt[8]
                else:
                    ra_ = rb_ = tgt[4]; Tl_ = 1.0
                Tc_ = max(0.0, min(Tl_, 1.5) - L_)
                xc_ = vx_ * L_ + vx_ * tau_ * (1.0 - np.exp(-Tc_ / tau_))
                narrow_t = ("~" in tgt[3]) or tgt[3][0] == "p" or tgt[3] == "j"
                c_ = (ra_ + rb_) / 2
                hw_ = max((rb_ - ra_) / 2, (6*s) if narrow_t else cfg["deadzone"] * s)
                if xc_ < c_ - hw_:
                    hold("left", False); hold("right", True)
                elif xc_ > c_ + hw_:
                    hold("right", False); hold("left", True)
                else:
                    release_all()

            vy_last[0] = vy_up; tgt_last[0] = tgt
            act_last[0] = ("→" if held["right"] else ("←" if held["left"] else "·")) + mode
            tele.append((round(t, 3), round(player[0]), round(player[1]), round(vy_up), round(PHYS["vx"]),
                         "" if tgt is None else tgt[0], "" if tgt is None else tgt[1], "" if tgt is None else tgt[2],
                         "" if tgt is None else tgt[3], "" if tgt is None else round(tgt[4]),
                         "" if tgt is None or len(tgt) < 6 else round(tgt[5]),
                         int(held["left"]), int(held["right"]), mode or "", len(plats), len(enemies), int(stuck),
                         round(getattr(vt, "total_scroll", 0.0)),
                         "|".join(f"{c[0]}:{c[1]}-{c[2]}@{c[3]}{c[4]}:dx{c[5]}:r{c[6]}b{c[7]}" for c in sorted(DBG)[:5])))
            if len(tele) > 2400: del tele[:len(tele) - 2400]
            if t - tele_flush[1] > 0.5:
                tele_flush[1] = t
                try:
                    an = cv2.resize(img, None, fx=0.5, fy=0.5)
                    for x0_, x1_, top_, k_ in plats:
                        c_ = (0, 200, 255) if "~" in k_ else ((255, 0, 255) if "!" in k_ else (0, 255, 255))
                        cv2.rectangle(an, (int(x0_/2), int(top_/2)), (int(x1_/2), int(top_/2) + 3), c_, 1)
                    for sx0, sx1, stop in SPIKES:
                        cv2.rectangle(an, (int(sx0/2), int(stop/2) - 8), (int(sx1/2), int(stop/2)), (255, 0, 255), 1)
                    for e in enemies:
                        cv2.rectangle(an, (int((e[0]-e[2]/2)/2), int((e[1]-e[3]/2)/2)), (int((e[0]+e[2]/2)/2), int((e[1]+e[3]/2)/2)), (0, 0, 255), 1)
                    if tgt is not None:
                        cv2.rectangle(an, (int(tgt[0]/2), int(tgt[2]/2) - 2), (int(tgt[1]/2), int(tgt[2]/2) + 5), (0, 255, 0), 2)
                    cv2.circle(an, (int(player[0]/2), int(player[1]/2)), 3, (255, 0, 255), -1)
                    cv2.putText(an, (("L" if held["left"] else "") + ("R" if held["right"] else "") + mode), (5, 40), 0, 0.5, (0, 0, 255), 1)
                    io_submit(lambda an=an, p_=os.path.join(LIVE_F, f"{t:.3f}.jpg"): cv2.imwrite(p_, an, [cv2.IMWRITE_JPEG_QUALITY, 80]))
                except Exception:
                    pass
            if t - tele_flush[0] > 10:
                tele_flush[0] = t; io_submit(lambda now_=t, tl_=list(tele): live_flush(now_, tl_))
            if t - raw_dump[0] > 3.0:             # 每 3 秒存一张原始全分辨率画面（无损），用来调识别
                raw_dump[0] = t
                try:
                    RAW = os.path.join(LIVE, "raw"); os.makedirs(RAW, exist_ok=True)
                    def _dump_raw(im_=img, p_=os.path.join(RAW, f"{t:.3f}.png"), RAW=RAW):
                        cv2.imwrite(p_, im_, [cv2.IMWRITE_PNG_COMPRESSION, 1])
                        for fn in sorted(os.listdir(RAW))[:-12]:
                            os.remove(os.path.join(RAW, fn))
                    io_submit(_dump_raw)
                except Exception:
                    pass
            if t - last_log > 1.0:
                act = "→" if held["right"] else ("←" if held["left"] else "·")
                log(f"[a={0 if PHYS['a'] is None else PHYS['a']/s:.0f} vmax={0 if PHYS['vmax'] is None else PHYS['vmax']/s:.0f}] 角色({player[0]:.0f},{player[1]:.0f}) vy={vy_up:5.0f} 平台{len(plats):2d} 敌人{len(enemies)} 目标dx={'无' if tgt is None else round(tgt[4])} 按键{act}{mode}")
                last_log = t

            # 头顶有敌人：射击
            if cfg["shoot"] and enemies and t - last_shot > 0.25:
                for ex, ey, ew, eh, et in enemies + moving:          # 包括按速度预测的位置（提前量）
                    if et != "balloon" and ey + eh/2 < player[1] - 60*s and player[1] - ey < 680*s and abs(wrap_dx(player[0], ex, col)) < ew/2 + 15*s:
                        key_tap_async(K["up"], t); last_shot = t; break

            fps_n += 1
            if t - fps_t > 5:
                print(f"{fps_n/(t-fps_t):.0f} fps | 平台 {len(plats)} 敌人 {len(enemies)} | vy {vy_up:.0f}"); fps_t, fps_n = t, 0
            time.sleep(0.001)
          except Exception:
            import traceback; log("出错：" + traceback.format_exc()); release_all(); time.sleep(0.5)
    release_all(); flush_taps(1e18); log("退出")
    if st.get("reload"):
        sys.exit(3)

if __name__ == "__main__":
    main()
