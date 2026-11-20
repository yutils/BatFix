# -*- coding: utf-8 -*-
"""Diagnose backup creation through the REAL GUI path (WM_COPYDATA forwarding)."""
import os, sys, time, shutil, subprocess
ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)
_VER = open(os.path.join(PROJ, 'VERSION'), 'r', encoding='utf-8').read().strip()
EXE = os.path.join(PROJ, 'dist', 'BatFix_v%s.exe' % _VER)
W = os.path.join(ROOT, 'backup_diag')
if os.path.isdir(W): shutil.rmtree(W)
os.makedirs(W)

RAW = '@echo off\nrem 中文注释\necho 中文测试\necho 你好，世界！\npause\n'
GOOD = '@echo off\r\nchcp 65001 >nul\r\nrem 中文注释 \r\necho 中文测试 \r\necho 你好，世界！ \r\npause\r\n'

def put(name, data, readonly=False):
    p = os.path.join(W, name)
    with open(p, 'wb') as f: f.write(data)
    if readonly: os.chmod(p, 0o444)
    return p

def baks(name):
    return sorted(f for f in os.listdir(W)
                  if f.startswith(name + '.bak'))

def show(tag, names):
    print('--- ' + tag)
    for n in names:
        p = os.path.join(W, n)
        d = open(p, 'rb').read() if os.path.isfile(p) else b''
        print('   %-34s %4d B  baks=%s' % (n, len(d), baks(n)))

files = {
    'A_raw_lf.bat':      put('A_raw_lf.bat', RAW.encode('utf-8')),
    'B_already_ok.bat':  put('B_already_ok.bat', GOOD.encode('utf-8')),
    'C_gbk.bat':         put('C_gbk.bat', RAW.replace('\n', '\r\n').encode('gbk')),
    'D_readonly.bat':    put('D_readonly.bat', RAW.encode('utf-8'), True),
    'E_script.cmd':      put('E_script.cmd', RAW.encode('utf-8')),
    'F_中文很长的文件名测试.bat': put('F_中文很长的文件名测试.bat', RAW.encode('utf-8')),
}
os.makedirs(os.path.join(W, 'sub'), exist_ok=True)
put('sub/G_in_folder.bat', RAW.encode('utf-8'))

names = list(files)
show('BEFORE', names)

p1 = None
try:
    p1 = subprocess.Popen([EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.2)

    # batch 1: forward 4 files at once (same as dropping 4 onto the exe/window)
    batch1 = [files[n] for n in ('A_raw_lf.bat', 'B_already_ok.bat', 'C_gbk.bat', 'D_readonly.bat')]
    r = subprocess.run([EXE] + batch1, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
    time.sleep(0.6)
    show('AFTER batch1 (4 files, rc=%d)' % r.returncode, list(files))

    # batch 2: folder + .cmd + long Chinese name
    batch2 = [os.path.join(W, 'sub'), files['E_script.cmd'], files['F_中文很长的文件名测试.bat']]
    r = subprocess.run([EXE] + batch2, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
    time.sleep(0.6)
    show('AFTER batch2 (folder + cmd + long name)', list(files))

    # batch 3: same already-ok file again (should still be backed up)
    r = subprocess.run([EXE, files['B_already_ok.bat']], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
    time.sleep(0.6)
    show('AFTER batch3 (same ok file again)', ['B_already_ok.bat'])

    print('--- sub folder:', sorted(os.listdir(os.path.join(W, 'sub'))))
finally:
    if p1 and p1.poll() is None:
        p1.terminate()
        try: p1.wait(timeout=5)
        except subprocess.TimeoutExpired: p1.kill()
print('done')
