# -*- coding: utf-8 -*-
"""Generate a large, byte-exact corpus of .bat / .cmd files for BatFix."""
import os, json, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(ROOT, 'cases')
os.makedirs(CASES, exist_ok=True)
# Previous run leaves a read-only test file; clear attributes before regenerating.
for _f in os.listdir(CASES):
    try: os.chmod(os.path.join(CASES, _f), 0o666)
    except OSError: pass

cases = {}

def add(name, data, note=''):
    cases[name] = data
    return name

def u(s): return s.encode('utf-8')
def g(s): return s.encode('gbk')
def u16le(s): return b'\xff\xfe' + s.encode('utf-16-le')
def u16be(s): return b'\xfe\xff' + s.encode('utf-16-be')
def u32le(s): return b'\xff\xfe\x00\x00' + s.encode('utf-32-le')
def crlf(s): return s.replace('\n', '\r\n').encode('utf-8') if isinstance(s, str) else s

BASE = """@echo off
rem 这是中文注释
echo 中文测试😀
echo 中文测试：你好，世界！
:: 上面一行用来验证行尾
echo 测试符号：「」、；：“”‘’
pause
"""
# Real GBK/ANSI editors replace unrepresentable chars (emoji) with '?'.
BASE_GBK = BASE.encode('gbk', errors='replace')

# ---------------- encoding variants ----------------
add('01_ansi_gbk_crlf.bat',       BASE_GBK, 'ANSI/GBK + CRLF')
add('02_utf8_nobom_crlf.bat',     BASE.encode('utf-8'), 'UTF-8 no BOM + CRLF')
add('03_utf8_bom_crlf.bat',       b'\xef\xbb\xbf' + BASE.encode('utf-8'), 'UTF-8 BOM')
add('04_utf16le_bom.bat',         u16le(BASE), 'UTF-16 LE BOM (PowerShell Out-File)')
add('05_utf16be_bom.bat',         u16be(BASE), 'UTF-16 BE BOM')
add('06_utf32le_bom.bat',         u32le(BASE), 'UTF-32 LE BOM')
add('07_stacked_bom.bat',         b'\xef\xbb\xbf' * 3 + BASE.encode('utf-8'), '3x stacked UTF-8 BOM')
add('08_pure_ascii.bat',          b'@echo off\r\necho Hello World\r\npause\r\n', 'pure ASCII')
add('09_utf8_bom_lf.bat',         (b'\xef\xbb\xbf' + BASE.encode('utf-8')).replace(b'\r\n', b'\n'), 'UTF-8 BOM + LF')
add('10_utf8_nobom_lf.bat',       BASE.encode('utf-8').replace(b'\r\n', b'\n'), 'UTF-8 no BOM + LF')
add('11_utf8_cr_only.bat',        BASE.encode('utf-8').replace(b'\r\n', b'\r'), 'CR-only newlines')
add('12_mixed_newlines.bat',      BASE.encode('utf-8').replace(b'\r\n', b'\n', 3), 'mixed CRLF/LF')
add('13_no_trailing_newline.bat', BASE.encode('utf-8').rstrip(b'\r\n'), 'no final newline')
add('14_many_trailing_blanks.bat', BASE.encode('utf-8') + b'\r\n\r\n\r\n', 'trailing blank lines')
add('15_utf16le_nobom.bat',       BASE.encode('utf-16-le'), 'BOM-less UTF-16LE heuristic')
add('16_empty.bat',               b'', 'empty file')
add('17_only_chinese_line.bat',   u('echo 只有一行中文'), 'single line, no newline, ends non-ASCII')

# ---------------- chcp variants ----------------
add('20_chcp_65001_existing.bat', u('@echo off\r\nchcp 65001 >nul\r\necho 中文测试\r\n'), 'existing chcp')
add('21_chcp_936.bat',            BASE_GBK.replace(b'@echo off', b'@echo off\r\nchcp 936 >nul', 1), 'chcp 936 must be normalized')
add('22_chcp_65001_no_nul.bat',   u('@echo off\r\nchcp 65001\r\necho 中文测试'), 'chcp without >nul')
add('23_chcp_uppercase.bat',      u('@echo off\r\nCHCP 65001 >NUL\r\necho 中文测试'), 'uppercase CHCP')
add('24_chcp_at_prefix.bat',      u('@echo off\r\n@chcp 65001>nul\r\necho 中文测试'), '@chcp no space')
add('25_chcp_duplicated.bat',     u('@echo off\r\nchcp 65001 >nul\r\necho 中文\r\nchcp 65001 >nul\r\nchcp 936\r\n'), 'duplicate chcp lines')
add('26_chcp_late.bat',           u('@echo off\r\necho 前面就有中文\r\nchcp 65001 >nul\r\necho 后面中文'), 'chcp too late, must hoist')
add('27_for_f_chcp.bat',          u('@echo off\r\nfor /f "tokens=2 delims=:" %%a in (\'chcp\') do set OLD=%%a\r\necho 中文\r\n'), "for /f ('chcp') must survive")
add('28_chcp_no_number.bat',      u('@echo off\r\nchcp\r\necho 中文'), 'chcp with no codepage must survive')
add('29_if_chcp_inline.bat',      u('@echo off\r\nif 1==1 chcp 936\r\necho 中文'), 'inline chcp must not be deleted')
add('30_chcp_com.bat',            u('@echo off\r\nchcp.com 65001 >nul\r\necho 中文'), 'chcp.com form')

# ---------------- syntax / line tail ----------------
BLOCK = """@echo off
if exist "C:\\Windows" (
  echo 括号块内的中文
  echo 第二行也是中文
) else (
  echo 否则分支中文
)
for %%i in (1 2 3) do (
  echo 循环体中文
)
for %%i in (a b) do echo 单行循环中文
pause
"""
add('40_if_for_blocks.bat', BLOCK.encode('utf-8'), 'if/for parenthesis blocks')

CONT = """@echo off
echo 这是续行 ^
拼接的中文
echo 结束中文
pause
"""
add('41_caret_continuation.bat', CONT.encode('utf-8'), '^ line continuation untouched')

SET_LINES = """@echo off
set x=中文值
set "y=已经带引号的中文"
set /p z=请输入内容
set /a n=1+1
echo %x% 和 %y% 和 !n!
pause
"""
add('42_set_variants.bat', SET_LINES.encode('utf-8'), 'set value must not gain trailing space')

add('43_redirect_chinese_target.bat', u('@echo off\r\necho 中文内容>结果\r\necho 第二行>>输出\r\n'), 'redirect target must be quoted')
add('44_redirect_ascii_target.bat',   u('@echo off\r\necho 中文内容>out.txt\r\n'), 'ASCII redirect target untouched')
add('45_path_commands.bat',           u('@echo off\r\ncd 中文目录\r\ndel 中文文件.txt\r\ncopy 源文件 目标文件\r\n'), 'path args quoted')
add('46_goto_labels.bat',             u('@echo off\r\ngoto :开始\r\n:开始\r\necho 标签中文\r\ncall :子程序\r\ngoto :eof\r\n:子程序\r\necho 子程序中文\r\n'), 'goto/call labels')
add('47_comments_labels.bat',         u(':: 中文注释\r\nrem 另一条中文注释\r\n:中文标签\r\n@echo off\r\necho 正文中文'), 'comments and labels')
add('48_delayed_expansion.bat',       u('@echo off\r\nsetlocal enabledelayedexpansion\r\nset v=中文\r\necho !v! 中文\r\nendlocal'), 'delayed expansion')
add('49_pipe_and_amp.bat',            u('@echo off\r\necho 中文 | findstr /c:"中" && echo 成功中文\r\necho 结尾中文 & echo 另一句中文\r\n'), 'pipe / && / & chains')
add('50_emoji_symbols.bat',           u('@echo off\r\necho 😀🎉 表情\r\necho 「」【】、；：“”‘’《》\r\necho ①㊣龘靐\r\n'), 'emoji / fullwidth / rare CJK')
add('51_trailing_spaces.bat',         u('@echo off\r\necho 已经有尾随空格 \r\necho 中文测试 \r\n'), 'already-padded lines stay unchanged')
add('52_already_normalized.bat',      u('@chcp 65001 >nul\r\n@echo off\r\necho 中文测试 \r\necho 你好，世界！ \r\n'), 'fully normalized file must be SKIP')
add('53_gbk_special_chars.bat',       ('@echo off\r\necho 中文测试\r\necho 全角符号「」、；：\r\npause\r\n').encode('gbk'), 'GBK special chars')
add('54_binary_like.bat',             b'MZ\x90\x00\x03\x00\x00\x00echo \xd6\xd0\xce\xc4', 'binary-looking, must SKIP')
add('55_long_line.bat',               u('@echo off\r\necho ' + '中文' * 4200 + '\r\n'), 'very long line warning')
add('56_chinese_filename_测试脚本.bat', BASE.encode('utf-8'), 'Chinese filename')
add('57_dot_cmd.cmd',                 BASE.encode('utf-8'), '.cmd extension')
add('58_crlf_in_quotes.bat',          u('@echo off\r\nset "s=a>b"\r\necho %s% 中文'), '> inside quotes')
add('59_two_handles.bat',             u('@echo off\r\ncommand 2>错误日志 1>输出日志\r\n'), 'multiple redirect handles')
# "浣犲ソ涓栫晫" is exactly what "你好世界" becomes when UTF-8 bytes are
# misread as GBK and then saved as UTF-8 (fully reversible through CP936).
add('60_mojibake.bat',                u('@echo off\r\nrem 浣犲ソ涓栫晫\r\necho 浣犲ソ涓栫晫\r\npause\r\n'), 'mojibake text, opt-in repair')
add('61_no_echo_off.bat',             u('echo 中文测试\r\nrem 注释中文\r\npause\r\n'), 'no @echo off at top')
add('62_comment_first.bat',           u(':: 文件头注释中文\r\n@echo off\r\necho 正文中文'), 'comment before @echo off')
add('63_set_with_special.bat',        u('@echo off\r\nset v=a^&b中文\r\necho 结束'), 'set value with metacharacter')
add('64_echo_dot_forms.bat',          u('@echo off\r\necho.中文\r\necho(中文\r\necho: 中文\r\n'), 'echo. / echo( forms')
add('65_no_newline_ascii_end.bat',    u('@echo off\r\necho Hello'), 'ASCII ending, no newline')

def c(s): return s.replace('\n', '\r\n').encode('utf-8')

# ---------------- the 4 files the user actually reported broken ----------------
U1 = ('@chcp 65001 >nul\n@echo off\n'
      'rem 你的中文内容从这里开始 \n'
      'echo 中文测试😀 \n'
      'echo 中文测试：你好，世界！ \n'
      ':: 上面 >nul 屏蔽代码页切换的提示文字 \n'
      'echo 测试符号：【】，、；：“”‘’ \n'
      'pause\n')
U2 = U1.replace('😀 ', '').replace(' \n', '\n')
U3 = U2.replace('@chcp 65001 >nul', '@chcp')
U4 = U1
add('U1_lf_padded.bat',   U1.encode('utf-8'), 'user case 01: LF + already padded')
add('U2_crlf_unpadded.bat', c(U2), 'user case 02: CRLF, needs padding')
add('U3_gbk_bare_chcp.bat', U3.replace('\n', '\r\n').encode('gbk'), 'user case 03: GBK + bare chcp')
add('U4_bom_padded.bat',  b'\xef\xbb\xbf' + c(U4), 'user case 04: UTF-8 BOM + padded')

# ---------------- chcp edge cases ----------------
add('70_chcp_2nul.bat',        c('@echo off\nchcp 65001 2>nul\necho 中文\n'))
add('71_chcp_space_redirect.bat', c('@echo off\nchcp 65001 > nul\necho 中文\n'))
add('72_chcp_com_upper.bat',   c('@echo off\n@CHCP.COM 65001 >NUL\necho 中文\n'))
add('73_chcp_ampersand.bat',   c('@echo off\nchcp 65001&echo 中文\n'))
add('74_chcp_936_ampersand.bat', c('@echo off\nchcp 936&echo 中文\n'))
add('75_chcp_and_and.bat',     c('@echo off\nchcp 65001 >nul && echo 中文\n'))
add('76_comment_mentions_chcp.bat', c(':: 用 chcp 65001 切换代码页\n@echo off\necho 中文\n'))
add('77_echo_mentions_chcp.bat',    c('@echo off\necho chcp 65001 是命令\necho 中文\n'))
add('78_forf_chcp_tokens.bat', c('@echo off\nfor /f "tokens=2 delims=:" %%a in (\'chcp\') do set OLD=%%a\necho 中文\n'))
add('79_bare_chcp_with_chinese.bat', c('@echo off\nchcp\nrem 中文\necho 结束\n'))

# ---------------- line-tail character classes ----------------
add('80_ideographic_space.bat', c('@echo off\necho 中文\u3000\n'))
add('81_tab_ending.bat',        c('@echo off\necho 中文\t\n'))
add('82_emoji_ending.bat',      c('@echo off\necho 表情😀\n'))
add('83_kana_ending.bat',       c('@echo off\necho 日本語かな\n'))
add('84_hangul_ending.bat',     c('@echo off\necho 한국어\n'))
add('85_fullwidth_paren.bat',   c('@echo off\necho 括号）\n'))
add('86_music_euro.bat',        c('@echo off\necho 音乐♪\necho 欧元€\n'))
add('87_blank_lines.bat',       c('@echo off\n\n   \necho 中文\n\n'))
add('88_very_long.bat',         c('@echo off\necho ' + '中文' * 4200 + '\n'))
add('89_rare_cjk.bat',          c('@echo off\necho 龘靐齉爩\n'))
add('90_combining_mark.bat',    c('@echo off\necho cafe\u0301中文\n'))

# ---------------- syntax structures ----------------
add('91_nested_blocks.bat', c('''@echo off
if exist "C:\\Windows" (
  if 1==1 (
    for %%i in (a b) do (
      echo 嵌套中文
    )
  )
) else (
  echo 否则中文
)
'''))
add('92_else_if.bat', c('''@echo off
if 1==2 (
  echo 甲中文
) else if 1==1 (
  echo 乙中文
) else (
  echo 丙中文
)
'''))
add('93_for_l.bat', c('@echo off\nfor /l %%i in (1,1,3) do (\n  echo 第 %%i 次中文\n)\n'))
add('94_for_f_delims.bat', c('@echo off\nfor /f "delims=" %%a in (data.txt) do (\n  echo 读到 %%a 中文\n)\n'))
add('95_caret_in_block.bat', c('''@echo off
if 1==1 (
  echo 这是续行 ^
  拼接中文
)
'''))
add('96_chinese_varname.bat', c('@echo off\nset 变量=中文值\necho %变量%\n'))
add('97_quoted_special.bat', c('@echo off\nset "x=a&b|c>d"\necho %x% 中文\n'))
add('98_setp_unquoted.bat', c('@echo off\nset /p ans=请输入姓名\n'))
add('99_redirect_handles.bat', c('@echo off\ncommand 2>错误日志 1>输出日志\necho 中文\n'))
add('100_input_redirect.bat', c('@echo off\nsort <输入文件\necho 中文\n'))
add('101_goto_eof.bat', c('@echo off\ngoto :eof\necho 中文\n:eof\nexit /b 0\n'))
add('102_start_chinese.bat', c('@echo off\nstart "" "中文程序.exe"\necho 中文\n'))
add('103_call_with_args.bat', c('@echo off\ncall :子程序 参数中文\ngoto :eof\n:子程序\necho %~1 中文\n'))
add('104_if_defined.bat', c('@echo off\nif defined PATH echo 已定义中文\n'))
add('105_pipeline_chinese.bat', c('@echo off\necho 中文 | findstr /c:"中"\necho 结束中文\n'))
add('106_and_or_chain.bat', c('@echo off\necho 中文 && echo 成功中文 || echo 失败中文\n'))
add('107_gt_inside_quotes.bat', c('@echo off\necho "a>b" 中文\n'))
add('108_chinese_path.bat', c('@echo off\ncd /d "D:\\中文目录\\子目录"\necho 中文\n'))
add('109_exit_b.bat', c('@echo off\nif 1==1 exit /b 0\necho 中文\n'))
add('110_percent_escape.bat', c('@echo off\necho 100%% 中文\nfor %%i in (1) do echo %%i 中文\n'))

# ---------------- encoding / newline edge cases ----------------
add('111_utf16be_lf.bat', (b'\xfe\xff' + c('@echo off\necho 中文\n').decode('utf-8').encode('utf-16-be')))
add('112_utf32be_bom.bat', b'\x00\x00\xfe\xff' + c('@echo off\necho 中文\n').decode('utf-8').encode('utf-32-be'))
add('113_four_boms.bat', b'\xef\xbb\xbf' * 4 + c('@echo off\necho 中文\n'))
add('114_mid_bom.bat', c('@echo off\necho 中文') + b'\xef\xbb\xbf' + c('\necho 结束\n'))
add('115_gbk_lf_no_final.bat', ('@echo off\necho 中文测试\necho 你好世界').encode('gbk'))
add('116_ascii_no_newline.bat', b'@echo off\r\necho Hello   ')
add('117_binary_nul.bat', b'MZ\x90\x00\x03\x00echo \xd6\xd0\xce\xc4')
add('118_large_file.bat', c('@echo off\n' + ''.join('echo 第%d行中文\n' % i for i in range(300))))
add('119_upper_CMD.CMD', c('@echo off\necho 中文\n'))
add('120_name with spaces.bat', c('@echo off\necho 中文\n'))
add('121_crlf_blank_tail.bat', c('@echo off\necho 中文\n\n\n'))

# ---------------- display-only cases (safe to actually execute) ----------------
DISPLAY = '@echo off\nchcp 65001 >nul\necho 中文测试\necho 中文测试：你好，世界！\necho 测试符号：【】，、；：“”‘’\n'
add('D1_utf8_crlf_nopad.bat',   c(DISPLAY))
add('D2_utf8_lf_nopad.bat',     DISPLAY.encode('utf-8'))
add('D3_utf8_bom_nopad.bat',    b'\xef\xbb\xbf' + c(DISPLAY))
add('D4_gbk_nopad.bat',         DISPLAY.replace('\n', '\r\n').encode('gbk'))
add('D5_utf8_no_chcp.bat',      c(DISPLAY.replace('chcp 65001 >nul\n', '')))
add('D6_utf8_bare_chcp.bat',    c(DISPLAY.replace('chcp 65001 >nul', '@chcp')))
D7 = ('@echo off\nchcp 65001 >nul\n'
      'echo 中文测试 \necho 中文测试：你好，世界！ \necho 测试符号：【】，、；：“”‘’ \n')
add('D7_utf8_padded.bat',       c(D7))
add('D8_utf16le_nopad.bat',     b'\xff\xfe' + DISPLAY.replace('\n', '\r\n').encode('utf-16-le'))

# write all
for name, data in cases.items():
    with open(os.path.join(CASES, name), 'wb') as f:
        f.write(data)

# one read-only file
ro = os.path.join(CASES, '66_readonly.bat')
with open(ro, 'wb') as f:
    f.write(BASE.encode('utf-8'))
os.chmod(ro, 0o444)

manifest = {
    'cases': sorted(list(cases.keys()) + ['66_readonly.bat']),
    'notes': {name: '' for name in cases},
}
with open(os.path.join(ROOT, 'manifest.json'), 'w', encoding='utf-8') as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

print('generated %d cases in %s' % (len(manifest['cases']), CASES))
