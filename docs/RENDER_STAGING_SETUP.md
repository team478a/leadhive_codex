# Render試験配置案（まだ未配置）

基準: main@c3ab53ad241262ddd7973845d7322010f5411219。
配置候補を`deploy/cloud/render-staging.yaml`に固定した。Render利用の決定や
課金の承認を意味しない。アプリ/API/Migrationを変更せず、PR #42のcloud imageを使う。

## 費用と対象

2026-10-10の[公式料金表](https://render.com/pricing)の表示を確認。

| 対象 | plan | 月額USD |
| --- | --- | ---: |
| 公開Web | 0.5c-512mb | 7 |
| 内部API | 0.5c-512mb | 7 |
| 内部PostgreSQL | 0.1c-256mb | 6 |
| DB storage 1GB | 0.30/GB | 0.30 |
| 合計 | 最小の接続試験用 | 20.30 |

これは基本リソース料金の見積もりで、上限保証ではない。税・為替・workspaceの有料プラン・
通信超過・build超過・検索/AI等は別。作成画面で現在の請求見積もりを最終確認する。
この構成は低負荷のログイン/Agent接続試験専用。大量収集・ブラウザ実行・3社本運用の
容量を保証しない。Worker/preview/autoscalingは追加しない。料金通知と月額上限は
アカウント確定後に設定し、超過通知がサービスを自動停止するとは扱わない。

## スマートフォンから準備すること

1. Renderアカウントへログイン（未作成なら作成）。GitHubの対象repositoryへのアクセスを許可。
2. Blueprint作成画面で`team478a/leadhive_codex`とmain、設定ファイル
   `deploy/cloud/render-staging.yaml`を選ぶ。事前にこのPRをmainへ統合する必要がある。
3. 3resourceの名前が既存アプリと衝突しないこと、region Singapore、料金を確認する。
   同名の既存resourceがあれば続行せず全ての参照名を変更する。
4. 課金についてHumanの確認が済むまで、作成/Deploy/Applyは押さない。
   autoDeployTrigger=offでも最初の作成は配置・課金を発生させる。

ログインや支払い情報は利用者自身がサービス画面へ入力する。Chat/Gitへ貼り付けない。

## 配置実行時の運用手順

- 初回に要求されるSETTINGS_ENCRYPTION_KEYは新規のFernet key。秘密設定へ直接登録し、
  別の安全な保管先へ保管。Renderのランダム秘密値生成にFernet形式を暗黙依存しない。
- CORS_ORIGINSとPUBLIC_APP_URLは同じ実HTTPS origin、末尾slashなし。
  まだ割当URL不明なら仮に`https://staging.invalid`で開始し、実URL確定後に両方を設定して
  APIを手動再配置する。仮originの状態ではログイン操作をしない。
- DB接続値と内部API hostnameはBlueprint参照で設定。DBは外部IP全拒否。
  内部ネットワークは同じRender workspace内で共有されるため、機密試験用workspaceを使う。
- APIのpreDeployCommandで既存Alembicを実行。API起動・Webの/api/health・migrationログを確認。
  migration失敗時は続行しない。ログに資格情報を記載しない。
- APIのShellで`python -m app.cli`の既存Human作成機能を使う。
  emailは引数、passwordはgetpassに入力し、ログ/コマンド引数へ出さない。
  最初のUserだけ管理者となる。既存本番ユーザーはコピーしない。
- [共通配置検証手順](CLOUD_STAGING_READINESS.md)のHTTPS/Secure Cookie/Project境界確認後、
  Agentを試験APIだけON、Human管理者がoutreach:readだけの短期資格情報を発行。
  PC読取接続、他Project拒否、revoke後拒否を確認し、AgentをOFFへ戻す。

APIへのDATABASE_URLは試験DBだけ。検索API・AI・SMTP・IMAPキー、既存リストを入れない。
Human承認作成・送信・Codex送信タスクは行わない。送信flagはOFFのまま。
sync:falseの値は後のBlueprint同期で更新されないため、変更時はAPI設定画面で直接更新する。
自動deployはOFFだが、手動deploy前にはmainのCI成功とcommitを固定する。

## 現時点の状態

Blueprintは静的検証対象で、Renderアカウント/APIへの作成リクエストは行っていない。
実HTTPS、初期User、PC認証、backup復元は未検証。試験環境を用意したと報告しない。
この候補が不要なら削除してもローカル運用には影響しない。

検証済み: YAML解析とRender公開JSON Schema（2026-10-10取得）でvalidation成功。
参照resource/build path、非公開API、DB外部IP全拒否、送信OFF、Agent OFF、
Secure Cookie、workerなし、自動deployなし、秘密値promptを確認。
検証ライブラリはGit管理外の専用venvだけへ導入し、アプリ依存は変更していない。
Render側のアカウント条件・region availability・作成時の検証はまだ行っていない。

参考: [Blueprint仕様](https://render.com/docs/blueprint-spec)、
[Private Services](https://render.com/docs/private-services)、[TLS](https://render.com/docs/tls)。
