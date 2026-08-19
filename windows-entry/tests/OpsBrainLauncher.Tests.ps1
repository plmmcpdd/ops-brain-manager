Describe 'Ops Brain Windows launcher source' {
    It 'uses explicit JSON mode for create and attach before canonical show and projection' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        if (-not $sourceRoot) { throw 'OPS_BRAIN_LAUNCHER_SOURCE must point to windows-entry.' }
        $entry = Get-Content -LiteralPath (Join-Path $sourceRoot 'templates\new_ops_client_entry.ps1') -Raw -Encoding UTF8
        $entry | Should -Match "@\('create',[^\r\n]+?'--json'\)"
        $entry | Should -Match "@\('attach',[^\r\n]+?'--json'\)"
        $entry | Should -Match '@\(''show'', ''--client'', \$name, ''--json''\)'
        $entry | Should -Match 'New-OpsProjection -Root \$root -Client \$show\.Payload\.data'
    }
    It 'parses successful create JSON without the invalid JSON regression' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        if (-not $sourceRoot) { throw 'OPS_BRAIN_LAUNCHER_SOURCE must point to windows-entry.' }
        $temp = Join-Path $env:TEMP ('ops-brain-create-json-' + [guid]::NewGuid().ToString())
        try {
            New-Item -ItemType Directory -Path $temp -Force | Out-Null
            $shim = Join-Path $temp 'manager-json-shim.ps1'
            $shimText = "param()`r`nWrite-Output '{`"ok`":true,`"code`":`"ok`",`"data`":{`"client_id`":`"regression`",`"display_name`":`"Regression`",`"workspace`":`"/tmp/regression`",`"status`":`"active`",`"origin`":`"created`"},`"error`":null}'`r`nexit 0`r`n"
            [System.IO.File]::WriteAllText($shim, $shimText, (New-Object System.Text.UTF8Encoding($false)))
            Import-Module (Join-Path $sourceRoot 'launcher\OpsBrainLauncher.psm1') -Force
            $runtime = [pscustomobject]@{ wsl_distribution='Ubuntu-E'; manager_wsl_path='/tmp/manager' }
            $result = Invoke-OpsManagerJson -Runtime $runtime -ManagerArguments @('create','--name','Regression','--workspace','/tmp/regression','--json') -WslCommand $shim
            $result.ExitCode | Should -Be 0
            $result.Payload.ok | Should -BeTrue
            $result.Payload.data.origin | Should -Be 'created'
        } catch {
            $_.Exception.Message | Should -Not -Match 'Manager returned invalid JSON \(exit 0\)'
            throw
        } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
    }
    It 'executes mocked create and attach JSON through canonical show and projection' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        if (-not $sourceRoot) { throw 'OPS_BRAIN_LAUNCHER_SOURCE must point to windows-entry.' }
        $temp = Join-Path $env:TEMP ('ops-brain-new-client-flow-' + [guid]::NewGuid().ToString())
        try {
            New-Item -ItemType Directory -Path $temp -Force | Out-Null
            $shim = Join-Path $temp 'manager-flow-shim.ps1'
            $shimText = @'
$command = @($args | Where-Object { $_ -in @('create','attach','show') } | Select-Object -First 1)
$origin = if ($command -eq 'attach') { 'attached' } else { 'created' }
Write-Output ('{"ok":true,"code":"ok","data":{"client_id":"flow-client","display_name":"Flow Client","workspace":"/tmp/flow-client","status":"active","origin":"' + $origin + '"},"error":null}')
exit 0
'@
            [System.IO.File]::WriteAllText($shim, $shimText, (New-Object System.Text.UTF8Encoding($false)))
            Import-Module (Join-Path $sourceRoot 'launcher\OpsBrainLauncher.psm1') -Force
            $runtime = [pscustomobject]@{ wsl_distribution='Ubuntu-E'; manager_wsl_path='/tmp/manager' }
            $created = Invoke-OpsManagerJson -Runtime $runtime -ManagerArguments @('create','--name','Flow Client','--workspace','/tmp/flow-client','--json') -WslCommand $shim
            $created.Payload.ok | Should -BeTrue
            $created.Payload.data.origin | Should -Be 'created'
            $attached = Invoke-OpsManagerJson -Runtime $runtime -ManagerArguments @('attach','--name','Flow Client','--workspace','/tmp/flow-client','--json') -WslCommand $shim
            $attached.Payload.ok | Should -BeTrue
            $attached.Payload.data.origin | Should -Be 'attached'
            $show = Invoke-OpsManagerJson -Runtime $runtime -ManagerArguments @('show','--client','Flow Client','--json') -WslCommand $shim
            $projection = New-OpsProjection -Root $temp -Client $show.Payload.data
            $projection | Should -Be (Join-Path $temp '客户\flow-client')
            Test-Path -LiteralPath (Join-Path $projection '客户信息.json') | Should -BeTrue
            Test-Path -LiteralPath (Join-Path $projection '打开运营大脑.cmd') | Should -BeTrue
        } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
    }
    It 'contains no bash -lc command construction' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        if (-not $sourceRoot) { throw 'OPS_BRAIN_LAUNCHER_SOURCE must point to windows-entry.' }
        $module = Get-Content -LiteralPath (Join-Path $sourceRoot 'launcher\OpsBrainLauncher.psm1') -Raw -Encoding UTF8
        $module | Should -Not -Match 'bash\s+-lc'
    }
    It 'accepts Unicode projection IDs and rejects unsafe or escaping segments' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        if (-not $sourceRoot) { throw 'OPS_BRAIN_LAUNCHER_SOURCE must point to windows-entry.' }
        $temp = Join-Path $env:TEMP ('ops-brain-projection-id-' + [guid]::NewGuid().ToString())
        try {
            Import-Module (Join-Path $sourceRoot 'launcher\OpsBrainLauncher.psm1') -Force
            foreach ($clientId in @('ascii-client','client_01','小红书一号测试客户','美国移民-01')) {
                $client = [pscustomobject]@{ client_id=$clientId; display_name=$clientId; workspace='/tmp/workspace'; status='active'; origin='created' }
                Get-ProjectionRoot -Root $temp -Client $client | Should -Be (Join-Path $temp ('客户\' + $clientId))
            }
            foreach ($clientId in @('', '.', '..', '../escape', 'a/b', 'a\b', "a`nb", "a`rb", ([string][char]1), 'con', 'NUL')) {
                $client = [pscustomobject]@{ client_id=$clientId; display_name='Unsafe'; workspace='/tmp/workspace'; status='active'; origin='created' }
                { Get-ProjectionRoot -Root $temp -Client $client } | Should -Throw
            }
        } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
    }
    It 'uses the required Remote WSL and absolute path workspace contract' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        if (-not $sourceRoot) { throw 'OPS_BRAIN_LAUNCHER_SOURCE must point to windows-entry.' }
        $client = Get-Content -LiteralPath (Join-Path $sourceRoot 'templates\open_ops_client.ps1') -Raw -Encoding UTF8
        $module = Get-Content -LiteralPath (Join-Path $sourceRoot 'launcher\OpsBrainLauncher.psm1') -Raw -Encoding UTF8
        $client | Should -Match '--new-window'
        $client | Should -Match '--remote'
        $module | Should -Match 'folders=@'
        $module | Should -Match 'path=\[string\]\$Launch.workspace'
    }
    It 'passes the non-Pester fallback checks' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        if (-not $sourceRoot) { throw 'OPS_BRAIN_LAUNCHER_SOURCE must point to windows-entry.' }
        & (Join-Path $PSScriptRoot 'run_launcher_fallback.ps1')
        $LASTEXITCODE | Should -Be 0
    }
    It 'writes BOM customer PowerShell entries and ASCII CRLF customer CMD files' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        $temp = Join-Path $env:TEMP ('ops-brain-encoding-' + [guid]::NewGuid().ToString())
        try {
            & (Join-Path $sourceRoot 'deploy_windows_entry.ps1') -TargetRoot $temp
            $module = Join-Path $temp '系统文件_请勿修改\Launcher\OpsBrainLauncher.psm1'
            Import-Module $module -Force
            $client = [pscustomobject]@{ client_id='中文客户'; display_name='中文 客户'; workspace='/tmp/中文客户'; status='active'; origin='created' }
            $projection = New-OpsProjection -Root $temp -Client $client
            $entryBytes = [System.IO.File]::ReadAllBytes((Join-Path $projection 'open_ops_brain_entry.ps1'))
            @($entryBytes[0], $entryBytes[1], $entryBytes[2]) | Should -Be @(239,187,191)
            $cmdBytes = [System.IO.File]::ReadAllBytes((Join-Path $projection '打开运营大脑.cmd'))
            ($cmdBytes | Where-Object { $_ -gt 127 }).Count | Should -Be 0
            @($cmdBytes[0], $cmdBytes[1], $cmdBytes[2]) | Should -Not -Be @(239,187,191)
            [System.Text.Encoding]::ASCII.GetString($cmdBytes) | Should -Match "`r`n"
            $workspace = New-OpsWorkspace -ProjectionRoot $projection -Launch ([pscustomobject]@{ client_id='中文客户'; display_name='中文 客户'; workspace='/tmp/中文客户' }) -Runtime ([pscustomobject]@{ auto_start_agent=$false })
            $workspaceBytes = [System.IO.File]::ReadAllBytes($workspace)
            @($workspaceBytes[0], $workspaceBytes[1], $workspaceBytes[2]) | Should -Not -Be @(239,187,191)
        } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
    }
    It 'runs generated customer PowerShell and CMD entries in TestMode' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        $temp = Join-Path $env:TEMP ('ops-brain-entry-' + [guid]::NewGuid().ToString())
        try {
            & (Join-Path $sourceRoot 'deploy_windows_entry.ps1') -TargetRoot $temp -SyncProjections
            $env:OPS_BRAIN_TEST_MODE = '1'
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $temp '客户\austin-hvac-demo\open_ops_brain_entry.ps1')
            $LASTEXITCODE | Should -Be 0
            & cmd.exe /c (Join-Path $temp '客户\austin-hvac-demo\打开运营大脑.cmd')
            $LASTEXITCODE | Should -Be 0
        } finally { Remove-Item Env:OPS_BRAIN_TEST_MODE -ErrorAction SilentlyContinue; if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
    }
    It 'generates an Agent folderOpen task with an explicit bootstrap path but no inline prompt' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        $temp = Join-Path $env:TEMP ('ops-brain-task-' + [guid]::NewGuid().ToString())
        try {
            Import-Module (Join-Path $sourceRoot 'launcher\OpsBrainLauncher.psm1') -Force
            $launch = [pscustomobject]@{ client_id='client-a'; display_name='Client A'; workspace='/tmp/client-a' }
            New-Item -ItemType Directory -Path (Join-Path $temp '.ops-launch') -Force | Out-Null
            Write-Utf8TextNoBom -LiteralPath (Join-Path $temp '.ops-launch\initial_prompt.txt') -Text (Get-OpsBootstrapText -Client $launch)
            $disabled = New-OpsWorkspace -ProjectionRoot $temp -Launch $launch -Runtime ([pscustomobject]@{ auto_start_agent=$false })
            (Get-Content -LiteralPath $disabled -Raw -Encoding UTF8 | ConvertFrom-Json).PSObject.Properties.Name | Should -Not -Contain 'tasks'
            $enabled = New-OpsWorkspace -ProjectionRoot $temp -Launch $launch -Runtime ([pscustomobject]@{ auto_start_agent=$true; agent_launcher_wsl='/tmp/launch_ops_agent.sh'; agent_command_wsl='/tmp/claude-deepseek' })
            $data = Get-Content -LiteralPath $enabled -Raw -Encoding UTF8 | ConvertFrom-Json
            $task = $data.tasks.tasks[0]
            $task.command | Should -Be 'bash'
            $task.options.cwd | Should -Be '/tmp/client-a'
            $task.runOptions.runOn | Should -Be 'folderOpen'
            $task.runOptions.instanceLimit | Should -Be 1
            $task.args.Count | Should -Be 5
            $task.args[4] | Should -Match '/\.ops-launch/initial_prompt\.txt$'
            ($task.args[0..3] -join ' ') | Should -Not -Match 'prompt|token|key'
        } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
    }
    It 'keeps WSL stderr separate from Manager JSON stdout and finds fallback code.cmd' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        $temp = Join-Path $env:TEMP ('ops-brain-streams-' + [guid]::NewGuid().ToString())
        $oldLocal = $env:LOCALAPPDATA
        $oldPath = $env:PATH
        try {
            New-Item -ItemType Directory -Path $temp -Force | Out-Null
            $shim = Join-Path $temp 'wsl-shim.ps1'
            [System.IO.File]::WriteAllText($shim, "param()`r`nWrite-Output '{""ok"":true,""code"":""ok"",""data"":{},""error"":null}'`r`nWrite-Error -Message 'harmless warning' -ErrorAction Continue`r`nexit 0`r`n", (New-Object System.Text.UTF8Encoding($false)))
            Import-Module (Join-Path $sourceRoot 'launcher\OpsBrainLauncher.psm1') -Force
            $runtime = [pscustomobject]@{ wsl_distribution='Ubuntu-E'; manager_wsl_path='/tmp/manager' }
            $result = Invoke-OpsManagerJson -Runtime $runtime -ManagerArguments @('doctor','--json') -WslCommand $shim
            $result.Payload.ok | Should -BeTrue
            $result.Stderr | Should -Match 'harmless warning'
            $fallback = Join-Path $temp 'Programs\Microsoft VS Code\bin'
            New-Item -ItemType Directory -Path $fallback -Force | Out-Null
            $fallbackCode = Join-Path $fallback 'code.cmd'
            [System.IO.File]::WriteAllText($fallbackCode, "@echo off`r`n", [System.Text.Encoding]::ASCII)
            $env:LOCALAPPDATA = $temp
            $env:PATH = ''
            (Get-OpsCodeCommand).Source | Should -Be $fallbackCode
        } finally {
            $env:LOCALAPPDATA = $oldLocal; $env:PATH = $oldPath
            if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
        }
    }
    It 'returns visible nonzero output through customer CMD when the shared script is missing' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        $temp = Join-Path $env:TEMP ('ops-brain-failure-' + [guid]::NewGuid().ToString())
        try {
            & (Join-Path $sourceRoot 'deploy_windows_entry.ps1') -TargetRoot $temp -SyncProjections
            Remove-Item -LiteralPath (Join-Path $temp '系统文件_请勿修改\Launcher\open_ops_client.ps1') -Force
            $env:OPS_BRAIN_TEST_MODE = '1'
            $output = & cmd.exe /c (Join-Path $temp '客户\austin-hvac-demo\打开运营大脑.cmd') 2>&1
            $LASTEXITCODE | Should -Not -Be 0
            (@($output) -join "`n") | Should -Not -BeNullOrEmpty
            (@($output) -join "`n") | Should -Match 'Ops Brain launch failed'
        } finally { Remove-Item Env:OPS_BRAIN_TEST_MODE -ErrorAction SilentlyContinue; if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
    }
    It 'shows shared capabilities without making them part of core checks' {
        $sourceRoot = $env:OPS_BRAIN_LAUNCHER_SOURCE
        $repair = Get-Content -LiteralPath (Join-Path $sourceRoot 'templates\repair_ops_runtime_entry.ps1') -Raw -Encoding UTF8
        $repair | Should -Match "@\('capabilities', '--json'\)"
        $repair | Should -Match 'Shared Intelligence Capabilities \(non-blocking\)'
        $repair | Should -Not -Match "checks.*capabilit"
        $repair | Should -Match 'test -x \$runtime\.agent_command_wsl'
        $repair | Should -Not -Match 'which claude-deepseek'
    }
}
