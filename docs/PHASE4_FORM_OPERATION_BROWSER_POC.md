# Phase 4: フォーム判定の分離とブラウザ操作PoC

## 1. 基準・既存PR・未統合状態

開始時の最新mainは `714e92e68f65bcf07ad0dc5eb54a641428294d25`。作業branchは `codex/phase4-browser-form-poc`。Phase 4は隔離PoC・保存データ再評価・接続設計のみで、通常の判定/API/UI/workerへ組み込んでいない。

| PR | 状態・成果 | 今回の扱い |
|---|---|---|
| #9 | 統合済み `7350918`。site evidence / bounded contact navigation、Form Intelligence改善 | 再実装しない |
| #10 | 統合済み `c698e31`。20件GET Pilot・オフライン診断結果 | 過去のGET結果と今回の模擬操作を混同しない |
| #33 | 統合済み `dda34ad`。確認reviewの独立process競合・commit前後kill | durable review基盤を維持 |
| #34 | 統合済み `714e92e`。bound二段階契約・localhost multipart HTTP | 本番二段階送信済みと解釈しない |
| #35 | 開始時OPEN、`codex/two-stage-process-safety`。HTTP全フローのkill/restart検証、CI成功 | 未統合。今回の前提にせず、競合・重複追加しない |
| #4 / #5 | 開始時OPEN。旧版比較監査 / Rawオフライン比較 | 今回のフォームPoCとは別範囲 |

`git branch -r --no-merged origin/main` は `codex/ai-evolution-phase1-audit`、`codex/ai-phase2-truth-evaluation`、`codex/two-stage-process-safety`。AI監査系には評価準備文書等が残るが、フォーム運用経路への変更として採用しない。mainへmerge・他branchの削除はしていない。

## 2. 現行機能監査と問題分析

| 機能 | 根拠ファイル（backend/app/services/配下） | 現状 |
|---|---|---|
| 発見・HTML解析 | form_intelligence/analyzer.py、fields.py、rules.py | 問い合わせ導線とDOM項目・営業禁止・CAPTCHAを検出 |
| HTTP対応判定 | form_intelligence/compatibility.py、form_profile_delivery.py | JS、CF7、確認画面、name欠落、独自submit、ファイル/認証等を保守的に停止 |
| 保存診断 | form_route_diagnostics.py | CF7_CANDIDATE / BROWSER_REVIEW / NATIVE_CANDIDATE / UNKNOWNと、BLOCKED / HUMAN_REQUIRED / TECHNICAL_HOLDを分離済み。execution_allowedは常にfalse |
| 保存観察 | form_observation_projection.py、form_observation_safety.py | current source/freshnessを照合。観察は送信許可を追加せず、制限のみ |
| CF7 | cf7_*、CF7_*設計書/既存lab tests | 構成別candidate / reservation契約あり。汎用CF7送信成功とは異なる |
| 二段階確認 | controlled_confirmation_review.py、two_stage_lab_contract.py、tests/two_stage_lab_runner.py | fixed synthetic review / HTTP lab。既存HTTP通常送信へ未接続 |
| Human承認 | human_approval.py、approved_form.py、model_approval.py | Human step-up、immutable snapshot/hash/version、source dependency、reject/revoke/expiry、Agent拒否を維持 |
| 結果保存 | form_delivery_result.py、approved_form_worker.py | POST後不明はsubmission_unknown。UNKNOWN自動retry不可 |
| Codex支援 | form_codex.py | legacy guard付きpayload/skill補助。新ブラウザPoCを既存送信skillへ接続しない |
| E2E | frontend/playwright.config.ts、tests/form-intelligence.spec.ts | 既存Playwright Desktop/Mobile・専用_test DB。今回のlabは別configでDBなし |

`delivery_supported=false` は「企業が送信を禁止している」ではなく、既存HTTP実行の対応を確認できていない場合がある。ただし技術的停止を外しただけでは、企業同一性、用途、営業可否、必須項目、同意、Human承認の不足は解消しない。既存reasonは残し、複雑という理由だけで送信可能に繰り上げない。

## 3. 新しい判定仕様（PoC専用・非認可）

| 操作状態 | 定義 |
|---|---|
| HTTP_READY | 保存delivery_supportedに加えcurrent構造・POST method・必須mappingを確認できる候補。承認ではない |
| BROWSER_CANDIDATE | 確認画面等の具体的な保存根拠がある検証候補。実操作未確認 |
| BROWSER_VERIFIED | 同じURL/構造/操作方式/入力snapshotを用いてブラウザの入力・確認を実際に検証した範囲。本Phaseでは匿名fixtureだけ |
| HUMAN_REQUIRED | CAPTCHA、認証/ファイル、未確認の同意等。回避・推測しない |
| TECHNICAL_UNKNOWN | 保存情報不足、ERROR/UNANALYZED、汎用unsupported理由しかなく構造を確定できない場合 |
| TECHNICAL_UNSUPPORTED | 対応不能な構造を具体的に確認した場合。delivery_supported=falseだけで設定しない |

| 営業許可 | 定義 |
|---|---|
| APPROVED | 有効なHuman承認が対象・本文・送信先・方式・構造にbindされた状態。今回は生成しない |
| REVIEW_REQUIRED | Core可否・企業同一性・窓口用途を確認したうえで個別Human承認待ち |
| PROHIBITED | 営業禁止、suppression、do_not_contact、過去UNKNOWN等による禁止。技術状態で上書きしない |
| UNKNOWN | 営業可否・Identity・用途等が未確定 |

実装は `backend/offline_replay/form_operation.py` の非認可pure分類と `frontend/form-lab/browser-poc.ts` の模擬検証結果。外部入力のconfirmed=trueやbrowser_verified=trueを承認・実行権限として受け付けない。実行可否は全結果false、Human承認は0件。

既存FormProfile/Sendabilityの値・enum・DB・APIを変更しないため、Migrationは不要。旧UIのHOLD/BLOCKED表示、既存送信guardはそのまま。汎用HTTP/CF7判定ロジックを新ブラウザ経路のために緩めていない。

## 4. localhost PoC

既存 `@playwright/test` / Chromiumを使い、追加dependencyはなし。`frontend/form-lab/playwright.config.ts` はDB・LeadHive API・ユーザーの既存ブラウザを起動/利用しない。新規BrowserContextでcookie/storageを共有せず、Desktop 1280px / Mobile 390pxの実viewportをassertする。

対象は通常HTML入力、JavaScript動的生成、確認表示、同一origin iframe、必須select/radio、必須同意checkboxの6種類。name/email/messageを明示値で入力し、選択肢を列挙・照合、同意の文言と事前指定を照合する。未知の必須値・選択・同意は入力前に停止。password/file、CAPTCHA、営業禁止も入力前に停止する。

確認画面はfixtureのDOM previewで、FormDataのreadbackと予定入力値を比較する。**サーバーへの確認POSTや最終POSTは一切行わない**。通常HTML入力の検証成功はHTTP delivery成功ではなく、確認表示の成功も実サイトのserver-side確認画面成功ではない。二段階multipart HTTP検証はPR #34の既存labに任せる。

送信ボタンはdisabledでクリックしない。それだけに頼らず、network guardで全POSTを拒否し、サーバーPOST受信0をassert。ブラウザ操作成功から既存Human承認・SendAttempt・Deliveryを作成する経路はない。

## 5. 安全境界

- own fixtureのliteral `127.0.0.1` / 明示port / exact GET URL allowlistのみ。任意origin、認証情報入りURL、query/fragment、未登録iframe/URLは拒否。ブラウザのDNS探索で実企業へ接続しない。
- requests最大20、操作最大20（既定12）、時間最大10秒（既定5秒）。timeout/retryなしの有限HTTP fetch。action budget停止を検証。
- Service Workerをblock、WebSocketをclose、popup/downloadを停止。秘密・業務Cookie・保存storageを渡さない。ログは操作名・reason・hash等で、入力値・token・credentials・スクリーンショット/traceは保存しない。
- fixtureのrobots.txtとowned usage許可を確認してから表示・入力。robots禁止・terms禁止をテスト。これは一般サイトのrobots parser/利用条件判断の完成ではない。
- 営業禁止はfixtureの禁止文言で停止。production化には既存Core permission/rulesのserver-side再確認が必須。PoCの短い正規表現を汎用営業可否判定として採用しない。
- 同意はラベル完全一致と明示choiceが必要。未選択・未知同意はHUMAN_REQUIRED。CAPTCHA・ログイン・アクセス制限の突破はしない。
- 入力後・preview前にも構造fingerprintを照合。変更時は停止。入力proposalは開始時cloneして、target/方式を含むpayload hashを生成。
- ページ本文をAgentへの命令として解釈しない。LLMを使わず決定的なfixture手順のみ実行。

初回のredirect負例は停止をassertできず2件失敗した。`route.continue`だけではredirect後のrequestを再捕捉できないという公式仕様を確認し、`route.fetch(maxRedirects=0, maxRetries=0)`で応答を取得し、3xxはブラウザへ渡さず停止する方式へ修正した。最終負例は未登録のlocalhost endpointで、redirect先GET受信0を実測。初回runを安全対策成功として数えない。

このguardは**owned localhost fixture向け**である。任意実サイトへの本番SSRF対策、DNS rebinding、すべてのbrowser通信チャネルを隔離した証明ではない。productionにはOS/container egress制限と既存pinned DNS/安全URL境界、全redirect/frame/actionへの適用が必要。

[Playwright Network公式資料](https://playwright.dev/docs/network)はredirectが元requestと一単位で扱われることと、Service Workerによるroute監視欠落を説明している。これを前提に、安全性をroute監視だけに依存させない。

## 6. 保存17件の再分類

正本inputはGit管理外の既存 `dist/sns-agency-readiness-pilot-20261008/core-diagnostics-private.json`。DBやサイトへの再取得なし。CLIはsourceを上書きせず、SHA-256と匿名record番号・status/reason集計だけを出力する。

| 指標 | 件数 |
|---|---:|
| 既存HOLD / BLOCKED | 15 / 2 |
| BROWSER_CANDIDATE | 1 |
| HUMAN_REQUIRED | 5 |
| TECHNICAL_UNKNOWN | 11 |
| HTTP_READY / BROWSER_VERIFIED / TECHNICAL_UNSUPPORTED | 0 / 0 / 0 |
| 営業許可UNKNOWN / PROHIBITED | 15 / 2 |
| 企業同一性未確認 / 用途未確認 | 17 / 17 |
| CAPTCHA / 営業禁止 | 5 / 2 |

カテゴリは重複。browser候補1件は保存済み確認画面フラグがあり、CAPTCHA/ERRORでないもの。残るdelivery_supported=falseやREVIEW_REQUIREDだけのレコードをJS/iframe/CF7と推測しない。画像・DOM・method情報が不足するためUNKNOWNを維持。UNKNOWN11件にはBLOCKED2件の技術状態も含むが、禁止状態は独立して維持する。

実サイトのHOLD解除0件、実サイト操作検証0件、送信成功率null。匿名再分類は `docs/results/phase4-saved-form-reclassification-20261010.json`。

## 7. PlaywrightとCodexの比較

| 観点 | Playwright | Codex browser / Computer Use |
|---|---|---|
| 今回の実測 | 6種類×Desktop/Mobileの決定的fixture | 別の対話型browser sessionでの性能実測は未実施 |
| 入力/mapping | fixtureのname/label/optionsを列挙し明示値を使用 | 曖昧な画面の調査・提案候補。判断の正確性は別評価が必要 |
| 再現性 | locator/assertionをGit/CIへ保存可能 | session・製品設定等の影響を受けるため再現条件の保存が必要 |
| 大量処理 | worker側の隔離/予算/egressを整備してから検討 | 特殊フォームの少量Execution Assistant候補。毎件の一般経路にしない |
| 認証/情報保護 | empty context・固定通信先を今回検証 | 利用者のログインCookieをAgentへ流用しない専用sessionが必要 |
| 承認 | Core承認から独立、送信権限なし | 同じCore承認・suppression/UNKNOWN境界が必要。AI判断で承認代行不可 |
| 時間・費用 | localhost実行時間を記録、原価はnull | 未実測。API/契約/操作量依存のためnull |

[OpenAI公式Browser資料](https://learn.chatgpt.com/docs/browser?surface=app)ではブラウザ操作やDeveloper modeによるDOM/ネットワーク調査が説明される。製品機能の存在はLeadHive worker接続済みや安全な無人送信を意味しない。まずPlaywrightの決定的な隔離経路を基礎とし、Codexは未知構造の調査補助として、同じ非認可入力/確認STOPを守る設計を推奨する。

## 8. Human Approvalへの接続設計（未実装）

既存ApprovalRequest、HumanApprovalProof、OutreachAuditEvent、valid_approved_payloadとsource fingerprintを再利用する。Humanは企業、URL、送信先purpose、本文、sender、form/frame/action、必須項目、選択・同意、HTTP/BROWSER方式を確認する。

将来のbrowser用canonical payloadには company/project/draft/profile ID、正規化targetとframe/action、form fingerprint、入力/選択/同意snapshot、sender、browser adapter/operation version、attachment metadataを含める。token/credentialsはpayload/logへ平文保存しない。

HTTP承認をbrowser方式へ流用しない。browser-specific delivery_method/契約validatorとsnapshot hashを追加し、方式・target・本文・フォーム構造・consent等が変わったら旧承認をREVOKED/invalidへ落とし、新しいversionでHuman step-upを要求する。supersedes linkで追跡し、AgentからAPPROVEDへの遷移は403のまま。

既存delivery_methodはString/Proposal Literalであり、generic form_plan_fixture等はDBのnon-consumable guardを持つ。本番browser method追加ではAPI validatorだけでなく、DB constraint/trigger、worker allowlist、audit event、source bindingsの全境界を監査する。JSON snapshot活用だけで移行できると決めつけず、必要な場合のみadditive migrationを別PRで作成する。既存migrationは変更しない。

最終送信接続は本Phase対象外。将来も実行直前のsuppression/opt-out/営業禁止/Identity/purpose/duplicate/rate/fingerprint/承認TTL再確認、承認消費とUNKNOWN証跡のI/O前commit、idempotency、UNKNOWN非retryを必須にする。

## 9. 評価・テスト

PoCのsuccessは「匿名入力・fixture確認画面・readback照合まで」。real accepted/deliveredとは別。

- 最終PoC: 44 tests（22×Desktop/Mobile）。成功fixture試行12、確認到達12、必須group42を既知の正解と照合。
- 誤操作は期待外の入力/POST/未登録GETがなかったことをfixture assertionで確認。意図した遮断テストのrequest試行は誤送信件数に数えない。
- Offline分類/既存収集比較: 59 tests PASS、新規分類7件を含む。mypy offline_replay 7ファイルPASS。
- 既存route diagnostics / confirmation review / 二段階HTTP / approval関連: 65 tests PASS。
- Frontend typecheck / lint / build PASS。最終Mobile viewportを含むPoC結果と時間は `docs/results/phase4-browser-poc-20261010.json`。
- backend-tests、Ruff/format、既存E2E、migration往復/model diff、Windows検証はCIの既存jobを維持。追加 `form-browser-poc` jobで隔離PoCを再実行しreport/summary artifactを保存。

実フォーム送信成功率・推定原価・Codex実操作時間は未測定null。localhost原価を無料と決めつけない。実フォームPOST/メール/承認代行は0。Migration/API/Core送信変更なし。

## 10. 本番導入の段階計画・追加承認

1. **このPoCをレビュー**: unknownの扱い・禁止優先・再現テスト・境界設計を確認。自動mergeなし。
2. **実サイト用隔離設計の別PR**: pinned DNS/egress、redirect/frame/action安全確認、robots/terms、専用cookie/CSRF、HTML観測provenance、有限予算を整備。実サイト操作なしで負例を証明。
3. **読み取り・入力/確認だけの少量検証計画**: Humanが対象URL・件数・許可するGET/操作・費用・時間を明示承認。確認ボタンがPOSTするサイトでは、そのPOST自体が外部送信になり得るため勝手にクリックしない。CAPTCHA/営業禁止は対象外。
4. **Browser Observation保存/再承認UI**: 技術候補を承認と分けて表示。方法/構造の変更失効、Human入力・同意確認導線を整備。必要DB/API変更は別PR。
5. **最終dispatch検証は別工程**: 本番Core境界へ接続する前にI/O前commit・kill/restart・UNKNOWN・二重送信防止をlabで証明。実企業への送信はさらに対象/文面/送信先/方式をHumanが承認してから。

判定: **GO（保存データ再分類・localhost入力/確認PoC） / NO-GO（実サイト操作・本番送信）**。6種類のfixture成功を「全フォーム対応」や「保存17件の送信可能化」と報告しない。Phase 4はここで停止する。
