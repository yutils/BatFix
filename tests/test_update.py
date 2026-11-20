# -*- coding: utf-8 -*-
"""
Regression suite for the GitHub Releases update check.

Covers:
  * offline version comparison + JSON parsing (--selftest-update)
  * real network probe never crashes and reports a well-defined state
  * startup is not blocked by the background request
  * a failed/offline check shows NO message box and NO red dot
  * clicking "检查更新" while offline also stays silent
  * the red dot is actually rendered when a newer release exists
"""
import os, sys, time, shutil, struct, subprocess, ctypes
from ctypes import wintypes

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)
_VER = open(os.path.join(PROJ, 'VERSION'), 'r', encoding='utf-8').read().strip()
EXE = os.path.join(PROJ, 'dist', 'BatFix_v%s.exe' % _VER)
WORK = os.path.join(ROOT, 'update_work')
if os.path.isdir(WORK):
    shutil.rmtree(WORK)
os.makedirs(WORK)

u32 = ctypes.windll.user32
CLASS = 'BatFix_MainWindow_9C3E'
WM_CLOSE, WM_NULL = 0x0010, 0x0000
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
SMTO_ABORTIFHUNG = 0x0002

u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.FindWindowW.restype = wintypes.HWND
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                    wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                    ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                              wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.FindWindowExW.restype = wintypes.HWND
u32.GetDC.argtypes = [wintypes.HWND]
u32.GetDC.restype = wintypes.HDC
u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
g32 = ctypes.windll.gdi32
g32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
ENUM_CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u32.EnumWindows.argtypes = [ENUM_CB, wintypes.LPARAM]

failures = []


def ck(cond, msg):
    if not cond:
        failures.append(msg)
    print('  %-4s %s' % ('OK' if cond else 'FAIL', msg))


def run(args, timeout=20):
    return subprocess.run([EXE] + args, capture_output=True, timeout=timeout)


def find_main():
    return u32.FindWindowW(CLASS, None)


def close_all():
    """Test scripts assume exclusive use of the GUI."""
    h = find_main()
    if h:
        u32.PostMessageW(h, WM_CLOSE, 0, 0)
        time.sleep(0.7)
    return find_main() == 0


def top_windows(pid):
    out = []

    def cb(h, _):
        p = wintypes.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            buf = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(h, buf, 256)
            out.append((h, buf.value))
        return True

    fn = ENUM_CB(cb)
    u32.EnumWindows(fn, 0)
    return out


def bmp_rgb(path, x, y):
    """Read one pixel from a 24-bit top-down DIB (biHeight < 0)."""
    with open(path, 'rb') as f:
        d = f.read()
    off = struct.unpack_from('<I', d, 10)[0]
    w, h = struct.unpack_from('<ii', d, 18)
    bpp = struct.unpack_from('<H', d, 28)[0]
    row = ((w * (bpp // 8) + 3) // 4) * 4
    i = off + y * row + x * (bpp // 8)
    return d[i + 2], d[i + 1], d[i]   # RGB


def is_red(c):
    return c[0] > 180 and c[1] < 120 and c[2] < 120


print('BatFix v%s  更新检查专项回归' % _VER)
print('=' * 62)

# ---------------------------------------------------------------- 1. offline logic
print('[1] 离线逻辑自测 (--selftest-update)')
r = run(['--selftest-update'], timeout=15)
s = r.stdout.decode('utf-8', 'replace')
ck(r.returncode == 0, '退出码 0')
ck('UPDATE_SELFTEST' in s and 'fail=0' in s, '版本比较 / JSON 解析全部通过: ' + s.strip())
ck('FAIL ' not in s, '没有失败项')

# ---------------------------------------------------------------- 2. real network
print('[2] 真实网络探针 (--update-sync)')
t0 = time.time()
r = run(['--update-sync'], timeout=20)
dt = time.time() - t0
s = r.stdout.decode('utf-8', 'replace').strip()
ck(r.returncode == 0, '网络失败不算程序错误，退出码 0')
ck('UPDATE_SYNC' in s, '返回明确状态: ' + s.replace('\n', ' | '))
ck(dt < 15, '请求有超时上限，耗时 %.2fs' % dt)
# State 2 = 已是最新, 3 = 发现新版, 4 = 静默失败; all are valid outcomes.
ck(any(('state=%d' % n) in s for n in (2, 3, 4)), '状态属于 2/3/4')

# ---------------------------------------------------------------- 3. red dot render
print('[3] 红点渲染 (--shot / --update-demo)')
close_all()
shots = {}
for tag, extra in (('plain', []), ('demo', ['--update-demo']),
                   ('dark_demo', ['--dark', '--update-demo'])):
    p = os.path.join(WORK, tag + '.bmp')
    rr = run(['--shot', p] + extra, timeout=15)
    ck(rr.returncode == 0 and os.path.isfile(p) and os.path.getsize(p) > 1000,
       '%s 预览生成成功' % tag)
    shots[tag] = p
if all(os.path.isfile(p) for p in shots.values()):
    dot = (750, 16)
    ck(not is_red(bmp_rgb(shots['plain'], *dot)), '无新版本时该位置不是红点')
    ck(is_red(bmp_rgb(shots['demo'], *dot)), '浅色主题发现新版本 -> 红点可见')
    ck(is_red(bmp_rgb(shots['dark_demo'], *dot)), '深色主题发现新版本 -> 红点可见')

# ---------------------------------------------------------------- 4. async + silent
print('[4] 启动不阻塞 + 联网失败静默')
close_all()
p = subprocess.Popen([EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    t0 = time.time()
    hwnd = 0
    while time.time() - t0 < 5:
        hwnd = find_main()
        if hwnd:
            break
        time.sleep(0.02)
    boot = time.time() - t0
    ck(bool(hwnd), '主窗口创建成功 (%.3fs)' % boot)
    ck(boot < 2.0, '启动未被网络请求阻塞')

    if hwnd:
        # UI thread must stay responsive while the HTTP request is in flight.
        res = wintypes.DWORD()
        ok = u32.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG, 1000,
                                     ctypes.byref(res))
        ck(bool(ok), '检查进行中 UI 线程仍可响应消息')

        # The update button sits at cx-200 .. cx-68, y=16..46.
        rc = wintypes.RECT()
        u32.GetClientRect(hwnd, ctypes.byref(rc))
        cx = rc.right - rc.left
        hdc = u32.GetDC(0)
        dpi = g32.GetDeviceCaps(hdc, 88)
        u32.ReleaseDC(0, hdc)
        S = dpi / 96.0 if dpi else 1.0
        x, y = int((cx - 134) * S + .5), int(31 * S + .5)
        lp = (y << 16) | (x & 0xFFFF)
        u32.SendMessageW(hwnd, WM_LBUTTONDOWN, 0, lp)
        u32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lp)

        # Wait long enough for the request to finish (or time out), then look
        # for any dialog window owned by this process. A failed check must
        # produce none -- that is the "silent" requirement.
        time.sleep(4.0)
        wins = top_windows(p.pid)
        ck(any(c == CLASS for _, c in wins), '主窗口仍在运行')
        ck(not any(c == '#32770' for _, c in wins),
           '联网失败未弹出任何对话框 (窗口类: %s)' % ','.join(c for _, c in wins))
    # wait a little more and confirm no late dialog appears
    time.sleep(1.0)
    ck(not any(c == '#32770' for _, c in top_windows(p.pid)),
       '等待后依然没有迟到的提示框')
finally:
    if p.poll() is None:
        u32.PostMessageW(find_main() or 0, WM_CLOSE, 0, 0)
        try:
            p.wait(timeout=4)
        except subprocess.TimeoutExpired:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

# ---------------------------------------------------------------- 5. real pipeline
# --update-file feeds a local Release JSON through the SAME parse/compare/
# publish/paint pipeline as the HTTPS response. This is how we verify the
# behaviour before the repo has its first real Release.
print('[5] 端到端：Release JSON -> 版本判定 -> 红点 (--update-file)')
close_all()
TAG = 'https://github.com/yutils/BatFix/releases/tag/0.0.2'
CASES = [
    ('新版_tag',   ('{"tag_name":"0.0.2","name":"v0.0.2","html_url":"%s",'
                    '"body":"说明 \\"tag_name\\":\\"9.9.9\\""}' % TAG).encode('utf-8'), True),
    ('仅有名称',   '{"name":"v0.1.0"}'.encode('utf-8'), True),
    ('同版本',     '{"tag_name":"0.0.1","name":"v0.0.1"}'.encode('utf-8'), False),
    ('更旧版本',   '{"tag_name":"0.0.0"}'.encode('utf-8'), False),
    ('预发布',     '{"tag_name":"v0.0.1-beta1"}'.encode('utf-8'), False),
    ('404响应',    '{"message":"Not Found"}'.encode('utf-8'), False),
    ('非法版本',   '{"tag_name":"not-a-version"}'.encode('utf-8'), False),
    ('空响应',     b'', False),
    ('非法UTF8',   b'{"tag_name":"\xff\xfe"}', False),
    ('危险URL',    ('{"tag_name":"0.0.2","html_url":"javascript:alert(1)"}').encode('utf-8'), True),
]
paths = {}
for name, payload, want in CASES:
    jf = os.path.join(WORK, name + '.json')
    with open(jf, 'wb') as f:
        f.write(payload)
    paths[name] = jf
    bmp = os.path.join(WORK, name + '.bmp')
    rr = run(['--shot', bmp, '--update-file', jf], timeout=15)
    ok = rr.returncode == 0 and os.path.isfile(bmp) and os.path.getsize(bmp) > 1000
    red = ok and is_red(bmp_rgb(bmp, 750, 16))
    ck(ok and red == want, '%-10s 红点=%s (期望 %s)' % (name, red, want))

# a non-existent file must behave exactly like a network failure: no dot
miss = os.path.join(WORK, 'missing.json')
bmp = os.path.join(WORK, 'missing.bmp')
rr = run(['--shot', bmp, '--update-file', miss], timeout=15)
ck(rr.returncode == 0 and os.path.isfile(bmp) and not is_red(bmp_rgb(bmp, 750, 16)),
   '响应文件不存在 -> 静默无红点')

# synchronous probe: verify version classification and safe download page
r = run(['--update-sync', '--update-file', paths['新版_tag']], timeout=15)
s = r.stdout.decode('utf-8', 'replace')
ck(r.returncode == 0 and 'state=3' in s and TAG in s,
   '同步探针判定为「发现新版」并使用 release 页面: ' + s.strip().replace('\n', ' | '))
r = run(['--update-sync', '--update-file', paths['同版本']], timeout=15)
s = r.stdout.decode('utf-8', 'replace')
ck(r.returncode == 0 and 'state=2' in s,
   '同步探针判定为「已是最新」: ' + s.strip().replace('\n', ' | '))
r = run(['--update-sync', '--update-file', paths['404响应']], timeout=15)
s = r.stdout.decode('utf-8', 'replace')
ck(r.returncode == 0 and 'state=4 (silent)' in s,
   '同步探针 404 -> 静默失败: ' + s.strip().replace('\n', ' | '))
r = run(['--update-sync', '--update-file', paths['危险URL']], timeout=15)
s = r.stdout.decode('utf-8', 'replace')
ck('page=https://github.com/yutils/BatFix/releases/latest' in s,
   '不可信 html_url 回退到官方 Releases 页: ' + s.strip().replace('\n', ' | '))

# ---------------------------------------------------------------- 6. dialog on update
# Launch a real GUI fed by a local Release JSON (no network), then click the
# update button. A version-comparison dialog must appear; we close it without
# pressing "Yes" so no browser is opened.
print('[6] 发现新版本 -> 点击弹出版本对比对话框')
close_all()
p2 = subprocess.Popen([EXE, '--update-file', paths['新版_tag']],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    hwnd = 0
    t0 = time.time()
    while time.time() - t0 < 5:
        hwnd = find_main()
        if hwnd:
            break
        time.sleep(0.02)
    ck(bool(hwnd), '带本地 Release JSON 启动主窗口成功')
    if hwnd:
        time.sleep(0.6)                       # background thread publishes state
        rc = wintypes.RECT()
        u32.GetClientRect(hwnd, ctypes.byref(rc))
        cx = rc.right - rc.left
        hdc = u32.GetDC(0)
        dpi = g32.GetDeviceCaps(hdc, 88)
        u32.ReleaseDC(0, hdc)
        S = dpi / 96.0 if dpi else 1.0
        x, y = int((cx - 134) * S + .5), int(31 * S + .5)
        lp = (y << 16) | (x & 0xFFFF)
        # PostMessage (not SendMessage): a modal dialog would block the caller.
        u32.PostMessageW(hwnd, WM_LBUTTONDOWN, 0, lp)
        u32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)
        dlg = 0
        t0 = time.time()
        while time.time() - t0 < 3:
            dlg = next((h for h, c in top_windows(p2.pid) if c == '#32770'), 0)
            if dlg:
                break
            time.sleep(0.05)
        ck(bool(dlg), '点击「发现 v0.0.2」弹出版本对比对话框')
        if dlg:
            # MB_YESNO has no close button (WM_CLOSE is ignored). Click the
            # second Button child = "否", so no browser is opened.
            first = u32.FindWindowExW(dlg, 0, 'Button', None)
            no = u32.FindWindowExW(dlg, first, 'Button', None) if first else 0
            if no:
                u32.SendMessageW(no, 0x00F5, 0, 0)    # BM_CLICK
            else:
                u32.PostMessageW(dlg, 0x0111, 7, 0)   # WM_COMMAND / IDNO
        gone = False
        t0 = time.time()
        while time.time() - t0 < 3:
            if not any(c == '#32770' for _, c in top_windows(p2.pid)):
                gone = True
                break
            time.sleep(0.1)
        ck(gone, '对话框可正常关闭，程序继续运行')
finally:
    h = find_main()
    if h:
        u32.PostMessageW(h, WM_CLOSE, 0, 0)
    if p2.poll() is None:
        try:
            p2.wait(timeout=4)
        except subprocess.TimeoutExpired:
            p2.terminate()
            try:
                p2.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p2.kill()

print('=' * 62)
if failures:
    for f in failures:
        print('  FAIL: ' + f)
    sys.exit(1)
print('ALL UPDATE CHECKS PASSED')
