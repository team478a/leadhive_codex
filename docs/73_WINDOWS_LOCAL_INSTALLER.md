# Windows初心者向けローカルインストール

## 利用者に必要なもの

- Windows 10または11
- 8GB以上のメモリ（16GB推奨）
- 初回インストール時のインターネット接続

Docker Desktop、Python、Node.js、PostgreSQLを事前に個別インストールする必要はない。LeadHiveのデータ、APIキー、メール設定は利用者のPC内へ保存される。

## 初回インストール

1. GitHubのLeadHiveリポジトリをZIPでダウンロードし、通常のフォルダーへ展開する。
2. `Install-LeadHive.cmd`をダブルクリックする。
3. Docker Desktopが未導入の場合、表示された公式利用条件を確認して同意する。
4. WSL 2の有効化でWindowsの管理者確認が表示された場合は許可する。
5. 再起動を求められた場合はWindowsを再起動し、もう一度`Install-LeadHive.cmd`を実行する。
6. 初回だけ管理者メールアドレスと12文字以上のパスワードを入力する。
7. ブラウザでLeadHiveが自動的に開いたらログインする。

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
| `Update-LeadHive.cmd` | 新しいソースへ更新後、DB更新と再起動を行う |
| `Backup-LeadHive.cmd` | DBと暗号化キーを`backups`フォルダーへ保存する |

起動URLは通常`http://localhost:8787`。8787番ポートが使用中の場合、初回インストール時に8788〜8797から空いている番号を自動選択する。

## 保存場所

- 業務データ：Dockerの`leadhive-local-postgres-data`ボリューム
- DBパスワード・暗号化キー：展開フォルダー直下の`.env.local`
- 手動バックアップ：展開フォルダー直下の`backups`

`.env.local`を失うと管理画面で保存したAPIキーやメールパスワードを復号できない。PC交換やフォルダー削除の前に`Backup-LeadHive.cmd`を実行し、生成された`.dump`と`.env.local`の両方を別媒体へ保管する。

## アップデート

1. `Backup-LeadHive.cmd`を実行する。
2. 新版のZIPを展開する。
3. 旧フォルダーの`.env.local`を新版フォルダー直下へコピーする。
4. `Update-LeadHive.cmd`を実行する。

Composeプロジェクト名とDBボリューム名は固定されているため、同じPCなら新版フォルダーから既存データを再利用できる。

## 技術構成

`compose.local.yaml`がPostgreSQL、FastAPI、バックグラウンドワーカー、Nginx配信のReact画面を起動する。DBは外部へ公開せず、Web画面だけを`127.0.0.1`へ公開する。Migrationは起動・更新時にAlembicで適用する。
