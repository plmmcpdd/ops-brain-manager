param([string]$SourceRoot=(Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$temp = Join-Path $env:TEMP ('ops-brain-unicode-e2e-' + [guid]::NewGuid().ToString())
$wslTemp = & wsl.exe -d Ubuntu-E -- mktemp -d /tmp/ops-brain-unicode-e2e.XXXXXX
if ($LASTEXITCODE -ne 0) { throw 'Cannot create WSL smoke directory.' }
$clientName = [regex]::Unescape('\u5c0f\u7ea2\u4e66\u4e00\u53f7\u6d4b\u8bd5\u5ba2\u6237')
try {
    $registry = "$wslTemp/registry.json"
    $workspace = "$wslTemp/$clientName"
    $manager = '/home/rong/projects/content-ops-lab/ops-brain-manager/ops_brain.py'
    $raw = & wsl.exe -d Ubuntu-E -- python3 $manager --registry $registry create --name $clientName --workspace $workspace --json
    if ($LASTEXITCODE -ne 0) { throw 'Unicode Manager create failed.' }
    $created = (@($raw) -join "`n") | ConvertFrom-Json
    if (-not $created.ok -or $created.data.client_id -ne $clientName) { throw 'Unicode Manager identity mismatch.' }
    $initialized = & wsl.exe -d Ubuntu-E -- python3 $manager --registry $registry runtime initialize --client $clientName --content-form short-text --cadence-days 2 --data-collection manual --pool-status none --benchmark-status none --hooks yes --json
    if ($LASTEXITCODE -ne 0 -or (((@($initialized) -join "`n") | ConvertFrom-Json).data.status -ne 'READY')) { throw 'Unicode runtime initialization failed.' }
    foreach ($arguments in @(
        @('show','--client',$clientName,'--json'),
        @('resolve-launch','--client',$clientName,'--json'),
        @('doctor','--json')
    )) {
        $payload = & wsl.exe -d Ubuntu-E -- python3 $manager --registry $registry @arguments
        if ($LASTEXITCODE -ne 0 -or -not (((@($payload) -join "`n") | ConvertFrom-Json).ok)) { throw "Manager command failed: $($arguments[0])" }
    }
    Import-Module (Join-Path $SourceRoot 'launcher\OpsBrainLauncher.psm1') -Force
    $projection = New-OpsProjection -Root $temp -Client $created.data
    $runtime = [pscustomobject]@{ auto_start_agent=$true; agent_launcher_wsl='/home/rong/projects/content-ops-lab/ops-brain-manager/windows-entry/launcher/launch_ops_agent.sh'; agent_command_wsl="$wslTemp/mock-agent" }
    $codeWorkspace = New-OpsWorkspace -ProjectionRoot $projection -Launch $created.data -Runtime $runtime
    $task = (Get-Content -LiteralPath $codeWorkspace -Raw -Encoding UTF8 | ConvertFrom-Json).tasks.tasks[0]
    if ($task.args[1] -ne $clientName) { throw 'Generated task lost Unicode client_id.' }
    $setup = @'
mkdir -p "$1/.config/claude-deepseek" "$1/bin"
: > "$1/.config/claude-deepseek/env"
printf '#!/usr/bin/env bash\nexit 0\n' > "$1/bin/claude"
chmod +x "$1/bin/claude"
printf '#!/usr/bin/env bash\nprintf started:ok > "$OPS_BRAIN_E2E_RESULT"\n' > "$2"
chmod +x "$2"
'@
    $setupEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($setup))
    $setupCommand = "echo $setupEncoded | base64 -d | bash -s -- '$wslTemp/home' '$wslTemp/mock-agent'"
    & wsl.exe -d Ubuntu-E -- bash -lc $setupCommand
    if ($LASTEXITCODE -ne 0) { throw 'Cannot prepare WSL mock Agent fixture.' }
    & wsl.exe -d Ubuntu-E -- test -x "$wslTemp/mock-agent"
    if ($LASTEXITCODE -ne 0) { throw 'Mock Agent fixture is not executable.' }
    $launcher = '/home/rong/projects/content-ops-lab/ops-brain-manager/windows-entry/launcher/launch_ops_agent.sh'
    & wsl.exe -d Ubuntu-E -- env "HOME=$wslTemp/home" "OPS_BRAIN_BASE_CLAUDE=$wslTemp/home/bin/claude" "OPS_BRAIN_AGENT_STATE_ROOT=$wslTemp/state" "OPS_BRAIN_E2E_RESULT=$wslTemp/result" bash $launcher $clientName $workspace "$wslTemp/mock-agent" $task.args[4]
    if ($LASTEXITCODE -ne 0) { throw 'Unicode Agent launcher smoke failed.' }
    $result = & wsl.exe -d Ubuntu-E -- cat "$wslTemp/result"
    if ((@($result) -join "`n") -notmatch 'started:') { throw 'Mock Agent was not reached.' }
    Write-Output 'Unicode cross-layer E2E smoke passed.'
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
    if ($wslTemp -and $wslTemp -like '/tmp/ops-brain-unicode-e2e.*') { & wsl.exe -d Ubuntu-E -- rm -rf -- $wslTemp }
}
