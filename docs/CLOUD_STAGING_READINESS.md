# クラウド試験環境の準備

基準: main@7ce1622fc4547508e531e8f691ab18b94fcd4f2e（PR #41統合済み）。

## この工程のゴール

スマートフォンでHTTPSのLeadHive画面を開き、PCから専用Agent資格情報で
提案のメタデータだけを参照できる試験環境。実送信・Codex送信タスクは接続しない。
現時点は配置用ファイルの準備段階。クラウド環境の作成・HTTPS実接続は未実施。

## 構成

- 公開Web: `frontend/Dockerfile.cloud`（リポジトリrootをbuild context）。
- 非公開API: 既存`backend/Dockerfile`（backendをbuild context）、port 8000。
- 非公開PostgreSQL: 試験専用の新規DB。既存の営業DB・資格情報はコピーしない。
- Workerは作成しない。ジョブを開始せず、Agent接続だけを確認する。
- Webの`/api/`を内部APIへproxyし、画面とAPIを同じHTTPS originで提供する。

既存のローカルDockerfile・nginx設定は維持。cloud版はAPI_HOSTとPORTを
nginx公式imageのtemplate展開で設定する。API_HOSTには運用者が設定した内部DNS名だけを
使う。APIを公開しない。HTTPS終端・HTTPからHTTPSへの転送はクラウド側で必須。
cloud版のforwarded protoはhttps固定なので、直接HTTP公開には使わない。
ブラウザのCORSを全許可にせず、PUBLIC_APP_URL/CORS_ORIGINSは公開画面の完全一致origin。

## 配置前に確定するもの

クラウドアカウント、利用region、月額上限、課金プラン、試験用URL、DBバックアップと
復旧方法を確定する。有料resourceは見積もりとHuman確認の後に作成する。
RenderならWeb+Private Service+PostgreSQL、Railwayなら公開Web+内部API+PostgreSQLが候補。
この工程では特定サービスの契約・設定を自動変更しない。
3社の本運用は会社ごとにアプリ・DB・資格情報を分離する案から始める。
今回の試験環境を3社共用の本番環境に転用しない。

## 配置手順

1. 新規試験DBを作り、接続先を確認する。既存DBを指定しない。
2. backendへDATABASE_URL、新規FernetのSETTINGS_ENCRYPTION_KEYを秘密設定として登録。
   キーは再配置ごとに再生成しない。DB復旧と一緒に復旧できる別の保管先へ保存する。
3. `deploy/cloud/staging.env.example`の安全設定をbackendへ登録。公開HTTPS originも登録。
   SMTP/IMAP/検索/AIキーは初回試験に不要。Agentは最初OFF。
4. 新規DBに対して既存Alembicの`python -m alembic upgrade head`を一回実行する。
   migration成功後にAPIを起動。startupに自動migrationを追加しない。
5. WebへAPI_HOSTを内部DNS名、PORTをplatformの待受portとして登録しcloud imageを配置。
6. HTTPS画面と`/api/health`、Secure Cookie、ログイン、他Projectへのアクセス拒否を確認。
   初期Human管理者は既存の管理者作成手順で作る。共有パスワードをGitへ残さない。
7. 架空の試験Projectを作成。送信関連flagはOFFのまま、試験APIだけAgentをONにする。
   Human管理者が`outreach:read`のみ・短期・そのProjectだけのCredentialを発行。
8. [PC読取接続手順](CLOUD_PC_CODEX_CONNECTOR.md)で一回取得。
   正常応答・execution_allowed=false・他Project拒否・revoke後拒否を確認する。
   空の提案一覧は接続確認として有効。送信やHuman承認を作成する必要はない。
9. CredentialをrevokeしAgentをOFFへ戻す。試験日時、commit、検証結果を記録する。

既存Agent GETは期限/変更検査と監査記録のためDB更新することがある。
PCの「読取専用」はGETのみ・送信操作なしを意味し、DB無変更保証ではない。

## 完了判定・切り戻し

cloud Docker build/nginx起動確認と、実際のHTTPS配置成功は分けて記録する。
現時点で実クラウド接続、スマートフォンの外部URL、PC資格情報の接続は未検証。
公開URLが確定するまでlocalhostをスマートフォン向けURLとして案内しない。
送信0件、承認0件、workerなしを維持する。
問題時は公開Webを停止し、AgentをOFF/revoke、直前imageへ戻す。
DBは保全し、migrationを機械的にdowngradeしない。

## ローカル検証結果（2026-10-10）

- cloud用Docker imageのbuild（TypeScript検査・Vite buildを含む）成功。
- 隔離Docker network上の模擬APIへproxyできること、SPAのroot/fallback、nginx構文を確認。
  mockは静的fixtureで、実DBや外部サイトへの接続は行っていない。
- PC読取コネクター回帰30件PASS。
- ビルド用source-map-jsを1.2.1から1.2.2へ限定更新。
  [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)への対応。
  npm ci後のauditは脆弱性0件。公開後の安全性全体を保証するものではない。
- 実クラウド、TLS、Secure Cookie、Human/Agent認証のライブ検証は未実施。

## 公式資料

- [Render Private Services](https://render.com/docs/private-services)
- [Render TLS](https://render.com/docs/tls)
- [Render Blueprint仕様](https://render.com/docs/blueprint-spec)
- [Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles)

費用はprovider/region/plan決定後の見積もり。未確定費用を0円と扱わない。
