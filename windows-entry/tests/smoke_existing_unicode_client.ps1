param([Parameter(Mandatory=$true)][string]$WindowsRoot)
$ErrorActionPreference = 'Stop'
$clientName = [regex]::Unescape('\u5c0f\u7ea2\u4e66\u4e00\u53f7\u6d4b\u8bd5\u5ba2\u6237')
$clientsFolder = [regex]::Unescape('\u5ba2\u6237')
$systemFolder = [regex]::Unescape('\u7cfb\u7edf\u6587\u4ef6_\u8bf7\u52ff\u4fee\u6539')
$projection = Join-Path (Join-Path $WindowsRoot $clientsFolder) $clientName
Import-Module (Join-Path $WindowsRoot ($systemFolder + '\Launcher\OpsBrainLauncher.psm1')) -Force
$runtime = Get-OpsRuntime -Root $WindowsRoot
$resolved = Invoke-OpsManagerJson -Runtime $runtime -ManagerArguments @('resolve-launch', '--client', $clientName, '--json')
if ($resolved.ExitCode -ne 0 -or -not $resolved.Payload.ok) { throw 'Cannot inspect existing Unicode client.' }
$launch = $resolved.Payload.data
if ($launch.launch_allowed -or $launch.runtime.status -ne 'NOT_INITIALIZED') { throw 'Existing Unicode client did not fail closed.' }
[pscustomobject]@{ client_id=$launch.client_id; workspace=$launch.workspace; runtime_status=$launch.runtime.status; launch_allowed=$launch.launch_allowed; fail_closed=$true }
