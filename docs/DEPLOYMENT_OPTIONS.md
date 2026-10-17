# LeadHiveの導入方法を選ぶ

LeadHiveはクラウド運用とローカル運用の両方を提供する方針です。
同じアプリのコード・DB定義・Human承認を使い、保存場所と起動方法を分けます。
現在のクラウド版は配置設定まで完成した試験段階で、提供用URLは未発行です。

## どちらを選ぶか

| 希望 | 選ぶ方法 | 利用者に必要なこと |
| --- | --- | --- |
| スマートフォンや複数PCから利用したい | クラウド | 発行されたHTTPS URLへログイン |
| 営業リストやAPIキーを自社PCに保存したい | ローカル（Windows Docker版） | 配布ZIPからインストール、PCを起動して使う |
| Docker不要で試してみたい | Windows Native試作版 | EXE起動。ただし本番配布版ではない |

ローカルでも検索API・AIを使う処理は外部通信と各サービスの費用が必要です。
「データがPCに保存される」ことと「完全オフライン」は異なります。
ローカルURLをスマートフォンで開いても、スマートフォン自身を指すため接続できません。
PCのportをそのままインターネットへ公開しないでください。

## クライアントへの提供方針

- 導入時に会社ごとにクラウド/ローカルを選択する。クラウドは会社ごとのアプリ/DBで開始する。
- ローカルを選んだ会社をクラウドへ強制移行しない。両方とも同じmainからreleaseを作る。
- User、Project、会社リスト、APIキー、暗号化キー、バックアップは会社ごとに分離する。
- リリース番号/commit、DB migration、配置方式を管理担当者が記録し、同じ修正を両方式へ配布する。
- クラウドの配置とローカルの更新は別作業。GitHubへのmergeだけではどちらも自動更新しない。
- 各会社の正本は選択した一つのDB。クラウドとPCで同じリストを同時に送信運用しない。

## ローカル版を始める

検証済みのWindows Docker配布ZIPを受け取り、展開して`Install-LeadHive.cmd`を起動します。
通常は`http://localhost:8787`で使います。起動/停止/更新/バックアップのコマンドは維持します。
他社の.env.local・backupを入れないでください。新規導入ではその会社専用の環境を作ります。
詳しくは同梱の`docs/73_WINDOWS_LOCAL_INSTALLER.md`を参照してください。

Docker不要のNative版は別の試作環境です。送信OFF、workerなし、更新・backup復元・
別PC移行未対応なので、Docker版と同等の本番提供版として案内しません。
Native版の制限は同梱README-FIRST.txtを優先してください。

## クラウド版を始める

管理担当者が会社専用環境を配置し、HTTPS URLと初期Userを発行します。
利用者はアプリをインストールせず、ブラウザで使います。
現在のRender構成はログイン/PC読取接続の試験専用で、workerを起動しません。
大量収集・解析・送信の本運用開始には容量評価、backup/復元、worker、安全設定の確認が必要です。
配置手順はrepositoryの`docs/RENDER_STAGING_SETUP.md`にあります。
クラウド管理用設定や秘密値はローカル配布ZIPへ同梱しません。

## 本番のワーカーの場所と更新手順

2026-10-17時点で、リポジトリにある配置定義から実際の本番ワーカーの場所は確認できません。
`deploy/cloud/render-staging.yaml` はWeb/API/DBのみで、APIの`WORKER_PAUSED`も`true`です。
`compose.yaml`はDBのみ、`deploy/leadhive-worker.service.example`はsystemd用の例です。
したがって、実際の本番ワーカーがRender、PCのDocker、systemdのどれで稼働しているかは未確認です。
本番の配置先を変更する前に、Render Dashboardと稼働PC/VMのDocker・systemd状態を管理者が確認してください。

確認できる環境では、ログイン後の画面下部にAPI版と直近5分以内のワーカー版・ホスト名が表示されます。
フォームDMの最終集計には、そのOperationJobを実行したワーカー版・ホスト名も表示されます。
版が異なる場合は、APIと同じGit commitへワーカーを更新し、再度heartbeatと画面表示を確認してください。

- Renderにワーカーサービスが実在する場合：Dashboardでそのサービスを特定し、APIと同じブランチ・commitを選んで手動Deployします。現在のBlueprintにはworkerサービスがないため、サービスの存在を推測して追加・起動しないでください。
- Dockerの場合：同一commitを使い、PowerShellで`$commit = git rev-parse --short=7 HEAD`を取得してから`docker build --build-arg "LEADHIVE_GIT_COMMIT=$commit" -f backend/Dockerfile backend`でイメージを作成し、実際の配置定義に従ってworkerコンテナを更新します。
- systemdの場合：`/opt/leadhive`のコードと依存関係をAPIと同じcommitに更新し、`sudo systemctl restart leadhive-worker`後に`sudo journalctl -u leadhive-worker -n 100`と画面のheartbeatを確認します。

再起動前に実行中ジョブ・送信停止状態・バックアップを確認してください。GitHubのmergeだけでは、Renderやローカルworkerは更新されません。

## Codexとの接続

クラウド本体とPC側Codexを組み合わせる構成を準備しています。
今あるPC connectorは提案メタデータの読取だけで、送信タスクを自動起動しません。
ローカル版の既存Skillも維持しますが、Skillの存在だけで送信許可にはなりません。
Human承認、送信OFF、営業禁止、suppression、CAPTCHA、UNKNOWN保護を両方式で維持します。
クラウドからPCへ送信実行を引き渡す仕組みはまだ未完成です。

## 後から運用方式を変更する場合

ローカルPC間の移行は既存Import-LeadHiveBackup手順を使います。
ローカルとクラウド間の全データ移行・同期は未実装です。
CSVを入出力しても承認・履歴・suppression・API設定の完全移行にはなりません。
移行時は元環境を停止し、DBと暗号化キーを保全、配送UNKNOWNや承認の失効を確認する
専用工程が必要です。バックアップをそのままRenderへ流し込まないでください。

まず各会社の運用方式を決め、その方式で導入します。移行機能や自動同期を
今回のクラウド試験開始の前提にはしません。
