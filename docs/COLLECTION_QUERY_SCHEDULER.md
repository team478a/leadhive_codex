# 工程2: 公平な検索配分と永続的な予算予約

基準: `codex/raw-offline-comparison-20261009@de20699461e46ad362ac0bdd25ea52c4779d031b`（PR #7マージ後）。2026-10-09。

## 変更範囲

既存の件数目標付きSerper収集に `fair-v1` を追加する。CRM、送信、Human承認、公式サイト判定、記事からの企業抽出は変更しない。Google Places/gBizINFO、通常件数指定の収集、定期収集、Raw Benchmarkの独立実行経路は従来のまま。

`COLLECTION_FAIR_SCHEDULER_ENABLED=false` が既定。APIによる新規の `collect_search` / Serper / target_count付きジョブを作る時だけ、ONならサーバーが計画を固定する。利用者やAgentが任意のplan/rootを送るAPIはない。OFF後も既に固定したジョブとその再開は同じ版を使う。旧ジョブはON後も従来runnerのまま。停止は既存のキャンセル操作を使う。

計画snapshotは検索語（同一語の重複は除く）、地域、目標、条件binding、追加調査plan、版と上限を含む。hashを検証してから実行する。現段階は既存の1地域文字列×最大20検索語であり、全国の地域分割・類義語自動生成は工程5。

## 予算と停止

- 1応答の取込範囲10件、Discovery attemptの全体上限50、目標最大500を維持。
- 各検索語の1ページ目、次に2ページ目へ配分。再試行待ちの検索語を待たず、実行可能な別検索語へ進む。
- 成功応答で独立した新規Company候補が増えない状態が2回連続した時、その検索語を停止。REVIEW_REQUIRED/NO_MATCHの新規候補も増分。条件MATCHの増分と混同しない。
- 各検索語最大5ページ。停止・ページ上限は完全な地域CoverageやRecallの証明ではない。
- 記事/SNS/求人等のRaw観測は工程1の台帳に残るが、未実装の記事抽出を新規Company増分として数えない。
- 429、5xx、接続/timeoutのみ最大2回追加retry（初回を含め各page最大3attempt）。通常4xx/認証/応答形式エラーはretryしない。各retryも50枠を予約する。
- Retry-Afterと指数backoff（2、4秒）を守り、取消/heartbeatを確認。Retry-Afterが60秒超なら早めに再送せずSOURCE_ERRORで停止する。再開しても同一pageの試行数はリセットしない。恒久エラー/試行上限の検索語は終端となり、設定を修正した新ジョブが必要。
- 既存の任意ExternalPresence追加調査は独立した既存予算を使用し、Discoveryの50回とは別。Discovery50回を全外部API呼出数と表記しない。金額不明は0円としない。

## 永続性と復旧

新Model: `CollectionQueryTask`（未検索語を含むcursor/停滞/状態）と `CollectionSearchAttempt`（予約順、page、worker、CollectionJob、成否/不明、新規候補増分）。Migration: `2f178bf991d0`、親 `18dc401aa791`。

最初のOperationJobをrootとして、再実行で作ったOperationJobも同じqueueと予算を使う。root rowをロックして予約順を決め、unique制約で競合を防ぐ。実行OperationJobのworker/lease/cancelを確認し、HTTPの前に予約をcommitする。予約に紐づくCollectionJobを介して工程1Raw台帳・Usage・Source Observationと接続する。

Raw/Usageは先行保存。Company取込・観測・attempt成功・cursor更新は同一transactionでcommit。旧workerは現在のworker/leaseを再確認しなければ取込できない。予約後のクラッシュやキャンセルは、再開時にUNKNOWNとし、消費予算を戻さない。同じpageを調べ直す場合にも新予約が必要。終端attemptの変更と予約内容の変更はDB triggerで拒否する。

HTTPとDBのexactly-onceを保証しない。応答とRaw保存の間のクラッシュでは応答を失い得る。Raw保存後、取込前の中断ではCAPTUREDが残り、新しい予約での検索が必要になる場合がある。不明な検索料金を確定した料金として示さない。これは**検索**の復旧規則であり、UNKNOWN外部送信の自動retry禁止は変更していない。

追加調査はCompany取込後の既存経路。そこで中断した場合、Discoveryの取込済みpageは再取込しないが、追加調査の完全な再実行保証を新設していない。

## 画面と権限

既存CollectionProgressに予定/未検索/継続候補/エラー/ページ上限/結果不明を追加。予算終了で検索が残る場合はPARTIALと明示する。SEARCHES_STOPPEDも全企業収集完了を意味しない。既存Operation一覧APIで読めるため新APIは追加していない。

Humanのowner/editorによる新規開始・取消・再開、viewerの閲覧、他projectの404、Agent/BearerとCookie混在拒否を維持。query/attemptのproject/plan整合性と不変の予約をDBでも検証する。

## 検証と導入

外部API・実サイト・AI・承認・外部送信の実行なし。保存済みfixture/合成候補による実runner/workerのDBテストと純粋policyのオフラインreplayを実施。重複gapのfixtureでは旧1回停止で1候補、新方式では2候補。20語fixtureは全1ページ目へ配分し50attemptで停止。これは制御の検証であり実データの適合率・公式サイト率・問い合わせ発見率の改善証明ではない。

ローカルの検証結果とCIリンクはPRに記載する。DBにtaskが残るdowngradeは拒否し、破壊して戻さない。空の専用test DBではupgrade→downgrade→upgradeとAlembic差分検証を行う。ロールバックは新計画の発行をOFFにし、実行中ジョブをキャンセルして前コードへ戻す運用を基本とする（進行中のfair-v1を旧runnerへ切り替えない）。

次工程は情報抽出/公式照合/問い合わせ探索（工程3）。本PRのマージ・実検索Pilot・全国拡大・予算増加・本番反映は実行しない。
