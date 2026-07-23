Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Utf8NoBom {
    param([Parameter(Mandatory=$true)][string]$LiteralPath, [Parameter(Mandatory=$true)]$Value)
    $parent = Split-Path -Parent $LiteralPath
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($LiteralPath, ($Value | ConvertTo-Json -Depth 8), $encoding)
}

function Write-Utf8TextNoBom {
    param([Parameter(Mandatory=$true)][string]$LiteralPath, [Parameter(Mandatory=$true)][string]$Text)
    $parent = Split-Path -Parent $LiteralPath
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($LiteralPath, $Text, $encoding)
}

function Write-Utf8TextWithBom {
    param([Parameter(Mandatory=$true)][string]$LiteralPath, [Parameter(Mandatory=$true)][string]$Text)
    $parent = Split-Path -Parent $LiteralPath
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $encoding = New-Object System.Text.UTF8Encoding($true)
    [System.IO.File]::WriteAllText($LiteralPath, $Text, $encoding)
}

function Write-AsciiCmd {
    param([Parameter(Mandatory=$true)][string]$LiteralPath, [Parameter(Mandatory=$true)][string]$Text)
    if ($Text -match '[^\x00-\x7F]') { throw "CMD template must be ASCII: $LiteralPath" }
    $parent = Split-Path -Parent $LiteralPath
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $crlf = ($Text -replace "`r?`n", "`r`n")
    [System.IO.File]::WriteAllText($LiteralPath, $crlf, [System.Text.Encoding]::ASCII)
}

function Get-OpsRuntime {
    param([Parameter(Mandatory=$true)][string]$Root)
    $path = Join-Path $Root '配置\runtime.json'
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing runtime configuration: $path" }
    return (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Write-OpsLog {
    param([Parameter(Mandatory=$true)][string]$Root, [Parameter(Mandatory=$true)][string]$Event, [hashtable]$Data=@{})
    $record = [ordered]@{ timestamp=(Get-Date).ToUniversalTime().ToString('o'); event=$Event; data=$Data }
    $path = Join-Path $Root ('日志\launcher-' + (Get-Date -Format 'yyyyMMdd') + '.jsonl')
    $line = $record | ConvertTo-Json -Compress -Depth 6
    $parent = Split-Path -Parent $path
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    [System.IO.File]::AppendAllText($path, ($line + [Environment]::NewLine), (New-Object System.Text.UTF8Encoding($false)))
}

function Write-OpsUserFailure {
    param([Parameter(Mandatory=$true)][string]$Root, [Parameter(Mandatory=$true)][string]$Step, [Parameter(Mandatory=$true)]$Exception, [int]$ExitCode=2)
    $reason = [string]$Exception.Exception.Message
    Write-OpsLog -Root $Root -Event 'launch-failed' -Data @{ step=$Step; exit_code=$ExitCode; reason=$reason }
    Write-Host ("运营大脑启动失败：" + $Step) -ForegroundColor Red
    Write-Host ("原因：" + $reason) -ForegroundColor Red
    Write-Host ("错误码：" + $ExitCode) -ForegroundColor Red
    Write-Host '建议：请运行“修复运行环境.cmd”查看诊断。' -ForegroundColor Red
}

function Invoke-OpsManagerJson {
    param([Parameter(Mandatory=$true)]$Runtime, [Parameter(Mandatory=$true)][string[]]$ManagerArguments, [string]$WslCommand='wsl.exe')
    $arguments = @('-d', [string]$Runtime.wsl_distribution, '--', 'python3', ([string]$Runtime.manager_wsl_path + '/ops_brain.py')) + $ManagerArguments
    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $raw = & $WslCommand @arguments 2> $stderrPath
        $exitCode = $LASTEXITCODE
        $stderr = [System.IO.File]::ReadAllText($stderrPath)
        $text = @($raw) -join "`n"
        try { $payload = $text | ConvertFrom-Json } catch {
            $detail = if ($stderr) { $stderr.Trim() } else { $text }
            throw "Manager returned invalid JSON (exit $exitCode): $detail"
        }
        if ($null -eq $payload) { throw "Manager returned no JSON (exit $exitCode)" }
        return [pscustomobject]@{ ExitCode=$exitCode; Payload=$payload; Arguments=$arguments; Stderr=$stderr }
    } finally {
        if (Test-Path -LiteralPath $stderrPath) { Remove-Item -LiteralPath $stderrPath -Force }
    }
}

function Get-OpsManagerFailureMessage {
    param([Parameter(Mandatory=$true)]$Result, [Parameter(Mandatory=$true)][string]$Fallback)
    if ($null -ne $Result.Payload -and $Result.Payload.error) { return [string]$Result.Payload.error }
    if ($Result.Stderr) { return [string]$Result.Stderr.Trim() }
    return ($Fallback + ' (exit ' + [string]$Result.ExitCode + ')')
}

function Get-OpsCodeCommand {
    $command = Get-Command code.cmd -ErrorAction SilentlyContinue
    if ($null -ne $command) { return [pscustomobject]@{ Source=$command.Source; Discovery='PATH' } }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Microsoft VS Code\bin\code.cmd'),
        (Join-Path $env:ProgramFiles 'Microsoft VS Code\bin\code.cmd')
    )
    if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} 'Microsoft VS Code\bin\code.cmd') }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return [pscustomobject]@{ Source=$candidate; Discovery='fallback' } }
    }
    return $null
}

function Convert-WindowsPathToWsl {
    param([Parameter(Mandatory=$true)]$Runtime, [Parameter(Mandatory=$true)][string]$LiteralPath)
    $full = [System.IO.Path]::GetFullPath($LiteralPath)
    if ($full -notmatch '^([A-Za-z]):\\(.*)$') { throw "Only local drive paths can be converted: $LiteralPath" }
    $drive = $Matches[1].ToLowerInvariant()
    $tail = $Matches[2] -replace '\\', '/'
    return ('/mnt/' + $drive + '/' + $tail)
}

function Get-ProjectionRoot {
    param([Parameter(Mandatory=$true)][string]$Root, [Parameter(Mandatory=$true)]$Client)
    $folder = if ($Client.status -eq 'archived') { '已归档客户' } else { '客户' }
    return (Join-Path (Join-Path $Root $folder) $Client.client_id)
}

function New-OpsProjection {
    param([Parameter(Mandatory=$true)][string]$Root, [Parameter(Mandatory=$true)]$Client)
    $projection = Get-ProjectionRoot -Root $Root -Client $Client
    $archiveRoot = Join-Path (Join-Path $Root '已归档客户') $Client.client_id
    $activeRoot = Join-Path (Join-Path $Root '客户') $Client.client_id
    $other = if ($projection -eq $archiveRoot) { $activeRoot } else { $archiveRoot }
    if ((Test-Path -LiteralPath $other) -and -not (Test-Path -LiteralPath $projection)) {
        Move-Item -LiteralPath $other -Destination $projection
    }
    New-Item -ItemType Directory -Path (Join-Path $projection '.ops-launch\logs') -Force | Out-Null
    $info = [ordered]@{ version=1; client_id=$Client.client_id; display_name=$Client.display_name; workspace=$Client.workspace; status=$Client.status; synced_at=(Get-Date).ToUniversalTime().ToString('o') }
    Write-Utf8NoBom -LiteralPath (Join-Path $projection '客户信息.json') -Value $info
    Write-Utf8TextNoBom -LiteralPath (Join-Path $projection '.ops-launch\initial_prompt.txt') -Text ("当前客户：" + $Client.display_name + "`n当前工作区：" + $Client.workspace + "`n请先读取并报告当前Cheat状态。在用户给出明确任务前，不要自动执行生产动作。不得修改共享Cheat Runtime。`n")
    Write-AsciiCmd -LiteralPath (Join-Path $projection '打开运营大脑.cmd') -Text '@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0open_ops_brain_entry.ps1"
set "OPS_EXIT=%ERRORLEVEL%"
if not "%OPS_EXIT%"=="0" (
    echo.
    echo Ops Brain launch failed. Exit code: %OPS_EXIT%
    echo Run the repair entry from the Ops Brain root.
    if not "%OPS_BRAIN_TEST_MODE%"=="1" pause
)
exit /b %OPS_EXIT%
'
    $entry = @'
param()
try {
    $root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $parameters = @{ ProjectionRoot=$PSScriptRoot }
    if ($env:OPS_BRAIN_TEST_MODE -eq '1') { $parameters.TestMode = $true }
    & (Join-Path $root "系统文件_请勿修改\Launcher\open_ops_client.ps1") @parameters
    exit $LASTEXITCODE
} catch {
    Write-Host ("运营大脑入口失败：" + $_.Exception.Message) -ForegroundColor Red
    Write-Host '建议：请运行“修复运行环境.cmd”查看诊断。' -ForegroundColor Red
    exit 2
}
'@
    Write-Utf8TextWithBom -LiteralPath (Join-Path $projection 'open_ops_brain_entry.ps1') -Text $entry
    return $projection
}

function Sync-OpsProjections {
    param([Parameter(Mandatory=$true)][string]$Root, [Parameter(Mandatory=$true)]$Runtime)
    $result = Invoke-OpsManagerJson -Runtime $Runtime -ManagerArguments @('list', '--all', '--json')
    if ($result.ExitCode -ne 0 -or -not $result.Payload.ok) { throw (Get-OpsManagerFailureMessage -Result $result -Fallback 'Cannot list clients for projection sync') }
    foreach ($client in $result.Payload.data.clients) { New-OpsProjection -Root $Root -Client $client | Out-Null }
    return $result.Payload.data.clients
}

function Test-OpsProjectionIdentity {
    param([Parameter(Mandatory=$true)][string]$ProjectionRoot, [Parameter(Mandatory=$true)]$Runtime)
    $directoryId = Split-Path -Leaf $ProjectionRoot
    $infoPath = Join-Path $ProjectionRoot '客户信息.json'
    if (-not (Test-Path -LiteralPath $infoPath)) { throw "Missing projection identity file: $infoPath" }
    $info = Get-Content -LiteralPath $infoPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $resolved = Invoke-OpsManagerJson -Runtime $Runtime -ManagerArguments @('resolve-launch', '--client', [string]$directoryId, '--json')
    if ($resolved.ExitCode -ne 0 -or -not $resolved.Payload.ok) { throw (Get-OpsManagerFailureMessage -Result $resolved -Fallback 'Cannot resolve client launch identity') }
    $launch = $resolved.Payload.data
    if ($directoryId -ne $info.client_id -or $directoryId -ne $launch.client_id -or $info.workspace -ne $launch.workspace) { throw "Projection identity mismatch; launch refused" }
    if (-not $launch.launch_allowed -or $launch.status -ne 'active' -or -not $launch.workspace_exists) { throw "Launch refused: $($launch.reason)" }
    return $launch
}

function New-OpsWorkspace {
    param([Parameter(Mandatory=$true)][string]$ProjectionRoot, [Parameter(Mandatory=$true)]$Launch, [Parameter(Mandatory=$true)]$Runtime)
    $workspace = [ordered]@{ folders=@(@{ name=('运营工作区 - ' + [string]$Launch.display_name); path=[string]$Launch.workspace }) }
    if ([bool]$Runtime.auto_start_agent) {
        $workspace.settings = [ordered]@{ 'task.allowAutomaticTasks'='on' }
        $workspace.tasks = [ordered]@{ version='2.0.0'; tasks=@([ordered]@{
            label='启动运营大脑 Agent'; type='process'; command='bash'
            args=@([string]$Runtime.agent_launcher_wsl, [string]$Launch.client_id, [string]$Launch.workspace, [string]$Runtime.agent_command_wsl)
            options=[ordered]@{ cwd=[string]$Launch.workspace }
            presentation=[ordered]@{ reveal='always'; focus=$true; panel='dedicated'; showReuseMessage=$false; clear=$false }
            runOptions=[ordered]@{ runOn='folderOpen'; instanceLimit=1 }
            problemMatcher=@()
        }) }
    }
    $path = Join-Path $ProjectionRoot '.ops-launch\运营大脑工作台.code-workspace'
    Write-Utf8NoBom -LiteralPath $path -Value $workspace
    return $path
}

Export-ModuleMember -Function *
