# -*- coding: utf-8 -*-
"""
Regression suite for the backup guarantee, exercised through the REAL GUI
path (WM_COPYDATA forwarding == dropping files onto the window / exe icon).

Rule under test: every in-place conversion snapshots the original file,
EVEN IF the file is already fully compliant and no byte needs rewriting.
"""
import os, sys, time, shutil, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)
_VER = open(os.path.join(PROJ, 'VERSION'), 'r', encoding='utf-8').read().strip()
EXE = os.path.join(PROJ, 'dist', 'BatFix_v%s.exe' % _VER)
W = os.path.join(ROOT, 'backup_matrix')
if os.path.isdir(W): shutil.rmtree(W)
os.makedirs(W)

RAW = '@echo off\nrem 中文注释\necho 中文测试\necho 你好，世界！\npause\n'
GOOD = '@echo off\r\nchcp 65001 >nul\r\nrem 中文注释 \r\necho 中文测试 \r\necho 你好，世界！ \r\npause\r\n'
GBK = RAW.replace('\n', '\r\n').encode('gbk')


def put(name, data, readonly=False):
    p = os.path.join(W, name)
    with open(p, 'wb') as f:
        f.write(data)
    if readonly:
        os.chmod(p, 0o444)
    return p


def baks(path):
    d, n = os.path.dirname(path), os.path.basename(path)
    return sorted(f for f in os.listdir(d) if f.startswith(n + '.bak'))


failures = []
def check(cond, msg):
    if not cond:
        failures.append(msg)


def send(paths, p1):
    r = subprocess.run([EXE] + paths, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=40)
    check(r.returncode == 0, 'forwarding returned %d' % r.returncode)
    time.sleep(0.5)


# ---- prepare inputs ----
IN = {
    'A_raw_lf.bat':         put('A_raw_lf.bat', RAW.encode('utf-8')),
    'B_already_ok.bat':     put('B_already_ok.bat', GOOD.encode('utf-8')),
    'C_gbk.bat':            put('C_gbk.bat', GBK),
    'D_readonly.bat':       put('D_readonly.bat', RAW.encode('utf-8'), True),
    'E_script.cmd':         put('E_script.cmd', RAW.encode('utf-8')),
    'F_中文很长的文件名测试.bat': put('F_中文很长的文件名测试.bat', RAW.encode('utf-8')),
    'G_bom.bat':            put('G_bom.bat', b'\xef\xbb\xbf' + RAW.replace('\n', '\r\n').encode('utf-8')),
    'H_utf16le.bat':        put('H_utf16le.bat', b'\xff\xfe' + RAW.replace('\n', '\r\n').encode('utf-16-le')),
}
original = {n: open(p, 'rb').read() for n, p in IN.items()}

os.makedirs(os.path.join(W, 'sub', 'deep'), exist_ok=True)
IN['I_folder.bat'] = put('sub/I_folder.bat', RAW.encode('utf-8'))
IN['J_deep.bat'] = put('sub/deep/J_deep.bat', RAW.encode('utf-8'))
original['I_folder.bat'] = open(IN['I_folder.bat'], 'rb').read()
original['J_deep.bat'] = open(IN['J_deep.bat'], 'rb').read()

p1 = None
try:
    p1 = subprocess.Popen([EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.3)

    # 1. one batch of 8 files, mixed encodings / extensions / names
    first8 = [IN[n] for n in ('A_raw_lf.bat', 'B_already_ok.bat', 'C_gbk.bat',
                              'D_readonly.bat', 'E_script.cmd', 'F_中文很长的文件名测试.bat',
                              'G_bom.bat', 'H_utf16le.bat')]
    send(first8, p1)
    for n in ('A_raw_lf.bat', 'B_already_ok.bat', 'C_gbk.bat', 'D_readonly.bat',
              'E_script.cmd', 'F_中文很长的文件名测试.bat', 'G_bom.bat', 'H_utf16le.bat'):
        b = baks(IN[n])
        check(len(b) == 1, '%s expected 1 backup, got %s' % (n, b))
        if b:
            bakdata = open(os.path.join(os.path.dirname(IN[n]), b[0]), 'rb').read()
            check(bakdata == original[n], '%s backup content != original bytes' % n)

    # 2. folder drop (recursive) -> every bat inside gets a backup
    send([os.path.join(W, 'sub')], p1)
    for n in ('I_folder.bat', 'J_deep.bat'):
        b = baks(IN[n])
        check(len(b) == 1, '%s (folder drop) expected 1 backup, got %s' % (n, b))

    # 3. already-compliant file dropped a 2nd and 3rd time -> a NEW backup each time
    for expect in (2, 3):
        send([IN['B_already_ok.bat']], p1)
        b = baks(IN['B_already_ok.bat'])
        check(len(b) == expect,
              'B_already_ok.bat after %d drops expected %d backups, got %s' % (expect, expect, b))

    # 4. unchanged file really stayed byte-identical (no accidental rewrite)
    check(open(IN['B_already_ok.bat'], 'rb').read() == original['B_already_ok.bat'],
          'already-compliant file was modified')

    # 5. the "自动备份" GUI toggle still works: turn it off by clicking pill 1
    #    (verified separately via CLI --no-backup below)

    # CLI obeys the same single-instance rule, so close the GUI first.
    p1.terminate()
    try:
        p1.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p1.kill()

    # 6. CLI --no-backup must NOT create backups
    offdir = os.path.join(W, 'nobak')
    os.makedirs(offdir, exist_ok=True)
    off = os.path.join(offdir, 'K_off.bat')
    with open(off, 'wb') as f:
        f.write(RAW.encode('utf-8'))
    r = subprocess.run([EXE, '--cli', '--no-backup', off],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    check(r.returncode == 0, '--no-backup CLI exit %d' % r.returncode)
    check(baks(off) == [], '--no-backup still created a backup')

    # 7. CLI in-place WITH backup must create one even for a compliant file
    ondir = os.path.join(W, 'withbak')
    os.makedirs(ondir, exist_ok=True)
    on = os.path.join(ondir, 'L_ok.bat')
    with open(on, 'wb') as f:
        f.write(GOOD.encode('utf-8'))
    r = subprocess.run([EXE, '--cli', on], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
    check(r.returncode == 0, 'CLI in-place exit %d' % r.returncode)
    check(len(baks(on)) == 1, 'CLI in-place on a compliant file created %s' % baks(on))

    # 8. --out mode must not create backups next to the source
    outdir = os.path.join(W, 'outmode')
    os.makedirs(outdir, exist_ok=True)
    src = os.path.join(W, 'M_out.bat')
    with open(src, 'wb') as f:
        f.write(RAW.encode('utf-8'))
    r = subprocess.run([EXE, '--cli', '--out', outdir, src], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
    check(r.returncode == 0, '--out CLI exit %d' % r.returncode)
    check(baks(src) == [], '--out mode created a backup next to the source')

finally:
    if p1 and p1.poll() is None:
        p1.terminate()
        try:
            p1.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p1.kill()

print('=' * 74)
print('backup matrix  : 8 mixed files + 2 folder files + 3 repeat drops + 3 CLI modes')
print('=' * 74)
for n in sorted(original):
    print('  %-34s baks=%s' % (n, baks(IN[n]) if n in IN else '?'))
if failures:
    print('FAILURES (%d):' % len(failures))
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('ALL BACKUP CHECKS PASSED')
