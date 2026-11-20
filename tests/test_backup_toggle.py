# -*- coding: utf-8 -*-
"""
Verify the GUI checkboxes: toggle behaviour AND the press/release
mis-tap guard (a press that starts on another control must not flip it).
"""
import os, sys, time, shutil, subprocess, ctypes
from ctypes import wintypes

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)
_VER = open(os.path.join(PROJ, 'VERSION'), 'r', encoding='utf-8').read().strip()
EXE = os.path.join(PROJ, 'dist', 'BatFix_v%s.exe' % _VER)
W = os.path.join(ROOT, 'backup_toggle')
if os.path.isdir(W):
    shutil.rmtree(W)
os.makedirs(W)

GOOD = ('@echo off\r\nchcp 65001 >nul\r\n'
        'echo 中文测试 \r\necho 你好，世界！ \r\n')

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.FindWindowW.restype = wintypes.HWND
u32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.GetDC.argtypes = [wintypes.HWND]; u32.GetDC.restype = wintypes.HDC
u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
g32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
CLASS = 'BatFix_MainWindow_9C3E'


def geom(hwnd):
    hdc = u32.GetDC(0)
    dpi = g32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
    u32.ReleaseDC(0, hdc)
    S = dpi / 96.0 if dpi else 1.0
    rc = wintypes.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(rc))
    return S, rc.right - rc.left


def pt(S, x, y):
    return (int(y * S + .5) << 16) | (int(x * S + .5) & 0xFFFF)


def check_point(cx, index):
    """centre of the narrow checkbox item (2x2 grid)"""
    m, gap = 28, 16
    colW = (cx - 2 * m - gap) // 2
    x = m + (index % 2) * (colW + gap) + 80
    y = (246 if index < 2 else 276) + 14
    return x, y


def click(hwnd, S, cx, index):
    x, y = check_point(cx, index)
    lp = pt(S, x, y)
    u32.SendMessageW(hwnd, WM_LBUTTONDOWN, 0, lp)   # guard requires press...
    u32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lp)    # ...and release on the same item
    time.sleep(0.25)
    return x, y


def slip_click(hwnd, S, cx, index):
    """press on the drop card, release on a checkbox -> must be ignored"""
    sx, sy = 300, 160           # inside DropRect (h == 1)
    rx, ry = check_point(cx, index)
    u32.SendMessageW(hwnd, WM_LBUTTONDOWN, 0, pt(S, sx, sy))
    u32.SendMessageW(hwnd, WM_LBUTTONUP, 0, pt(S, rx, ry))
    time.sleep(0.25)


def baks(p):
    d, n = os.path.dirname(p), os.path.basename(p)
    return [f for f in os.listdir(d) if f.startswith(n + '.bak')]


def drop(p):
    r = subprocess.run([EXE, p], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
    time.sleep(0.5)
    return r.returncode


def newfile(name):
    p = os.path.join(W, name)
    open(p, 'wb').write(GOOD.encode('utf-8'))   # already compliant on purpose
    return p


p1 = None
fail = []
try:
    p1 = subprocess.Popen([EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.3)
    hwnd = u32.FindWindowW(CLASS, None)
    if not hwnd:
        fail.append('main window not found')
        raise RuntimeError('no window')
    S, cx = geom(hwnd)

    # 1. default ON -> backup even for an already-compliant file
    a = newfile('A_default_on.bat')
    drop(a)
    if not baks(a):
        fail.append('default ON did not create a backup')

    # 2. mis-tap guard: press elsewhere, release on the "自动备份" checkbox
    slip_click(hwnd, S, cx, 1)
    b = newfile('B_slip_ignored.bat')
    drop(b)
    if not baks(b):
        fail.append('slip click wrongly turned OFF the backup checkbox')

    # 3. proper click -> OFF
    x, y = click(hwnd, S, cx, 1)
    c = newfile('C_toggled_off.bat')
    drop(c)
    if baks(c):
        fail.append('toggle OFF still created a backup')

    # 4. proper click again -> back ON
    click(hwnd, S, cx, 1)
    d = newfile('D_toggled_on.bat')
    drop(d)
    if not baks(d):
        fail.append('toggle back ON did not restore backups')

    print('checkbox hit: dpi-scale=%.2f  client=%d  click=(%d,%d)' % (S, cx, x, y))
finally:
    if p1 and p1.poll() is None:
        p1.terminate()
        try:
            p1.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p1.kill()

for n in ('A_default_on.bat', 'B_slip_ignored.bat', 'C_toggled_off.bat', 'D_toggled_on.bat'):
    print('  %-26s baks=%s' % (n, baks(os.path.join(W, n))))
if fail:
    for f in fail:
        print('  - ' + f)
    sys.exit(1)
print('ALL CHECKBOX / MIS-TAP CHECKS PASSED')
