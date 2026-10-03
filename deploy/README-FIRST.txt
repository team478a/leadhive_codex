LeadHive Windows ローカル版
===========================

このフォルダーは検証済み配布版として管理担当者から受け取って使用します。
初期提供は1社1専用環境、送信停止・Agent OFFです。収集・企業管理・文面準備・承認から始めます。
GitHubのソースZIPや他社の環境ファイルは使用しないでください。

詳しい利用方法
--------------
初めて使う方は「Open-QuickStart.cmd」をダブルクリックしてください。
詳しい機能は「Open-Manual.cmd」でマニュアルを開き、
上から順にお読みください。
最短の開始手順、企業収集、メール・フォーム送信、バックアップ、困ったときの
確認方法をまとめています。

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
- Open-QuickStart.cmd: 初心者向け収集・準備専用ガイド
- Stop-LeadHiveOutbound.cmd: 送信停止を保存（workerは別途Resume）
- Open-Manual.cmd     : 利用マニュアルをメモ帳で開く
- Start-LeadHive.cmd  : 起動してブラウザを開く
- Stop-LeadHive.cmd   : 停止する（データは残ります）
- Update-LeadHive.cmd : 新しい配布パッケージへ更新する
- Backup-LeadHive.cmd : データと暗号化キーをバックアップする
- Restore-LeadHive.cmd: 最新バックアップを確認付きで復元する
- Diagnose-LeadHive.cmd: Docker・WSL・LeadHiveの状態を診断する
- Adopt-LeadHive.cmd  : 環境IDのない旧版を確認して引き継ぐ
- Resume-LeadHive.cmd : 保守後、配送履歴を確認してworkerを再開する
- Import-LeadHiveBackup.cmd : 元PC停止後のbackupを新PCへ移行する
- Repair-LeadHiveInstance.cmd : 検証可能な初回登録失敗を復旧する

初期提供の機能範囲
------------------
メール・フォーム・SMTPテスト・Codex送信引渡しは停止します。
承認キューでHuman承認を記録しても、送信は行われません。
コピー済みの古いCodexタスクや別PCからの送信も実行しないでください。

大切なデータ
------------
「.env.local」には暗号化キーが保存されます。削除したり他人へ渡したりしないでください。
PC交換やアップデートの前には「Backup-LeadHive.cmd」を実行してください。
バックアップは同名のdump、env.local、identity.jsonを一組で保管してください。
別会社の設定やバックアップは利用しないでください。
バックアップ・更新・復元後、workerは停止したままです。定期収集も停止します。
送信停止時は、配送待ちを保持したままResumeで収集・解析だけ再開できます。
送信有効時は未解決配送があると拒否します。初期提供で送信を有効にしないでください。
結果不明の送信は再試行しないでください。
新PCへの移行時は旧PCを停止し、通常インストールではなくImportコマンドを使います。
旧版から更新する場合は、先に元の設定で「Adopt-LeadHive.cmd」を実行します。
環境IDやキーが一致しない場合は停止します。キーを生成し直さず管理担当者へ相談してください。
起動できない場合は「Diagnose-LeadHive.cmd」で診断ファイルを作成してください。

通常の接続先: http://localhost:8787
利用マニュアル: docs\82_LEADHIVE_USER_MANUAL.md
導入・復元の詳細: docs\73_WINDOWS_LOCAL_INSTALLER.md

復元・別PC移行後は再ログインが必要です。Agent credentialも失効します。未処理・承認済みの提案は再作成・再承認してください。過去の承認は自動復活しません。

G1.3: 初期は外部送信停止です。Stop-LeadHiveOutbound.cmdで停止し、Resume-LeadHive.cmdで収集・解析だけ再開できます。旧PCとコピー済みCodex送信タスクも停止してください。

サンプルCSV: docs\acceptance\LEADHIVE_ACCEPTANCE_SAMPLE.csv（架空2件、サイトURLなし）
