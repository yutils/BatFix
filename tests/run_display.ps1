# Execute the converted display-only .bat files with native PowerShell syntax
# and capture their real stdout/stderr so check_runtime.py can verify them.
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $root 'out'
$dst = Join-Path $root 'display_out'
New-Item -ItemType Directory -Force -Path $dst | Out-Null
foreach ($f in (Get-ChildItem $src -Filter 'D*.bat')) {
    $o = & $f.FullName 2>&1 | Out-String
    [IO.File]::WriteAllText((Join-Path $dst ($f.Name + '.txt')), $o,
                            (New-Object Text.UTF8Encoding($false)))
}
Write-Output ("ran " + (Get-ChildItem $dst -Filter '*.txt').Count + " display cases")
