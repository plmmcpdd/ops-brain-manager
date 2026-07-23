param()
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Import-Module (Join-Path $root '系统文件_请勿修改\Launcher\OpsBrainLauncher.psm1') -Force
try {
    $runtime = Get-OpsRuntime -Root $root
    $result = Invoke-OpsManagerJson -Runtime $runtime -ManagerArguments @('list', '--all', '--json')
    if ($result.ExitCode -ne 0 -or -not $result.Payload.ok) { throw (Get-OpsManagerFailureMessage -Result $result -Fallback 'Cannot read client registry.') }
    foreach ($client in $result.Payload.data.clients) {
        $projection = Get-ProjectionRoot -Root $root -Client $client
        if (-not (Test-Path -LiteralPath $projection)) { Write-Warning ("Missing Windows projection: " + $client.client_id) }
    }
    Write-OpsLog -Root $root -Event 'client-center-opened' -Data @{ clients=@($result.Payload.data.clients).Count }
    Start-Process explorer.exe -ArgumentList @((Join-Path $root '客户'))
    exit 0
} catch {
    Write-OpsUserFailure -Root $root -Step '客户中心打开' -Exception $_ -ExitCode 2
    exit 2
}
