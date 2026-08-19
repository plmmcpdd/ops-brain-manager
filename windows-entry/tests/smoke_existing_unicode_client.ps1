param([Parameter(Mandatory=$true)][string]$WindowsRoot)
$ErrorActionPreference = 'Stop'
$clientName = [regex]::Unescape('\u5c0f\u7ea2\u4e66\u4e00\u53f7\u6d4b\u8bd5\u5ba2\u6237')
$clientsFolder = [regex]::Unescape('\u5ba2\u6237')
$systemFolder = [regex]::Unescape('\u7cfb\u7edf\u6587\u4ef6_\u8bf7\u52ff\u4fee\u6539')
$projection = Join-Path (Join-Path $WindowsRoot $clientsFolder) $clientName
Import-Module (Join-Path $WindowsRoot ($systemFolder + '\Launcher\OpsBrainLauncher.psm1')) -Force
$runtime = Get-OpsRuntime -Root $WindowsRoot
$launch = Test-OpsProjectionIdentity -ProjectionRoot $projection -Runtime $runtime
$codeWorkspace = New-OpsWorkspace -ProjectionRoot $projection -Launch $launch -Runtime $runtime
$task = (Get-Content -LiteralPath $codeWorkspace -Raw -Encoding UTF8 | ConvertFrom-Json).tasks.tasks[0]
$wslTemp = & wsl.exe -d $runtime.wsl_distribution -- mktemp -d /tmp/ops-brain-existing-unicode.XXXXXX
if ($LASTEXITCODE -ne 0) { throw 'Cannot create existing-client smoke root.' }
try {
    $setup = @'
mkdir -p "$1/.config/claude-deepseek" "$1/bin"
: > "$1/.config/claude-deepseek/env"
printf '#!/usr/bin/env bash\nexit 0\n' > "$1/bin/claude"
chmod +x "$1/bin/claude"
printf '#!/usr/bin/env bash\ncp "$OPS_BRAIN_AGENT_STATE_ROOT/$OPS_BRAIN_EXPECTED_CLIENT_ID.lock/metadata.json" "$OPS_BRAIN_METADATA_COPY"\nprintf reached > "$OPS_BRAIN_RESULT"\n' > "$2"
chmod +x "$2"
'@
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($setup))
    $command = "echo $encoded | base64 -d | bash -s -- '$wslTemp/home' '$wslTemp/mock-agent'"
    & wsl.exe -d $runtime.wsl_distribution -- bash -lc $command
    if ($LASTEXITCODE -ne 0) { throw 'Existing-client fixture setup failed.' }
    & wsl.exe -d $runtime.wsl_distribution -- env "HOME=$wslTemp/home" "OPS_BRAIN_BASE_CLAUDE=$wslTemp/home/bin/claude" "OPS_BRAIN_AGENT_STATE_ROOT=$wslTemp/state" "OPS_BRAIN_EXPECTED_CLIENT_ID=$clientName" "OPS_BRAIN_METADATA_COPY=$wslTemp/metadata.json" "OPS_BRAIN_RESULT=$wslTemp/result" bash $runtime.agent_launcher_wsl $clientName $launch.workspace "$wslTemp/mock-agent" $task.args[4]
    if ($LASTEXITCODE -ne 0) { throw 'Existing Unicode mock launch failed.' }
    $result = & wsl.exe -d $runtime.wsl_distribution -- cat "$wslTemp/result"
    $metadata = ((& wsl.exe -d $runtime.wsl_distribution -- cat "$wslTemp/metadata.json") -join "`n") | ConvertFrom-Json
    & wsl.exe -d $runtime.wsl_distribution -- test -e "$wslTemp/state/$clientName.lock"
    $lockCleaned = $LASTEXITCODE -ne 0
    if ((@($result) -join '') -ne 'reached' -or $metadata.client_id -ne $clientName -or $metadata.workspace -ne $launch.workspace -or -not $lockCleaned) { throw 'Existing Unicode launcher evidence mismatch.' }
    [pscustomobject]@{ client_id=$launch.client_id; workspace=$launch.workspace; resolve_reason=$launch.reason; mock_agent='reached'; metadata_client_id=$metadata.client_id; lock_cleaned=$lockCleaned }
} finally {
    if ($wslTemp -like '/tmp/ops-brain-existing-unicode.*') { & wsl.exe -d $runtime.wsl_distribution -- rm -rf -- $wslTemp }
}
