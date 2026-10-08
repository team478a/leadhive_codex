# Phase B2 — Humanの用途確認証跡と窓口READY

## 完了対象

窓口候補を整理し、Human owner/editorが公式サイトの公開ページを確認した用途・対象範囲・根拠URL・説明を保存する。
保存済み情報を基に、既存の技術・連絡可否条件と現在有効な用途証跡を満たした窓口だけSendability READYへ進める。
READYは **窓口の準備候補**。DM文面完成、送信承認、配送可能性の実サイト疎通、送信成功を意味しない。
`dm_ready=false`、`execution_allowed=false`、`live_destination_checked=false`を維持。Recommended Destination、Funnel確定反映、Phase C/D、外部Agent接続は開始しない。

## データとMigration

additive migration `e49867e60dcd`、親 `06a2f819c310`。
新Model `DestinationReviewEvent`。既存Migration、ApprovalRequest、HumanApprovalProof、配送Modelは変更しない。

- Project、元Company/ContactDestinationのID、Human User ID、単調増加versionを保存。
- CONFIRMED / REVOKEDは用途確認の追加イベントであり、ApprovalRequest APPROVEDではない。
- purpose、scope、公開根拠URL、説明（10〜1000文字）、snapshot_hash、canonicalization_version、作成・失効日時。
- 7日がserver上限。任意expires_at、confirmed、actor ID等の追加入力を拒否。
- DB triggerでProject所属・現在のHuman owner/editor・有効な窓口link・version連続性を確認。
- UPDATE / DELETE / TRUNCATEは拒否。確認取消は新しいREVOKEDイベントを追加。
- Companyの削除・統合や窓口整理で古い履歴を新しい対象へ移植しない。元IDで残るため、新しいCompanyでは使えない。
- 既存のProject全体削除のcascadeだけは維持する。Project内の個別履歴削除APIは設けない。Project削除後までの監査保持は別のretention設計課題。
- 証跡があるdowngradeは拒否。ロールバックはコードを戻しadditive tableを維持する。データを消してdowngradeしない。

## Snapshotと失効

`destination-review-v1`のcanonical JSONをSHA-256でhash。全文Snapshotや資格情報は証跡テーブルへ複製しない。
対象はProject/Company ID、企業・店舗Identity、登録先/品質/保護情報、連絡禁止、ContactDestinationのID/値/属性、link、公式サイト証跡、ContactPerson、FormProfile、フォーム項目。
フォーム項目は更新時刻だけに依存せず、selector、type、必須性、マッピング、confidence、選択肢・選択値等の実データも含める。

| 表示状態 | 条件 |
| --- | --- |
| UNREVIEWED | 記録なし |
| CURRENT | 最新CONFIRMED、7日以内、現在のsnapshotと一致 |
| STALE | 対象・窓口・解析等またはcanonicalization versionが変化 |
| EXPIRED | 現在時刻が失効時刻以上 |
| REVOKED | 最新イベントが取消 |

期限やstaleは毎回読み取り時に判定し、旧イベントのUPDATEはしない。
フォーム再解析や窓口変更後に同じ本文を黙って再利用しない。UIはsnapshotが変わると入力欄をリセットし、新たな確認操作を求める。
並行・再送リクエストはexpected hashとexpected_review_versionで409。Project行lockとDB unique/triggerでもversionを直列化。
このlockは配送予約やdispatch承認ではない。

## Human API

| API | 条件 |
| --- | --- |
| GET `/api/companies/{id}/sendability` | Project閲覧者。証跡の状態/version/確認者ID/根拠、現在のhash、can_reviewを返す |
| POST `/api/companies/{id}/destinations/{id}/reviews` | Human owner/editor。用途・scope・根拠、expected hash/versionが必要 |
| POST `/api/companies/{id}/destinations/{id}/reviews/revoke` | Human owner/editor。現在のexpected review versionが必要 |

Agent credentialをHumanへ変換しない。Agent/Human Cookie混在は既存guardで拒否。Viewerと他Projectの書込も拒否。
根拠URLは公式サイトと同じ正規化domainの公開URLのみ。credential付き、private literal、localhost、別domain、query/fragmentは拒否。
動的URLのqueryや外部予約サイトを根拠URLにする機能はこの工程では追加しない。登録先URL自体は既存方式を維持する。
根拠入力はHumanの陳述であり、記載内容の正しさをAIやアプリが実サイト取得で検証したという意味ではない。
資格情報・SMTP/API keyは読み取らず、入力欄にも秘密情報を入れないよう明示。根拠文はReactのtextとして表示し、HTMLや命令として実行しない。

## READY条件と残る安全制御

現行Identity/公式サイトCONFIRMED証跡、候補の登録、現在のHuman用途確認、record_typeに合うscope、適切な用途、メールのverified品質または通常フォームの技術条件が必要。
support/recruitment/reservationはHOLD、unknown用途/scopeや企業・店舗不一致はREVIEW。groupはREADYにしない。
用途確認がCURRENTでも、Suppression/opt-out相当の既存禁止、do_not_contact、営業禁止、UNKNOWN、過去送信・処理中、共有窓口、CAPTCHA、主フォームURL不一致、古い解析、必須項目不足等を解除しない。
既存Core permissionのALLOWEDも必要。AI scoreやHumanの用途入力でHard Blockを上書きしない。
同一窓口が後から別店舗に登録された場合は、解析hashが同じでも毎回のCore guardでREADYから外れる。
解析の7日期限はB1の保守的なcache条件を維持し、送信時のlive fingerprint再確認は将来の配送工程に残す。

## 画面

企業一覧 → 詳細 → リスト完成の根拠 → 窓口の利用可否と理由 → 窓口を開く。
候補未整理の場合は先に「プロジェクトの窓口候補を整理」を実行。
用途・企業/店舗/group・公式根拠URL・公開ページの説明を入力して「用途確認を記録」。
確認者ID・作成日時・7日の期限・記録version・根拠を表示。「用途確認を取り消す」は追加イベントで処理。
Viewerは参照のみ。Humanの送信承認/送信ボタンは追加しない。
別候補の問題が全体の理由一覧にも含まれるため、全体状態と窓口別状態を併記する。

## 検証と運用範囲

Backend関連テスト40件が成功。合成データでCURRENT→READY、再送/版競合、Identity/フォーム/項目変更、stale、失効、取消、用途/scope不適合、共有窓口、禁止、Agent/Viewer/他Project、DB append-onlyと所属、Company削除後の保持、Project削除互換、非空downgrade拒否を確認する。
既存B1とA1の関連回帰、mypy/Ruff、Frontend typecheck/lint/build、desktop/mobileで用途保存・取消と承認/送信なし、API起動、専用DBでupgrade/downgrade/upgrade/model差分を検証する。
desktop/mobile E2Eは2件成功（32.1秒）。mypy、Ruff、Frontend typecheck/lint/buildも成功。
全回帰、Migration検証、Windows package等は最終コミットのGitHub CIで確認する。
稼働中100店舗のDB・コンテナ・停止worker、配布packageへは反映しない。実企業GET、検索/AI API、SMTP、Form POST、Codex task、実送信は実行しない。

## 次のゴール B3

窓口候補の選択・Recommended Destinationと固定cohort Funnelへの確定反映。
既存100店舗には構造化したIdentity/公式サイト確認証跡が不足しているため、その確認経路も先に整える。用途確認だけで既存リストをREADYにしない。
適切な用途・根拠・過去履歴・共有窓口を評価し、単純なメール優先にしない。独立窓口の数とLead数を区別する。
Source利用条件審査はA3の独立工程として維持。DM READYは文面とEvidenceのPhase C、Human Approval/配送結果との結合はDを経て確定する。
