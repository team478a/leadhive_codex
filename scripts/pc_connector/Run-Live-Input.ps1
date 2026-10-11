param([string]$InputFile)
$ErrorActionPreference = 'Stop'
try {
    $liveRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
    foreach ($liveName in @('NODE_OPTIONS', 'NODE_PATH', 'NODE_EXTRA_CA_CERTS', 'NODE_TLS_REJECT_UNAUTHORIZED', 'LEADHIVE_OFFLINE_BROWSER_EXECUTABLE')) { [Environment]::SetEnvironmentVariable($liveName, $null, 'Process') }
    if (-not $env:PATHEXT) { $env:PATHEXT = '.COM;.EXE;.BAT;.CMD' }
    $liveNode = Join-Path $liveRoot 'runtime/node.exe'
    if (Test-Path -LiteralPath $liveNode) {
        & $liveNode (Join-Path $PSScriptRoot 'verify-runner.cjs')
        if ($LASTEXITCODE -ne 0) { throw 'Package integrity failure' }
        $env:LEADHIVE_OFFLINE_BROWSER_EXECUTABLE = Join-Path $liveRoot 'runtime/chromium/chrome.exe'
    } else { $liveNode = (Get-Command node.exe -ErrorAction Stop).Source }
    if (-not $InputFile) {
        Add-Type -AssemblyName System.Windows.Forms
        $liveDialog = New-Object System.Windows.Forms.OpenFileDialog
        $liveDialog.Title = 'LeadHiveの実ページ入力専用依頼を選択（送信なし）'
        $liveDialog.Filter = 'JSON files (*.json)|*.json'
        if ($liveDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
        $InputFile = $liveDialog.FileName
    }
    $liveFile = Get-Item -LiteralPath $InputFile
    if ($liveFile.Length -gt 100000) { throw 'Task too large' }
    $liveServer = Read-Host '自分が利用するLeadHiveのHTTPS URLを入力（依頼のURLを無条件に信用しないでください）'
    if ((Read-Host '入力のみ・確認ボタンも送信ボタンも押しません。続行する場合 INPUT と入力') -ne 'INPUT') { exit 0 }
    $env:LEADHIVE_LIVE_FORM_INPUT = '1'
    $env:LEADHIVE_LIVE_INPUT_FILE = $liveFile.FullName
    $env:LEADHIVE_LIVE_INPUT_SERVER = $liveServer.Trim().TrimEnd('/')
    Set-Location -LiteralPath (Join-Path $liveRoot 'frontend')
    & $liveNode node_modules/playwright/cli.js test --config form-lab/live-runner.config.ts
    if ($LASTEXITCODE -ne 0) { throw 'Runner failed' }
    Write-Host '入力診断結果は frontend/test-results/live-input-runner に保存しました。確認・承認・送信は行っていません。'
    exit 0
} catch { Write-Host '停止しました。PCの依存関係・依頼期限・接続先を確認してください。秘密情報は表示していません。'; exit 1 }
