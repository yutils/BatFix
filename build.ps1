#requires -Version 3.0
<#
  BatFix 一键编译（跨平台环境自适应）
  - 自动探测 Visual Studio / Build Tools 2017~2022 任意版本与 SKU
  - 自动探测 Windows 10/11 SDK 与 MSVC 工具集
  - 手工构造 INCLUDE/LIB/Path，不依赖 Developer PowerShell / vcvarsall.bat
  - 支持 x64 / x86 / both，静态 CRT (/MT)，产物零第三方 DLL
#>
param(
    [ValidateSet('x64', 'x86', 'both')][string]$Arch = 'both'
)

$ErrorActionPreference = 'Continue'
# PowerShell 5.1 caches the console encoding at startup and ignores a later
# chcp. Set it explicitly so Chinese messages are emitted as UTF-8 on every
# Windows edition, regardless of the system ANSI code page.
try {
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $utf8NoBom
    $OutputEncoding = $utf8NoBom
} catch { }
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Src = Join-Path $Root 'src'
$Dist = Join-Path $Root 'dist'
$OrigPath = $env:Path
New-Item -ItemType Directory -Force -Path $Dist | Out-Null

function Info([string]$m) { Write-Host "  $m" }
function Step([string]$m) { Write-Host ""; Write-Host "== $m" -ForegroundColor Cyan }
function Fail([string]$m) { Write-Host ""; Write-Host "[失败] $m" -ForegroundColor Red }

function Invoke-Native([string]$prog, [string[]]$argv) {
    # PowerShell 5.1 turns native stderr into ErrorRecords; fold and unwrap.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $out = & $prog @argv 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message }
        else { [string]$_ }
    }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return @{ Code = $code; Out = $out }
}

# ---------------------------------------------------------------- 版本（单点来源）
$versionFile = Join-Path $Root 'VERSION'
if (-not (Test-Path $versionFile)) {
    Fail '找不到 VERSION 文件。'
    exit 1
}
$Version = ([IO.File]::ReadAllText($versionFile, [Text.Encoding]::UTF8)).Trim()
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Fail "VERSION 内容不是 x.y.z 格式: $Version"
    exit 1
}
$vp = $Version.Split('.')
$VersionNum = "$($vp[0]),$($vp[1]),$($vp[2]),0"
$ExeX64 = "BatFix_v$Version.exe"
$ExeX86 = "BatFix_v${Version}_x86.exe"

# 生成 version.h，C++ 与 rc.exe 共用同一份版本信息。
# rc.exe 对行尾很敏感：必须是单个 CRLF 且文件末尾要有换行。
$vhLines = @(
    '#pragma once',
    ('#define BATFIX_VERSION_TEXT "' + $Version + '"'),
    ('#define BATFIX_VERSION_WTEXT L"' + $Version + '"'),
    ('#define BATFIX_VERSION_NUM ' + $VersionNum),
    ('#define BATFIX_EXE_NAME "' + $ExeX64 + '"'),
    '#define BATFIX_ICON_ID 101'
)
[IO.File]::WriteAllText((Join-Path $Dist 'version.h'),
    (($vhLines -join "`r`n") + "`r`n"), (New-Object Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "  BatFix v$Version 一键编译" -ForegroundColor White
Write-Host "  项目根目录: $Root"
Write-Host ""

# ---------------------------------------------------------------- VS 探测
Step '1/5  查找 Visual Studio / Build Tools'
$vsList = New-Object System.Collections.Generic.List[string]
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (Test-Path $vswhere) {
    $r = Invoke-Native $vswhere @('-all', '-products', '*', '-property', 'installationPath')
    foreach ($line in $r.Out) {
        $p = ([string]$line).Trim()
        if ($p -and (Test-Path $p) -and -not $vsList.Contains($p)) { $vsList.Add($p) }
    }
}
# 兜底：扫描常见安装目录（vswhere 缺失或返回不全时）
$skus = @('BuildTools', 'Community', 'Professional', 'Enterprise', 'Preview')
$years = @('2022', '2019', '2017')
$vsRoots = @((Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio'),
             (Join-Path $env:ProgramFiles 'Microsoft Visual Studio'))
foreach ($vr in $vsRoots) {
    foreach ($y in $years) {
        foreach ($s in $skus) {
            $p = Join-Path $vr "$y\$s"
            if ((Test-Path $p) -and -not $vsList.Contains($p)) { $vsList.Add($p) }
        }
    }
}

$Vc = $null; $VcVer = ''; $VsRoot = ''
foreach ($vs in $vsList) {
    $msvcRoot = Join-Path $vs 'VC\Tools\MSVC'
    if (-not (Test-Path $msvcRoot)) { continue }
    foreach ($v in (Get-ChildItem $msvcRoot -Directory -Name | Sort-Object -Descending)) {
        $cand = Join-Path $msvcRoot $v
        if (Test-Path (Join-Path $cand 'bin\Hostx64\x64\cl.exe')) {
            $Vc = $cand; $VcVer = $v; $VsRoot = $vs; break
        }
    }
    if ($Vc) { break }
}
if (-not $Vc) {
    Fail '没有找到 MSVC C++ 编译器 (cl.exe)。'
    Write-Host ""
    Write-Host "  请安装 Visual Studio 2022/2019 Build Tools（免费），勾选"
    Write-Host "  「使用 C++ 的桌面开发 / Desktop development with C++」，"
    Write-Host "  并确保包含 MSVC 工具集与 Windows 10/11 SDK。"
    Write-Host "  下载: https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022"
    Write-Host ""
    Write-Host "  如果只是想直接使用，请从项目 Releases 页面下载预编译版本。"
    exit 1
}
Info "VS    : $VsRoot"
Info "MSVC  : $VcVer"

# ---------------------------------------------------------------- SDK 探测
Step '2/5  查找 Windows SDK'
$kitRoots = @((Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10'),
              (Join-Path $env:ProgramFiles 'Windows Kits\10'))
$Kit = ''; $SdkVer = ''
foreach ($k in $kitRoots) {
    $incRoot = Join-Path $k 'Include'
    if (-not (Test-Path $incRoot)) { continue }
    foreach ($v in (Get-ChildItem $incRoot -Directory -Name |
                    Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' } |
                    Sort-Object -Descending)) {
        if (Test-Path (Join-Path $k "Lib\$v\um\x64\kernel32.lib")) {
            $Kit = $k; $SdkVer = $v; break
        }
    }
    if ($SdkVer) { break }
}
if (-not $SdkVer) {
    Fail '没有找到 Windows 10/11 SDK (Lib\<ver>\um\x64\kernel32.lib)。'
    Write-Host "  请在 Visual Studio Installer 中勾选「Windows 10/11 SDK」后重试。"
    exit 1
}
Info "SDK   : $SdkVer"
Info "路径  : $Kit"

# ---------------------------------------------------------------- 资源（图标 + 版本信息）
Step '3/5  编译图标与版本资源'
# rc.exe needs the SDK include path for winres.h (set here, before Build-One).
$env:INCLUDE = "$(Join-Path $Kit "Include\$SdkVer\ucrt");" +
               "$(Join-Path $Kit "Include\$SdkVer\um");" +
               "$(Join-Path $Kit "Include\$SdkVer\shared");" +
               "$(Join-Path $Kit "Include\$SdkVer\winrt")"
$rcExe = Join-Path $Kit "bin\$SdkVer\x64\rc.exe"
$resFile = Join-Path $Dist 'app.res'
$Res = $null
if (Test-Path $rcExe) {
    $r = Invoke-Native $rcExe @('/nologo', "/I$Dist", "/I$Src",
                                "/fo$resFile", (Join-Path $Src 'version.rc'))
    if ($r.Code -eq 0 -and (Test-Path $resFile)) {
        $Res = $resFile
        Info "rc.exe 完成 -> dist\app.res（图标 + VERSIONINFO）"
    } else {
        Write-Host "  [警告] 资源编译失败，exe 将没有图标/版本信息。" -ForegroundColor Yellow
        foreach ($l in $r.Out) { Write-Host "    $l" }
    }
} else {
    Write-Host "  [警告] 找不到 rc.exe，exe 将没有图标/版本信息。" -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 编译
function Build-One([string]$arch) {
    if ($arch -eq 'x86') {
        $bin = Join-Path $Vc 'bin\Hostx64\x86'
        $sdkA = 'x86'; $libA = 'x86'; $machine = 'X86'; $outName = $ExeX86
    } else {
        $bin = Join-Path $Vc 'bin\Hostx64\x64'
        $sdkA = 'x64'; $libA = 'x64'; $machine = 'X64'; $outName = $ExeX64
    }
    $cl = Join-Path $bin 'cl.exe'
    $link = Join-Path $bin 'link.exe'
    if (-not (Test-Path $cl) -or -not (Test-Path $link)) {
        Fail "$arch 工具集不完整（缺少 $bin 下的 cl.exe / link.exe）。"
        return $false
    }

    $env:INCLUDE = "$(Join-Path $Vc 'include');" +
                   "$(Join-Path $Kit "Include\$SdkVer\ucrt");" +
                   "$(Join-Path $Kit "Include\$SdkVer\um");" +
                   "$(Join-Path $Kit "Include\$SdkVer\shared");" +
                   "$(Join-Path $Kit "Include\$SdkVer\winrt")"
    $env:LIB = "$(Join-Path $Vc "lib\$libA");" +
               "$(Join-Path $Kit "Lib\$SdkVer\ucrt\$sdkA");" +
               "$(Join-Path $Kit "Lib\$SdkVer\um\$sdkA")"
    $env:Path = "$bin;" + (Join-Path $Kit "bin\$SdkVer\$sdkA") + ";$OrigPath"
    $env:VSCMD_VER = 'manual'
    $env:VSCMD_ARG_TGT_ARCH = $arch

    $obj = Join-Path $Dist "BatFix_$arch.obj"
    $exe = Join-Path $Dist $outName
    $log = Join-Path $Dist "build_$arch.log"
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("VS   = $VsRoot")
    $lines.Add("MSVC = $VcVer")
    $lines.Add("SDK  = $SdkVer")
    $lines.Add("ARCH = $arch")

    Info "[$arch] cl.exe ..."
    $r = Invoke-Native $cl @('/nologo', '/c', '/std:c++17', '/MT', '/O2', '/EHsc',
                              '/W3', '/utf-8', "/I$Dist", "/Fo:$obj",
                              (Join-Path $Src 'BatFix.cpp'))
    $lines.Add("--- cl.exe (exit $($r.Code)) ---")
    foreach ($l in $r.Out) { $lines.Add([string]$l) }
    if ($r.Code -ne 0) {
        [IO.File]::WriteAllLines($log, $lines, (New-Object Text.UTF8Encoding($false)))
        Fail "[$arch] 编译失败，详见 $log"
        foreach ($l in $r.Out) { Write-Host "    $l" }
        return $false
    }

    # A running BatFix keeps its exe mapped, so link.exe cannot overwrite it
    # (LNK1104). Windows DOES allow renaming a mapped image: move the old
    # file aside, then link a fresh one. The running instance is unaffected.
    if (Test-Path -LiteralPath $exe) {
        try {
            Remove-Item -LiteralPath $exe -Force -ErrorAction Stop
        } catch {
            $stale = "$exe.prev"
            Remove-Item -LiteralPath $stale -Force -ErrorAction SilentlyContinue
            try {
                Move-Item -LiteralPath $exe -Destination $stale -Force -ErrorAction Stop
                Info "[$arch] 旧 exe 正在运行，已另存为 $(Split-Path -Leaf $stale)"
            } catch {
                Fail "[$arch] 无法替换正在使用的 exe，请关闭 BatFix 后重试"
                return $false
            }
        }
    }

    Info "[$arch] link.exe ..."
    $linkArgs = @('/NOLOGO', '/MANIFEST:NO', '/SUBSYSTEM:WINDOWS',
                  "/MACHINE:$machine", "/OUT:$exe", $obj)
    if ($Res) { $linkArgs += $Res }
    $r = Invoke-Native $link $linkArgs
    $lines.Add("--- link.exe (exit $($r.Code)) ---")
    foreach ($l in $r.Out) { $lines.Add([string]$l) }
    if ($r.Code -ne 0) {
        [IO.File]::WriteAllLines($log, $lines, (New-Object Text.UTF8Encoding($false)))
        Fail "[$arch] 链接失败，详见 $log"
        return $false
    }

    $mt = Join-Path $Kit "bin\$SdkVer\$sdkA\mt.exe"
    if (Test-Path $mt) {
        $r = Invoke-Native $mt @('-nologo', '-manifest', (Join-Path $Src 'app.manifest'),
                                 "-outputresource:$exe;#1")
        $lines.Add("--- mt.exe (exit $($r.Code)) ---")
        foreach ($l in $r.Out) { $lines.Add([string]$l) }
    } else {
        $lines.Add('--- mt.exe 未找到，跳过清单嵌入（不影响运行）---')
    }

    [IO.File]::WriteAllLines($log, $lines, (New-Object Text.UTF8Encoding($false)))
    Remove-Item $obj -ErrorAction SilentlyContinue
    if (Test-Path $exe) {
        $fi = Get-Item $exe
        Write-Host "  [$arch] 完成 -> dist\$outName  ($($fi.Length) 字节)" -ForegroundColor Green
        return $true
    }
    Fail "[$arch] 未生成 exe"
    return $false
}

Step '4/5  编译'
$targets = if ($Arch -eq 'both') { @('x64', 'x86') } else { @($Arch) }
$ok = $true
foreach ($a in $targets) { if (-not (Build-One $a)) { $ok = $false } }

Step '5/5  结果'
$env:Path = $OrigPath
if ($ok) {
    Write-Host ""
    Write-Host "  编译完成 v$Version，产物位于:" -ForegroundColor Green
    Write-Host "    $Dist"
    foreach ($a in $targets) {
        $n = if ($a -eq 'x86') { $ExeX86 } else { $ExeX64 }
        $p = Join-Path $Dist $n
        if (Test-Path $p) { Write-Host "    $n  ($((Get-Item $p).Length) 字节)" }
    }
    Write-Host ""
    Write-Host "  单文件、静态 CRT，只依赖系统 DLL (kernel32/user32/gdi32/comdlg32/shell32)。"
    exit 0
}
Fail '至少有一个架构编译失败。'
exit 1
