$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$managerRoot = Split-Path -Parent $sourceRoot
$wslTemp = (& wsl.exe -d Ubuntu-E -- mktemp -d /tmp/ops-brain-shared-e2e.XXXXXX).Trim()
$windowsTemp = Join-Path $env:TEMP ('ops-brain-shared-e2e-' + [guid]::NewGuid().ToString('N'))
try {
    if ($wslTemp -notmatch '^/tmp/ops-brain-shared-e2e\.[A-Za-z0-9]+$') { throw "Unexpected WSL temp path: $wslTemp" }
    New-Item -ItemType Directory -Path $windowsTemp -Force | Out-Null
    $registry = $wslTemp + '/registry.json'
    $workspace = $wslTemp + '/workspace'
    $managerWsl = ($managerRoot -replace '\\','/' -replace '^//wsl.localhost/Ubuntu-E','') + '/ops_brain.py'
    $raw = & wsl.exe -d Ubuntu-E -- python3 $managerWsl --registry $registry create --name 'Future Shared Capability Client' --workspace $workspace --json
    if ($LASTEXITCODE -ne 0) { throw 'temporary Manager create failed' }
    $created = (@($raw) -join "`n") | ConvertFrom-Json
    Import-Module (Join-Path $sourceRoot 'launcher\OpsBrainLauncher.psm1') -Force
    $projection = New-OpsProjection -Root $windowsTemp -Client $created.data
    $runtime = [pscustomobject]@{
        auto_start_agent = $true
        agent_launcher_wsl = '/home/rong/projects/content-ops-lab/ops-brain-manager/windows-entry/launcher/launch_ops_agent.sh'
        agent_command_wsl = '/home/rong/.local/bin/claude-deepseek'
    }
    $codeWorkspace = New-OpsWorkspace -ProjectionRoot $projection -Launch $created.data -Runtime $runtime
    $authorityPlugin = ($managerRoot -replace '\\','/' -replace '^//wsl.localhost/Ubuntu-E','') + '/runtime/ops-brain-runtime'
    $events = & wsl.exe -d Ubuntu-E --cd $workspace -- /home/rong/.local/bin/claude-deepseek --setting-sources project --plugin-dir $authorityPlugin --agent ops-brain-runtime:ops-brain-core --disable-slash-commands --add-dir /home/rong/tools/cheat-on-content --add-dir /home/rong/.claude/skills/social-account-doctor/scripts --add-dir /home/rong/.claude/skills/social-account-doctor/references --disallowedTools Write,Edit,Bash,WebFetch,WebSearch --no-session-persistence --max-budget-usd 0.02 --output-format stream-json --verbose -p 'Reply OK only.'
    if ($LASTEXITCODE -ne 0) { throw 'Claude discovery smoke failed' }
    $init = (@($events)[0] | ConvertFrom-Json)
    if ($init.type -ne 'system' -or $init.subtype -ne 'init') { throw 'Claude init event missing' }
    if ($init.skills -contains 'social-account-doctor') { throw 'root Doctor Skill bypass is available' }
    if ($init.tools -contains 'Skill') { throw 'root generic Skill tool is available' }
    if ($init.agents -notcontains 'ops-brain-runtime:doctor-evidence') { throw 'doctor-evidence subagent is not registered' }
    if (Test-Path -LiteralPath (Join-Path $windowsTemp 'workspace\.claude\skills\social-account-doctor')) { throw 'Skill was copied into client workspace' }
    [pscustomobject]@{
        client_id = $created.data.client_id
        projection = (Test-Path -LiteralPath $projection)
        code_workspace = (Test-Path -LiteralPath $codeWorkspace)
        root_doctor_skill_available = $false
        root_skill_tool_available = $false
        doctor_subagent_registered = $true
        per_client_install = $false
    } | ConvertTo-Json -Compress
} finally {
    if ($wslTemp -match '^/tmp/ops-brain-shared-e2e\.[A-Za-z0-9]+$') { & wsl.exe -d Ubuntu-E -- rm -rf -- $wslTemp }
    if (Test-Path -LiteralPath $windowsTemp) { Remove-Item -LiteralPath $windowsTemp -Recurse -Force }
}
