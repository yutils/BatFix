# -*- coding: utf-8 -*-
"""Verify that converted .bat files actually display Chinese when executed."""
import os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(ROOT, 'display_out')
files = sorted(f for f in os.listdir(DST) if f.endswith('.txt')) if os.path.isdir(DST) else []
bad = []
BAD_MARKERS = ['is not recognized', 'not recognized as an internal',
               'Active code page', '\ufffd', '??', 'CommandNotFound']

for f in files:
    t = open(os.path.join(DST, f), 'r', encoding='utf-8').read()
    for want in ['中文测试', '你好，世界！', '测试符号：【】，、；：“”‘’']:
        if want not in t:
            bad.append('%s missing %r' % (f, want))
    for m in BAD_MARKERS:
        if m in t:
            bad.append('%s contains %r' % (f, m))
    if t.count('中文测试') < 2:
        bad.append('%s echoed fewer lines than expected' % f)

print('runtime-checked : %d files' % len(files))
for f in files:
    t = open(os.path.join(DST, f), 'r', encoding='utf-8').read()
    print('  %-32s %s' % (f, repr(t[:110])))
if not files:
    bad.append('no runtime results; run run_display.ps1 first')
if bad:
    print('FAILURES:')
    for b in bad: print('  - ' + b)
    sys.exit(1)
print('ALL RUNTIME CHECKS PASSED')
