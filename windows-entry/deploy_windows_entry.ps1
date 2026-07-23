param([string]$TargetRoot='E:\运营大脑', [switch]$SyncProjections, [switch]$EnableAutoStartAgent)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'templates'
$launcher = Join-Path $PSScriptRoot 'launcher'
Import-Module (Join-Path $launcher 'OpsBrainLauncher.psm1') -Force
function Copy-PowerShellSource { param([string]$Source,[string]$Destination) $parent = Split-Path -Parent $Destination; if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }; Copy-Item -LiteralPath $Source -Destination $Destination -Force }
try {
    foreach ($path in @('客户','已归档客户','配置','日志','系统文件_请勿修改\Manager','系统文件_请勿修改\Launcher')) { New-Item -ItemType Directory -Path (Join-Path $TargetRoot $path) -Force | Out-Null }
    Copy-PowerShellSource (Join-Path $launcher 'OpsBrainLauncher.psm1') (Join-Path $TargetRoot '系统文件_请勿修改\Launcher\OpsBrainLauncher.psm1')
    Copy-PowerShellSource (Join-Path $launcher 'launch_ops_agent.sh') (Join-Path $TargetRoot '系统文件_请勿修改\Launcher\launch_ops_agent.sh')
    foreach ($name in @('open_ops_client.ps1')) { Copy-PowerShellSource (Join-Path $source $name) (Join-Path $TargetRoot ('系统文件_请勿修改\Launcher\' + $name)) }
    foreach ($name in @('open_ops_client_center.ps1','new_ops_client_entry.ps1','repair_ops_runtime_entry.ps1')) { Copy-PowerShellSource (Join-Path $source $name) (Join-Path $TargetRoot $name) }
    $cmds = @{ '打开运营大脑客户中心.cmd'='@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0open_ops_client_center.ps1"
set "OPS_EXIT=%ERRORLEVEL%"
if not "%OPS_EXIT%"=="0" (
    echo.
    echo Ops Brain client center failed. Exit code: %OPS_EXIT%
    echo Run the repair entry from the Ops Brain root.
    if not "%OPS_BRAIN_TEST_MODE%"=="1" pause
)
exit /b %OPS_EXIT%
'; '新建客户.cmd'='@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0new_ops_client_entry.ps1"
set "OPS_EXIT=%ERRORLEVEL%"
if not "%OPS_EXIT%"=="0" (
    echo.
    echo Ops Brain new client entry failed. Exit code: %OPS_EXIT%
    echo Run the repair entry from the Ops Brain root.
    if not "%OPS_BRAIN_TEST_MODE%"=="1" pause
)
exit /b %OPS_EXIT%
'; '修复运行环境.cmd'='@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0repair_ops_runtime_entry.ps1"
set "OPS_EXIT=%ERRORLEVEL%"
if not "%OPS_EXIT%"=="0" (
    echo.
    echo Ops Brain repair entry failed. Exit code: %OPS_EXIT%
    if not "%OPS_BRAIN_TEST_MODE%"=="1" pause
)
exit /b %OPS_EXIT%
' }
    foreach ($name in $cmds.Keys) { Write-AsciiCmd -LiteralPath (Join-Path $TargetRoot $name) -Text $cmds[$name] }
    $config = Join-Path $TargetRoot '配置\runtime.json'
    if (-not (Test-Path -LiteralPath $config)) { Write-Utf8NoBom -LiteralPath $config -Value ([ordered]@{ version=1; wsl_distribution='Ubuntu-E'; manager_wsl_path='/home/rong/projects/content-ops-lab/ops-brain-manager'; runtime_wsl_path='/home/rong/tools/cheat-on-content'; default_client_root_wsl='/home/rong/projects/content-ops-clients'; auto_start_agent=$false; agent_command_wsl='/home/rong/.local/bin/claude-deepseek'; agent_launcher_wsl='/home/rong/projects/content-ops-lab/ops-brain-manager/windows-entry/launcher/launch_ops_agent.sh' }) }
    if ($EnableAutoStartAgent) { $runtime = Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json; $runtime.auto_start_agent = $true; if (-not $runtime.agent_command_wsl) { $runtime | Add-Member -NotePropertyName agent_command_wsl -NotePropertyValue '/home/rong/.local/bin/claude-deepseek' }; if (-not $runtime.agent_launcher_wsl) { $runtime | Add-Member -NotePropertyName agent_launcher_wsl -NotePropertyValue '/home/rong/projects/content-ops-lab/ops-brain-manager/windows-entry/launcher/launch_ops_agent.sh' }; Write-Utf8NoBom -LiteralPath $config -Value $runtime }
    Write-Utf8TextNoBom -LiteralPath (Join-Path $TargetRoot '使用说明.txt') -Text "双击客户中心查看入口投影；新建客户调用 WSL Manager；默认不自动启动 Agent。`n"
    if ($SyncProjections) { $runtime = Get-OpsRuntime -Root $TargetRoot; Sync-OpsProjections -Root $TargetRoot -Runtime $runtime | Out-Null }
    Write-Host "部署完成：$TargetRoot"
    exit 0
} catch { Write-Error $_.Exception.Message; exit 2 }
