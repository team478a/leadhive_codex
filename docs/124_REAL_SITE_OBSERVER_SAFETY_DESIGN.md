# 実サイト用CF7 Observer — O1安全設計・静的観察の検証

## 1. ゴール・現在の判定

2026-10-06、基準 `codex/integration@e6ae1e3`。検証器commitは `c079e38`。P1〜P3の候補保存・Human確認・改訂を維持し、実サイト用observerの導入を別ゴールへ分離した。

今回の範囲は**安全設計と、架空HTMLによる未登録の静的観察prototype**。実企業のGET、CF7 REST GET/POST、API/worker登録、DB保存、migration、送信・予約・consume、配布更新・deployは行わない。

判定：**O1の管理下静的観察は検証可能。本番observer・実CF7候補への登録はNOT READY。** 次はO2の管理下GET接続検証だけ。P3完了やHTTP/TLS試験成功を、実サイトの送信可否保証に換算しない。

## 2. 現行境界の確認

| 現行実装 | 再利用・不足 |
|---|---|
| `scripts/pinned_tls_lab/transport.py` | 全DNS回答検査、数値IP固定、元hostname SNI/Host、TLS verify、proxy/cookie不使用、retry0、redirect拒否、identity応答64KiB、単調時計deadline。未登録prototype。Resultはstatus/body/pinned_ipのみで、HTML metadataの検証契約が不足 |
| `scripts/pinned_tls_lab/resolver.py` / `dns_worker.py` | DNS固着の子process隔離・admission・kill/wait・未確認終了quarantine。OS起動固着/親強制終了までの絶対停止保証ではない |
| `backend/app/services/scraper.py` | 既存SafeFetcherには事前DNS検査後のhostname再解決と環境proxy依存が残る。新observerへそのまま接続しない。今回は変更しない |
| `backend/app/services/form_intelligence/analyzer.py` / `rules.py` | DOM/label/禁止/CAPTCHAの解析を持つ。既存 `sales_contact_status` は禁止未検出かつform_foundならALLOWED、`_captcha_type` は未検出ならCAPTCHA_NONE。この値を新observerの「実証済み許可・不在証明」として再利用しない |
| `backend/app/model_form_intelligence.py` / `schema_form_intelligence.py` | captcha enumにUNVERIFIEDがない。デフォルトもCAPTCHA_NONE。未知状態をNONEへ丸めて既存Profileへ保存する経路は作らない |
| `backend/app/model_cf7.py` / migration `0152bc1f7548` | source_kindはCONTROLLED_FIXTUREのみ、append-only・所有関係・期限をDBで制約。実サイトHTMLをfixtureとして偽装して保存しない |
| `backend/app/services/cf7_candidate_preparation.py` | 専用test DB・fixture版・現在Profile・permission・鮮度・hash再構築を要求する。新observer結果は対象外 |
| `backend/app/services/cf7_candidate_contract.py` | immutableな非実行candidate契約。版・URL・control・wire検証は再利用可能。検出したDOMだけで契約を完成したことにしない |
| `backend/app/services/contact_permission.py` | suppression/opt-out/do_not_contact/禁止/既送信・UNKNOWN等の最終Core境界を維持。observerを新しいALLOW判定器にしない |

上記は接続前のblocker。既存の通常解析・送信経路を今回修正済み、またはALLOWEDの意味を全面変更済みとは報告しない。

## 3. 分離する責務と将来フロー

```text
Project / Company / 既知contact URL（サーバー側解決）
  → Principal / tenant / job予算 / Core禁止確認
  → Fetch Policy（GETのみ、robots・宛先・request予算）
  → Resolver / pinned TLS / bounded response
  → 静的DOM観察（Untrusted Data、JSを実行しない）
  → Observation Evidence（許可・不在証明ではない）
  → deterministic Rules / Human assessment / capability検証
  → 非実行candidateの新規契約・新Human承認
  → STOP（送信は別ゴール）
```

Agentへ任意URL、header、cookie、proxy、TLS context、HTTP method、raw HTML uploadを渡させない。Company IDから現在のProject/URLを解決し、URL変更・権限剥奪・cancelを各境界で再確認する。Dots固有APIにはしない。

## 4. 取得Policy案（まだ未実装）

- 初期はCompanyに保存された1つのcontact URLだけ。自動リンク巡回・問い合わせpath推測・assets/iframe/REST rootへの追加取得をしない。
- HTTPS・hostname・443・匿名。userinfo/IP literal/fragment/制御文字/backslash、queryや曖昧なencoded path・dot segment、認証依存は初期拒否。contact page以外の操作用URLへ進めない。
- robotsを同一originで別の安全GETとして確認。401/403/禁止/error/不明な規則はcontact GETをしない。404の扱いは明示Policyと試験で固定し、未知を無条件allowにしない。robots取得もrequest/site予算に含める。
- 全GETごとに全DNS回答の公開性を検査し、選択IPへ固定、元hostnameでTLS検証。私有IP・混在回答・proxy・証明書無効化・自動別IP fallbackなし。
- redirectは初期全停止。表示されたLocationへ自動追従しない。圧縮は初期拒否、GET retry0、有限request deadline。429/503等を自動連打しない。
- status200、単一で整合するContent-Type/charset/encoding/lengthを検証。header総量・重複header・途中切断・宣言length不一致にも上限/停止規則が必要。bodyはUTF-8・最大64KiB。初期非対応はHuman Requiredへ案内し、認証や圧縮をこっそりfallbackしない。
- cookie/Authorization/LeadHive session/Agent credential/API/SMTP鍵を一切継承しない。Set-Cookieを次requestへ持ち越さない。DNS childは既存の最小環境分離を維持する。
- GETでも相手側のaccess logや副作用を完全には否定できない。「Form POSTなし」と「相手サイトの副作用なし」を区別する。

## 5. O1静的観察prototype

`scripts/cf7_observer_lab/observer.py` の `analyze(page_url, body, status, media_type)` は渡されたbytesだけを解析する。I/O・app/DB・approval/dispatcherをimportしない。pinned labのURL validatorのみ利用する。

初期対象はHTTPS・同一origin・UTF-8・64KiB以内・単一CF7 form・静的JSONのwpcf7.api・path形式REST root・固定6.1.4・既知hidden6欄・空posted-data hash・整合したform ID/unit/container・既知control型。subdirectory rootは観察できるが、対応済み認可へ昇格しない。

重複HTML attributeをBeautifulSoupの修復前に拒否し、JSON重複key、form/ID/nameの重複、任意JS handler、未知hidden/nonce/token、file/select、label不足、disabled/readonly、外部form controls、base override、invert acceptance等で停止する。query rootや特殊構成は初期未対応。

観察結果はimmutableな `structure_json` と版付きevidence hash。URL/metadata/有効HTML bytes/hash/decision/reason/構造をbindする。controlsは順序・name/type/label/required/checkbox value/default checkedを記録するが、選択を作らず、mappingはHUMAN_REQUIRED。default checkedをHumanの同意へ読み替えない。

| 出力 | 意味 |
|---|---|
| REVIEW_REQUIRED / STATIC_ONLY_UNVERIFIED | 静的構造を抽出できたが、runtime/営業許可/CAPTCHA/構成の確認が必要 |
| BLOCKED / SALES_PROHIBITED | 限定ruleで禁止表記を検出。構造を承認へ進めない |
| HUMAN_REQUIRED | CAPTCHA兆候、特殊同意、カスタム動作等。自動対応へ進めない |
| UNSUPPORTED | URL/metadata/encoding/構造/版等が初期対象外 |

**すべて `source_kind=STATIC_HTML_UNVERIFIED`、`eligible_for_approval=false`。** 営業許可は原則UNCERTAIN、禁止検出時だけPROHIBITED。CAPTCHAは原則UNVERIFIED、兆候検出時だけDETECTED。ALLOWED/CAPTCHA_NONE/READYを出力しない。

禁止検出は限定した文字列ruleであり網羅的ではない。外部JSの内容・動的CAPTCHA・server/plugin設定・規約の意味は未検証。不検出を安全証明にしない。hashが同じでも外部script/server設定の不変を証明しない。CPU・OS異常までの絶対parse deadline/sandboxは未実装。

## 6. 保存・既存Foundation接続案（設計のみ）

最初の実サイト保存は `FormObservationEvidence` 等の独立したappend-only診断証拠を候補とする。project/company/profile/job、取得source、fetch/parser/policy version、serverの観察時刻/期限、URL/公開IP・TLS検証metadata、HTML digest、structure digest、control/route、reason、UNVERIFIED状態を持たせる。保存内容・retention・サイズ・tenant boundaryはO3で最小schemaを決める。

raw HTML、cookie、認証header、未知token、鍵、任意scriptは通常ledgerへ保存しない。原本が調査に必要なら権限・暗号化・短期retention・redactionを別設計する。digestだけでは禁止表記の根拠を説明できないので、固定rule IDと限定・無害化した証拠文を検討する。

技術対応の検証やHumanによる意味確認は別の版付きAssessmentにし、STATIC observationを上書きして検証済みへ見せない。新しいobservations/source/Assessment変更で旧candidateを失効させる。既存解析の手動修正保護も維持する。

現在のCF7Observationへ入れるためにsource_kind CHECKを外したり、fixture label/observer版を偽装したりしない。将来必要なDB変更はadditive migrationとして検証し、P1のCONSUMED/予約/実行リンク拒否を保持する。

新実サイトcandidateを許す前に、source種別/版/期限/現在source/meaning/technical capabilityのserver再構築とDB bindingを追加設計する。Human approvalと送信認可は別。Agentのboolean、AIの自由文、手動「送ってよい」でCore禁止/CAPTCHA/UNKNOWNを無効化しない。

## 7. Job・大量処理・監査案

既存OperationJobとProject境界を再利用する計画。まず1社1URL、少数admissionとsiteごとの間隔。collectionや送信上限とは別のfetch予算を持ち、同じjob/URL/source versionの重複観察を抑制する。途中cancel・worker停止・DNS child未回収は固定errorで停止し、quarantine/管理者確認を行う。

新scope追加が必要ならHuman管理で最小のobservation create/readへ限定する。既存 `company:read` を任意Web fetch権限へ読み替えない。scope/APIは今回は追加しない。

begin/fetch blocked/parse decision/source changed/cancel/failed/evidence savedをactor/job/project/company・版・hash・固定reasonで記録する。原文を命令と扱わない。送信件数やSENT/UNKNOWNの配送台帳へ観察を加算しない。

## 8. Blockerと段階的実装計画

| 工程 | ゴール・受入 | 停止点 |
|---|---|---|
| O1（今回） | 静的観察を認可と分離し、架空HTMLの安全caseと既存TLS/DNS回帰を確認 | app/DB/実サイト未接続 |
| O2 | 管理下TLS HTML serverでGET-only fetch→parse。metadata/response上限、robots、DNS変更/固着、証明書、redirect、圧縮、切断、credential、cancelを連結検証 | 外部実サイト/API/DB保存なし |
| O3 | tenant/job・非認可の証拠保存・診断UI。UNVERIFIED状態のschemaとappend-only migration監査 | fixture/PENDINGへ自動昇格しない |
| O4 | 管理下の実CF7でDOM/外部JS/config/手動mapping・同意・capabilityの証拠を検証 | 営業許可を静的未検出で確定しない |
| O5 | 新sourceの非実行候補binding、Human承認・改訂・失効・DB/API/UI受入 | 予約/consume/送信不可を維持 |
| 別ゴール | 実行用契約・直前再検証・SendAttempt/UNKNOWN・idempotency・運用制限の設計/検証 | 個別に計画し、実送信へ自動移行しない |

最大blocker：①既存fetchのIP固定/proxy不足、②HTTP metadata/parse隔離・予算/robots未統合、③ALLOWED/CAPTCHA_NONEの観察と確認済み判断の区別、④実サイト証拠の保存schema/source binding未実装、⑤静的HTMLではruntime/plugin/CAPTCHA/営業許可を実証できないこと。

## 9. 検証記録・運用状態

Windows / Python 3.12、BeautifulSoup 4.15.0、httpcore 1.0.9、既存backend開発環境を使用。runtime依存の追加・変更なし。再現方法は [README](../scripts/cf7_observer_lab/README.md)。

- 新observer **14 tests成功（最終実行0.239秒）**。静的構造の抽出、必須/任意と初期checkedの区別、prompt injectionを単なるtextとして保持、営業禁止/CAPTCHA兆候で停止、危険page/root、JSON重複/動的config/非JSON定数、版/hidden/ID不整合、重複attribute/name/ID、custom JS/base/外部controls、invert、file/select/label、encoding/HTTP metadata/サイズ、hash変更、非認可状態の固定を確認した。テスト内subcaseを別件数へ加算しない。
- 既存pinned TLS/DNS **33 tests成功（25.542秒）**。管理下loopback TLSと隔離DNS fixtureだけ。検査用public IPへ実接続した試験ではない。
- 既存CF7 protocol/gateway/contract bridgeのoffline **20 tests成功（2.653秒）**。実WordPress lab全体や実企業との試験ではない。
- 上記3群は独立した試験。**GET取得→HTML解析→DB証拠保存のend-to-end成功ではない。** その接続はO2/O3に残る。
- Ruff lint/format、compileall、observer 1ファイルのmypy `--strict --follow-imports=silent` 成功。型検査ではMYPYPATHで既存pinned labを解決した。全applicationの型/回帰試験ではない。
- application/Frontend/DB/migrationを変更していないため、P3のBackend回帰、UI E2E、Frontend build、migration往復は再実行していない。
- 稼働API healthはstatus/databaseともok、送信workerはexited。新prototypeから外部DNS/HTTPを呼んでいない。prototype/既存TLS labはアプリ未登録で、稼働SafeFetcherの不足を修正済みとはしない。

変更は未登録labとこの設計/indexのみ。既存application、API、Model、migration、DB、UI、worker、配布物を変更していない。次はO2だけ。実企業アクセスや送信対応を開始しない。
