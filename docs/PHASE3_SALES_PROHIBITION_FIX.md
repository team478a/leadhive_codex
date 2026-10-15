# Phase 3：明示的な営業問い合わせ拒否の検出修正

## 問題と変更

2026-10-09。main基準 `e15b1a773e2b61295f5b1c72ec09c41e7cba9b37`。実装commit `9fdf9cd0abf2447f8b4ce8358d27078d8ef1815a`。

Humanが営業対象適合とした4候補の保存済み窓口本文を監査したところ、2窓口に明示的な営業拒否があるにもかかわらず既存ruleがALLOWEDを返した。適合する会社であることは、その特定窓口への営業許可を意味しない。

`backend/app/services/form_intelligence/rules.py` の共通パターンへ以下を追加した。

- 「営業・勧誘を目的としたお問い合わせはご遠慮ください」等の目的句。
- 「営業のメールはこちらでは承ることはできません」等の受付拒否。
- 空白、HTML要素分割、窓口指定、関連する拒否表現を扱う。
- 目的句パターンは文末区切りを跨がず、後続拒否までの長さを制限する。会社名・業種・domainのハードコードはしない。

既存 `PROHIBITED_PATTERNS` をForm Intelligence、フォーム解析、target refresh、live checkが共有しているため、API・認証・承認・送信処理は追加・変更していない。Human承認、suppression、CAPTCHA、UNKNOWN等の既存guardを維持する。`recommended_option` に静的型注釈のみを追加し、既存tuple長差によるmypyエラーを解消した。選択ロジックは変更しない。

## 同一保存データによる比較

| 指標 | 修正前 | 修正後 |
|---|---:|---:|
| 対象候補 | 4 | 4 |
| rule ALLOWED | 4 | 2 |
| rule PROHIBITED | 0 | 2 |
| Sendability READY / DM READY | 0 / 0 | 0 / 0 |

既存の同じ保存済み `text_excerpt` を、固定mainのruleと修正後ruleで再判定した。元ファイルhashを前後照合し、上書きしていない。詳細・実ページURL・引用はGit管理外のprivate監査へ保持した。

- 匿名比較：`docs/results/phase3-sales-prohibition-before-after-20261009.json`
- 発見時の監査：`PHASE3_QUALIFIED_CONTACT_REVIEW.md`
- 発見時の匿名集計：`docs/results/phase3-qualified-contact-review-20261009.json`

残るALLOWED 2窓口も送信可能・窓口用途確認済みとは扱わない。確認画面・必須予算・送信者情報がある窓口と、顧客向け無料相談の窓口であり追加確認が必要。この選択4件を全候補の禁止検出率や業種適合率に一般化しない。

## テストと品質確認

最初にテストを追加し、修正前は11失敗・20成功を確認。修正後は同じ31ケースがすべて成功。

- 明示的な営業拒否をform有無にかかわらずPROHIBITEDにする。
- 送信前 `_parse_form` が拒否する。外部送信は実行しない。
- HTMLタグで拒否文が分割されていても検出する。
- 協業・OEM受付、営業専用窓口の案内、関係のない採用問い合わせ制限を誤って禁止扱いしない。
- live check APIのmock HTMLでも検出し、Approval・Delivery・Jobを作らない。既存fingerprint/fieldを維持し、実行許可を出さない。

ローカルの関連6テストファイルで **130 passed**。Form Intelligence、フォーム送信、readiness、保存観測安全判定、live check、permission ruleを含む。専用 `_test` DBを使用し、既存Alembic upgrade/checkをconftestで確認。本番DBは使用していない。

Backend Ruff全体成功、format全体461ファイル成功、変更ruleのmypy成功、APIアプリimport成功。Frontend・DB schema・migration変更なし。全体Backend、Frontend、E2E、migration、Windows配布検証はPRのCIで確認する。

## 安全・互換性・制限

外部GET0、有料検索0、AI0、本番DB書込0、Approval0、Email0、Form POST0。稼働workerや本番設定は変更しない。deploy・merge・営業実行はしない。

保存済みFormProfileを一括更新する処理やmigrationは追加しない。修正前の保存レコードが自動的にPROHIBITEDへ更新されるとは保証しない。承認済みpayloadを変更しない。今回の私的評価対象は別途Evidence overlayで当該窓口をBLOCKEDとして保持し、送信へ進めない。既存送信前の取得・解析経路では新パターンが使われるが、すべての外部Agent/特殊フォーム実行経路を今回の比較で網羅したとは主張しない。

正規表現は対象文型の改善であり、あらゆる自然言語・否定の否定・例外条件の解釈を完成させるものではない。複数窓口があるページの窓口限定制限は保守的に停止し、別の営業専用Destinationの確認で解決する。CAPTCHA突破や禁止解除はしない。

## 次の工程とrollback

PRの全CIを確認してレビューへ提出し停止する。自動マージしない。Humanがマージした後でも、残る2窓口の用途・現在の構造・suppression・送信者確認を経ずDM READYへ進めない。

DB変更がないためrollbackは実装commitのrevertで可能。ただし営業禁止の見落としが復活するため、revert時も禁止判明窓口の停止を維持する。データ破壊や既存migrationの書換えは不要。
