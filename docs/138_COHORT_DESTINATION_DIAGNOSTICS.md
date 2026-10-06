# Phase B3b — Fixed Cohort Destination Diagnostics

## ゴール

固定営業リストについて、窓口準備のREADY/REVIEW/HOLD/BLOCKED、重複を除いた窓口候補、READYの独立窓口、不足理由と次の作業を表示。
窓口準備READYと、文面・Evidenceが揃ったDM READYを分ける。後者は未判定。
新たな許可判断を作らず、企業詳細の既存Sendability `sendability-b3-v1`を再利用する。

## API / Service

GET `/api/completion-cohorts/{id}/destination-diagnostics`

- Human Project閲覧者のみ。Viewerも参照可。Agent/Human混在は既存guardで拒否。
- offset 0〜3000、limit既定25/上限50。固定cohortのCompany ID順で取得。範囲外は422。
- expected_context_hashを次ページへ渡す。Project/TargetProfile営業条件が変化した場合は409で再集計。
- response: cohort/hash/context/診断定義、固定分母、offset/inspected/next_offset、開始・取得日時、各Leadの状態/理由と次の作業、候補窓口のhash key/状態/共有判定。
- URI/メールそのものは集計用レスポンスへ重複出力しない。既存正規化値＋channelのSHA-256 keyで窓口を区別する。hashは秘密情報の暗号化ではない。
- Company削除・統合・別Projectへの移動はHOLD/LEAD_REMOVED_OR_MERGEDとして数える。後から追加したCompanyは固定分母に含めない。
- DB書込み、外部GET、AI/検索API、送信/承認/dispatchは実行しない。新Model/Migrationなし。

## 大量リストと観測範囲

既存cohort上限3000件を維持。1 requestで3000件のSendabilityを同期実行しない。
UIは25件ずつ順次取得し、診断済み件数を表示。全件を受信するまで部分集計。
処理中断、ページ取得失敗、営業条件/定義/分母/ページ順序/IDの異常は完了扱いにしない。
中断済みページは部分集計として残し、再集計は最初から行う。画面離脱・集計対象切替・再読込後の古いresponseは破棄。
ページ間の照合/解析/禁止/履歴等の更新をロックしない。これは観測期間の診断であり、一時点に固定した承認payload snapshotではない。
集計開始〜最終ページ日時を表示し、情報更新時は再集計する。送信前のlive再確認・Human Approvalを代替しない。
期間中の全データ変化を検出するsnapshot tokenや永続した集計ジョブは今回追加しない。

## 数え方

- Lead状態: 各固定IDを一度だけ数える。削除済みもHOLDで分母を維持。
- 独立窓口候補数: channel＋正規化destination keyのdistinct。既存ダッシュボードの候補数とは違い、診断進捗に応じた値。
- 共通窓口: 診断範囲で複数Leadに結び付くkey、または既存Sendabilityの共有判定あり。複数店舗を削除/統合しない。
- READYの独立窓口: 診断範囲内で1 Leadにのみ結び付き、共有判定のないREADY候補。未診断/範囲外の窓口を推定しない。
- 共通keyが後続ページで見つかった場合、独立READY数は減ることがある。部分集計を最終値と見せない。
- 不足/停止理由: READY以外のLeadをreason codeごとに一度だけ数える。複数理由の合計はLead数と一致しない。別候補の理由も含むため詳細で確認する。
- sales prohibition/suppression/UNKNOWN/CAPTCHA/共有/過去送信/品質/Identity/用途等の既存制御を維持。

## UI

ダッシュボード → リスト完成率 → Project/固定集計対象 →「窓口診断を集計」。
部分/全件、READY/REVIEW/HOLD/BLOCKED、distinct候補、共通窓口、READYの独立窓口、不足理由/次の作業を表示。
「窓口集計を中断」、再集計、計測再読込が可能。承認/送信ボタンなし。
旧A2の常にREVIEWとなる簡易分類は表示をやめ、企業詳細と同じ診断で表示する。旧report APIのdiagnosticsは互換性のため維持し、Funnel変換率へ直接流用しない。
DM READY率、Cost per DM READY、文面Evidence/承認/送信と結合していない段階は未判定を維持。

## 検証

合成データで、ページ境界の共通key/単独READY、単件診断との一致、欠損IDと固定分母、上限、条件変更409、Viewer/他Project/Agent、承認/配送レコード不変を検証。
PC/mobileで26件の2ページ集計、中断→部分保持→最初から再集計、共通keyの重複除外、理由件数、DM READY未判定、既存レビュー時間操作を確認。
Backend関連回帰、mypy/Ruff、Frontend typecheck/lint/build、Migration差分、API起動、最終HEADのCIを確認。
ローカル結果：Backend関連49件成功、mypy 2ファイル成功、Ruff成功、Frontend typecheck/lint/build成功、desktop/mobile E2E 2件成功（1.1分）。
稼働DB/コンテナ/停止worker、配布packageは変更しない。実送信、外部API、実企業アクセスは行わない。

## 次のゴール

同条件窓口のHuman確定選択を、対象/用途/解析のhash/versionへbindした準備証跡として追加。
その後Phase Cのテンプレート＋確認済み個別情報＋Evidenceへ接続し、初めてDM READYを確定する。
Human送信承認・既存配送へ接続するPhase Dは別工程。今回自動送信や配送予約を追加しない。
