# Offline archived HTML only. No live browser navigation or send capability.
$ErrorActionPreference = 'Stop'
$trialFailureHint = 'PCランナーの準備とNode.jsの導入を確認してください。'
try {
    $trialRepo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
    $trialFrontend = Join-Path $trialRepo 'frontend'
    if (-not (Test-Path -LiteralPath (Join-Path $trialFrontend 'node_modules'))) {
        throw 'PCランナーの準備が必要です。frontendの依存関係とPlaywright Chromiumを導入してください。'
    }
    $trialNpm = Get-Command npm.cmd -ErrorAction Stop
    Add-Type -AssemblyName System.Windows.Forms
    $trialDialog = New-Object System.Windows.Forms.OpenFileDialog
    $trialDialog.Title = 'LeadHiveから保存した入力試行の依頼JSONを選択'
    $trialDialog.Filter = 'JSON files (*.json)|*.json'
    if ($trialDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
    $trialFile = Get-Item -LiteralPath $trialDialog.FileName
    $trialFailureHint = '依頼ファイルは1MB以下のJSONを指定してください。'
    if ($trialFile.Length -gt 1000000) { throw '依頼ファイルが上限を超えています。' }
    try { $trialTask = Get-Content -LiteralPath $trialFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw '依頼JSONを確認してください。' }
    if ($trialTask.PSObject.Properties['transfer']) {
        $trialFailureHint = '信頼するLeadHiveの接続先を、資格情報・パスなしのHTTPS URLで設定してください。'
        $trialConfigDir = Join-Path $env:LOCALAPPDATA 'LeadHive'
        $trialConfig = Join-Path $trialConfigDir 'offline-input-origin.txt'
        $trialOrigin = if (Test-Path -LiteralPath $trialConfig) { (Get-Content -LiteralPath $trialConfig -Raw).Trim() } else { Read-Host '信頼するLeadHiveのHTTPS URLを入力（例 https://YOUR-LEADHIVE-HOST）' }
        $trialUri = [System.Uri]$trialOrigin
        if (-not $trialUri.IsAbsoluteUri -or $trialUri.Scheme -ne 'https' -or $trialUri.Port -ne 443 -or $trialUri.UserInfo -or $trialUri.Query -or $trialUri.Fragment -or $trialUri.AbsolutePath -ne '/') {
            throw '資格情報・パスを含まないHTTPSの接続先を指定してください。'
        }
        $trialOrigin = $trialUri.GetLeftPart([System.UriPartial]::Authority)
        $trialFailureHint = '保存した接続先と依頼の接続先が一致しません。自動転送を停止しました。'
        if ($trialOrigin -ne $trialTask.transfer.origin) { throw '保存した接続先と依頼の接続先が一致しません。自動転送を停止しました。' }
        New-Item -ItemType Directory -Path $trialConfigDir -Force | Out-Null
        [System.IO.File]::WriteAllText($trialConfig, $trialOrigin)
        $env:LEADHIVE_OFFLINE_REPORT_ORIGIN = $trialOrigin
    }
    $env:LEADHIVE_OFFLINE_FORM_INPUT = '1'
    $env:LEADHIVE_OFFLINE_INPUT_FILE = $trialFile.FullName
    Set-Location -LiteralPath $trialFrontend
    $trialFailureHint = '入力試行に失敗しました。上の固定エラーコードと、Playwright Chromiumの導入状態を確認してください。'
    & $trialNpm.Source run trial:offline-form-input
    if ($LASTEXITCODE -ne 0) { throw '入力試行に失敗しました。上のエラーを確認してください。' }
    Write-Host '診断完了。転送状態がRECORDEDならクラウド画面で履歴を更新してください。FAILED/DISABLEDなら結果JSONがPCに残ります。送信・Human承認は行っていません。'
    exit 0
} catch {
    # Never print task JSON, credentials or arbitrary parse errors.
    Write-Host ('実行を停止しました。' + $trialFailureHint)
    exit 1
}
