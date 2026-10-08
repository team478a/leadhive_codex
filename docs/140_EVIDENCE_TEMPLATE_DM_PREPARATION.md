# Phase C1 — 根拠付きテンプレートDM下書き

## ゴール

CURRENTのHuman選択窓口に対して、基本テンプレートとHumanが公式公開ページで観察した事実を組み合わせ、
本文・宛先・根拠URL・引用・確認者・日時・選択版を固定した下書きを保存する。
外部AI、検索、サイト取得、承認、送信、worker、配布更新を実行しない。
既存Human ApprovalやCore Safety Rulesを変更しない。

## 既存機能との関係

`OutreachTemplate`と既存Projectのテンプレート作成APIを再利用する。
既存`OutreachDraft`は承認・送信画面から取得できるため、この工程では新しい準備記録をそこへ書き出さない。
C1の下書きは`LeadDmPreparation`の固定snapshotとして保存する。
送信者・フォーム入力値・承認用payloadへの接続をC2で行い、その際に既存Draft/ApprovalRequestを再利用する。
既存営業文面生成、メール、フォーム、Human step-upの実装は維持する。

## 作成フロー

1. 企業・店舗と公式サイトを照合する。
2. 窓口の用途を確認し、READYの窓口をHumanが選択する。
3. 基本文面を選択または作成する。サービス説明、提案、CTA、署名を基本文面にまとめる。
4. 公式サイト内の公開根拠URL、引用、引用に含まれる事実を入力する。
5. Humanが公開ページで観察したことを確認し、根拠付き下書きを保存する。

事実はHumanの自己申告による観察記録。サーバーがWebを取得・独立検証した事実ではない。
confidenceは`HUMAN_OBSERVED`とし、AI要約を確認済み事実として流用しない。
公開情報を命令として実行・再展開せず、Reactではテキストとして表示する。

## テンプレート

基本文面に1つの`{{personalization}}`を要求し、`{{company_name}}`を任意に許可する。
UIから新規登録すると、会社名・個別化の位置を自動で用意するため、手で差し込み記法を書く必要はない。
個別化は「公開情報で『確認した事実』を拝見しました。」相当の一文。
未知の差し込み、壊れた記法、個別化の件名挿入、本文10,000字超、件名300字超等を拒否する。
入力値は一度だけ置換する。引用内のテンプレートに見える文字列は再展開しない。
80/20は基本文面中心の設計方針であり、厳密な文字数比率やAI利用率ではない。

## 保存とAPI

Migration `37945a503231`（親`1ea563b6ad2d`）は追加のみ。
`LeadDmPreparation`にProject・企業歴史ID・Human確認者、選択ID/版、テンプレートID/hash、
営業条件hash、固定snapshotと期限を保存する。

- GET `/api/companies/{company_id}/dm-preparation`
  - 同Projectのテンプレート（最大100件）、現在のHuman選択、条件hash、最新10件の準備記録。
  - Project viewerも参照可能。
- POST 同URL
  - owner/editor + Human sessionのみ。
  - 期待する選択版、宛先hash、テンプレートhash、営業条件hashを要求。不一致は409。
  - 公式ドメイン内の公開URLだけを許可。認証情報・query・fragment・危険URLを拒否。
  - 事実は10〜500文字、引用10〜2,000文字。事実が引用に含まれることを要求。
  - `fact_observed=true`はHumanの事実観察記録であり送信承認ではない。
  - `confirmed`や任意の期限は拒否。Agent Bearer混在は403。他Project/viewerの作成を拒否。

Projectロック下で窓口READYと選択有効性を再確認して保存する。
DB triggerもHuman membershipと現在の選択ID/版・期限を検証する。
snapshotのUPDATE/DELETE/TRUNCATEを拒否し、企業削除時にも歴史IDを保持する。
Project削除のcascadeは既存互換として維持するため、Project削除後の永久監査保存ではない。
保存後の修正はテンプレートや事実を確認し直して新しい準備記録を作る。
履歴のあるdowngradeは拒否する。

## 状態と有効性

`DRAFT_PREPARED`は、期限内、窓口選択CURRENT・同じ版/hash、同じ営業条件とテンプレートの場合だけ。
他の状態は`REVIEW`。保存snapshot自体は書き換えず、取得時に再評価する。

| 理由 | 要再確認となる条件 |
|---|---|
| PREPARATION_EXPIRED | 選択期限を上限とした準備期限切れ（最長7日） |
| DESTINATION_CHOICE_CHANGED | 選択の取消・更新・失効、Suppression、UNKNOWN、共有窓口等 |
| DESTINATION_CHANGED | 宛先hash不一致 |
| SALES_CONTEXT_CHANGED | SalesObjective、地域、TargetProfile条件の変更 |
| TEMPLATE_CHANGED | テンプレート内容変更・削除 |

取得時のキャッシュ診断であり、その後のdispatch時の再検証を代替しない。
窓口条件が戻った場合も、現在の準備診断を返すだけで外部送信権限を生成しない。

## DM READYの境界

C1はDRAFT PREPAREDで止める。`dm_ready=false`, `execution_allowed=false`。
FunnelのDM READY件数・率は未判定のまま維持する。準備記録数をDM READYへ加算しない。
C2で少なくとも以下をそろえ、DM READYを定義・計測する。

- 有効な選択窓口と同一性・用途・安全診断
- 固定された宛先、文面、根拠
- 検証した送信者情報
- フォームなら必要入力値・fingerprint・技術対応条件
- Humanが最終承認画面へ渡せるimmutable payload

Human ApprovalはDM READYの次段階。C2でも承認の自動代替や実送信を行わない。

## 検証

専用`_test`DBと架空exampleドメインで、本文・根拠の保存、変更による再確認、
URL/入力/版検証、viewer/他Project/Agent境界、snapshot改変禁止、送信副作用なしを確認する。
PC/mobile E2Eでテンプレート登録、Human観察確認、保存・再読込・宛先変更による再確認を検証する。
稼働DB、worker、配布フォルダには反映しない。

## ローカル検証結果（2026-10-06）

- 関連Backend 71 passed（本工程10件、既存窓口・照合・用途・集計61件）。
- PC/mobile E2E 6 passed（新下書き、既存窓口選択、照合・用途確認）。
- Ruff、変更Service/APIのmypy、Frontend typecheck/lint/build成功。
- 検証API起動、外部通信・承認/送信requestなし。
- 空の専用DBで親revisionまでdowngrade→head upgrade→Alembic check成功。
- 既存500kB chunk警告は継続し、隠さない。将来の画面単位分割課題。

## 次のゴール

C2：送信者・フォーム入力値・根拠付き下書きを固定し、既存Human Approvalに渡す準備とDM READY診断を完成させる。
実送信は別の工程とする。
