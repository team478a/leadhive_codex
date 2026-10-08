# Windows初心者向けローカルインストール

## 利用者に必要なもの

- Windows 10または11
- 8GB以上のメモリ（16GB推奨）
- 初回インストール時のインターネット接続

Docker Desktop、Python、Node.js、PostgreSQLを事前に個別インストールする必要はない。LeadHiveのデータ、APIキー、メール設定は利用者のPC内へ保存される。

Codex支援フォームを使う場合は、同じWindowsユーザーでCodexを利用できることが必要。LeadHive専用Skillはインストーラーが自動配置する。

## 初回インストール

1. 管理担当者から検証済みの配布ZIP（VERSION・manifest付き）を受け取り、OneDrive外の通常のフォルダーへ展開する。GitHubのソースZIPは使用しない。
2. `Install-LeadHive.cmd`をダブルクリックする。
3. Docker Desktopが未導入の場合、表示された公式利用条件を確認して同意する。
4. WSL 2の有効化でWindowsの管理者確認が表示された場合は許可する。
5. 再起動を求められた場合はWindowsを再起動し、もう一度`Install-LeadHive.cmd`を実行する。
6. 初回だけ管理者メールアドレスと12文字以上のパスワードを入力する。
7. ブラウザでLeadHiveが自動的に開いたらログインする。

インストーラーは`leadhive-form-submit` Skillを`%USERPROFILE%\.agents\skills`へ配置する。Skillがすぐ表示されない場合はCodexを一度再起動する。`Update-LeadHive.cmd`はアプリと一緒にSkillも更新する。

初回はコンテナイメージの取得とビルドを行うため、数分かかる場合がある。2回目以降は`Start-LeadHive.cmd`で起動する。

## Docker Desktopの自動導入

ウィザードはDocker Desktopの有無を確認し、未導入の場合だけDocker公式サイトからPCのCPUに合うインストーラーを取得する。実行前にWindowsの署名検証でDocker発行のファイルであることを確認する。

- ユーザー単位インストールを使用
- Linuxコンテナ用のWSL 2を使用
- Windowsコンテナ機能は無効
- Docker利用条件への同意チェック後だけインストール
- WSL未導入時はMicrosoft公式の`wsl --install --no-distribution`を実行

Docker Desktopは、個人利用、教育、非商用オープンソース、条件を満たす小規模事業者では無償で利用できる。その他の企業利用や政府機関では有償契約が必要になる場合があるため、ウィザードに表示される公式利用条件を確認する。

- [Docker Desktop Windowsインストール要件](https://docs.docker.com/desktop/setup/install/windows-install/)
- [Docker Subscription Service Agreement](https://www.docker.com/legal/docker-subscription-service-agreement/)
- [Microsoft WSLコマンド](https://learn.microsoft.com/windows/wsl/basic-commands)

## 日常操作

| ファイル | 用途 |
| --- | --- |
| `Start-LeadHive.cmd` | LeadHiveを起動してブラウザを開く |
| `Stop-LeadHive.cmd` | LeadHiveを停止する。データは残る |
| `Update-LeadHive.cmd` | 検証済みの新配布ファイルへ置換後、停止・安全backup・DB更新を実行する。元の.env.localを保持し、他社の設定をコピーしない |
| `Backup-LeadHive.cmd` | DBと暗号化キーを`backups`フォルダーへ保存する |
| `Restore-LeadHive.cmd` | 最新バックアップを確認付きで復元する。復元前にも安全バックアップを作成する |
| `Diagnose-LeadHive.cmd` | Docker・WSL・LeadHiveの状態を秘密情報なしの診断ファイルへ出力する |
| `Adopt-LeadHive.cmd` | 既存環境を確認して環境IDを登録する。DBやキーを置き換えず、サービスも起動しない |
| `Resume-LeadHive.cmd` | 保守後のworker再開。送信停止時は配送待ちを保持して収集・解析だけ再開 |
| `Stop-LeadHiveOutbound.cmd` | 送信停止を保存しサービスを再作成。workerは停止したまま |
| `Open-QuickStart.cmd` | 初心者向け収集・準備専用ガイドを開く |
| `Import-LeadHiveBackup.cmd` | 停止済み元PCの検証済みbackupを専用の新PCへ移行 |
| `Repair-LeadHiveInstance.cmd` | 初回登録が途中で失敗し、正しいラベル付きDB volumeが残っている場合の登録完了 |

起動URLは通常`http://localhost:8787`。8787番ポートが使用中の場合、初回インストール時に8788〜8797から空いている番号を自動選択する。

## 保存場所

- 業務データ：新規環境はDockerの`leadhive-<環境ID>-data`ボリューム。引継ぎ済み旧環境は既存ボリュームを維持する
- DBパスワード・暗号化キー：展開フォルダー直下の`.env.local`
- 手動バックアップ：展開フォルダー直下の`backups`

`.env.local`には環境ID、Compose名、データボリューム名、DBパスワードと暗号化キーを保存する。Dockerには対応する`<データボリューム名>-identity`ボリュームも登録する。識別用ボリュームも削除しない。

`.env.local`を失うと管理画面で保存したAPIキーやメールパスワードを復号できない。PC交換やフォルダー削除の前に`Backup-LeadHive.cmd`を実行し、同じファイル名を持つ`.dump`、`.dump.env.local`、`.dump.identity.json`の3点を安全な別媒体へ保管する。

## 復元

1. `Restore-LeadHive.cmd`をダブルクリックすると、`backups`内の最新dumpが選ばれる。
2. 表示されたファイルを確認し、`RESTORE`と入力する。
3. アプリとworkerが停止し、現在のDBが安全バックアップされた後、別の新規DBへdumpが復元される。
4. 全テーブルの内容ハッシュ、Migration、秘密情報の復号が検証され、成功時だけ接続先が切り替わる。元のDBは削除しない。
5. 完了メッセージのURLを開く。画面は再開するがworkerは停止したまま。配送履歴を確認して`Resume-LeadHive.cmd`へ進む。

別のdumpを使う場合は、dumpファイルを`Restore-LeadHive.cmd`へドラッグして実行する。環境ID、キー、dumpのハッシュが一致しない場合は復元前に停止する。識別情報のない旧バックアップも自動復元しないため、元ファイルを保持して管理担当者へ相談する。

通常の起動・インストールは、消失したDBを空のDBとして作り直さない。新しいPCへの移行は以下の専用手順を使う。

### 新しいPCへ移行

1. 元のPCでG1.2形式のbackupを作成し、dump・env.local・identity.jsonの3点を安全にコピーする。
2. 元のPCで`Stop-LeadHive.cmd`を実行する。同じ会社の旧PCと新PCを同時運用しない。
3. 新PCの専用環境でDocker Desktopを起動し、検証済み配布ZIPを展開する。先に通常インストールで新しい環境を作らない。
4. backupのdumpを`Import-LeadHiveBackup.cmd`へドラッグし、元PCを停止したことを確認して指定文字列を入力する。
5. 元の環境ID・暗号化キーを保持して新規DBへ復元・検証する。成功後もworkerは停止している。

移行が途中で失敗した場合は、ファイルとDBを保持する。同じbackup・同じ未完了環境に限りImportを再実行できる。
identity登録が途中で失敗した場合は`Repair-LeadHiveInstance.cmd`で、残存volumeの環境IDとキー照合値を検査する。判定できない場合や旧固定volumeは自動修復しない。
旧PC上の既存データvolumeを消してImportする手順にはしない。識別情報のない旧backupやG1.1形式だけのbackupは、検証報告がないためG1.2の通常復元対象外。

### workerを再開

backup・update・restore後は、検索スケジュールや収集を含むworker全体が停止している。通常のStartやInstallでも、この停止状態を引き継ぐ。
`Resume-LeadHive.cmd`は未処理・実行中・失敗配送、未完了campaign/form batchを検査する。G1.3の送信停止時は履歴を保持して収集・解析だけ再開できる。送信有効時は該当があれば再開を拒否する。初期提供では送信停止を解除しない。
特に失敗履歴には送信結果不明が含まれ得るため、上書き・削除・単純retryで解除しない。管理担当者が外部送信履歴と突合する必要がある。現段階ではその自動照合・解除UIは未実装。
送信停止の場合や該当がない場合も、外部送信履歴と元PC停止を確認し、表示された環境IDを含む確認文字列を入力して再開する。
保守失敗が残っている場合は、先に更新/復元の問題を解決する。Startはアプリも自動再開しない。

## 起動できない場合

`Diagnose-LeadHive.cmd`を実行すると、`diagnostics`フォルダーへ状態確認ファイルを作成する。このファイルには`.env.local`の値、APIキー、メールパスワード、企業データを出力しない。

Docker Desktopでruntime pathやsocketのエラーが表示された場合は、Docker Desktopの完全終了と再起動、Windows再起動、Docker Desktop標準診断の順で確認する。Factory resetはDocker volumeを消す可能性があるため、バックアップを確保した最後の手段とする。

## アップデート

1. `Backup-LeadHive.cmd`を実行する。
2. 新版のZIPを展開する。
3. 旧フォルダーの`.env.local`を新版フォルダー直下へコピーする。
4. `Update-LeadHive.cmd`を実行する。

Updateはアプリとworkerを停止してからビルドし、Migration前に安全backupを自動作成する。完了後もworkerは停止したまま。失敗した場合は保守状態を維持し、通常Startで迂回して再開しない。
rollbackには元のbackupと旧版の検証済み配布物を使用する。旧DBや失敗した隔離DBを削除せず、管理担当者が対応する版へ復旧する。通常運用でDB downgradeを行わない。

同じPCの同じ環境であれば、元の`.env.local`に記録された環境IDとDocker側の登録を検証して既存データを再利用する。別環境を自動検索したり、旧`.env`へ自動切替したりしない。ID/キー/DB接続先が不一致、ボリュームが消失した場合は停止する。

### 環境IDのない旧版からの引継ぎ

1. 元の設定、データ、バックアップを保持する。別の会社の設定を使わない。
2. 新版フォルダーに元の`.env.local`をコピーする。
3. `Adopt-LeadHive.cmd`を実行し、表示されるDBボリューム・Compose名が対象会社のものか確認する。
4. 指定された確認文字列を入力すると環境IDが登録される。元の設定は`.env.local.pre-identity`にも保持する。
5. その後、通常の更新へ進む。

元の設定が`.env`だけの場合は、管理担当者が`Adopt-LeadHive.cmd -EnvironmentPath "元の.envの絶対パス"`を使用する。既存の`.env.local`が別にある場合は上書きせず停止する。元の暗号化キーは生成し直さない。
対応する旧DBは`leadhive-local-postgres-data`で、既存DBコンテナのvolumeとパスワードを照合する。判定できない環境や登録途中の失敗は自動修復せず、管理担当者が元の設定とDocker登録を確認する。

各社は専用PC/VMで利用する。同じPCのフォルダー複製やポート変更を企業間隔離の代わりにしない。

## 技術構成

`compose.local.yaml`がPostgreSQL、FastAPI、バックグラウンドワーカー、Nginx配信のReact画面を起動する。DBは外部へ公開せず、Web画面だけを`127.0.0.1`へ公開する。Migrationは起動・更新時にAlembicで適用する。

## 配布パッケージの作成

開発者はリポジトリ直下から次を実行する。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\package-windows.ps1
```

未commitの変更・未追跡ファイルがある場合は配布を拒否する。cleanなcommitから`git archive`でソースを取り出し、`dist`へコミット番号付きZIPと`.sha256`を出力する。`VERSION.txt`には完全な40桁commitを記録する。
ZIPには実行必須ファイルとLeadHive専用Codex Skillだけを含め、環境ファイル、dump、仮想環境、`node_modules`、テスト結果、既存データは含めない。全ファイルに`MANIFEST-SHA256.txt`を付与し、保守操作時にも内容を検証する。
backupsのenvには秘密値が含まれる。backup全体を暗号化保管し、提供先別にアクセス制限する。checksum/manifestは暗号化・電子署名の代わりではない。

### 復元・別PC移行後の認証と承認

バックアップに含まれたログインsession、再認証challenge、Agent credential、未処理・承認済みApprovalRequestは復元時に失効します。再ログインし、Agentを利用する場合は管理者が既存のcredential発行APIで再発行してください（Agent管理UIは未実装）。営業提案は再作成してHumanが再承認します。過去の文面・承認者・承認日時・監査履歴は保存されます。workerは別途確認して再開するまで停止したままです。

### 収集専用運用（G1.3）

配布の初期設定は外部送信停止です。収集・解析・企業管理・文面準備・Human承認は利用できますが、メール・フォーム・SMTPテスト・Codex送信支援は実行できません。画面上部で停止状態を確認できます。

停止するには`Stop-LeadHiveOutbound.cmd`を実行してください。サービスを停止・再作成するため一時的に画面が切れ、workerは停止します。その後`Resume-LeadHive.cmd`で確認すると、送信停止を保持したまま収集・解析workerを再開できます。古い配送待ちは削除・自動再送されません。

環境ファイルの編集だけでは稼働中processに反映されません。別PC・古いcontainer・コピー済みCodexタスクの停止は別途確認してください。初期提供では送信停止を解除しません。
