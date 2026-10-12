# URLから営業条件を提案する

基準main: 3fc95c22a644c47ec88ea14919e9e8f9a2e6ee56

ターゲットプロファイルの作成・編集画面で、販売サービスの公開URLと営業目的（任意）を入力する。
保存済みOpenAIキー・モデルを利用し、サービス概要、根拠原文、最大3つの営業ターゲット、
提案理由、検索語（最大8個）、確認が必要な点を提示する。
直接販売とOEM・販売提携の区別は営業目的で指定できる。

利用者が案を選んで「設定へ反映」を押すまでは入力欄を更新しない。
反映後も検索語・条件を編集できる。保存は既存のプロファイルAPIを利用する。
「保存してプロジェクト作成へ」でプロファイル・地域・提案内容を引き継ぐ。
プロジェクト名と地域を確認して保存し、既存の企業収集画面から件数・予算を指定して開始する。
加点・減点・除外・JSON等は詳細設定へまとめた。既存手入力・複製・編集も維持する。

## API・安全・費用

POST `/api/target-profiles/propose-from-url` はHuman Browser session必須。
Agent・混在資格情報は既存principal guardで拒否する。
DB更新・Company作成・Job作成・収集・Human承認・送信は行わない。Migrationなし。

既存SafeFetcherで指定ページのみを読む。robots、SSRF、各リダイレクトの再検証、
サイズ・時間・GET回数上限を維持する。JavaScriptを描画せず本文不足はエラー。
1ページ解析（robots/redirectのGETは別）、本文最大12,000文字、AI最大1回、
最大2,500出力token、45秒timeout、自動retryなし。
失敗時は既存手入力を保持し、利用者が再提案する。

Web本文は信頼しない資料としてモデルへ渡す。structured outputで上限を検証し、
根拠引用は入力本文に存在する原文だけを返す。根拠は実サイトのHuman Truthを意味しない。
AIの業種適性・検索語は提案であり、自動除外や送信許可ではない。
URL/営業目的変更は未反映の提案を破棄し、古い応答の適用を防ぐ。
利用者が既に反映した設定は勝手に消さない。

入出力token数、モデル、取得日時、本文hash、最終URLを応答する。
料金単価は設定しない。金額は未測定。キー・全文・秘密情報はログやGitに保存しない。
利用者へAIへの本文送信・費用発生を画面で案内する。

## 検証

外部GET・有料AI・検索APIは今回実行していない。実モデルの提案品質は未検証。
AI/取得をmockした単体8件と、API/auth・既存scraper回帰19件（合計27件）を
専用_test DBで実行し成功。
Migration upgrade/model diffは専用DBの既存fixtureで成功。
Desktop/Mobileの隔離Playwrightで22件成功。
Backend Ruff/format/mypy/API import、Frontend typecheck/lint/buildを実行。
GitHub CIはPRの最終headに対して別途確認する。

### 2026-10-12 CI E2E回帰修正

初回CIのpush / pull_requestは両方、業種別名とprofile CRUDのDesktop/Mobile計4件が失敗した。
詳細設定を閉じた状態の入力欄へfillしていたことと、複製先の説明文も含めたhasTextが
元profileと複製先を同時選択したことが原因。103件成功・3件skipの結果とは分けて扱う。
テストにsummaryを開く操作を追加し、複製元は完全一致のheadingで選択する。
詳細欄が最初は非表示であることも検証する。UIを常時展開する変更やforce操作で回避しない。
修正後は専用_test DB・localhostで該当4件を再実行する。最新CIの全件成功とは区別する。

本変更はPR提出まで。本番反映はマージ後にWeb/API両方が必要。
既存Agent権限・承認・送信境界は変更しない。

## 制限

URLを読む前のAI依頼は認証済み利用者に限定するが、アカウント単位の回数課金上限は
既存AI解析と同様に今後の課題。1回ごとの出力・取得上限を設ける。
複数ページ追加調査・保存済み提案履歴・自動Query Expansionは対象外。
採用した条件は既存TargetProfileに保存される。非採用案はページを閉じると破棄する。
