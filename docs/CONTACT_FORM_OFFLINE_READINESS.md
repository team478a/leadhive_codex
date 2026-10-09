# 発見した2フォームの既存ルールによるオフライン確認

2026-10-09。基準 `459284da2b63dc1d4059c9fe592af4a384bbc8d8`。
Branch `codex/contact-form-offline-readiness`。2サイトGET検証結果はPR #13で提出済み（開始時OPEN）。本作業はそのprivate保存HTMLを再利用し、PR #13を自動mergeしない。

## 実施範囲

`dist/g1-two-site/20261009T045050Z/` の2サイトの問い合わせHTMLをSHA-256照合して読み込み、既存関数を直接呼び出した。接続/DNSを禁止したPythonプロセスで、DBを使う `analyze_company_forms` は起動していない。

使用した既存関数:

- `contact_discovery.is_contact_form`: 問い合わせフォームDOMの選択。元のform_indexを保持。
- `form_intelligence.fields.parse_form_fields` / `mapping_review_reason`: 必須項目とDOM/rule mapping。
- `rules.sales_contact_status` / `recommended_option`: 禁止表記とカテゴリ候補。AI providerを呼ばない。
- `compatibility.assess_delivery_compatibility`: 静的送信形式の互換性。
- `analyzer._page_kind` / `_captcha_type` / `_confirmation_page` / `_profile_status` / `_review_reason`: 既存評価条件の再利用。

新しいAIスコア・判定基準・adapterは追加しない。画面表示やDB FormProfileは変更していない。

## 結果

| 指標 | 以前検出済みケース | 以前未検出ケース |
|---|---|---|
| 問い合わせDOM | あり | あり |
| 保存ページで禁止表記のrule一致 | なし | なし |
| 既存rule sales status | ALLOWED | ALLOWED |
| CAPTCHA静的判定 | CAPTCHA_RECAPTCHA | CAPTCHA_NONE |
| 確認画面ボタン | なし | あり |
| 標準送信互換性 | 非対応（Contact Form 7） | 静的判定では対応 |
| 入力項目（hidden/submit等を除く） | 6 | 7 |
| 必須項目 | 4 | 4 |
| 必須mapping未確定 | 0 | 1 |
| 既存profile評価 | REVIEW_REQUIRED | REVIEW_REQUIRED |

READY 0、REVIEW_REQUIRED 2、BLOCKED 0。これは既存関数による解析結果で、Human確認済みラベル・営業許可・DM READYではない。

## ケース1: CAPTCHAと標準経路非対応

一般問い合わせフォームでcompany/contact name/email/phone/subject/messageの6項目を解析できた。必須mapping未確定は0。ただしreCAPTCHAを含む保存HTMLのため、既存安全ルールでHuman操作・確認が必要。Contact Form 7も標準POST経路では未対応と返る。

CAPTCHAを回避するadapterや自動送信は追加しない。Codex支援だけでCAPTCHAを代行できるとは扱わない。判定は動的なCAPTCHAの現在状態を検証したものではなく、保存HTMLの静的マーカーに基づく保守的な結果。

## ケース2: 問い合わせ目的と確認画面

本文・会社名・担当者名・email・phoneの候補mappingあり。必須radio `purpose` はunknownで、Humanが用途を確認する必要がある。選択肢には提案/提携系があるが、このフォームが営業提案を許可しているとは確定しない。選択肢を自動的に選んで送信へ進めない。

必須でない `system_check` もunknown。名前だけから「スパム対策だから空欄で安全」と推測して処理しない。確認画面ボタンは検出したが、POSTして確認画面の実経路を検証していない。静的compatibilityのsupported=trueは完走可能・送信許可を意味しない。

## 重要な意味の違い

既存 `sales_contact_status` は、フォームあり且つ既知の禁止patternが一致しなければALLOWEDを返す。今回のALLOWEDは「保存ページで既知patternに一致しなかった」というrule結果であり、積極的な営業許可の証拠ではない。ruleを変更・緩和していない。

`_page_kind` はURLとページ先頭テキストによりケース1=partnership、ケース2=supportを返した。ナビゲーション文言にも影響される粗いheuristicであり、窓口の正式用途として採用しない。一般問い合わせという見出しとの違いはHuman reviewで解決する必要がある。

Company Identity、公式サイト同一性、対象業種、Core permission、suppression、opt-out、送信履歴、共有Destination、senderはDBを読んでいないため未確認。profile評価だけで営業先として適格・送信可能としない。ポータル窓口と企業窓口の目的も分離する。

## Human確認へ渡す項目

1. 送信対象企業と窓口の同一性・用途、ポータル運営窓口への誤送信がないか。
2. 営業提案が許可されるか。禁止表記未検出と許可確認を分ける。
3. CAPTCHAはHuman Required。CF7/確認画面の動的経路は未検証として残す。
4. 必須カテゴリの適切な選択、unknown項目の意味。個別ページにある選択肢を汎用ルールへ無条件に追加しない。
5. 既存Core safetyとHuman Approvalは実送信前に必須。今回ApprovalRequestを作らない。

## 成果物・安全

匿名集計 `results/contact-form-offline-readiness-20261009.json`。
private `dist/g1-form-review/private.json` / `run.py` はGit除外。実ページURL・項目根拠はprivateに保持し、Gitへ個別企業情報やページHTMLを含めない。runner hashを集計へ記録。

SHA照合、対象2件・2フォーム、profile集計、外部要求/検索/AI/DB read-write/Approval/メール/Form送信0をassert確認した。provider・worker起動なし。Human時間・適合率はnull。アプリコード・API・Migration・依存関係変更なし。

## 判定・次の優先順位

**オフライン確認完了。両件ともREVIEW_REQUIREDを維持。**

次は2件のHumanレビューを既存画面/ledgerへどう渡すか確認し、用途・営業許可・必須mappingの判断をHumanができる状態へ整理する。CAPTCHAや禁止判定を弱める実装・自動レビュー完了・Approval生成は行わない。今回新規外部GETやDM準備/送信へは進まず停止する。
