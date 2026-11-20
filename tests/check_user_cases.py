# -*- coding: utf-8 -*-
"""End-to-end check of the exact 4 files the user reported broken."""
import os, sys, shutil, subprocess
ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)
_VER = open(os.path.join(PROJ, 'VERSION'), 'r', encoding='utf-8').read().strip()
EXE = os.path.join(PROJ, 'dist', 'BatFix_v%s.exe' % _VER)
SRC = os.path.join(ROOT, 'user_cases')
OUT = os.path.join(ROOT, 'user_cases_out')
RUN = os.path.join(ROOT, 'user_run')
for d in (OUT, RUN):
    if os.path.isdir(d): shutil.rmtree(d)
    os.makedirs(d)

names = sorted(n for n in os.listdir(SRC) if n.endswith('.bat'))
original = {n: open(os.path.join(SRC, n), 'rb').read() for n in names}
rc = subprocess.run([EXE, '--cli', '--out', OUT, '--report', os.path.join(ROOT, 'user_report.tsv')]
                    + [os.path.join(SRC, n) for n in names],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
report = open(os.path.join(ROOT, 'user_report.tsv'), 'r', encoding='utf-8').read()
bad = []
if rc.returncode != 0: bad.append('CLI exit %d' % rc.returncode)
for n in names:
    p = os.path.join(OUT, n)
    if not os.path.isfile(p): bad.append(n + ' missing output'); continue
    d = open(p, 'rb').read()
    t = d.decode('utf-8')
    lines = t.split('\r\n')
    if lines and lines[-1] == '': lines.pop()
    checks = [
        (not d.startswith(b'\xef\xbb\xbf'), n + ' still has BOM'),
        (d.endswith(b'\r\n'), n + ' lacks trailing CRLF'),
        (all(not ln or ord(ln[-1]) <= 0x7F for ln in lines), n + ' line ends with non-ASCII'),
        (t.count('chcp 65001') == 1, n + ' duplicate chcp'),
        (lines[0] == '@echo off' and lines[1] == 'chcp 65001 >nul', n + ' wrong chcp layout'),
        ('Active code page' not in t, n + ' contains a bare chcp that prints an extra line'),
    ]
    for ok, msg in checks:
        if not ok: bad.append(msg)
    # originals untouched in --out mode
    if open(os.path.join(SRC, n), 'rb').read() != original[n]:
        bad.append(n + ' ORIGINAL MODIFIED')
    # prepare a pause-free copy for real execution
    open(os.path.join(RUN, n), 'wb').write(t.replace('pause', 'rem pause').encode('utf-8'))

print('user files converted : %d' % len(names))
for l in report.splitlines():
    if '\tENC=' in l:
        f = dict(x.split('=', 1) for x in l.split('\t')[1:] if '=' in x and not x.startswith('WARN='))
        print('  %-20s %-24s %-8s %s' % (os.path.basename(l.split('\t')[0]),
              f.get('ENC', ''), f.get('RESULT', ''), f.get('MSG', '')))
if bad:
    for b in bad: print('  - ' + b)
    sys.exit(1)
print('ALL USER-CASE BYTE CHECKS PASSED')
