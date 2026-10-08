# CF7・JavaScript確認画面の実行経路アダプター設計

## 1. ゴールと基準

2026-10-06、`codex/integration@279b2584729e01cf773068cadd8b4bc4afa87162`。[解析1.7のGET確認](105_HELD_FORM_V17_GET_ONLY_RECHECK.md)を踏まえ、未対応経路を安全に追加する条件を設計する。今回は文書のみ。アプリ・API・DB・Migration・UIの変更、実サイトGET/入力/POST、匿名サーバーでのPOST、Codexタスク起動、外部AI呼出しは行わない。テスト表は実行結果ではなく将来の受入条件。

CF7という識別だけで特定のAPIや成功応答を仮定しない。プラグインversion・サイト設定・独自拡張を実装前に確認する必要がある。今回、公式プロトコルの検証や実サイトの動作検証は行っていない。

## 2. 現在の実装と再利用箇所

| 根拠ファイル（backend/app/services/以下） | 現在の境界 | 方針 |
|---|---|---|
| form_intelligence/compatibility.py | CF7・明示的なJS経路をsupported=falseにする | 保留を維持。静的候補と実行対応を混同しない |
| form_intelligence/fingerprint.py | 項目の位置・name/id・label/type・required/optionsのhash | 維持。ただし操作手順・JS・通信先を網羅しないため追加の経路証拠が必要 |
| form_approval_preparation.py | 保存済み情報からform_direct提案・Human選択済み入力値を準備 | 通常経路を維持。アダプター用準備は別Service境界で追加する案 |
| approved_form.py:validate/reserve | Human証明・期限・hash/version・権限・重複を確認。確認画面あり/不明を拒否 | 通常経路の条件を緩めない。新しいdelivery_methodは明示的な検証分岐を経る |
| approved_form_worker.py:begin/run | 通常経路のGET検査後、承認CONSUMEDと永続UNKNOWNをPOST前に同一transactionでcommit | 共通安全境界として再利用する設計。現状のrunはsubmit_formへ固定接続 |
| form_submission_guard.py | 共通advisory lockとFormDelivery unknown予約 | 維持。アダプターにも同じcompany/form URLの二重試行防止を適用 |
| form_delivery.py | HTMLを再取得、禁止/CAPTCHA/互換性/fingerprint/action/必須値を確認 | 通常のstatic POST経路として維持 |
| form_delivery_result.py | 通常HTTP応答・確認画面・完了証拠を判定。POST後の例外はsubmission_unknown | 再利用可能な概念と既存テストを残す。ブラウザ応答/CF7応答の成功根拠は別検証が必要 |
| form_codex.py | legacy flag配下のskill用payload生成 | 維持。ただし新しいHuman承認の実行証明にはならないため、そのまま新経路へ接続しない |

特に、form_delivery_result.pyには確認画面の二段階POST処理があるが、承認付きworkerはconfirmation_expected=falseであり、approved_form.validateも確認画面を拒否する。旧コードが存在することを「承認付き確認画面対応済み」と扱わない。

既存のsuppression/opt-out/連絡禁止、step-up、append-only監査、上限・サイト間隔、一時停止、Agent/Human分離はそのまま使う。SYSTEMをHumanとして記録しない。AutomationPolicyの将来導入とは分け、初期アダプターは既存MANUAL承認を必須とする。

## 3. 経路の分類

優先順はBLOCKED → HUMAN REQUIRED → CODEX ASSISTED → NORMAL PATH。分類は実行許可そのものではない。

| 分類 | 条件 | 実行境界 |
|---|---|---|
| BLOCKED | suppression/opt-out/do_not_contact/営業禁止、危険URL、既存UNKNOWN・重複試行等 | アダプター・Codex・Human通常操作で迂回不可 |
| HUMAN REQUIRED | CAPTCHA、同意の必須性不明、連絡方法未選択、添付・login・曖昧な通信先/確認内容 | 自動操作停止。CAPTCHA突破しない。解決後も承認内容と構造を再確認 |
| CODEX ASSISTED | 通常経路では扱えないが、限定手順・通信境界・承認内容の照合を人が確認できる特殊フォーム | 将来の支援候補。legacy payloadを渡すだけで実行しない。中央の予約・消費・結果記録へ接続できるまで準備/確認に限定 |
| NORMAL PATH | 既存static direct、または匿名受入試験に合格した明示的adapter/versionと経路descriptor | 共通安全検証と永続予約の後、承認した手順のみ実行 |

現時点ではCecil/PALIOは通常経路対象外。静的解析でCAPTCHA_NONE・営業ALLOWEDでも実行許可にはしない。JS実行後のCAPTCHAや新しい禁止文言でも停止する。

## 4. 最小Service案

以下は提案する内部契約であり、既存関数・APIとして存在するものではない。

1. `identify(document)`：静的証拠からadapter候補を選ぶ。CF7識別/JSボタンの存在だけでは実行readyを返さない。
2. `describe(fixture_or_readonly_page)`：操作計画、通信先、項目、既知の段階、制限、未確認点を返す。採用versionが不明なら要確認。
3. `validate_plan(snapshot, current_descriptor)`：同じ営業入力・宛先・手順・adapter/versionかをdeterministicに照合する。
4. `execute(authorized_context)`：中央が発行した一回の試行contextのみ受ける。任意URL・script・自由文の操作指示を受け取らない。
5. `classify_result(evidence)`：SUBMITTED/UNKNOWN等の機械的な理由付き結果を返す。AIの「成功したと思う」で成功にしない。

中央がDB transaction・権限・承認消費・rate/duplicate制御を所有し、adapterは承認を作成/消費せず、キュー再登録・retryも行わない。未登録adapter/versionはfail closed。旧direct実装は別adapterへ作り直す必要はない。

## 5. 承認に固定する内容

既存payload_snapshot/hash/versionを再利用し、将来新しいcanonicalization versionで経路descriptorのhashを含める案。既存snapshotは書き換えない。旧承認を新adapterで使わず再準備・再承認する。

- Company/Project、channel、delivery_method、adapter ID/version。
- form URL、origin（scheme/hostname/port）、form selectorの根拠、送信先・HTTP method・encoding・許可された段階。
- sender、subject/body、全営業入力、連絡方法・同意のHuman選択、未選択の任意同意を除外する規則。
- field fingerprintと経路descriptor、確認画面で照合する意味項目、予定される最終操作。
- 期限・最大段階数・試行時間・通信先制限・response判定version。

field fingerprintだけではJS変更の検出が足りない。入力送信に関わるscript/resource versionまたは固定した手順・通信descriptorを追加照合する。未知のscriptや変更時は停止し、全面的な動作同一性を保証できるとは扱わない。無関係なanalyticsも含む全HTML hashで雑に対応するのではなく、実行に関係する証拠をversion付きで定義し、曖昧なら支援へ送る。

CSRF/nonce等の短命tokenは秘密の実行時情報として扱い、監査に生値を保存しない。承認対象の営業入力から分離するが、自由なhidden値変更を許さない。許容するtokenのname・由来・binding規則を限定する。hidden値に含まれる宛先・本文・添付先等はtoken例外ではなく意味payloadとして照合する。分類不能なら停止。

確認画面の表示値・hidden値・JSON等から復元した最終意味payloadが承認snapshotに一致することが必要。欠落・切り詰め・差替え・新しい必須同意・宛先変更は最終操作をしない。確認後しか分からない宛先は事前承認対象を固定できないため初期対象外。

## 6. CF7候補

最初の対象は匿名fixtureで再現した固定version・固定構成のCF7相当契約とする。実CF7全体への互換性を宣言しない。ブラウザ経由か専用HTTPadapterかはprotocol確認後に決める。

form actionと実際の送信APIが異なる場合、現在のform_action_urlだけで承認済みとしない。API endpoint・form識別子・必要token・encoding・response schemaをdescriptorへ固定する。未知の拡張、file、CAPTCHA、外部送信先、未知のhookは対象外。

CF7の応答を匿名JSON fixtureで分類する。既知の受付成功状態・form ID・HTTP応答を同じ試行に対応付け、曖昧な200/HTML/別ID/不明statusを成功にしない。「受付成功」と相手のメール到達・返信を区別する。HTTP clientやブラウザを共に使って同じフォームを二度送らない。fallbackは最初の外部試行前だけ可能とする。

## 7. JavaScript確認画面候補

ブラウザは任意scriptを安全と仮定せず、限定されたExecution Layerとして扱う。人のCookie・API key・SMTP credentialを渡さない。隔離profileを使い、終了時に廃棄する。download・popup・外部navigation・private/link-local network・未知の通信先は拒否する。送信とは別のresource GETにもSSRF/origin/size/time制限が必要。

「確認」クリック、入力event、page loadでも送信が起こり得るため、見た目のボタン名を副作用境界にしない。匿名fixtureを除くread-only検査では非GET通信と営業入力を禁止し、計画を確定できなければ要支援のまま。実行時は、サイトJSを動かす前から非GETをdefault denyにし、中央の永続UNKNOWN/承認消費がcommit済みの場合のみ許可された経路を開く。GETで送信する未知経路も許可しない。

未知のJSを実行する汎用自動送信は初期対象外。既知のfixture/限定adapterで、営業入力→確認の各eventに生じる通信を測定し、承認したplanを超える通信を拒否する。確認画面を開いた後も、最終payload・送信先・CAPTCHA・禁止文言を再照合する。

## 8. 試行状態とUNKNOWN

既存予約のqueued→checking→unknown→submitted/failedを維持する。段階詳細は別の証拠としてPRECHECK/INTERACTING/CONFIRM_REVIEW/FINAL_REQUEST/RESULT_OBSERVEDを記録する案。unknownは実行中を保守的に含み、「最終POSTがまだだから再試行可能」と扱わない。

1. 同じapproval/keyの予約重複、company/form URLの未知試行、期限・権限・suppression等を中央で拒否。
2. 副作用のない事前検査でdescriptor/hash/version/入力条件を照合。
3. 中央transactionで承認消費、FormDelivery UNKNOWN、dispatch開始、監査をcommit。
4. 固定planに沿う一回の実行。各段階前に停止設定・有効な安全条件を確認。POST直前のDB条件と外部受付を完全に原子化できるとは保証しない。
5. 同じ試行の受付成功証拠があればsubmitted。最初の副作用候補の前に停止できた証拠がある場合だけfailed/blockedに区別。通信後のvalidation errorでも現行の保守的UNKNOWNを自動で緩めない。
6. timeout、redirect再POST要求、browser/worker消失、確認画面不一致、結果保存失敗はUNKNOWN維持。Human Reviewへ。別adapter/legacy/Codexによる自動retry禁止。

外部サイトのidempotencyは仮定しない。同一承認からの一回の試行開始を保証する設計であり、外部側のexactly-once受付を保証するものではない。ブラウザやHTTP clientの自動再POST、307/308での再送、script内retryを抑止できない場合は対象外とする。

## 9. DB/API/UIへの影響案

今回変更しない。将来の最小additive案：FormProfileに静的なdelivery_supportedとは別のadapter candidate/version/descriptor hash・verified scope、Approval snapshotにexecution plan version/hash、dispatchに段階別証拠を保持。新規Modelは既存のJSON/監査eventで足りるか確認後に決める。Migrationを書き換えない。

Agentへexecute/approveを公開しない。現在のschema_approval.pyはdelivery_methodをemail/form_direct/form_codexに限定する。既存Human準備・step-up・予約APIを継承する案だが、schema enum・canonicalization・DB trigger・proof検証を確認し、未対応methodの受付を先に有効化しない。Project外のprofile/approval/contextを使用不可。tenant別送信者が未整備である既存制約をこの工程で解決済みと扱わない。

UIは「静的候補」「adapterで検証した範囲」「未確認」「Human対応」を区別。段階・承認する通信先/操作・停止理由・UNKNOWNを表示する。送信/予約ボタンを今回追加しない。技術保留を解除する操作は新しい証拠・再準備・Human承認を前提とする。

## 10. 匿名fixtureの受入試験計画

専用DB・管理下HTTP lab・合成Human session・合成送信者のみ。通常設定はOFF。lab限定の通信先許可はProductionに適用できない構造とし、現存92番の隔離検証方針を再利用する。

| ケース | 必須結果 |
|---|---|
| CF7相当の固定schema受付成功 | 受付1回、同じform ID/試行の証拠、submitted、監査・承認CONSUMED |
| CF7未知status・別form ID・曖昧200・受付後切断 | UNKNOWN、繰り返しclaim/時間経過で受付回数不変 |
| JS確認がローカルDOMだけ／確認がPOST | 承認済み有限planのみ。副作用前commitを検証、最終受付1回 |
| 確認POSTが実は受付を兼ねる | 最終操作を重ねない。識別不能ならUNKNOWN/対象外 |
| 確認後の本文/宛先/同意/hidden意味値変更 | 最終送信0。既に通信した場合UNKNOWN、自動fallback0 |
| token更新／token名・由来変更 | 既知bindingだけ許容。未知は停止。監査にtoken生値なし |
| script/adapter/version/経路hash変更 | 旧承認拒否、再準備必須 |
| CAPTCHA出現・禁止文言・suppression/opt-out追加 | 自動処理停止。未知受付をFAILEDへ置き換えない |
| cross-origin/private URL・popup/download・未知network request | 許可しない。外部漏えい0 |
| input eventによる早期通信・JS retry・307再POST | 事前deny、予約後も未知/重複通信拒否。抑止不能ならadapter対象外 |
| 多worker同時claim・同approval別key・directとadapter競争 | 一回の試行開始、共有duplicate制御 |
| commit前/後・確認後・受付直後のprocess kill | 副作用前は受付0。開始後はUNKNOWN永続、自動再試行0 |
| Agent承認/実行・Human Cookie混在・viewer・他Project | 拒否、認証/権限境界を維持 |
| 回帰 | 既存direct、同意・連絡方法、期限/失効、上限・site間隔、取消、PC/mobileを維持 |

成功率・処理速度・月10,000件の能力はこのfixture試験だけで実証しない。新しい経路が使えるフォーム割合も別測定。

## 11. 実装順序と停止条件

1. **次の一工程：匿名fixture仕様と副作用なしのadapter descriptor/plan検証。** 成功・失敗・UNKNOWNの合成応答を定義し、snapshot照合・未知経路拒否のunit testを実装する。実行器・送信接続は追加しない。
2. Human承認payload/DB制約への最小追加を独立工程で検証。旧directの回帰と旧承認の非転用を確認。
3. CF7相当固定契約のHTTP lab adapterを独立工程で実装・障害試験。受入合格まで既定OFF。
4. JS確認用の隔離browser/network guardを独立工程で検証。実企業を利用しない。
5. 中央workerへの明示的接続、UIの検証範囲表示、配布更新を別工程とする。実サイトの受理確認や本番有効化は別の承認・計画が必要。

通信境界が固定できない、tokenと意味入力を分離できない、JS内再送を抑止できない、永続UNKNOWNを維持できない、確認後payload照合ができない場合はNORMAL PATHへ昇格しない。汎用ブラウザの自由な営業自動操作へ拡大しない。Cecil/PALIOの保留は維持する。
