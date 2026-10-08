# SNS運用代行会社30社・実運用E2E Pilot

## 現在の判定

2026-10-07 JST、**準備停止 / NO-GO（実送信）**。ユーザー指示書第12項の「詳細商品情報・訴求内容は現在の営業Purpose / Template / Human入力を使用し、不足している場合は創作せず停止」に従う。

現在の画面接続先の保存データには、姫路市美容院のRaw Benchmark Project1件だけがある。sales_objectiveは「Raw Collection測定専用。営業・補完は実行しない。」、OutreachTemplate0件、Company0件、OutreachDraft0件。SNS事業者向けの標準TargetProfileは存在するが、売る商品の仕様・OEM条件・価格・CTAは確認できない。TargetProfileは顧客像であり商品仕様の代わりにしない。

利用者へ商品名・主要機能・OEM/代理店の提供範囲・価格（未定なら未定）・DMの次の行動を質問した。別Projectに設定済みなら、そのProject名を確認する。入力待ちの間に商品・価格・効果・サービス提供条件を創作しない。

## 1. 基準と環境

- Branch: `codex/integration`
- 基準commit: `0736356470b207ffc286b552994878b34573b7b6`
- 製品コード検証: [CI 37596532321](https://github.com/team478a/leadhive_codex/actions/runs/37596532321)、検証HEAD `b1066096dbcef46a20dbe0264cc13300cb8c57ff`、全7 job成功。Backend 1,296 passed / 45 skipped / 50 subtests、E2E 78 passed / 2 skipped。
- 開始時の基準commit自体の文書追記CI 37597735728は実行中。今回新たな製品コード・テスト・Model・Migrationを変更していない。
- 確認範囲: `http://localhost:18985/` の既存ローカル実行環境、`leadhive_raw_pilot_20261007`。DB照会はread-only transaction。別PC・別実行環境の設定が同じとは断定しない。
- outbound OFF維持。送信用worker起動、外部サービス設定変更、Production deploymentなし。

## 2. 検索条件（未実行）

日本国内、法人、公式サイトが確認可能、企業向けSNS運用代行・SNSマーケティング支援・SNSコンサルティングを提供。候補最大30社。WANTは問い合わせ先、各SNS運用対応、広告・コンサルティング・投稿制作・料金・OEM/代理店/パートナー情報。WANT不足は除外理由にしない。

個人、フリーランス、閉業、公式サイト停止、自社集客としてSNSを使うだけの会社、重複、営業禁止・連絡禁止・Suppressionは除外。検索語はユーザー指定のSNS運用代行会社、SNSマーケティング会社、Instagram運用代行、TikTok運用代行、SNSコンサルティング会社を候補とするが、検索語一致だけで正解にしない。既存の地域・業種条件の自動判定を緩めない。

商品情報不足で停止したため、検索・追加GET・外部AI・Collection job・Completionを開始していない。過去の美容院Raw40観測を今回の30社候補へ流用していない。

## 3〜9. 候補・Human Truth・精度・窓口・DM READY

| 指標 | 今回の測定値 | 状態 |
|---|---:|---|
| SNS企業候補収集数 | 0 | 収集未開始 |
| Human確認済み | 0 | Human Truth未作成 |
| 正解企業数 | null | 未測定 |
| 誤判定数・理由 | null | 未測定 |
| 重複数・率 | null | 未測定 |
| Precision | null | Human確認分母なし |
| 公式サイト発見率 | null | 未測定 |
| メール可能 / フォーム可能 / 両方可能 | null | 未測定 |
| 問い合わせ先なし / REVIEW・HOLD | null | 未測定 |
| 問い合わせ可能率 / REVIEW_REQUIRED率 | null | 未測定 |
| DM READY | 0 | 今回の準備対象なし |
| DM READY率 / Human修正率 | null | 未測定 |
| DM準備対象・未準備件数 | null | 対象未確定 |

PRIMARY / SERVICE / MENTION_ONLYはHuman確認待ち。全候補を人が確認し、企業・法人・公式サイト・SNSサービス・窓口・重複・営業禁止の根拠を確認するまでHuman Truthや送信対象として確定しない。AI調査案とHuman確定結果は区別する。

## 10〜11. 訴求A/B・送信予定

- A: 自社の商品ラインナップに追加できる、という方向。
- B: 予算が合わず失注する顧客へ別の選択肢を提案できる、という方向。

この二つは指示書の訴求方向のみ。本文・価格・効果・OEM契約条件は未作成。A/B対象数はnull。企業固有情報はHuman確認済みEvidenceだけをDMへ使う。

送信予定メール件数・フォーム件数はnull（未確定）。公開された法人向けメール優先、次にフォーム。Sendability / Suppression / Form Readiness / immutable payload / Human Approval等の既存guardを維持する。技術未対応フォームはREVIEW/HOLD、CAPTCHAはHuman Requiredとし、回避しない。

## 12〜14. 初回10社・送信結果

実送信0件。Email0 / Form0 / 新規Approval0。今回の送信試行がないため、ACCEPTED / DELIVERED / UNKNOWN / FAILED・フォーム受付の率はすべてnull。SMTPテスト・Codexフォーム送信も未実行。

商品情報とHuman Truthを補い、DM READY・文面・対象・チャネルの送信前報告を完了した時点で停止する。Humanの明示GOと対象payloadのHuman Approvalの両方が必要。最初は最大10社、例A5/B5。10社後に再停止し、UNKNOWNを自動再送しない。残りへの自動継続はしない。

## 15〜17. 問題と優先順位

| 優先 | 分類 | 問題 / 根拠 | 次に必要なこと |
|---|---|---|---|
| 1 | DM_PREPARATION | 今回の商品Purpose・Template・仕様を確認できない | Humanの商品入力、または設定済みProjectの特定 |
| 2 | INDUSTRY_CLASSIFICATION / HUMAN_APPROVAL | 今回候補のHuman確認は未実施 | 最大30候補の収集後、全候補のHuman TruthとPRIMARY/SERVICE分類 |
| 3 | CONTACT_DISCOVERY / FORM_ANALYSIS | 今回対象の窓口と技術可否は未測定 | 保存情報優先、公式Evidenceと既存解析の確認 |

上記は未実施・入力不足であり、検索APIや送信APIの実行失敗とは扱わない。商品情報がないことを理由に新機能追加や大規模改修を開始しない。SNS投稿分析、Business Event、Lead Score、媒体専用Crawler、CRM拡張は対象外。

## 18〜19. 再開条件・GO判定

**現在の次の1工程: 営業商品情報をHuman入力で確定する、または設定済みProjectを特定する。**

その後に既存収集機能で最大30候補を収集し、Human確認対象リストと調査案を準備する。全候補Human確認前に実送信せず、未確認を正解・READYに繰り上げない。商品入力だけでは送信GO・Human Approvalとは扱わない。

現在は実送信NO-GO。初回10社・残り20社への継続可否は未判定。今回の実運用E2Eは未完了で、read-only事前確認とこの停止報告まで実施した。
