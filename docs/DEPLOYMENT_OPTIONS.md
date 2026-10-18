# LeadHiveの導入方法を選ぶ

LeadHiveはクラウド運用とローカル運用の両方を提供する方針です。
同じアプリのコード・DB定義・Human承認を使い、保存場所と起動方法を分けます。
現在の公開アプリは`https://app.leadhive.work`です。Render上のサービス名に`staging`が
含まれていても、利用者向け本番として運用している公開環境です。

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
現在の公開環境はRender上のWeb/API/DBに加え、ブラウザー処理専用のBackground Workerを
使います。Render構成は`deploy/cloud/render-staging.yaml`を参照してください。
ブラウザーWorkerの`1c-2g`プランは有料です。料金、backup/復元、容量、アラートの検証状況を
本番利用開始前に管理者が別途確認してください。初期構築時の履歴は
`docs/RENDER_STAGING_SETUP.md`、現行の運用確認は本節と`backend/browser_worker/README.md`を参照します。
クラウド管理用設定や秘密値はローカル配布ZIPへ同梱しません。

## 本番のワーカーの場所と更新手順

現行のRender構成では、ブラウザーWorkerは`leadhive-staging-browser-worker`という
Background Workerとして定義されています。`backend/browser_worker/Dockerfile`からビルドし、
APIとは別に手動デプロイします。Renderサービス名の`staging`は公開環境の区分を表しません。
実際の稼働状態・Live commit・環境変数は、変更のたびにRender Dashboardで確認してください。

デプロイはAPI（Migration完了を確認）→Web→ブラウザーWorkerの順で行い、3サービスが同じ
main commitを使うことを確認します。API `/api/health` が200であることに加え、画面の稼働版表示
または`GET /api/runtime-info`で直近5分以内のWorker heartbeatとcommit一致を確認します。
heartbeatが古い、Workerが見えない、または版が違う場合、ブラウザー解析・送信の開始を止めます。

設定は用途ごとに独立しています。ブラウザー解析はAPIとブラウザーWorkerの両方で
`BROWSER_FORM_ANALYSIS_ENABLED=true`、dry-runは両方で`BROWSER_FORM_DRY_RUN_ENABLED=true`が必要です。
実送信にはさらに`OUTBOUND_ENABLED`、`HUMAN_APPROVED_FORM_ENABLED`、
`BROWSER_FORM_DELIVERY_ENABLED`と、有効なHuman承認・送信上限が必要です。設定だけでは承認や
送信可否を迂回できません。各操作の直前にAPIとWorker双方の実効値を確認してください。
Render Blueprintは安全のため機能フラグをOFFにしています。Dashboardで変更した値を確認せずに
Blueprint同期を行うと設定が変わる可能性があるため、同期前に必ず差分を確認してください。

再起動前に実行中ジョブ・送信停止状態・DB backupを確認してください。GitHubのmergeだけでは
Renderサービスは更新されません。Renderの自動デプロイは無効で、各サービスの手動Deployが必要です。

旧`form-delivery-batches`経路は`LEGACY_FORM_DELIVERY_ENABLED=false`を維持します。
新規運用は承認付き送信経路を使い、旧履歴は移行・保持方針が決まるまで削除しません。

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
