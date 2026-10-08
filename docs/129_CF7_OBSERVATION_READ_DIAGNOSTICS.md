# O3-C1 — 保存済み静的フォーム観察の閲覧・診断

## 1. ゴールと範囲

基準は `codex/integration@f69820932da7c26615df8f7c94bcd9970a597086`。O3-Cを、C1（閲覧API・診断UI）とC2（管理下取得Jobの接続・cancel/recovery）に分割する。今回完成させるのはC1のみ。O3-BのModel・migration・保存契約を維持する。

観察は非認可の診断証拠であり、FormProfile、ApprovalRequest、送信先、予約、配送を生成・変更しない。現在の保存経路は管理下合成データ・専用 `_test` DBだけ。実サイト取得、実データ保存、worker起動、送信への接続は行わない。

## 2. API

`GET /api/companies/{company_id}/form-observations?limit=10&offset=0`

- Human browser session必須。既存company/project accessでowner/editor/viewerが閲覧可能。他Projectは404。Agent CredentialおよびCookieとの混在は既存principal guardで403。
- limit 1〜50、offset 0〜10000。観察日時・UUID降順。limit+1取得でhas_moreを返す。offset方式なので並行追加時にページ重複・ずれはあり得る。大量履歴のcursor化は別工程。
- 観察テーブル2個とsource hash関数の存在を検査。未導入なら `available=false`、空items、latest_job=null。migrationやDDLを自動実行しない。schema存在判定は完全なrevision互換性検証ではない。
- 返すのは証拠ID/Job ID、観察日時/期限、snapshot hash、固定enumの診断、理由の安全な分類、鮮度のみ。HTML、canonical JSON、binding、項目値、label、credentials、Job error/payloadは返さない。
- canonical bytesのSHA-256、保存JSONとの一致、Company/Project/Job/run/evidence ID、診断enum/非認可の固定値を確認。失敗した行はINVALID、diagnostic=null、固定理由。これは保存時の全contract再検証や取得証明ではない。
- `CURRENT` は期限内・現在source一致・未取り下げという診断上の分類。動作確認、営業許可、READYを意味しない。その他EXPIRED/SOURCE_CHANGED/RETIRED/INVALIDを区別する。
- 理由は静的未検証・営業禁止・CAPTCHA・構造要確認・整合性異常に集約。詳細のparser reason、control一覧、台帳一覧・retire操作APIは今回未公開。
- 最新cf7_observation Jobのstatus/countを履歴と別に返す。前回成功の保存証拠を最新処理成功として表示しない。外部取得・Job enqueue・retryは行わない。
- 最新Jobのpayload内Company検索、大量履歴の負荷、複数クエリ間の同時更新に対するsnapshot一貫性は未検証。診断表示をdispatch時の安全検証として使用しない。
- POST/PATCH/DELETEは追加しない。閲覧はwrite flagと独立し、送信許可の2値は常にfalse。

## 3. UI

企業詳細に独立した `CompanyFormObservationsPanel` を追加する。未知の営業可否/CAPTCHAを「なし」「許可」に変換しない。日時・期限・hash・理由・古い証拠・最新Job失敗を表示する。送信・承認・取得開始ボタンを設けない。

未導入DB、旧APIの404、取得失敗を既存の企業詳細から分離して表示する。失敗時に前の証拠を現在の結果として残さない。会社切替時には旧requestの結果を破棄し、ページをリセットする。Web由来文字列はHTMLとして実行しない。

## 4. 変更ファイル

- `backend/app/form_observation_routes.py`: bounded read APIと安全な診断projection。
- `backend/app/main.py`: read router登録。
- `backend/tests/test_form_observation_read.py`:権限・混在・旧schema・鮮度・改ざん・非送信テスト。
- `frontend/src/CompanyFormObservationsPanel.tsx`: 独立診断UI。
- `frontend/src/CompaniesPage.tsx`: panel接続のみ。
- `frontend/tests/form-observations.spec.ts`: PC/mobileで表示、旧版/取得失敗、HTML非実行、送信requestなし。

DB Model、migration、送信guard、worker、取得service、稼働DB、配布パッケージは変更しない。

## 5. 検証記録

実装commit：`5cd3c1478d65dfaec621ddfa1953aa1ff838989e`。2026-10-06に以下を確認した。

| 検証 | 結果 |
|---|---|
| 新read API・権限・改ざん・旧schema | 13 passed / 19.53秒 |
| O3-B保存、既存Operations、Contact Permission回帰 | 51 passed / 61.45秒 |
| Backend Ruff / format | 成功 |
| 新router mypy（check-untyped-defs / follow-imports=silent） | 1 file成功。全Backend strict typecheckではない |
| Frontend typecheck / lint / build | 成功 |
| 新UI Playwright desktop / mobile | 2 passed / 4.6分。desktop 1.2分、mobile 29.2秒 |
| 新UIファイル・E2Eファイルの最終ESLint | 成功 |
| 専用DB migration upgrade head / Alembic check | conftest・E2E setupで成功。新migrationなし |
| API起動 | 専用環境のUvicorn起動・health・APIテスト成功 |
| 既存稼働環境のread-only確認 | health status/database=ok、配信worker=exited |

Backendは計64件の選択テストであり、全Backend suite再実行ではない。最初の新APIテスト10件の成功は最終13件に含まれ、重複加算しない。UI初回は60秒のtest timeoutで2件失敗した。準備を含む上限を180秒に調整し、プロジェクト選択を既存テスト同様のrole locatorへ揃えた後、両viewportで最後まで成功した。

Backendテストは専用 `leadhive_o3c1_20261006_test` を使用した。旧schema互換性は、2テーブル・source関数をそれぞれrollback savepoint内でrenameし、未導入responseを実DBで確認した。UI観察responseはmockであり、管理下TLSの実取得や保存JobのE2E成功を意味しない。実保存と権限はPostgreSQL APIテストで確認した。実企業のアクセス・外部API・メール/Form送信は行っていない。

終了後、専用DBのevidence/events/users/email_deliveries/form_deliveriesが各0件、接続0件であることを確認して今回作成した専用DBだけを削除した。稼働DB・既存test DB・既存コンテナ・配布物は変更していない。

## 6. 残る制約・次工程

次はO3-C2：管理下専用の取得receipt/Job保存接続、cancel/recovery、lease・権限・source再確認。通常workerのclaim除外とfeature default OFFを維持し、専用test環境でのみ検証する。

既存Core permissionは新証拠を参照しないため、新観察の禁止/CAPTCHAが既存配送経路を止めるとは限らない。このblocker、実データ保持/削除、merge/delete互換性、Organization境界、実サイト取得許可は未解決。C1完成だけを理由に実サイトGETや送信へ進めない。
