LeadHive Windows ローカル版
===========================

このフォルダーは、そのままWindows PCへ展開して使用できます。

初回インストール
----------------
1. フォルダーをOneDrive内ではない通常の場所へ展開します。
2. 「Install-LeadHive.cmd」をダブルクリックします。
3. Docker Desktopが未導入の場合は、表示された利用条件を確認します。
4. 画面の案内に沿って管理者メールアドレスとパスワードを設定します。
5. ブラウザが開いたら、作成したアカウントでログインします。

インストーラーは「LeadHive Form Submit」Codex Skillもユーザー領域へ配置します。
Codexに表示されない場合は、Codexを一度再起動してください。

WSL 2の有効化後に再起動を求められた場合は、Windowsを再起動してから
「Install-LeadHive.cmd」をもう一度実行してください。

日常の操作
----------
- Start-LeadHive.cmd  : 起動してブラウザを開く
- Stop-LeadHive.cmd   : 停止する（データは残ります）
- Update-LeadHive.cmd : 新しい配布パッケージへ更新する
- Backup-LeadHive.cmd : データと暗号化キーをバックアップする

Codex支援フォーム
------------------
「承認してCodexタスクをコピー」を押し、確認後にコピーされた内容をCodexへ
貼り付けます。JavaScriptやiframeのフォームを一件ずつ操作できます。
CAPTCHAが表示された場合はCodexが停止するため、画面上で人が完了してください。

大切なデータ
------------
「.env.local」には暗号化キーが保存されます。削除したり他人へ渡したりしないでください。
PC交換やアップデートの前には「Backup-LeadHive.cmd」を実行してください。

通常の接続先: http://localhost:8787
詳細: docs\73_WINDOWS_LOCAL_INSTALLER.md
