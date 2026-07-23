param([Parameter(Mandatory=$true)][string]$ProjectionRoot, [switch]$TestMode)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Import-Module (Join-Path $PSScriptRoot 'OpsBrainLauncher.psm1') -Force
try {
    $runtime = Get-OpsRuntime -Root $root
    $launch = Test-OpsProjectionIdentity -ProjectionRoot $ProjectionRoot -Runtime $runtime
    $workspace = New-OpsWorkspace -ProjectionRoot $ProjectionRoot -Launch $launch -Runtime $runtime
    $workspaceWsl = Convert-WindowsPathToWsl -Runtime $runtime -LiteralPath $workspace
    $code = Get-OpsCodeCommand
    if ($null -eq $code) { throw '未找到 code.cmd。请运行“修复运行环境.cmd”查看 VS Code 诊断。' }
    $arguments = @('--new-window', '--remote', ('wsl+' + [string]$runtime.wsl_distribution), $workspaceWsl)
    Write-OpsLog -Root $root -Event 'launch-prepared' -Data @{ client_id=$launch.client_id; workspace=$launch.workspace; code_arguments=$arguments; test_mode=[bool]$TestMode }
    if ($TestMode) { Write-Output ('TestMode: code.cmd ' + ($arguments -join ' ')); exit 0 }
    & $code.Source @arguments
    exit $LASTEXITCODE
} catch {
    Write-OpsUserFailure -Root $root -Step '客户工作区启动' -Exception $_ -ExitCode 2
    exit 2
}
