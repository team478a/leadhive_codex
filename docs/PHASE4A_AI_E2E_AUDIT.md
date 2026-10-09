# Phase 4A — AI E2E導入監査・比較PoC

## 判定

**CONDITIONAL GO（隔離PoC導入可、AI操作能力の実測は未完了）**。
7種類の同一模擬フォーム・同一入力による比較環境を追加した。
Playwright方式は各2回、14/14成功。既存Desktop/Mobile 44/44も成功。
AI経路はOpenAI APIが `429 / credit_balance_exhausted` を返し、最初の操作前に停止。
AI成功率・必須項目認識率・誤入力率・再現性は **null / 未検証**。
失敗したAPI呼び出しをフォーム操作失敗や精度0%として扱わない。
ユーザーの完了条件のうち「AIの7種類実測」は未達であり、Phase 4A全体を完了とはしない。

## 基準・依存PR

- main: `714e92e68f65bcf07ad0dc5eb54a641428294d25`、2026-10-10再取得。
- 既存PoC: PR #36 / `codex/phase4-browser-form-poc@a8104aff2f1aa60770c1a7393178ad7674acfbf0`、未マージ。
- 作業: `codex/phase4a-ai-e2e-poc`。PR #36をbaseとする積み重ねPR。
- PoCコード初回commit: `c1418d9ced70c0c3879648d9205124970e87e30f`。
- AIの失敗試行はa8104af上の未commitの作業ツリー、成功baselineはc1418d9上で実行。
  集計JSONの各 `vcs` を優先し、集計生成commitとテスト対象commitを混同しない。
- PR #35（二段階HTTPの停止試験）は未マージ。本作業では変更しない。
- PR #9/#10/#33/#34の成果物、Human Approval、既存送信方式を維持。

## OSSコード監査

対象: [tester-army/e2e](https://github.com/tester-army/e2e)、
取得HEAD `da790a1250d9164064a7ddde17a931f61e161f31`、2026-10-09T15:34:16Z。
HEADソースとnpm公開版を分け、実行には `e2e@0.19.0`、`@e2e-dev/web@0.14.0` を固定。
npmにgitHeadは返らなかったためHEADと公開版の同一性は断定しない。
lockfileのintegrityで公開パッケージを固定する。

|項目|確認結果・根拠|
|---|---|
|License|[Apache-2.0 / LICENSE](https://github.com/tester-army/e2e/blob/da790a1250d9164064a7ddde17a931f61e161f31/LICENSE)、NOTICEはCopyright 2026 TesterArmy, Inc.|
|商用利用|LICENSEの許諾は商用利用を排除しない。再配布時のLICENSE/NOTICE保持・変更表示等の条件を守る。商標の利用許諾やAIサービス料金は別。全推移依存の法務審査を済ませたとは扱わない。|
|要件|TypeScript/ESM、Node `^22.22.3 || >=24.8.0`。CLI自体にPythonは不要。保存診断の再分類だけ既存Pythonを利用。|
|このPC|元Node22.15.0は非対応。PC全体を更新せずGit管理外にNode24.21.0を分離し実行。|
|依存|e2e: AI SDK provider / Zod / oxc / MCP server / Vitest expectなど。web: `playwright-core@1.63.0`。全98依存を隔離lockfileに固定。|
|AI|AI SDK v7、OpenAI/Anthropic/Google/XAI/OpenAI-compatible等のoptional peer。APIキー、対応subscription/local modelの選択肢あり。今回OpenAIのみ、他providerは未検証。|
|モデル|`gpt-5.4-mini-2026-03-17`、text-only。正確な操作結果はlocatorで検証し、AIの自己申告のみで成功にしない。|
|Playwright|web engineを介してChromium等を操作。既存frontendのPW依存とPoC依存を分離。両環境の実測PWは1.63.0。|
|成果物|`report.json`、`summary.md`、trace.md、failure screenshot、任意screenshot。ログを手作業で成功へ書き換えない。|
|保守|HEAD最終更新は前日。0.xでminor間のAPI変更可能。SECURITYは最新minorのみ修正対象とする。更新時はversion/lock/安全試験を再監査。|
|脆弱性|2026-10-10 `npm audit`: 0件。既知DBの照会結果であり、無脆弱性の保証ではない。|

詳細確認箇所:
`packages/e2e/package.json`, `packages/web/package.json`, `LICENSE`, `NOTICE`, `SECURITY.md`,
`packages/web/src/browser.ts`, `surface.ts`, `route-options.ts`,
`packages/e2e/src/agent/model/sdk.ts`, `agent/invocation.ts`, `report/build.ts`。

## セキュリティ監査と追加境界

e2eの [SECURITY.md](https://github.com/tester-army/e2e/blob/da790a1250d9164064a7ddde17a931f61e161f31/SECURITY.md) は、
テスト/config/dependencyにOS権限がありsandboxではないこと、webにorigin allowlistがないことを明記する。
したがって、e2e単体を本番フォーム送信エンジンへ直結するのはNO-GO。
モデル入力はuntrustedとして扱われるが、任意ページからのprompt injectionへの完全耐性は実証していない。

追加したfixture-only境界:

- 新規loopback serverの正確なURLだけ許可。他localhostサービスも不可。
- GETだけ。ブラウザのHTTP要求をすべてroute interceptionし、Nodeでredirect:manualのGETを行いfulfill。
  3xxは追わず拒否。route.continueは使わない。
- 最大30 request/試行、3秒/GET、64KB/ページ。操作16 step、8 model call、120秒/試行。
- Service Worker、WebSocket、EventSource、beacon、popup、submitを無効化。
- 最終送信buttonはdisabled、serverは非GETを405拒否。模擬環境へのPOSTも0件。
- Anonymous fixture、Human cookieなし、DB/production API/SMTP/worker/承認API接続なし。
- Provider URLもOpenAI Responsesの固定endpointのみ。telemetry OFF、model store=false。
- APIキーは認証済み再利用指示に従い一時process環境へ渡した。値・headers・request本文はusage ledgerに保存しない。
- OS-level egress sandboxではない。依存コード自身の通信・任意コード実行を封じる本番隔離は別途必要。

## 7種類・同一条件比較

共通入力: 匿名テスト会社・匿名担当者・fixture@example.com・模擬問い合わせ文。
会社名fieldは既存fixtureのoptional flagで追加し、通常Phase 4 fixtureは変更しない。
baselineは **e2e webのPlaywright surfaceによる決定的selector操作**、AIは同じsurfaceでagent.actの自然言語操作。
既存 `@playwright/test` の44件は別途regressionとして実施。新baselineを旧coordinatorの性能そのものと混同しない。

|模擬フォーム|baseline 2回|AI|
|---|---|---|
|通常HTML|2/2、確認・読み戻し一致|PROVIDER_BLOCKED|
|JS動的生成|2/2、確認・読み戻し一致|未実行|
|確認画面付き|2/2、確認・読み戻し一致|未実行|
|同一origin iframe|2/2、確認・読み戻し一致|未実行|
|必須select/radio|2/2、選択値一致|未実行|
|同意checkbox|2/2、指定された同意のみ|未実行|
|不正email入力|2/2、入力エラー検出・確認未到達|未実行|

baseline: 成功率100%、必須項目62/62認識、誤入力0、正常フォーム確認到達12/12、
error case認識2/2、7種類とも2回で再現。入力・検証時間はJSONのdurationMsに記録。
AIの最初の試行は操作前にAPI利用が阻害された。
test/report上のfailed/skippedと「操作能力未測定」を分ける。
同意文を読んだだけで全同意を許可する設計ではなく、明示指定した同意のみ対象。
実フォーム送信成功率はnull。

## 費用と失敗原因

[公式モデル情報](https://developers.openai.com/api/docs/models/gpt-5.4-mini) を2026-10-10確認:
入力$0.75/M tokens、出力$4.50/M tokens、cache input $0.075/M。
見積りはcache割引なしで保守的に算出。

- 1試行8model call、7種類×2回。provider HTTP request自体も最大112、予約費用総額$5で停止。
- maxInputTokens8,000、出力上限1,024。112callが各8k入力なら概算$1.19。
  system/schema等で増える可能性があるため、固定の成功費用予測ではない。実際はUTF-8 request byte数で保守予約する。
- 当初の試行で429を5回受け取り中断。改善したfail-closed再試行で1回、合計6 API request。
- 最後の実応答code: `credit_balance_exhausted`。HTTP接続は到達、残高不足でAI応答なし。
- 1 provider失敗後は追加API requestを停止。SDK内再試行にもローカル拒否応答を返す。
- 使用token・実請求額はproviderが返していないためnull。runner token0をAPI実請求0と解釈しない。
- 再実行には[API billing](https://platform.openai.com/settings/organization/billing)の残高確認が必要。
  新しいkey作成・追加課金・別modelへの自動切替は行っていない。
- 比較PoCの調整後に自動再試行しない。ChatGPT subscriptionとAPI billingは別。
  `gpt-6-luna`等の別小型modelは将来の候補だが、この実測を埋める代用にはしていない。

## HOLD17再評価

既存Phase 4のoffline classifierを再実行。保存済みprivate sourceのみ使用。
Company・URL・連絡先を新規公開成果物へ転記しない。

|項目|件数|
|---|---:|
|元HOLD / BLOCKED|15 / 2|
|HTTP_READY|0|
|BROWSER_CANDIDATE（AI候補含む、成功保証なし）|1|
|HUMAN_REQUIRED（CAPTCHA）|5|
|TECHNICAL_UNKNOWN|11|
|営業PROHIBITED / UNKNOWN|2 / 15|
|Identity / 用途未確認|17 / 17|
|BROWSER_VERIFIED / APPROVED|0 / 0|

営業禁止2件と技術分類は独立軸なので単純に合算しない。
実URLへのGET、入力、CAPTCHA操作、POSTは0。
保存情報不足の11件はAIブラウザ対応可能と断定しない。

## 本体へ組み込む場合の設計案（今回未実装）

1. Labの経験を検証用Browser Preview Adapterへ限定。AIを承認者や送信権限者にしない。
2. Core permission/suppression/URL/DNS/robots/terms/timeoutをdeterministicに実施。
3. Humanがtarget、field values、同意内容、目的、method、fingerprintを確認して既存step-up承認。
4. method/target/payload/DOM変更で既存承認を無効にする。ブラウザの成功判定と承認を分ける。
5. CAPTCHAはHUMAN_REQUIRED、営業禁止はBLOCKED。AIで解消しない。
6. previewからdispatchへは別実装・別承認。idempotency/UNKNOWN保護・Audit Ledgerは既存基盤を維持。
7. AI障害や曖昧な結果はUNKNOWN/HOLDで止める。決定的Playwright経路へ切替えてAI成功を捏造しない。

## テスト・成果物・残課題

- PoC TypeScript strict typecheck成功。
- 安全unit5/5（URL/POST/redirect、provider fail-close・秘密情報非保存、call/cost上限）、backend再分類7/7。
- baseline14/14、既存Desktop/Mobile44/44。
- 既存frontend typecheck/lint/build成功。既存bundleサイズwarningは残存、本作業では変更しない。
- 新CIはkey不要のtypecheck/safety/baselineのみ。fork PRへAPI keyを公開しない。
- 個別trace/screenshotはGit管理外 `ai-form-lab/results/`、CI baseline artifactsは7日保持。
- 集計: `docs/results/phase4a-ai-e2e-comparison-20261010.json`。
- Migration、既存backend/API/送信/承認UI変更なし。merge/deploy/外部DMなし。

未完了: API残高回復後のAI7種類×2回の操作実測、AI費用・再現性、実フォームのDOM適用可能性。
実企業アクセス・本番adapter・送信は今回の許可範囲外。
次はAPI billing確認後、このlocalhost AI比較だけを再実行し、結果を本PRへ追加する。
