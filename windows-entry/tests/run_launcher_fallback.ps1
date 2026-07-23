param([string]$SourceRoot=(Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$module = Join-Path $SourceRoot 'launcher\OpsBrainLauncher.psm1'
$deploy = Join-Path $SourceRoot 'deploy_windows_entry.ps1'
if (-not (Test-Path -LiteralPath $module) -or -not (Test-Path -LiteralPath $deploy)) { throw 'Launcher source is incomplete.' }
$text = Get-Content -LiteralPath $module -Raw -Encoding UTF8
foreach ($required in @('Invoke-OpsManagerJson','Convert-WindowsPathToWsl','Test-OpsProjectionIdentity','New-OpsWorkspace')) {
    if ($text -notmatch [regex]::Escape($required)) { throw "Missing launcher function: $required" }
}
if ($text -match 'bash\s+-lc') { throw 'Launcher must not use bash -lc.' }
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ('ops-brain-launcher-' + [guid]::NewGuid().ToString())
try {
    & $deploy -TargetRoot $temporary
    if ($LASTEXITCODE -ne 0) { throw 'Deployment fallback failed.' }
    foreach ($cmd in @('打开运营大脑客户中心.cmd','新建客户.cmd','修复运行环境.cmd')) {
        $bytes = [System.IO.File]::ReadAllBytes((Join-Path $temporary $cmd))
        if (($bytes | Where-Object { $_ -gt 127 }).Count -ne 0) { throw "CMD is not ASCII: $cmd" }
        if ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191) { throw "CMD has UTF-8 BOM: $cmd" }
        if (-not ([System.Text.Encoding]::ASCII.GetString($bytes).Contains("`r`n"))) { throw "CMD is not CRLF: $cmd" }
    }
    Write-Output 'Fallback launcher checks passed.'
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
