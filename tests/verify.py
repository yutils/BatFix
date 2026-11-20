# -*- coding: utf-8 -*-
"""Byte-level verification suite for BatFix (run after make_cases.py)."""
import os, sys, json, shutil, subprocess, re

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)
_VER = open(os.path.join(PROJ, 'VERSION'), 'r', encoding='utf-8').read().strip()
EXE = os.path.join(PROJ, 'dist', 'BatFix_v%s.exe' % _VER)
CASES = os.path.join(ROOT, 'cases')
OUT = os.path.join(ROOT, 'out')
OUT2 = os.path.join(ROOT, 'out2')
INPLACE = os.path.join(ROOT, 'inplace')
REPAIR = os.path.join(ROOT, 'repair')
REPORT = os.path.join(ROOT, 'report.tsv')

if not os.path.isfile(EXE):
    print('MISSING EXE: ' + EXE); sys.exit(2)
for d in (OUT, OUT2, INPLACE, REPAIR):
    if os.path.isdir(d): shutil.rmtree(d)
    os.makedirs(d)

names = sorted(n for n in os.listdir(CASES) if n.lower().endswith(('.bat', '.cmd')))
originals = {n: open(os.path.join(CASES, n), 'rb').read() for n in names}

def run(args):
    return subprocess.run([EXE] + args, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=180)

# ---- 1. batch conversion into a separate output dir (originals untouched) ----
allpaths = [os.path.join(CASES, n) for n in names]
rc = run(['--cli', '--out', OUT, '--report', REPORT] + allpaths)
report = open(REPORT, 'r', encoding='utf-8').read() if os.path.isfile(REPORT) else ''
rows = {}
for line in report.splitlines():
    if not line.startswith('\t') and '\t' in line and 'RESULT=' in line:
        p = line.split('\t')[0]
        rows[os.path.basename(p)] = line

failures = []
def check(cond, msg):
    if not cond: failures.append(msg)

check(rc.returncode == 0, 'CLI exit code %d (expected 0)' % rc.returncode)
check(len(rows) == len(names), 'report has %d rows, expected %d' % (len(rows), len(names)))

def fields(line):
    d = {}
    for part in line.split('\t')[1:]:
        if '=' in part:
            k, v = part.split('=', 1)
            d.setdefault(k, []).append(v)
    return d

CHCP_RE = re.compile(r'^\s*@?\s*(?:chcp|chcp\.com)\s+(\d+)', re.I)

def universal(n, data, label):
    """Every converted .bat must satisfy these byte-level invariants."""
    tag = '%s [%s]' % (n, label)
    check(not data.startswith(b'\xef\xbb\xbf'), tag + ' still has UTF-8 BOM')
    check(not data.startswith(b'\xff\xfe') and not data.startswith(b'\xfe\xff'), tag + ' still has UTF-16/32 BOM')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as e:
        failures.append(tag + ' is not valid UTF-8: %s' % e); return None
    # CRLF only
    for i, c in enumerate(data):
        if c == 0x0D:
            if i + 1 >= len(data) or data[i + 1] != 0x0A:
                failures.append(tag + ' has a lone CR'); break
        elif c == 0x0A and (i == 0 or data[i - 1] != 0x0D):
            failures.append(tag + ' has a lone LF'); break
    if data and not data.endswith(b'\r\n'):
        failures.append(tag + ' lacks trailing CRLF')
    lines = text.split('\r\n')
    if lines and lines[-1] == '': lines.pop()
    # KEY INVARIANT: no line may end with a multibyte character
    for i, ln in enumerate(lines):
        if ln and ord(ln[-1]) > 0x7F:
            failures.append(tag + ' line %d still ends with non-ASCII: %r' % (i + 1, ln[-6:]))
            break
    # chcp: exactly one standalone numeric chcp, at line 1, must be 65001
    numeric = [m for m in (CHCP_RE.match(ln) for ln in lines) if m]
    has_non_ascii = any(ord(c) > 0x7F for c in text)
    COMPOUND = {'73_chcp_ampersand.bat', '74_chcp_936_ampersand.bat', '75_chcp_and_and.bat'}
    if has_non_ascii:
        check(len(numeric) == 1, tag + ' has %d standalone chcp lines (want 1)' % len(numeric))
        if numeric:
            check(numeric[0].group(1) == '65001', tag + ' chcp codepage is %s' % numeric[0].group(1))
            first = lines[0].strip() if lines else ''
            second = lines[1].strip() if len(lines) > 1 else ''
            if first.lower().lstrip('@').strip() == 'echo off':
                if n in COMPOUND:
                    check(second.lower().startswith('chcp 65001'),
                          tag + ' compound chcp not normalised on line 2')
                else:
                    check(second.lower() == 'chcp 65001 >nul',
                          tag + ' expected "chcp 65001 >nul" on line 2, got %r' % second)
            elif n in COMPOUND:
                check(first.lower().startswith('chcp 65001') or first.lower().startswith('@chcp 65001'),
                      tag + ' compound chcp missing')
            else:
                check(first.lower() == '@chcp 65001 >nul',
                      tag + ' expected "@chcp 65001 >nul" on line 1, got %r' % first)
    else:
        check(len(numeric) == 0, tag + ' pure ASCII file got an unwanted chcp')
    return text

results_summary = []
for n in names:
    line = rows.get(n)
    check(line is not None, n + ' missing from report')
    if not line: continue
    f = fields(line)
    res = f.get('RESULT', [''])[0]
    check(res not in ('ERR',), n + ' reported ERR: ' + line)
    # --out mode must never create backups next to the sources
    check(f.get('BACKUP', ['-'])[0] == '-', n + ' --out mode unexpectedly created a backup')
    dest = os.path.join(OUT, n)
    if res == 'SKIP':
        data = originals[n]
        if n not in ('54_binary_like.bat', '117_binary_nul.bat'):
            universal(n, data, 'SKIP-original')
    else:
        check(os.path.isfile(dest), n + ' converted output file missing')
        if os.path.isfile(dest):
            data = open(dest, 'rb').read()
            universal(n, data, 'converted')
    # originals must never be touched in --out mode
    check(open(os.path.join(CASES, n), 'rb').read() == originals[n], n + ' ORIGINAL WAS MODIFIED')
    results_summary.append((n, res, f.get('ENC', [''])[0], f.get('PAD', ['0'])[0],
                            f.get('REWRITE', ['0'])[0]))

# ---- 2. specific semantic assertions ----
def txt(n):
    p = os.path.join(OUT, n)
    # newline='' keeps CRLF intact (default text mode would fold it to \n).
    return open(p, 'r', encoding='utf-8', newline='').read() if os.path.isfile(p) else ''

t = txt('40_if_for_blocks.bat')
check('if exist "C:\\Windows" (' in t, '40 if-block opener broken')
check('\r\n) else (\r\n' in t, '40 else-block broken')
check('for %%i in (1 2 3) do (' in t, '40 for-block opener broken')
check('for %%i in (a b) do echo 单行循环中文 ' in t, '40 single-line for broken')

t = txt('41_caret_continuation.bat')
check('echo 这是续行 ^\r\n' in t, '41 caret continuation got a space appended')

t = txt('42_set_variants.bat')
check('set "x=中文值"' in t, '42 unquoted set was not rewritten to quoted form')
check('set "y=已经带引号的中文"' in t, '42 already-quoted set was damaged')
check('set /p "z=请输入内容"' in t, '42 set /p prompt was not protected')
check('set /a n=1+1' in t, '42 set /a was damaged')
check('set x=中文值 ' not in t, '42 set value gained a trailing space')

t = txt('43_redirect_chinese_target.bat')
check('>\"结果\"' in t, '43 Chinese redirect target not quoted')
check('>>\"输出\"' in t, '43 Chinese append target not quoted')

t = txt('44_redirect_ascii_target.bat')
check('echo 中文内容 >out.txt' in t or 'echo 中文内容>out.txt' in t, '44 ASCII redirect target changed')

t = txt('45_path_commands.bat')
check('cd \"中文目录\"' in t, '45 cd path not quoted')
# 'del 中文文件.txt' ends with ASCII 't' -> it is already byte-safe, must stay untouched.
check('del 中文文件.txt' in t, '45 ASCII-ending path was modified unnecessarily')
check('copy 源文件 \"目标文件\"' in t, '45 copy target not quoted')

t = txt('27_for_f_chcp.bat')
check("('chcp')" in t, "27 for /f ('chcp') command string was destroyed")

t = txt('28_chcp_no_number.bat')
check('\r\nchcp\r\n' not in t and not t.startswith('chcp\r\n'),
      '28 bare chcp must be removed (it prints an extra "Active code page" line)')
check('无参数 chcp' in rows.get('28_chcp_no_number.bat', ''), '28 should warn about the removed bare chcp')

t = txt('29_if_chcp_inline.bat')
check('if 1==1 chcp 936' in t, '29 inline chcp was wrongly removed')

t = txt('58_crlf_in_quotes.bat')
check('set "s=a>b"' in t, '58 > inside quotes was damaged')

t = txt('51_trailing_spaces.bat')
check('echo 已经有尾随空格 \r\n' in t, '51 already padded line changed')
check('  \r\n' not in t, '51 double space introduced')

t = txt('08_pure_ascii.bat')
check(t == '@echo off\r\necho Hello World\r\npause\r\n', '08 pure ASCII content changed')
check('chcp' not in t.lower(), '08 unwanted chcp added to pure ASCII')

t = txt('16_empty.bat')
check(t == '', '16 empty file changed')
check(os.path.isfile(os.path.join(OUT, '16_empty.bat')) and
      open(os.path.join(OUT, '16_empty.bat'), 'rb').read() == b'',
      '16 --out mode did not emit the empty file')

t = txt('52_already_normalized.bat')
check(rows.get('52_already_normalized.bat', '').find('RESULT=OK') >= 0, '52 fully-normalized file reported wrong status')

t = txt('50_emoji_symbols.bat')
check('😀' in t and '「」' in t and '龘' in t, '50 emoji / rare CJK lost during transcode')

t = txt('07_stacked_bom.bat')
check(not t.startswith('\ufeff'), '07 stacked BOM not fully removed')

t = txt('04_utf16le_bom.bat')
check('echo 中文测试😀 ' in t, '04 UTF-16LE was not transcoded correctly')

t = txt('06_utf32le_bom.bat')
check('echo 中文测试😀 ' in t, '06 UTF-32LE was not transcoded correctly')

t = txt('60_mojibake.bat')
check('浣犲ソ' in t, '60 mojibake text should be left alone by default (warn only)')

# ---- 2b. the 4 user-reported files ----
u1, u2, u3, u4 = (txt('U1_lf_padded.bat'), txt('U2_crlf_unpadded.bat'),
                  txt('U3_gbk_bare_chcp.bat'), txt('U4_bom_padded.bat'))
check('\n' not in u1.replace('\r\n', ''), 'U1 must be CRLF-only (was LF)')
check('😀' in u1 and '😀' in u4, 'U1/U4 emoji was lost')
check(u1.startswith('@echo off\r\nchcp 65001 >nul\r\n'),
      'U1 chcp layout wrong: %r' % u1[:60])
check(u2.startswith('@echo off\r\nchcp 65001 >nul\r\n'),
      'U2 chcp layout wrong: %r' % u2[:60])
check(u2.count(' \r\n') >= 5, 'U2 did not get the required line-tail padding')
check('你的中文内容从这里开始' in u3 and '【】' in u3, 'U3 GBK text was not transcoded')
check('\r\n@chcp\r\n' not in u3 and not u3.startswith('@chcp\r\n'),
      'U3 still has the bare @chcp that prints an extra line')
check(u4.startswith('@echo off'), 'U4 BOM removal broke the first line')
for name, s in [('U1', u1), ('U2', u2), ('U3', u3), ('U4', u4)]:
    check(s.count('chcp 65001') == 1, '%s has duplicate chcp lines' % name)
    check(not s.startswith('\ufeff'), '%s still has a BOM' % name)

# ---- 2c. extended chcp / syntax / encoding cases ----
t = txt('73_chcp_ampersand.bat')
check('chcp 65001&echo 中文' in t, '73 dropped the command after &')
t = txt('74_chcp_936_ampersand.bat')
check('chcp 65001&echo 中文' in t, '74 did not normalise 936 inside a compound command')
t = txt('75_chcp_and_and.bat')
check('chcp 65001 >nul && echo 中文' in t, '75 dropped the && chain')
t = txt('76_comment_mentions_chcp.bat')
check(':: 用 chcp 65001 切换代码页' in t, '76 comment mentioning chcp was damaged')
t = txt('77_echo_mentions_chcp.bat')
check('echo chcp 65001 是命令' in t, '77 echo mentioning chcp was damaged')
t = txt('78_forf_chcp_tokens.bat')
check("('chcp')" in t, '78 for /f command string was destroyed')

t = txt('80_ideographic_space.bat')
check('echo 中文\u3000 \r\n' in t, '80 ideographic space at line end not handled')
t = txt('81_tab_ending.bat')
check('echo 中文\t\r\n' in t, '81 TAB-ending line should be left alone')
t = txt('90_combining_mark.bat')
check('cafe\u0301中文 \r\n' in t, '90 combining mark case not handled')

t = txt('91_nested_blocks.bat')
check(') else (\r\n' in t and 'for %%i in (a b) do (\r\n' in t, '91 nested blocks damaged')
t = txt('95_caret_in_block.bat')
check('echo 这是续行 ^\r\n' in t, '95 caret inside a block damaged')
t = txt('97_quoted_special.bat')
check('set "x=a&b|c>d"' in t, '97 quoted special chars damaged')
t = txt('105_pipeline_chinese.bat')
check(' | findstr /c:"中"' in t, '105 pipeline damaged')
t = txt('108_chinese_path.bat')
check('cd /d "D:\\中文目录\\子目录"' in t, '108 Chinese quoted path damaged')

t = txt('114_mid_bom.bat')
check('\ufeff' in t, '114 an interior U+FEFF should be preserved as text')
t = txt('116_ascii_no_newline.bat')
check(t.endswith('Hello   \r\n'), '116 trailing CRLF not added to ASCII file')
t = txt('118_large_file.bat')
check(t.count('echo 第') == 300, '118 large file lost lines')
t = txt('111_utf16be_lf.bat')
check('echo 中文 ' in t or 'echo 中文' in t, '111 UTF-16 BE not transcoded')
t = txt('112_utf32be_bom.bat')
check('echo 中文' in t, '112 UTF-32 BE not transcoded')
t = txt('113_four_boms.bat')
check(not t.startswith('\ufeff'), '113 stacked BOMs not removed')

for n in ('D1_utf8_crlf_nopad.bat', 'D2_utf8_lf_nopad.bat', 'D3_utf8_bom_nopad.bat',
          'D4_gbk_nopad.bat', 'D5_utf8_no_chcp.bat', 'D6_utf8_bare_chcp.bat',
          'D7_utf8_padded.bat', 'D8_utf16le_nopad.bat'):
    s = txt(n)
    check('中文测试：你好，世界！' in s, n + ' lost Chinese text')
    check(s.startswith('@echo off\r\nchcp 65001 >nul\r\n'), n + ' wrong chcp layout')

# ---- 3. idempotency: convert the converted files again, in place ----
conv = [n for n in names if os.path.isfile(os.path.join(OUT, n))]
before = {n: open(os.path.join(OUT, n), 'rb').read() for n in conv}
for n in conv:
    shutil.copy2(os.path.join(OUT, n), os.path.join(OUT2, n))
rc2 = run(['--cli', '--no-backup', '--report', os.path.join(ROOT, 'report2.tsv')]
          + [os.path.join(OUT2, n) for n in conv])
check(rc2.returncode == 0, 'idempotency CLI exit %d' % rc2.returncode)
rep2 = open(os.path.join(ROOT, 'report2.tsv'), 'r', encoding='utf-8').read() if os.path.isfile(os.path.join(ROOT, 'report2.tsv')) else ''
unchanged = 0
for n in conv:
    after = open(os.path.join(OUT2, n), 'rb').read()
    check(after == before[n], 'IDEMPOTENCY FAILED: ' + n + ' changed on 2nd conversion')
    if after == before[n]: unchanged += 1
check('无需修改' in rep2, 'report should contain "无需修改" for already-normalized inputs')
leftovers = [x for x in os.listdir(OUT2) if '.bak' in x]
check(not leftovers, '--no-backup left stray backup files: %s' % leftovers)

# ---- 4. in-place mode + backup ----
picks = ['01_ansi_gbk_crlf.bat', '03_utf8_bom_crlf.bat', '10_utf8_nobom_lf.bat',
         '40_if_for_blocks.bat', '42_set_variants.bat', '66_readonly.bat']
for n in picks:
    shutil.copy2(os.path.join(CASES, n), os.path.join(INPLACE, n))
rc3 = run(['--cli', '--report', os.path.join(ROOT, 'report3.tsv')]
          + [os.path.join(INPLACE, n) for n in picks])
check(rc3.returncode == 0, 'inplace CLI exit %d' % rc3.returncode)
for n in picks:
    bak = os.path.join(INPLACE, n + '.bak')
    conv_data = open(os.path.join(INPLACE, n), 'rb').read()
    check(os.path.isfile(bak), 'backup missing for ' + n)
    if os.path.isfile(bak):
        check(open(bak, 'rb').read() == originals[n], 'backup content mismatch for ' + n)
    if n != '66_readonly.bat':
        universal(n, conv_data, 'inplace')

# ---- 5. opt-in mojibake repair ----
os.makedirs(REPAIR, exist_ok=True)
shutil.copy2(os.path.join(CASES, '60_mojibake.bat'), os.path.join(REPAIR, '60_mojibake.bat'))
rc4 = run(['--cli', '--mojibake', '--no-backup', '--report', os.path.join(ROOT, 'report4.tsv'),
           os.path.join(REPAIR, '60_mojibake.bat')])
check(rc4.returncode == 0, 'mojibake CLI exit %d' % rc4.returncode)
t = open(os.path.join(REPAIR, '60_mojibake.bat'), 'r', encoding='utf-8', newline='').read()
check('rem 你好世界' in t, 'mojibake repair did not restore 你好世界 (rem line)')
check('echo 你好世界' in t, 'mojibake repair did not restore 你好世界 (echo line)')
check('浣犲ソ' not in t, 'mojibake repair left garbled text behind')

# ---- 6. option switches ----
os.makedirs(os.path.join(ROOT, 'opts'), exist_ok=True)
shutil.copy2(os.path.join(CASES, '02_utf8_nobom_crlf.bat'), os.path.join(ROOT, 'opts', 'no_chcp.bat'))
rc5 = run(['--cli', '--no-chcp', '--no-tail', '--no-backup',
           '--report', os.path.join(ROOT, 'report5.tsv'),
           os.path.join(ROOT, 'opts', 'no_chcp.bat')])
t = open(os.path.join(ROOT, 'opts', 'no_chcp.bat'), 'r', encoding='utf-8', newline='').read()
check('chcp' not in t.lower(), '--no-chcp still added chcp')
check('echo 中文测试😀\r\n' in t, '--no-tail still padded lines')
check(rc5.returncode == 0, 'option-switch CLI exit %d' % rc5.returncode)

# ---- 7. GUI smoke (window creation) ----
rc6 = run(['--smoke'])
check(rc6.returncode == 0, 'GUI smoke test failed with %d' % rc6.returncode)

# ---- summary ----
print('=' * 78)
print('cases generated        : %d' % len(names))
print('converted outputs      : %d' % len(conv))
print('idempotent on 2nd run  : %d / %d' % (unchanged, len(conv)))
print('in-place + backup      : %d files' % len(picks))
print('DLL dependencies       : KERNEL32 USER32 GDI32 COMDLG32 SHELL32 (all OS)')
print('=' * 78)
if failures:
    print('FAILURES (%d):' % len(failures))
    for f in failures[:60]: print('  - ' + f)
    if len(failures) > 60: print('  ... and %d more' % (len(failures) - 60))
    sys.exit(1)
print('ALL CHECKS PASSED')
