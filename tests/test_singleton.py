# -*- coding: utf-8 -*-
"""Verify single-instance enforcement + drag/drop argument forwarding."""
import os, sys, time, shutil, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)
_VER = open(os.path.join(PROJ, 'VERSION'), 'r', encoding='utf-8').read().strip()
EXE = os.path.join(PROJ, 'dist', 'BatFix_v%s.exe' % _VER)
WORK = os.path.join(ROOT, 'singleton')
if os.path.isdir(WORK): shutil.rmtree(WORK)
os.makedirs(WORK)

src = os.path.join(WORK, '转发测试.bat')
ORIGINAL = '@echo off\r\necho 单例转发中文\r\npause\r\n'.encode('utf-8')
with open(src, 'wb') as f: f.write(ORIGINAL)

p1 = None
failures = []
try:
    # instance #1: plain GUI launch, stays alive
    p1 = subprocess.Popen([EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.2)
    if p1.poll() is not None:
        failures.append('first instance exited unexpectedly with %s' % p1.returncode)

    # instance #2: must NOT stay alive; should forward and exit immediately
    t0 = time.time()
    rc = subprocess.run([EXE, '--smoke'], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=15)
    dt = time.time() - t0
    if rc.returncode != 0: failures.append('second instance exit code %d' % rc.returncode)
    if dt > 6: failures.append('second instance did not exit promptly (%.1fs)' % dt)

    # instance #3: pass a .bat path -> forwarded via WM_COPYDATA to instance #1
    rc = subprocess.run([EXE, src], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=15)
    if rc.returncode != 0: failures.append('forwarding instance exit code %d' % rc.returncode)

    # give the first window time to handle WM_COPYDATA
    for _ in range(20):
        if os.path.isfile(src + '.bak'): break
        time.sleep(0.25)

    if not os.path.isfile(src + '.bak'):
        failures.append('WM_COPYDATA forwarding failed: no .bak created')
    data = open(src, 'rb').read()
    if data == ORIGINAL:
        failures.append('forwarded file was not converted')
    if b'\xef\xbb\xbf' in data[:3]: failures.append('forwarded file has BOM')
    if b'chcp 65001' not in data: failures.append('forwarded file lacks chcp 65001')
    for ln in data.decode('utf-8').split('\r\n'):
        if ln and ord(ln[-1]) > 0x7F:
            failures.append('forwarded file line ends with non-ASCII'); break
finally:
    if p1 is not None and p1.poll() is None:
        p1.terminate()
        try: p1.wait(timeout=5)
        except subprocess.TimeoutExpired: p1.kill()

print('single instance : second launch exit=%s in %.2fs' % (rc.returncode, dt))
print('arg forwarding  : %s' % ('OK' if os.path.isfile(src + '.bak') else 'FAILED'))
if failures:
    for f in failures: print('  - ' + f)
    sys.exit(1)
print('ALL SINGLETON CHECKS PASSED')
