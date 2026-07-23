param([switch]$RebuildProjections, [string]$ClearStaleClient)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Import-Module (Join-Path $root '系统文件_请勿修改\Launcher\OpsBrainLauncher.psm1') -Force
try {
    $runtime = Get-OpsRuntime -Root $root
    $checks = @()
    foreach ($name in @('wsl.exe', 'code.cmd')) { $checks += [pscustomobject]@{ check=$name; ok=($null -ne (Get-Command $name -ErrorAction SilentlyContinue)) } }
    $doctor = Invoke-OpsManagerJson -Runtime $runtime -ManagerArguments @('doctor', '--json')
    $checks += [pscustomobject]@{ check='manager doctor'; ok=($doctor.ExitCode -eq 0) }
    $runtimeCheck = & wsl.exe -d $runtime.wsl_distribution -- test -d $runtime.runtime_wsl_path
    $checks += [pscustomobject]@{ check='cheat runtime'; ok=($LASTEXITCODE -eq 0) }
    $agentCheck = & wsl.exe -d $runtime.wsl_distribution -- which claude-deepseek
    $checks += [pscustomobject]@{ check='claude-deepseek'; ok=($LASTEXITCODE -eq 0) }
    if ($runtime.agent_launcher_wsl -and $runtime.agent_command_wsl) {
        $sessionReport = & wsl.exe -d $runtime.wsl_distribution -- bash $runtime.agent_launcher_wsl --diagnose $runtime.agent_command_wsl
        $checks += [pscustomobject]@{ check='agent launcher diagnostics'; ok=($LASTEXITCODE -eq 0) }
        $sessionReport | ForEach-Object { Write-Host $_ }
    }
    $checks | Format-Table -AutoSize
    if ($RebuildProjections) {
        $answer = Read-Host '仅重建 Windows 投影。输入 YES 确认'
        if ($answer -eq 'YES') { Sync-OpsProjections -Root $root -Runtime $runtime | Out-Null; Write-Host 'Windows 投影已重建。' }
    }
    if ($ClearStaleClient) {
        $answer = Read-Host '仅清理已确认 stale 的 Agent lock。输入 YES 确认'
        if ($answer -eq 'YES') {
            & wsl.exe -d $runtime.wsl_distribution -- bash $runtime.agent_launcher_wsl --clear-stale $ClearStaleClient
            if ($LASTEXITCODE -ne 0) { throw 'stale Agent lock was not cleared' }
            Write-OpsLog -Root $root -Event 'stale-agent-lock-cleared' -Data @{ client_id=$ClearStaleClient }
        }
    }
    if ($checks.ok -contains $false) { exit 1 }
    exit 0
} catch {
    Write-OpsUserFailure -Root $root -Step '运行环境诊断' -Exception $_ -ExitCode 2
    exit 2
}
