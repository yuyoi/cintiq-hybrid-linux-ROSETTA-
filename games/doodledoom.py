#!/usr/bin/env python3
"""DOODLE DOOM (metal edition) - an endless zombie-doodle horde in a steel maze, for the Cintiq tablet.

Start with a pistol; tap / pen-tap a zombie to shoot it. Kills earn points: walk up to a weapon drawn on a wall
and hit BUY (shotgun 500, flying-V 1500; buying again refills ammo for half). RELOAD button or rocker centre reloads.
Rocker ring: up = walk, down = back off, left / right = turn (held keys, via the touch bridge's game-key mode).
Keyboard: arrows / WASD, space = shoot the middle, R = reload, Esc = quit.
Every texture, monster and the guitar are drawn by this file; no game data is needed.
"""
import atexit, collections, fcntl, math, mmap, os, random, struct, time
import numpy as np
import pygame

RW, RH = 320, 180                    # the 3-D view is rendered at this size, then scaled up
FOV = 0.66
# Round arena: a safe-ish room in the middle, three ring corridors around it, doors cut through each ring.
# The further out you go the nastier the walls, the zombies come from out there, and the better the wall weapons.
N = 33
C = N // 2
rnd = random.Random()
GRID = np.zeros((N, N), np.int32)
_yy, _xx = np.mgrid[0:N, 0:N]
_dist = np.hypot(_xx - C, _yy - C); _ang = np.arctan2(_yy - C, _xx - C)
for R, mat, doors, off in ((4.5, 1, 4, 0.4), (8.5, 2, 6, 0.0), (12.5, 3, 8, 0.2)):
    ring = np.abs(_dist - R) < 0.75
    door = np.zeros_like(ring)
    for k in range(doors):
        d = np.abs((_ang - (off + 2 * math.pi * k / doors) + math.pi) % (2 * math.pi) - math.pi)
        door |= d < 1.0 / R                                   # about two cells wide
    GRID[ring & ~door] = mat
GRID[_dist >= 15.4] = 4                                        # outer wall: furnace grates
for R, n_, off in ((6.5, 3, 0.5), (10.5, 5, 0.9), (14.0, 7, 0.3)):  # pillars to hide behind
    for k in range(n_):
        a_ = off + 2 * math.pi * k / n_
        GRID[int(round(C + R * math.sin(a_))), int(round(C + R * math.cos(a_)))] = 1 + k % 3
GRID[C - 1:C + 2, C - 1:C + 2] = 0


def _wall_spot(mat, angle):
    """A wall cell of this material near the angle, with free floor on its inner side (where you stand to buy)."""
    best = None
    for y in range(N):
        for x in range(N):
            if GRID[y, x] != mat or x in (0, N - 1) or y in (0, N - 1):
                continue
            inner = min(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)), key=lambda c: _dist[c[1], c[0]])
            if GRID[inner[1], inner[0]] != 0:
                continue
            d = abs((_ang[y, x] - angle + math.pi) % (2 * math.pi) - math.pi)
            if best is None or d < best[0]:
                best = (d, x, y)
    return best[1], best[2]


WEAPONS = {
    'pistol':  dict(name='PISTOL',     mag=8,  dmg=1, reload=1.0, radius=0.6, chain=0, multi=False, price=0,    splash=0),
    'shotgun': dict(name='SHOTGUN',    mag=5,  dmg=3, reload=1.7, radius=1.5, chain=0, multi=True,  price=500,  splash=0),
    'flyingv': dict(name='FLYING-V',   mag=12, dmg=2, reload=1.3, radius=0.8, chain=3, multi=False, price=1500, splash=0),
    'cannon':  dict(name='HELLCANNON', mag=4,  dmg=5, reload=2.2, radius=0.9, chain=0, multi=False, price=3000, splash=2.6),
}
WALLBUY = {_wall_spot(2, -math.pi / 2): 'shotgun', _wall_spot(3, math.pi / 2): 'flyingv', _wall_spot(4, math.pi): 'cannon'}
for (wx, wy), wid in WALLBUY.items():
    GRID[wy, wx] = {'shotgun': 5, 'flyingv': 6, 'cannon': 7}[wid]
FREE = [(x, y) for y in range(N) for x in range(N) if GRID[y, x] == 0]
WORDS = ['BRUTAL', 'SHRED', '\\m/', 'RIFF', 'METAL', 'GNARLY', 'HEADBANG', 'SOLO', 'DOOM', 'CRUSHED']
BEST_FILE = '/root/.doodledoom_best'
GAMEKEYS = '/tmp/gamekeys.txt'       # tells the touch bridge to pass hardware keys through as held keys
LOG = open('/tmp/doodledoom.log', 'w')


def log(msg):
    LOG.write('%s %s\n' % (time.strftime('%H:%M:%S'), msg)); LOG.flush()


# ---------------------------------------------------------------- procedural art
def stroke(img, pts, col, th=1):
    h, w = img.shape[:2]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) * 2 + 1
        xs = np.linspace(x0, x1, n); ys = np.linspace(y0, y1, n)
        for dx in range(-(th // 2), th - th // 2):
            for dy in range(-(th // 2), th - th // 2):
                img[np.clip((ys + dy).astype(int), 0, h - 1), np.clip((xs + dx).astype(int), 0, w - 1)] = col


def blur(a, k=3):
    out = a.copy()
    for _ in range(k):
        out = (out + np.roll(out, 1, 0) + np.roll(out, -1, 0) + np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 5
    return out


def rivet(t, x, y, r=3):
    yy, xx = np.mgrid[0:64, 0:64]
    d = (xx - x) ** 2 + (yy - y) ** 2
    t[d <= r * r] = (150, 150, 158)
    t[(d <= r * r) & (xx < x) & (yy < y)] = (215, 215, 222)
    t[(d <= r * r) & (xx > x) & (yy > y)] = (70, 70, 78)


def skull(t, cx, cy, col=(225, 220, 205)):
    yy, xx = np.mgrid[0:64, 0:64]
    t[((xx - cx) / 11.0) ** 2 + ((yy - cy) / 10.0) ** 2 <= 1] = col
    t[(abs(xx - cx) <= 6) & (yy >= cy + 6) & (yy <= cy + 13)] = col
    for ex in (cx - 5, cx + 5):
        t[(xx - ex) ** 2 + (yy - cy - 1) ** 2 <= 8] = (20, 10, 10)
    t[(abs(xx - cx) <= 1) & (yy >= cy + 5) & (yy <= cy + 7)] = (20, 10, 10)
    for tx in range(cx - 5, cx + 6, 3):
        t[cy + 10:cy + 13, tx] = (40, 30, 30)


def make_textures():
    r = np.random.RandomState(4)
    yy, xx = np.mgrid[0:64, 0:64]
    T = np.zeros((4, 64, 64, 3), np.uint8)
    # 0 riveted steel plate, brushed vertically
    n = blur(r.rand(64, 64), 1) * 0.5 + np.repeat(r.rand(1, 64), 64, 0) * 0.5
    t = (np.stack([n * 50 + 100, n * 50 + 104, n * 50 + 112], -1)).astype(np.uint8)
    t[(xx % 32 < 2) | (yy % 32 < 2)] = (45, 45, 52)
    for cx in (6, 26, 38, 58):
        for cy in (6, 26, 38, 58):
            rivet(t, cx, cy)
    T[0] = t
    # 1 rusty iron with a skull stencil
    n = blur(r.rand(64, 64), 4); m = blur(r.rand(64, 64), 2)
    t = np.stack([90 + n * 120 + m * 40, 50 + n * 60 + m * 15, 30 + n * 25], -1)
    t = np.clip(t, 0, 255).astype(np.uint8)
    t[(yy % 64 < 2)] = (40, 25, 20)
    skull(t, 32, 26, (200, 190, 170))
    T[1] = t
    # 2 diamond plate
    t = np.full((64, 64, 3), (120, 122, 130), np.uint8)
    d = ((xx + yy) % 16 < 3) & ((xx - yy) % 16 < 9) & (yy % 8 < 6)
    t[d] = (190, 192, 200); t[np.roll(d, 1, 0) & ~d] = (70, 72, 80)
    t[(xx % 64 < 2) | (yy % 64 < 2)] = (50, 50, 58)
    T[2] = t
    # 3 furnace grate: dark steel with glowing slots
    t = np.full((64, 64, 3), (38, 36, 40), np.uint8)
    slot = (yy % 12 >= 4) & (yy % 12 < 8) & (xx > 6) & (xx < 58)
    glow = blur(slot.astype(float), 2)
    t = np.clip(t + np.stack([glow * 255, glow * 110, glow * 20], -1), 0, 255).astype(np.uint8)
    t[slot] = (255, 150, 40)
    for cx in (4, 60):
        for cy in (4, 60):
            rivet(t, cx, cy, 2)
    T[3] = t
    T = np.concatenate([T, np.stack([wall_weapon('shotgun'), wall_weapon('flyingv'), wall_weapon('cannon')])])
    return T


SEG = {'0': 'abcdef', '1': 'bc', '2': 'abged', '3': 'abgcd', '4': 'fgbc', '5': 'afgcd', '6': 'afgedc', '7': 'abc', '8': 'abcdefg', '9': 'abfgcd'}


def digits(t, text, x, y, col, w=6, h=10):
    for ch in text:
        for sg in SEG.get(ch, ''):
            a = {'a': [(0, 0), (w, 0)], 'b': [(w, 0), (w, h // 2)], 'c': [(w, h // 2), (w, h)], 'd': [(0, h), (w, h)],
                 'e': [(0, h // 2), (0, h)], 'f': [(0, 0), (0, h // 2)], 'g': [(0, h // 2), (w, h // 2)]}[sg]
            stroke(t, [(x + a[0][0], y + a[0][1]), (x + a[1][0], y + a[1][1])], col, 1)
        x += w + 4


def wall_weapon(wid):
    """Dark steel panel with the weapon chalked on it and its price, Zombies style."""
    yy, xx = np.mgrid[0:64, 0:64]
    t = np.full((64, 64, 3), (52, 50, 56), np.uint8)
    t[(xx % 64 < 2) | (yy % 64 < 2)] = (30, 30, 34)
    c = (235, 235, 225)
    if wid == 'shotgun':
        stroke(t, [(8, 24), (50, 24), (52, 28), (22, 28), (14, 34), (8, 34), (8, 24)], c, 1)
        stroke(t, [(30, 28), (36, 32), (44, 32)], c, 1)
        digits(t, '500', 18, 42, (255, 200, 60))
    elif wid == 'cannon':
        stroke(t, [(6, 22), (52, 22), (52, 34), (6, 34), (6, 22)], c, 1)
        stroke(t, [(52, 20), (58, 18), (58, 38), (52, 36)], c, 1)
        stroke(t, [(22, 34), (20, 42), (26, 42), (28, 34)], c, 1)
        stroke(t, [(2, 26), (6, 26)], (255, 120, 40), 1); stroke(t, [(1, 30), (6, 30)], (255, 120, 40), 1)
        digits(t, '3000', 12, 48, (255, 200, 60))
    else:
        stroke(t, [(10, 40), (24, 30), (30, 36), (20, 48), (16, 40)], c, 1)
        stroke(t, [(24, 33), (54, 10)], c, 1)
        stroke(t, [(52, 8), (58, 6), (58, 12)], c, 1)
        digits(t, '1500', 12, 48, (255, 200, 60))
    for cx in (5, 59):
        for cy in (5, 59):
            rivet(t, cx, cy, 2)
    return t


S = 96                               # zombie sprite size (square, feet at the bottom)


def poly(img, pts, col):
    """Fill a polygon (even-odd rule) on an SxSx4 image."""
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w] + 0.5
    inside = np.zeros((h, w), bool)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        if y0 == y1:
            continue
        cond = ((y0 <= yy) & (yy < y1)) | ((y1 <= yy) & (yy < y0))
        xc = x0 + (yy - y0) * (x1 - x0) / (y1 - y0)
        inside ^= cond & (xx < xc)
    img[inside] = col


def ell(img, cx, cy, rx, ry, col):
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    img[((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1] = col


def make_zombie(kind, frame):
    """Front view of a shambling zombie. kind 0 = rotting shambler, 1 = horned demon brute, 2 = skeleton."""
    img = np.zeros((S, S, 4), np.uint8)
    r = np.random.RandomState(kind * 10 + 3)
    skin = [(112, 140, 96, 255), (150, 92, 88, 255), (222, 216, 196, 255), (176, 182, 190, 255)][kind]
    dark = tuple(int(c * 0.55) for c in skin[:3]) + (255,)
    shirt = [(150, 148, 136, 255), (60, 40, 36, 255), (60, 55, 50, 255), (52, 54, 66, 255)][kind]
    pants = [(52, 56, 78, 255), (45, 32, 28, 255), (40, 38, 44, 255), (34, 34, 40, 255)][kind]
    blood = (120, 8, 8, 255)
    sway = 3 if frame else -3
    wide = 4 if kind == 1 else 0
    # legs: a stiff one and a dragging one, swapping each frame
    lx, rx_ = (38, 58)
    lk = (36, 80) if frame else (39, 80); rk = (62, 79) if not frame else (59, 81)
    lf = (34, 94) if frame else (40, 94); rf = (64, 92) if not frame else (58, 94)
    stroke(img, [(lx, 64), lk, lf], pants, 9 if kind != 2 else 5)
    stroke(img, [(rx_, 64), rk, rf], pants, 9 if kind != 2 else 5)
    for f in (lf, rf):
        ell(img, f[0], f[1] - 1, 6, 3, (25, 20, 20, 255))
    if kind == 2:                                                       # bony shins showing
        stroke(img, [(lk[0], lk[1]), (lf[0], lf[1] - 3)], skin, 3)
        stroke(img, [(rk[0], rk[1]), (rf[0], rf[1] - 3)], skin, 3)
    # torso
    body = [(30 - wide, 36), (66 + wide, 36), (62 + wide // 2, 66), (34 - wide // 2, 66)]
    poly(img, body, shirt if kind != 1 else skin)
    if kind in (0, 3):                                                  # torn shirt, ribs through the rips, blood
        poly(img, [(40, 44), (50, 41), (54, 52), (44, 56)], dark)
        for yy_ in (45, 49, 53):
            stroke(img, [(42, yy_), (51, yy_ - 2)], (215, 205, 185, 255), 1)
        poly(img, [(34, 60), (40, 58), (38, 66), (34, 66)], (100, 98, 90, 255))
        for _ in range(5):
            ell(img, r.randint(34, 62), r.randint(38, 64), r.randint(2, 4), r.randint(2, 5), blood)
    else:                                                               # open ribcage
        poly(img, [(38, 40), (58, 40), (56, 60), (40, 60)], (35, 12, 12, 255))
        for yy_ in range(42, 60, 4):
            stroke(img, [(39, yy_ + 2), (48, yy_), (57, yy_ + 2)], (225, 215, 195, 255), 2)
        stroke(img, [(48, 38), (48, 62)], (225, 215, 195, 255), 2)
    stroke(img, [(30 - wide, 64), (66 + wide, 64)], (30, 20, 20, 255), 2)          # belt line
    # arms reaching forward, clawed hands
    for s_, sx in ((-1, 31 - wide), (1, 65 + wide)):
        elbow = (sx + s_ * 12, 46 + s_ * sway)
        hand = (sx + s_ * 8, 32 + s_ * sway // 2)
        stroke(img, [(sx, 40), elbow], shirt if kind == 0 else skin, 7)
        stroke(img, [elbow, hand], skin, 6)
        ell(img, hand[0], hand[1], 4, 4, skin)
        for k in (-1, 0, 1):
            stroke(img, [hand, (hand[0] + s_ * 2 + k * 3, hand[1] - 7)], (35, 25, 25, 255), 1)
    # neck and head
    stroke(img, [(48, 30), (48, 37)], dark if kind != 2 else skin, 7)
    tilt = 2 if frame else -2
    hx, hy = 48 + tilt, 21
    ell(img, hx, hy, 11 + wide // 2, 13, skin)
    if kind == 1:                                                       # horns
        for s_ in (-1, 1):
            stroke(img, [(hx + s_ * 8, hy - 9), (hx + s_ * 14, hy - 15), (hx + s_ * 12, hy - 20)], (232, 226, 210, 255), 3)
    if kind in (0, 3):                                                  # rot patches and scraggly hair
        ell(img, hx + 6, hy - 6, 4, 3, dark); ell(img, hx - 7, hy + 4, 3, 4, dark)
        for k in range(-8, 9, 3):
            stroke(img, [(hx + k, hy - 12), (hx + k + 1, hy - 16)], (40, 36, 30, 255), 1)
    for ex in (hx - 5, hx + 5):                                         # sunken sockets, red pin-point eyes
        ell(img, ex, hy - 1, 3.6, 3.2, (18, 8, 8, 255))
        ell(img, ex, hy - 1, 1.3, 1.3, (255, 40, 20, 255))
    if kind == 2:                                                       # skull nose
        poly(img, [(hx - 2, hy + 4), (hx + 2, hy + 4), (hx, hy + 1)], (18, 8, 8, 255))
    ell(img, hx, hy + 8, 5.5, 3.5 + frame, (30, 0, 0, 255))              # gaping mouth
    for tx in range(hx - 4, hx + 5, 2):
        img[hy + 5:hy + 7, tx] = (235, 230, 210, 255)
        img[hy + 10 + frame:hy + 12 + frame, tx] = (235, 230, 210, 255)
    if kind != 2:
        stroke(img, [(hx + 2, hy + 11), (hx + 3, hy + 20), (hx + 2, hy + 26)], blood, 2)   # drool of blood
    # light from the top left: darken the right side, then a dark sketch outline
    a = img[..., 3] > 0
    xs = np.arange(S)[None, :].repeat(S, 0)
    sh = a & (xs > 50)
    img[sh, :3] = (img[sh, :3] * 0.78).astype(np.uint8)
    grow = a | np.roll(a, 1, 0) | np.roll(a, -1, 0) | np.roll(a, 1, 1) | np.roll(a, -1, 1)
    img[grow & ~a] = (12, 8, 8, 255)
    return img


TEX = make_textures()
SPR = [[make_zombie(k, f) for f in (0, 1)] for k in range(4)]
BG = np.zeros((RH, RW, 3), np.uint8)
for y in range(RH):
    if y < RH // 2:
        k = y / (RH / 2); BG[y] = (int(25 + 90 * k), int(8 + 20 * k), int(10 + 8 * k))      # hellfire glow
    else:
        k = (y - RH / 2) / (RH / 2); BG[y] = (int(20 + 45 * k), int(20 + 45 * k), int(26 + 48 * k))
        if y % 6 == 0:
            BG[y] = BG[y] // 2                                                              # grating
CAM = 2 * np.arange(RW) / RW - 1


# ---------------------------------------------------------------- world
class Zombie:
    # kind: 0 shambler, 1 horned brute (tough, slow, hits hard), 2 skeleton, 3 runner (small, fast, weak)
    def __init__(s, x, y, speed, wave):
        s.x, s.y = x, y
        s.kind = 3 if wave >= 2 and rnd.random() < 0.3 else rnd.randrange(3)
        s.hp, mul, s.dmg, s.size = {0: (2, 1.0, 12, 0.95), 1: (3, 0.8, 20, 1.0), 2: (2, 1.0, 12, 0.95), 3: (1, 1.75, 5, 0.6)}[s.kind]
        s.speed = speed * mul
        s.phase = rnd.uniform(0, 6.28); s.dying = -1.0; s.dead = False


def free(x, y):
    return 0 <= int(x) < N and 0 <= int(y) < N and GRID[int(y), int(x)] == 0


def new_game():
    try: best = int(open(BEST_FILE).read())
    except Exception: best = 0
    return {'px': C + 0.5, 'py': C + 0.5, 'a': 0.0, 'hp': 100.0, 'zs': [], 'kills': 0, 'wave': 1, 'best': best,
            'over': False, 'hurt': 0.0, 'next_spawn': time.time() + 1.5, 'flow': None, 'flow_t': 0.0,
            'weapon': 'pistol', 'ammo': WEAPONS['pistol']['mag'], 'reload_until': 0.0, 'points': 0}


def flow_field(g):
    """BFS distance from the player's cell, so the horde finds its way through the maze."""
    dist = np.full((N, N), 999, np.int32)
    sx, sy = int(g['px']), int(g['py']); dist[sy, sx] = 0
    q = collections.deque([(sx, sy)])
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if GRID[ny, nx] == 0 and dist[ny, nx] == 999:
                dist[ny, nx] = dist[y, x] + 1; q.append((nx, ny))
    return dist


def cast(px, py, dx, dy, plx, ply):
    rdx = dx + plx * CAM; rdy = dy + ply * CAM
    mx = np.full(RW, int(px)); my = np.full(RW, int(py))
    ddx = np.where(rdx == 0, 1e30, np.abs(1 / np.where(rdx == 0, 1, rdx)))
    ddy = np.where(rdy == 0, 1e30, np.abs(1 / np.where(rdy == 0, 1, rdy)))
    sx = np.where(rdx < 0, -1, 1); sy = np.where(rdy < 0, -1, 1)
    sdx = np.where(rdx < 0, (px - mx) * ddx, (mx + 1 - px) * ddx)
    sdy = np.where(rdy < 0, (py - my) * ddy, (my + 1 - py) * ddy)
    hit = np.zeros(RW, bool); side = np.zeros(RW, np.int32)
    for _ in range(90):
        act = ~hit
        gx = act & (sdx < sdy); gy = act & ~(sdx < sdy)
        sdx[gx] += ddx[gx]; mx[gx] += sx[gx]; side[gx] = 0
        sdy[gy] += ddy[gy]; my[gy] += sy[gy]; side[gy] = 1
        np.clip(mx, 0, N - 1, out=mx); np.clip(my, 0, N - 1, out=my)
        hit |= GRID[my, mx] > 0
        if hit.all():
            break
    perp = np.maximum(np.where(side == 0, sdx - ddx, sdy - ddy), 0.05)
    wx = np.where(side == 0, py + perp * rdy, px + perp * rdx); wx -= np.floor(wx)
    tx = (wx * 64).astype(np.int32)
    tx = np.where(((side == 0) & (rdx > 0)) | ((side == 1) & (rdy < 0)), 63 - tx, tx)
    return perp, side, GRID[my, mx] - 1, np.clip(tx, 0, 63)


def render(g, now):
    px, py, a = g['px'], g['py'], g['a']
    dx, dy = math.cos(a), math.sin(a); plx, ply = -dy * FOV, dx * FOV
    perp, side, wt, tx = cast(px, py, dx, dy, plx, ply)
    lh = RH / perp; top = RH / 2 - lh / 2
    ty = (np.arange(RH)[:, None] - top[None, :]) / lh[None, :] * 64
    mask = (ty >= 0) & (ty < 64)
    pix = TEX[wt[None, :], np.clip(ty.astype(np.int32), 0, 63), tx[None, :]].astype(np.float32)
    shade = np.where(side == 1, 0.78, 1.0) * np.clip(1.3 - perp / 9, 0.25, 1.0)
    pix *= shade[None, :, None]
    pix[..., 0] += 25 * np.clip(1 - perp / 6, 0, 1)[None, :]                 # red light on nearby walls
    frame = np.where(mask[..., None], np.clip(pix, 0, 255).astype(np.uint8), BG)
    hits = []
    inv = 1.0 / (plx * dy - dx * ply)
    order = sorted((z for z in g['zs'] if not z.dead), key=lambda z: -((z.x - px) ** 2 + (z.y - py) ** 2))
    for z in order:
        sx, sy = z.x - px, z.y - py
        tX = inv * (dy * sx - dx * sy); tY = inv * (-ply * sx + plx * sy)
        if tY <= 0.15:
            continue
        scale = z.size * (1.0 if z.dying < 0 else max(0.05, 1 - (now - z.dying) / 0.35))
        h = int(RH / tY * scale)
        if h < 2:
            continue
        cx = int(RW / 2 * (1 + tX / tY) + math.sin(now * 2.6 + z.phase) * h * 0.05)      # shambling sway
        bottom = int(RH / 2 + RH / tY / 2) - int(abs(math.sin(now * 2.6 + z.phase)) * h * 0.03)
        x0, y0 = cx - h // 2, bottom - h
        cols = np.arange(max(0, x0), min(RW, x0 + h)); rows = np.arange(max(0, y0), min(RH, y0 + h))
        if not len(cols) or not len(rows):
            continue
        vis = tY < perp[cols]
        if not vis.any():
            continue
        spr = SPR[z.kind][int(now * 2.6 + z.phase) % 2]
        s = spr[(rows - y0) * S // h][:, (cols - x0) * S // h]
        m = (s[..., 3] > 0) & vis[None, :]
        reg = frame[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
        lit = s[..., :3].astype(np.float32) * min(1.0, max(0.35, 1.3 - tY / 9))
        if z.dying >= 0:
            lit[..., 0] = 255                                                  # flash red as it pops
        reg[m] = lit[m].astype(np.uint8)
        hits.append((tY, x0, y0, h, z))
    return frame, hits


def step(g, dt, mv, turn, now):
    a = g['a'] + turn * 2.8 * dt; g['a'] = a
    if mv:
        nx = g['px'] + math.cos(a) * mv * 3.3 * dt; ny = g['py'] + math.sin(a) * mv * 3.3 * dt
        if free(nx + 0.22 * math.copysign(1, nx - g['px']), g['py']): g['px'] = nx
        if free(g['px'], ny + 0.22 * math.copysign(1, ny - g['py'])): g['py'] = ny
    if g['flow'] is None or now - g['flow_t'] > 0.4:
        g['flow'] = flow_field(g); g['flow_t'] = now
    alive = [z for z in g['zs'] if z.dying < 0 and not z.dead]
    cap = min(18, 5 + 2 * g['wave'])
    if now > g['next_spawn'] and len(alive) < cap:                         # the horde never stops
        far = [c for c in FREE if 9 <= g['flow'][c[1], c[0]] < 999]
        if far:
            cx, cy = rnd.choice(far)
            g['zs'].append(Zombie(cx + 0.5, cy + 0.5, min(1.8, 0.6 + 0.09 * g['wave']), g['wave']))
        g['next_spawn'] = now + max(0.45, 2.4 - 0.18 * g['wave'])
    F = g['flow']
    for z in g['zs']:
        if z.dead:
            continue
        if z.dying >= 0:
            if now - z.dying > 0.35: z.dead = True
            continue
        vx, vy = g['px'] - z.x, g['py'] - z.y; dist = math.hypot(vx, vy)
        if dist < 1.2:
            tx, ty = g['px'], g['py']
        else:                                                              # walk downhill on the flow field
            cx, cy = int(z.x), int(z.y)
            best = min(((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)), key=lambda c: F[c[1], c[0]])
            tx, ty = best[0] + 0.5, best[1] + 0.5
        mx, my = tx - z.x, ty - z.y; ml = math.hypot(mx, my) or 1
        sp = z.speed * dt
        if dist > 0.45:
            if free(z.x + mx / ml * sp, z.y): z.x += mx / ml * sp
            if free(z.x, z.y + my / ml * sp): z.y += my / ml * sp
        if dist < 0.65:
            g['hp'] -= z.dmg * dt; g['hurt'] = now
    g['zs'] = [z for z in g['zs'] if not z.dead]
    if g['reload_until'] and now >= g['reload_until']:
        g['ammo'] = WEAPONS[g['weapon']]['mag']; g['reload_until'] = 0.0
    if g['hp'] <= 0 and not g['over']:
        g['over'] = True
        if g['kills'] > g['best']:
            g['best'] = g['kills']
            try: open(BEST_FILE, 'w').write(str(g['kills']))
            except OSError: pass
        log('game over kills %d wave %d' % (g['kills'], g['wave']))


def wall_offer(g):
    """The wall weapon the player stands at and looks towards, if any."""
    for (wx, wy), wid in WALLBUY.items():
        vx, vy = wx + 0.5 - g['px'], wy + 0.5 - g['py']; dist = math.hypot(vx, vy)
        if dist < 1.7:
            diff = (math.atan2(vy, vx) - g['a'] + math.pi) % (2 * math.pi) - math.pi
            if abs(diff) < 1.0:
                return wid
    return None


# ---------------------------------------------------------------- main loop
class FBOut:
    """Write finished frames straight into the panel's framebuffer (native X only).

    Sending frames through X costs ~200 ms each here (no SysV shared memory on this Android kernel), so the game
    pauses the desktop pusher (same flag PC mode uses), keeps its X window only for input, and puts pixels on the
    visible framebuffer page itself. The pusher repaints the desktop when the game exits."""
    def __init__(s, screen):
        s.ok = False
        if not (os.path.exists('/tmp/native-x') and os.path.exists('/dev/graphics/fb0')):
            return
        if screen.get_bitsize() != 32:
            return
        fd = os.open('/dev/graphics/fb0', os.O_RDWR)
        b = bytearray(160); fcntl.ioctl(fd, 0x4600, b); v = struct.unpack('<40I', bytes(b))
        s.W, s.H = v[0], v[1]
        s.mm = mmap.mmap(fd, v[2] * v[3] * 4)
        s.page = np.frombuffer(s.mm, dtype=np.uint32).reshape(v[3], v[2])[s.H:2 * s.H, :s.W]
        try: s.rot = open('/root/rotation').read().strip()
        except OSError: s.rot = 'normal'
        rm = screen.get_masks()[0]
        s.swap = (rm == 0xff0000) != (v[8] == 16)                    # red byte position differs between X and fb
        s.alpha = np.uint32(0xff000000)
        open('/tmp/mirror.pause', 'w').close()
        atexit.register(lambda: os.path.exists('/tmp/mirror.pause') and not os.path.exists('/tmp/pcmode')
                        and os.remove('/tmp/mirror.pause'))
        s.ok = True
        log('direct framebuffer output, rotation %s swap %s' % (s.rot, s.swap))

    def push(s, screen, rects):
        px = pygame.surfarray.pixels2d(screen)                          # [x][y] view of the window surface
        a = px.T
        W, H = s.W, s.H
        for r in rects:
            r = r.clip(screen.get_rect())
            if not r.w or not r.h:
                continue
            sub = a[r.top:r.bottom, r.left:r.right]
            if s.swap:
                sub = ((sub & 0xff) << 16) | (sub & 0xff00) | ((sub >> 16) & 0xff)
            sub = sub | s.alpha
            if s.rot == 'CW':
                s.page[r.left:r.right, W - r.bottom:W - r.top] = sub.T[:, ::-1]
            elif s.rot == 'CCW':
                s.page[H - r.right:H - r.left, r.top:r.bottom] = sub.T[::-1, :]
            elif s.rot == 'UD':
                s.page[H - r.bottom:H - r.top, W - r.right:W - r.left] = sub[::-1, ::-1]
            else:
                s.page[r.top:r.bottom, r.left:r.right] = sub
        del px, a


_TXT = {}


def outlined(font, text, col, edge=(20, 0, 0)):
    """Text with a dark outline, cached: rendering text is slow on this CPU (no NEON in pygame)."""
    key = (id(font), text, col, edge)
    s = _TXT.get(key)
    if s is None:
        a = font.render(text, True, edge); b = font.render(text, True, col)
        s = pygame.Surface((a.get_width() + 4, a.get_height() + 4), pygame.SRCALPHA)
        for ox, oy in ((0, 0), (4, 0), (0, 4), (4, 4), (2, 0), (0, 2), (4, 2), (2, 4)):
            s.blit(a, (ox, oy))
        s.blit(b, (2, 2))
        if len(_TXT) > 400:
            _TXT.clear()
        _TXT[key] = s
    return s


def main():
    with open(GAMEKEYS, 'w') as f:                                          # rocker ring -> held arrow keys
        f.write('%d\n115 Up\n114 Down\n224 Left\n225 Right\n102 r\n217 r\n139 space\n' % os.getpid())
    atexit.register(lambda: os.path.exists(GAMEKEYS) and os.remove(GAMEKEYS))
    pygame.init()
    info = pygame.display.Info(); SW, SH = info.current_w, info.current_h
    disp = pygame.display.set_mode((SW, SH), pygame.FULLSCREEN)       # the window is kept for input
    screen = disp
    if os.path.exists('/tmp/native-x'):      # draw in the framebuffer's byte order (RGBX) so frames go out unconverted
        screen = pygame.Surface((SW, SH), 0, 32, (0xff, 0xff00, 0xff0000, 0))
    pygame.display.set_caption('DOODLE DOOM')
    portrait = SH > SW
    B = int(min(SW, SH) * 0.085)
    side = 0 if portrait else 3 * B + 30                                    # room for the arrow pad and RELOAD
    sc = max(1.0, min((SW - 2 * side - 20) / RW, (SH - 250) / RH))          # as big as the screen allows
    VW, VH = int(RW * sc), int(RH * sc)
    vx0 = (SW - VW) // 2; vy0 = 110 if portrait else max(80, (SH - VH - 100) // 2)
    view = pygame.Rect(vx0, vy0, VW, VH)
    hud = pygame.Rect(vx0, view.bottom + 8, VW, 90)
    if portrait: padx, pady = 30, hud.bottom + 40
    else: padx, pady = max(10, (vx0 - 3 * B) // 2), SH - 40 - 3 * B
    pads = {'up': pygame.Rect(padx + B, pady, B, B), 'left': pygame.Rect(padx, pady + B, B, B),
            'right': pygame.Rect(padx + 2 * B, pady + B, B, B), 'down': pygame.Rect(padx + B, pady + 2 * B, B, B)}
    padarea = pads['left'].union(pads['right']).union(pads['up']).union(pads['down']).inflate(8, 8)
    rl = int(B * 1.7)
    reload_btn = (pygame.Rect(SW - rl - 40, hud.bottom + 40, rl, rl) if portrait else
                  pygame.Rect(view.right + max(10, (SW - view.right - rl) // 2), SH - rl - 40, rl, rl))
    quit_btn = pygame.Rect(SW - 100, 16, 84, 84)
    buy_btn = pygame.Rect(view.centerx - 230, view.bottom - 100, 460, 84)
    huge = pygame.font.Font(None, 110); big = pygame.font.Font(None, 80); mid = pygame.font.Font(None, 54); small = pygame.font.Font(None, 40)
    surf = pygame.Surface((RW, RH)).convert(screen)
    scaled = pygame.Surface((VW, VH)).convert(screen)
    padsurf = {}
    for on in (False, True):
        s = pygame.Surface((B, B)).convert(screen); s.fill((150, 30, 20) if on else (52, 50, 58)); padsurf[on] = s
    g = new_game(); hits = []; floats = []; gibs = []; booms = []; bolt = None; flash = 0.0
    clock = pygame.time.Clock(); frames = 0; tlog = time.time(); prof = [0.0, 0.0, 0.0]
    log('screen %dx%d view %dx%d scale %.2f' % (SW, SH, VW, VH, sc))
    fbo = FBOut(screen)

    def show(rects):
        if fbo.ok: fbo.push(screen, rects)
        else: pygame.display.update(rects)

    def draw_static():
        screen.fill((14, 8, 10))
        pygame.draw.rect(screen, (90, 90, 100), view.inflate(16, 16), 7)
        pygame.draw.rect(screen, (200, 40, 20), view.inflate(4, 4), 2)
        t = outlined(big, 'DOODLE DOOM', (255, 120, 30))
        screen.blit(t, (view.x, view.y - t.get_height() - 10))
        pygame.draw.rect(screen, (170, 25, 20), quit_btn, border_radius=12)
        x = mid.render('X', True, (255, 255, 255)); screen.blit(x, x.get_rect(center=quit_btn.center))
        show([screen.get_rect()])

    def draw_pads(held):
        pygame.draw.rect(screen, (14, 8, 10), padarea)
        for k, r in pads.items():
            screen.blit(padsurf[held == k], r); pygame.draw.rect(screen, (150, 150, 160), r, 3)
            cx, cy, q = r.centerx, r.centery, r.w // 4
            tri = {'up': [(cx, cy - q), (cx - q, cy + q), (cx + q, cy + q)], 'down': [(cx, cy + q), (cx - q, cy - q), (cx + q, cy - q)],
                   'left': [(cx - q, cy), (cx + q, cy - q), (cx + q, cy + q)], 'right': [(cx + q, cy), (cx - q, cy - q), (cx - q, cy + q)]}[k]
            pygame.draw.polygon(screen, (235, 235, 240), tri)

    def reload():
        W = WEAPONS[g['weapon']]
        if not g['reload_until'] and g['ammo'] < W['mag']:
            g['reload_until'] = time.time() + W['reload']

    def buy(wid):
        W = WEAPONS[wid]; price = W['price'] if g['weapon'] != wid else W['price'] // 2
        if g['points'] < price:
            floats.append(['NEED %d' % price, buy_btn.centerx, buy_btn.top, time.time()]); return
        g['points'] -= price; g['weapon'] = wid; g['ammo'] = W['mag']; g['reload_until'] = 0.0
        floats.append([W['name'] + '!', view.centerx, view.centery, time.time()])

    def damage(z, n, pos):
        z.hp -= n; g['points'] += 10
        for _ in range(10):
            gibs.append([pos[0], pos[1], rnd.uniform(-320, 320), rnd.uniform(-420, -80), time.time(),
                         rnd.choice([(170, 20, 20), (120, 170, 100), (230, 225, 210), (60, 60, 70)])])
        if z.hp <= 0 and z.dying < 0:
            z.dying = time.time(); g['kills'] += 1; g['points'] += 60
            floats.append([rnd.choice(WORDS), pos[0], pos[1], time.time()])
            if g['kills'] % 10 == 0:
                g['wave'] += 1; g['hp'] = min(100, g['hp'] + 25)
                floats.append(['WAVE %d' % g['wave'], view.centerx, view.centery, time.time()])

    def shoot(pos):
        nonlocal bolt, flash
        W = WEAPONS[g['weapon']]
        if g['reload_until']:
            return
        if g['ammo'] <= 0:
            reload(); return
        g['ammo'] -= 1
        if g['ammo'] == 0:
            reload()                                                       # auto reload on the last round
        flash = time.time(); chain = []
        rx, ry = (pos[0] - vx0) / sc, (pos[1] - vy0) / sc
        for tY, x0, y0, h, z in sorted(hits, key=lambda t: t[0]):
            if z.dying >= 0 or z.dead:
                continue
            cx, cy = x0 + h / 2, y0 + h / 2
            r = W['radius'] * max(h, 26)                                   # small far-away zombies stay hittable
            if ((rx - cx) / (r * 0.6)) ** 2 + ((ry - cy) / (r * 0.95)) ** 2 <= 1:
                damage(z, W['dmg'], pos); chain.append((z, pos))
                if not W['multi']:
                    break
        if W['chain'] and chain:                                           # flying-V: the lightning jumps on
            z0 = chain[0][0]
            seen = {id(t[4]): (vx0 + (t[1] + t[3] / 2) * sc, vy0 + (t[2] + t[3] / 2) * sc) for t in hits}
            near = sorted((z for z in g['zs'] if z is not z0 and z.dying < 0 and math.hypot(z.x - z0.x, z.y - z0.y) < 3.5),
                          key=lambda z: math.hypot(z.x - z0.x, z.y - z0.y))[:W['chain']]
            for z in near:
                p2 = seen.get(id(z), pos)
                damage(z, W['dmg'], p2); chain.append((z, p2))
        if W['splash'] and chain:                                          # hellcannon: everything near the impact
            z0 = chain[0][0]
            for z in g['zs']:
                if z is not z0 and z.dying < 0 and math.hypot(z.x - z0.x, z.y - z0.y) < W['splash']:
                    damage(z, W['dmg'], pos)
        if W['splash']:
            booms.append((pos, time.time()))
        bolt = ([pos] + [c[1] for c in chain[1:]], time.time(), g['weapon'])

    def draw_weapon(now, moving):
        wid = g['weapon']; reloading = bool(g['reload_until'])
        left = g['reload_until'] - now if reloading else 0
        dip = 150 if reloading else 0
        if reloading and left < 0.25: dip = 150 * left / 0.25
        bob = math.sin(now * 9) * 5 if moving else 0
        hx, hy = view.right - VW // 4, view.bottom - VH // 3 + bob + dip
        k = sc / 4.0                                                        # art was drawn for 4x
        P = lambda pts: [(hx + x * k, hy + y * k) for x, y in pts]
        if bolt and now - bolt[1] < 0.12:
            src = (hx, hy)
            for tgt in bolt[0]:
                if bolt[2] == 'flyingv':
                    pts = [src]; bx, by = tgt
                    for i in range(1, 7):
                        t = i / 7.0
                        pts.append((src[0] + (bx - src[0]) * t + rnd.uniform(-20, 20), src[1] + (by - src[1]) * t + rnd.uniform(-20, 20)))
                    pts.append(tgt)
                    pygame.draw.lines(screen, (255, 240, 120), False, pts, 6)
                    pygame.draw.lines(screen, (255, 255, 255), False, pts, 2)
                    src = tgt
                elif bolt[2] == 'cannon':                                  # rocket smoke trail
                    pygame.draw.line(screen, (120, 110, 100), src, tgt, 10)
                    pygame.draw.line(screen, (255, 160, 60), src, tgt, 4)
                elif bolt[2] == 'shotgun':
                    for _ in range(8):
                        pygame.draw.line(screen, (255, 220, 120), src, (tgt[0] + rnd.uniform(-80, 80), tgt[1] + rnd.uniform(-60, 60)), 3)
                else:
                    pygame.draw.line(screen, (255, 230, 150), src, tgt, 4)
                pygame.draw.circle(screen, (255, 200, 80), (int(tgt[0]), int(tgt[1])), 14 if bolt[2] != 'shotgun' else 26)
            pygame.draw.circle(screen, (255, 250, 200), (int(hx), int(hy)), 22)
        if wid == 'flyingv':
            pygame.draw.polygon(screen, (60, 40, 30), P([(0, 0), (12, -8), (120, 120), (108, 130)]))
            pygame.draw.polygon(screen, (40, 40, 45), P([(-18, -22), (6, -30), (14, -6), (-8, 4)]))
            vb = P([(100, 110), (230, 150), (160, 180), (200, 270), (120, 200)])
            pygame.draw.polygon(screen, (200, 20, 25), vb); pygame.draw.polygon(screen, (230, 230, 240), vb, 4)
            pygame.draw.line(screen, (230, 230, 240), P([(4, -2)])[0], P([(150, 165)])[0], 2)
        elif wid == 'cannon':
            pygame.draw.polygon(screen, (70, 30, 25), P([(-14, -10), (16, -26), (190, 150), (160, 176)]))
            pygame.draw.polygon(screen, (40, 40, 46), P([(-20, -12), (12, -30), (24, -18), (-8, 0)]))
            pygame.draw.polygon(screen, (230, 200, 60), P([(60, 40), (80, 28), (90, 40), (70, 52)]))
            pygame.draw.polygon(screen, (55, 55, 62), P([(110, 110), (130, 100), (150, 160), (126, 170)]))
        elif wid == 'shotgun':
            pygame.draw.polygon(screen, (55, 55, 62), P([(-6, -4), (10, -10), (150, 130), (132, 146)]))
            pygame.draw.polygon(screen, (120, 75, 40), P([(60, 70), (90, 50), (120, 95), (90, 110)]))
            pygame.draw.polygon(screen, (100, 60, 30), P([(132, 146), (150, 130), (240, 230), (190, 260)]))
        else:
            pygame.draw.polygon(screen, (70, 70, 78), P([(-4, -4), (14, -12), (90, 60), (72, 72)]))
            pygame.draw.polygon(screen, (45, 45, 50), P([(60, 50), (90, 60), (120, 140), (84, 150)]))
            pygame.draw.line(screen, (180, 180, 190), P([(2, -8)])[0], P([(80, 54)])[0], 2)

    def draw_hud(now):
        pygame.draw.rect(screen, (14, 8, 10), hud)
        hp = max(0, int(g['hp']))
        pygame.draw.rect(screen, (50, 50, 58), (hud.x, hud.y + 6, 306, 24))
        pygame.draw.rect(screen, (220, 30, 20) if hp > 30 else (255, 120, 0), (hud.x + 3, hud.y + 9, 3 * hp, 18))
        W = WEAPONS[g['weapon']]
        for i in range(W['mag']):
            col = (255, 200, 40) if i < g['ammo'] else (60, 60, 66)
            x = hud.x + 330 + i * 20
            pygame.draw.polygon(screen, col, [(x, hud.y + 4), (x + 14, hud.y + 4), (x + 7, hud.y + 30)])
        t = outlined(small, 'KILLS %d   WAVE %d   BEST %d' % (g['kills'], g['wave'], max(g['best'], g['kills'])), (240, 240, 240))
        screen.blit(t, (hud.right - t.get_width(), hud.y + 2))
        t = outlined(small, '%s    %d PTS' % (W['name'], g['points']), (255, 200, 60))
        screen.blit(t, (hud.x, hud.y + 44))
        reloading = bool(g['reload_until'])
        pygame.draw.rect(screen, (60, 60, 68), reload_btn, border_radius=18)
        blink = g['ammo'] == 0 and int(now * 4) % 2
        pygame.draw.rect(screen, (255, 200, 40) if blink else (150, 150, 160), reload_btn, 5, border_radius=18)
        lab = outlined(small, 'RELOADING' if reloading else 'RELOAD', (255, 220, 60))
        screen.blit(lab, lab.get_rect(center=reload_btn.center))

    draw_static(); last_held = 'init'
    drag = None                     # touch steering: a press on the view is a joystick until it turns out to be a tap
    while True:
        dt = min(clock.tick(30) / 1000.0, 0.1); now = time.time()
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_q)):
                pygame.quit(); return
            if e.type == pygame.KEYDOWN and e.key == pygame.K_r:
                reload()
            if e.type == pygame.KEYDOWN and e.key in (pygame.K_e, pygame.K_b) and wall_offer(g):
                buy(wall_offer(g))
            if e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                shoot(view.center)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if quit_btn.collidepoint(e.pos):
                    pygame.quit(); return
                if g['over']:
                    g = new_game(); continue
                offer = wall_offer(g)
                if offer and buy_btn.collidepoint(e.pos):
                    buy(offer)
                elif reload_btn.collidepoint(e.pos):
                    reload()
                elif view.collidepoint(e.pos):
                    drag = {'start': e.pos, 't': now, 'moved': False}
            if e.type == pygame.MOUSEBUTTONUP and e.button == 1 and drag:
                if not drag['moved'] and now - drag['t'] < 0.35:      # a quick tap shoots where it landed
                    shoot(drag['start'])
                drag = None
        keys = pygame.key.get_pressed(); mv = turn = 0
        if keys[pygame.K_UP] or keys[pygame.K_w]: mv += 1
        if keys[pygame.K_DOWN] or keys[pygame.K_s]: mv -= 1
        if keys[pygame.K_LEFT] or keys[pygame.K_a]: turn -= 1
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]: turn += 1
        held = None
        if pygame.mouse.get_pressed()[0]:
            mp = pygame.mouse.get_pos()
            for k, r in pads.items():
                if r.collidepoint(mp): held = k
        mv += (held == 'up') - (held == 'down'); turn += (held == 'right') - (held == 'left')
        stick = None
        if drag and pygame.mouse.get_pressed()[0]:
            mx, my = pygame.mouse.get_pos(); dx, dy = mx - drag['start'][0], my - drag['start'][1]
            if math.hypot(dx, dy) > 25 or now - drag['t'] > 0.35:
                drag['moved'] = True
            if drag['moved']:
                turn += max(-1.0, min(1.0, dx / 140.0)); mv += max(-1.0, min(1.0, -dy / 140.0))
                stick = (drag['start'], (drag['start'][0] + max(-90, min(90, dx)), drag['start'][1] + max(-90, min(90, dy))))
        elif drag and not pygame.mouse.get_pressed()[0]:
            drag = None
        if not g['over']:
            step(g, dt, mv, turn, now)

        T0 = time.time()
        frame, hits = render(g, now)
        T1 = time.time()
        pygame.surfarray.blit_array(surf, frame.swapaxes(0, 1))
        pygame.transform.scale(surf, (VW, VH), scaled)
        screen.blit(scaled, view)
        screen.set_clip(view)                                              # effects stay inside the view
        draw_weapon(now, mv or turn)
        if now - g['hurt'] < 0.2:
            pygame.draw.rect(screen, (230, 0, 0), view, 18)
        for b_ in booms[:]:                                                # hellcannon explosions
            t = now - b_[1]
            if t > 0.45: booms.remove(b_); continue
            rr = int(40 + 260 * t)
            pygame.draw.circle(screen, (255, 120, 20), b_[0], rr)
            pygame.draw.circle(screen, (255, 230, 120), b_[0], int(rr * 0.6))
            pygame.draw.circle(screen, (80, 20, 10), b_[0], rr, 6)
        if stick:                                                          # the touch joystick
            pygame.draw.circle(screen, (200, 200, 210), stick[0], 90, 3)
            pygame.draw.circle(screen, (255, 120, 30), stick[1], 34)
            pygame.draw.circle(screen, (255, 230, 200), stick[1], 34, 3)
        for c in gibs[:]:
            t = now - c[4]
            if t > 0.8: gibs.remove(c); continue
            pygame.draw.circle(screen, c[5], (int(c[0] + c[2] * t), int(c[1] + c[3] * t + 700 * t * t)), 6)
        for f in floats[:]:
            t = now - f[3]
            if t > 1.0: floats.remove(f); continue
            img = outlined(mid if not f[0].startswith('WAVE') else huge, f[0], (255, 70, 30) if f[0] != 'RELOAD!' else (255, 220, 60))
            screen.blit(img, (f[1] - img.get_width() // 2, f[2] - 70 - int(t * 90)))
        offer = wall_offer(g)
        if offer and not g['over']:
            OW = WEAPONS[offer]; price = OW['price'] if g['weapon'] != offer else OW['price'] // 2
            pygame.draw.rect(screen, (40, 90, 40) if g['points'] >= price else (70, 40, 40), buy_btn, border_radius=16)
            pygame.draw.rect(screen, (255, 200, 60), buy_btn, 4, border_radius=16)
            bl = outlined(mid, ('BUY %s  %d' if g['weapon'] != offer else 'AMMO %s  %d') % (OW['name'], price), (255, 230, 120))
            screen.blit(bl, bl.get_rect(center=buy_btn.center))
        if g['over']:
            a = outlined(huge, 'YOU GOT SCRIBBLED', (255, 60, 30))
            b = outlined(small, '%d kills, wave %d  -  tap to rise again' % (g['kills'], g['wave']), (240, 240, 240))
            screen.blit(a, a.get_rect(center=(view.centerx, view.centery - 30)))
            screen.blit(b, b.get_rect(center=(view.centerx, view.centery + 50)))
        screen.set_clip(None)
        draw_hud(now)
        dirty = [view, hud, reload_btn]
        if held != last_held:
            draw_pads(held); dirty.append(padarea); last_held = held
        T2 = time.time()
        show(dirty)
        T3 = time.time()
        prof[0] += T1 - T0; prof[1] += T2 - T1; prof[2] += T3 - T2
        frames += 1
        if now - tlog > 5:
            log('fps %.1f zombies %d kills %d hp %d | ms/frame render %.0f draw %.0f flip %.0f' % (
                frames / (now - tlog), len(g['zs']), g['kills'], max(0, int(g['hp'])), *(1000 * x / max(1, frames) for x in prof)))
            frames = 0; tlog = now; prof[:] = [0.0, 0.0, 0.0]


if __name__ == '__main__':
    main()
