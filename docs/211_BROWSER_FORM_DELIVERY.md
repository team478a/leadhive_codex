# 211 ブラウザによるフォーム解析・送信

作成: 2026-10-17。状態: **B1安全基盤・B2読み取り専用解析を実装。B3送信計画・承認を実装。B4送信実行は別PR**。

## 目的と境界

ブラウザー描画後のDOMを解析し、静的HTMLで確認できなかった問い合わせフォームの構造を保存する。B2で追加するのはGET専用の読み取り解析であり、フォーム入力・クリック・送信はしない。実サイト解析APIとWorkerは既定OFFで、田中さんの承認後にAPIとWorkerの両方で `BROWSER_FORM_ANALYSIS_ENABLED=true` を設定した場合だけ実行可能になる。このPRではフラグを有効化せず、実サイトにもアクセスしない。

送信・承認・送信上限・連絡禁止の判定は変更しない。解析で営業NGを検出した場合は既存の営業NG記録と同じく連絡禁止を維持する。CAPTCHAの自動化、bot検知回避、CAPTCHA解読サービス、未承認のフォーム送信は行わない。

## B1: ブラウザー安全基盤

### 通信先を制限する

- browser workerコンテナ内のloopbackだけで待ち受けるHTTPS CONNECTプロキシを使用する。Chromiumには `--proxy-server` を必ず指定し、loopbackを含むプロキシ迂回を無効にする。WebRTCとQUICも無効にする。
- B2では対象サイトのホスト（`www` のみ同一扱い）だけを許可する。外部埋め込み先は開かない。外部フォームドメインを許可する場合は、別途承認計画に完全一致ドメインを列挙する必要がある。
- プロキシはHTTPSの443番だけを扱い、CONNECTごとに許可ドメインを照合する。接続ごとに既存の `pinned_dns` でDNSを解決し、`public_addresses` で全回答を検証する。非公開・特殊用途IPが1つでも混ざる回答は拒否し、検証済み数値IPに接続を固定する。
- Playwrightのリクエスト遮断も残し、同一サイトHTTPSへのGET以外は遮断する。フォーム送信、ファイル選択、ダウンロード、新しいウィンドウ、WebSocketは許可しない。

### ページを開く前に確認する

- 最初のページ遷移より前に、同じプロキシ経由で `robots.txt` を取得する。既存の `SafeFetcher` と同じrobots判定を共通関数で使用する。
- 取得失敗、サイズ超過、未対応HTTP応答、リダイレクトは許可の証拠とみなさず停止する。404は既存の `SafeFetcher` と同様に許可、401/403およびDisallowは拒否する。
- メインフレームの各遷移で、パスワード欄、ページ本文・タイトルのログイン／サインイン表示、ログイン系パスを検査する。該当時は直ちに処理を停止する。

## B2: 表示後DOMの読み取り解析

### 対象と解析

- 対象URLはAPIが保存済みの `FormProfile` から選ぶ。対象は既知の問い合わせページで「フォームなし」「埋め込み未確認」、Contact Form 7、multipart、確認画面、JavaScript送信の候補に限る。ブラウザー解析済み、取得失敗、営業NG・連絡禁止、同一サイトでないURLは対象にしない。
- ブラウザーで問い合わせページを表示し、描画後DOMから既存の項目解析、同意・選択肢、CAPTCHA、営業NG、§5.1の日本語判定を再利用する。フォーム値はスナップショット前に除去し、項目・選択肢・送信経路などの構造だけからfingerprintを作る。外部CAPTCHAスクリプトが遮断されDOMで確認できない場合、既存解析で確認済みのCAPTCHA判定を消さず、安全側に保持する。
- 解析結果は既存の `FormProfile` を更新し、`analysis_source='browser'` とする。描画後にフォームがなければ未発見として保存する。外部iframe・外部フォームのDOMは取得せず、「埋め込み未確認」のまま記録する。
- 同一サイト（`www` の有無を同一扱い）のページはデータベースのadvisory lockで直列化し、1件の解析後に1秒以上空ける。1つのOperationJobは最大100社。対象URLはサーバー側で決定し、任意URLやドメインのAPI入力は受け付けない。
- 送信可否パネルに「ブラウザ解析済み」と、問い合わせページ到達・フォームなし、埋め込み未確認、Contact Form 7、multipart、確認画面、JavaScript送信の会社数を表示する。

### 有効化の手順

- `BROWSER_FORM_ANALYSIS_ENABLED` はアプリ設定、Browser WorkerのDockerfile、Render staging設定のすべてで既定 `false`。実行前に田中さんの承認を得る。
- 承認後、管理者がAPIとBrowser Workerの双方でフラグを個別に有効化する。RenderのBackground Worker提案は `deploy/cloud/render-staging.yaml` に全行コメントアウトしてある。Blueprint同期や有料リソース作成はこの変更に含めない。
- 有効化前に対象候補とURLの範囲を確認し、最初は少数で実行する。失敗・ログイン検出・robots拒否があれば停止し、対象拡大は再承認する。

## OperationJob

- 合成フォームは既存の `POST /api/projects/{project_id}/browser-form-analysis` でのみ受け付け、パッケージ済みfixture名・制限付き入力値に限定する。
- 実サイトの読み取り解析は `POST /api/projects/{project_id}/browser-form-analysis/recalculate` から要求する。APIが保存済み候補を最大100社選び、OperationJobのlease、cancel、stale recovery、重複防止で処理する。フラグOFFなら409で拒否する。
- 通常のapplication workerは `browser_form_analysis` をclaimしない。Browser Workerが実行直前にもフラグ・payload・会社・URLを再検証する。

## テストと確認

ブラウザー解析テストは合成HTMLとlocalhostのテストサーバーのみを使い、実サイトへのアクセスやフォーム送信は含めない。許可外ホスト、内部IP、DNS再束縛、robots拒否、ログイン遷移、非GET遮断、ダウンロード、新しいウィンドウ、ファイル選択、送信試行、DOM値の除去、fingerprint、OperationJobの上限・割当・重複防止・cancel・復旧を確認する。

## §6 B3: 送信計画と承認

### §6.1 対象

- `delivery_method='browser_form'` を追加し、保存済みのブラウザー解析プロフィールとフォームDraftから送信計画を作る。
- 第1版はフォームページ・送信先が同じHTTPSサイト内で完結するフォームだけを対象にする。外部フォームサービス、別サイトへの送信、ファイル入力は対象外。
- 表示型・非表示型を問わずCAPTCHAがあるフォームは対象外。
- `BROWSER_FORM_DELIVERY_ENABLED` は既定OFFのまま。承認の作成と送信実行は別工程とし、OFFの間はブラウザー送信予約を拒否する。

### §6.2 承認payload

承認payloadには、計画版、project/company/Draft/profile ID、解析fingerprint、問い合わせURL、action URL、form index、HTTP method、同一サイト限定、CAPTCHA判定、確認画面の有無、送信形式、各入力欄の安定したselector・name・型・値・必須情報を含める。正規化した計画全体のSHA-256をpayloadに含め、既存の承認payload hashに結び付ける。計画と保存済みプロフィール、Draft、送信者設定のいずれかが変わった場合は承認を無効化する。

### §6.3 計画の保存と判定

- 規則で一意に対応付けられる項目は規則で計画する。
- 規則で判定できない項目だけ、準備時に既存のAI判定Providerへ一度だけ提案を求め、プロフィールfingerprint・項目hashに結び付けて保存する。同じ構造での再表示・承認・送信ではAIを呼ばない。
- AI提案は人が確認する承認payloadに含める。送信実行時にAIを呼んだり値を変更したりしない。

### §6.4 既存フローとの接続

`BROWSER_READY` を送信可否の理由として表示し、フォーム確認キュー、承認提案の一括作成、送信画面の承認・予約一覧へ接続する。予約・実行はB4で実装するまで利用できず、既定OFFも維持する。送信・承認・送信上限・連絡禁止の既存判定を緩和しない。

## §7 B4: 送信実行（別PR）

B4では既存の送信前 `begin` と結果確定 `finish` を必ず使い、ブラウザーワーカーだけが `browser_form` 予約を取得する。`dry_run` は確認キューで確定したフォームへの入力・読み戻し・画面撮影だけを行い、送信ボタンを押さない。`submit` は有効な承認を持つ予約に限る。送信前に結果不明を永続化し、送信後の結果は `submitted` / `failed` / `unknown` のいずれかで確定する。送信前後のJPEGスクリーンショットは各200KB以下でDBへ保存し、90日後に削除する。Render Workerの永続ディスクには依存しない。

実サイトでの送信はこの文書やコードの実装だけでは許可されない。設定をOFFのまま維持し、実サイトでの実行前に田中さんの明示承認を得る。自動マージ・デプロイは行わない。
