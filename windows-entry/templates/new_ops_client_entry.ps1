param()
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Import-Module (Join-Path $root '系统文件_请勿修改\Launcher\OpsBrainLauncher.psm1') -Force
try {
    $runtime = Get-OpsRuntime -Root $root
    $name = Read-Host '客户显示名称'
    $mode = Read-Host '输入 create 或 attach'
    if ($mode -eq 'create') {
        $result = Invoke-OpsManagerJson -Runtime $runtime -ManagerArguments @('create', '--name', $name, '--workspace-root', [string]$runtime.default_client_root_wsl)
    } elseif ($mode -eq 'attach') {
        $workspace = Read-Host '现有 WSL 绝对工作区路径'
        $result = Invoke-OpsManagerJson -Runtime $runtime -ManagerArguments @('attach', '--name', $name, '--workspace', $workspace)
    } else { throw 'Only create or attach is supported.' }
    if ($result.ExitCode -ne 0 -or -not $result.Payload.ok) { throw (Get-OpsManagerFailureMessage -Result $result -Fallback 'Manager rejected the customer request. Registry was not bypassed.') }
    $show = Invoke-OpsManagerJson -Runtime $runtime -ManagerArguments @('show', '--client', $name, '--json')
    if ($show.ExitCode -ne 0 -or -not $show.Payload.ok) { throw (Get-OpsManagerFailureMessage -Result $show -Fallback 'Customer was created but launch identity could not be read.') }
    try {
        New-OpsProjection -Root $root -Client $show.Payload.data | Out-Null
        Write-Host '客户已创建，Windows入口已生成。'
    } catch {
        Write-Error '客户已创建，Windows入口生成失败。请运行部署同步或修复运行环境。'
        exit 3
    }
    exit 0
} catch {
    Write-OpsUserFailure -Root $root -Step '新建客户向导' -Exception $_ -ExitCode 2
    exit 2
}
