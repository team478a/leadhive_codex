# Purpose Based List Engine 完成検証前の確認結果

## 結論
2026-10-07、添付「LeadHive Purpose-Based List Engine 完成・実データ検証 次工程実装指示書」に基づき開始条件・既存実装・外部Sourceを確認した。Stage 0は完了。指示書19の「媒体利用条件が不明」「求人現在性を安全に判断できない」に該当し、新規実装・実データPilotには進まず停止した。
**判定: NO-GO（指定ユースケースの完成・本番利用）。既存機能の停止や削除を意味しない。**
完成確認用の検索は現状では一連で成立しない。未検証をMATCHへ繰り上げない。これは実装完了報告ではなく、停止理由と再開条件を記録する報告書である。

## 基準とCI
- branch: codex/integration
- 添付文書の監査基準: fbb499132c7c90cb80f1871b07cbfe93c4278083
- 今回確認した最新基準: e004b378ee4fd16eb54c88310a8c0f2812323964。originと一致。
- 今回の製品実装commit: なし。コード・API・DB・Migration変更なし。報告書のみ追加。
- [最新基準のCI run 37583920639](https://github.com/team478a/leadhive_codex/actions/runs/37583920639): 全7項目PASS。
- Backend tests、Backend lint（Ruff/format/mypy）、Frontend、Migration、PC/mobile E2E、Windows package、Form HTTP acceptanceが成功。既存テストの削除・新しいskipでGREENにしたものではない。
- 添付の「npm ciで失敗」という表現はジョブstep名。実際の前回失敗は既存completion-metrics mobile E2EのランダムUUID順に起因し、専用fixtureの順序固定で修正済み。依存関係やlockfileを根拠なく変更していない。詳細: [157](157_CONDITION_REVIEW_NAVIGATION.md)。

## 現在の実装と不足

| Stage | 現状 | 根拠・残課題 |
|---|---|---|
| 0 CI | 完了 | 最新基準の全7項目成功 |
| 1 自然文Proposal | PARTIAL | services/condition_proposal.pyは外部AIなしのbounded-templates-v1。AREA/INDUSTRY・存在・優先度を扱う。指定文全体、requestedCount抽出、現在募集中、複雑な日本語は未対応。UNRESOLVEDを残す |
| 2 地域Evidence | PARTIAL | services/region_condition.py、collection_fact_reviews.py。確認済みの公式住所と登録住所、Human証拠を照合。単なる検索語でMATCHにしない。媒体の住所を信頼Sourceとして新規取込する工程は未検証 |
| 3 業種Evidence | PARTIAL | industry_review_hints.pyは新鮮な確認済み公式本文の最大3抜粋を提示。HumanレビューのURL・excerpt・hash・versionを保存。類義語自動照合、title/description独立証拠、automatic業種確認は未実装 |
| 4 ACTIVE_JOB | NOT IMPLEMENTED | CollectionCondition schemaには存在するが、collection_conditions.evaluateでは専用分岐がなくUNKNOWN / VERIFICATION_UNSUPPORTED。FactReviewのDB制約・APIはAREA/INDUSTRYのみ。求人媒体FOUNDで代用しない |
| 5 HotPepper店舗同定 | PARTIAL | external_presence.pyのmatches_companyは名称＋電話または住所を要求。未関連EvidenceはREVIEW_REQUIRED、Human関連付けAPIも存在。専用店舗情報抽出・CONFIRMED/LIKELY等の評価・実データ同定精度は未実装/未測定 |
| 6 選択的補完 | PARTIAL | condition_collection.pyの固定条件binding・MUST/EXCLUDE媒体優先、extra_searchesのeligible判定・予算/期限・予約・AUTO停止を再利用可能。求人現在性を含む要求された全段階のpipelineは未完成 |
| 7 結果画面 | PARTIAL | CollectionConditions.tsxとConditionCollectionReport.tsxに条件別結果・理由・Evidenceリンク・Human確認・確認待ち絞り込み。全Projectの完全一致一覧、緩和時件数プレビュー、条件別判定方式の統一表示は未完成。現在の件数は表示ページ内 |
| 8 実データPilot | 未実行 | 今回のPilot 1/2/3はいずれも開始せず。既存Raw Pilotを新ユースケースの成果として流用しない |

## Condition ModelとEvidence
CollectionConditionRequestにHuman確定snapshot/hash/versionを持ち、OperationJobへのbindingを実行時に照合する。MUSTはAND、WANT不一致は採用を妨げず、EXCLUDE一致はNO_MATCH。MUST/EXCLUDEのUNKNOWNはREVIEW_REQUIRED。期限切れ・撤回・企業情報変更を反映する。
CollectionFactReviewはHumanのみ、append-only、現在のcompany_hashとexpected_versionを要求し、24時間で失効する。AREA/INDUSTRYのMATCH/NO_MATCH/UNKNOWNを保持。旧版や未確認を自動的に再採用しない。
ExternalPresence / ExternalPresenceEvidence / ExternalPresenceSearchはFOUND / NOT_FOUND / NOT_CHECKED / ERROR、PASSIVE / EXPLICIT_SEARCH / REQUIRED_VERIFICATION、URL・確認日時・関連確認を保持。検索結果の求人URLは掲載存在の観測であり、現在の募集事実ではない。

## Source利用条件の確認と停止理由
確認日: 2026-10-07。これは法的適合性の保証ではなく、自動取得を開始するための運用ゲートの確認である。

### HotPepper Beauty
[公式robots.txt](https://beauty.hotpepper.jp/robots.txt)は取得でき、一部検索・予約・会員系パスのDisallowと特定botのCrawl-delayがある。robotsだけでは営業リスト目的の取得、保存、再表示、第三者提供の許可を証明できない。
公式トップの利用規約表示は確認したが、想定した規約URL `https://beauty.hotpepper.jp/doc/kiyaku.html` の本文をこの調査では取得できなかった。美容クリニック、Academy、グルメの別サービスの規約を美容室掲載Sourceの許可として代用しない。
従って店舗ページCrawler・本文保持・同定用Datasetの本番利用は**未確認**。無断実装しない。検索エンジン経由のURL・snippetについても別途Serper契約と再利用/保存範囲の確認が必要で、直接ページアクセスしないことだけで適合済みとはしない。

### Indeed
[公式日本語利用規約](https://jp.indeed.com/legal?hl=ja)、最終更新2026-09-30、セクションD.21には無許可の自動アクセス・データ取得・商業利用に関する制限があり、書面許可とrobots条件に関する記述もある。今回の用途に対する許可・契約を確認できていないので、汎用Crawlerによる求人現在性取得を実装しない。robotsの一部許容を商業収集全体の許可へ読み替えない。

### その他
求人ボックスは今回採用・実データ取得していない。公式採用ページは代替候補だが、各サイトの利用条件、robots、ページの現在性、会社/店舗との一致を個別確認する必要がある。既存Instagram等はPresence URL/Evidence範囲のみで、投稿分析・大量保存は対象外。
Google Placesの保存/再利用条件確認は既存の課題として維持。外部Sourceの取得・保有契約が未確認のまま「本番利用可能Source」と断定しない。

## 本番Source判定

| Source/経路 | 判定 |
|---|---|
| URL/CSV等の利用者提供データ | 既存入力経路を維持。利用者が使用権限を持つ範囲が前提。自動Discovery精度の実証とは別 |
| Serper検索 | 既存実装・過去Raw Pilotの実行記録あり。今回のHotPepper/求人条件に関する保存・再表示範囲と実データ精度は未確認 |
| HotPepper Beauty専用Crawler | NO-GO / 利用条件・保存条件未確認 |
| Indeed専用Crawler | NO-GO / 用途に適合する許可未確認 |
| 求人ボックス専用Crawler | 未確認・未採用 |
| 公式企業/採用ページ | 個別条件・robots・Identity・現在性確認後の候補。現段階で全サイト利用可としない |
| Google Places補完/再利用 | 既存のSOURCE_TERMS_REVIEW_REQUIRED境界を維持 |

## Early Skip・Search Budget・Cancel/Recovery
既存のextra_searchesはAUTOなら追加検索せず、MUST/EXCLUDEの媒体はrequired planで優先する。MUSTの明確なNO_MATCH / EXCLUDE MATCHは以降の調査を止め、Companyを削除しない。UNKNOWNを不存在へ変えない。
追加検索は実行前にExternalPresenceSearchを予約してcommitし、operation/budget scopeで回数とtimeoutを制限する。中断済み試行も予算を消費し、stop callbackを利用する。今回この経路を実行していない。新しい求人処理をcancel/recoveryへ接続する場合は既存予約・失敗・進捗に合わせ、実測費用を0と推測しない。

## Pilot結果とHuman Truth
指定Pilotは未実行のため、下記はすべてnull/未測定。0件成功や0%精度として報告しない。

| 指標 | Pilot 1 | Pilot 2 | Pilot 3 |
|---|---|---|---|
| 候補数・完全一致数・確認待ち数 | null | null | null |
| Human reviewed・誤一致・誤除外・重複 | null | null | null |
| 公式サイト発見率・HotPepper同定率・求人確認率 | null | null | null |
| Instagram/フォーム発見率 | null | null | null |
| 追加検索回数・1企業あたり検索回数 | null | null | null |
| 処理時間・実原価 | null | null | null |

参考として、[147の既存Raw Pilot](147_RAW_COLLECTION_PILOT.md)は4 Run / Raw Hit 40 / Raw観測unique 11、Human reviewed 0、過去Serper API call 4。これは本指示の条件付きPilot、独立20店舗の発見、Human正解精度を意味しない。Human TruthをCodex/AIが作成・代行していない。
今回の製品Collection API呼出し、AI call、Completion job、承認作成、メール送信、フォーム送信は0。規約確認のWeb参照・GitHub CI確認は別の監査通信。金額・実データ処理時間・tokenは未測定null。outbound OFFとworker停止を維持し、実行設定を変更していない。

## DMへのObserved Facts引き渡し
今回DM生成・送信は開始しない。将来は検証済みPredicate、source URL、excerpt、observed_at、Human/Automatic、hash/versionを使う。Presenceと現在募集中を別事実として扱い、求人があることから「採用に困っている」、SNSがあることから「SNSに困っている」を確定事実に変換しない。期限切れや企業変更後の証拠を使わない。

## 必須テストと品質ゲートの扱い
既存CIは現行実装に対する合成テストの成功である。指示書の新機能24項目すべての受入テスト成功・実データ性能を意味しない。
- 既存確認対象: 条件proposalの未解釈保持/非実行、Human/Agent/Project境界、地域・業種Human evidence、複数MUST/WANT/EXCLUDE、予算・AUTO/SEARCH/REQUIRED、Early Skip、Evidenceリンク、固定条件binding、cancel/recoveryの既存経路。
- 未完了: 指定自然文全体、requestedCountの確認/引き継ぎ、ACTIVE_JOBの現在性、HotPepper専用Entity精度、条件緩和の件数試算、新pipeline全体の実データ/Human Truth比較。
- 今回は製品コード・Migrationを変更していないため、新たな合成テストで受入達成を装わない。

## 再開条件と実装順序
最初にSource取得方式を確定する。HotPepper Beautyは対象規約/契約と保存・表示・保持期限・第三者提供の範囲を確認し、求人は利用許可のあるSourceまたは個別確認した公式採用ページに限定する。条件を緩和してHotPepper MUSTを黙って外さない。
その境界が確定してから、順に実装する。
1. Stage 1: requestedCountと指定自然文を非実行Proposalへ構造化、Human確認で条件・件数・予算を固定。AIを使う場合もデータ境界・費用を確認し、未解釈を残す。
2. Stage 2/3: 既存地域EvidenceとHuman業種レビューを拡張。業種類義語はTargetProfile設定へ置き、Human Truthとautomatic結果を別記録する。
3. Stage 4/5: 求人現在性と店舗同定を別Evidenceとして保存。終了/期限/応募状態/会社・店舗の一致が不足する場合はUNKNOWN/REVIEW_REQUIRED。LIKELYを確定にしない。
4. Stage 6/7: 既存予算・Early Skip・固定条件と結果一覧へ接続。不足件数は実数、緩和はHuman提案・承認のみ。
5. Stage 8: 新規専用Projectで約20候補、Raw snapshot先行、限定Source、Humanレビュー入口を準備。実測UsageとHuman比較を保存。20件に届かなくても水増ししない。精度不足/費用超過等で停止。

**次に行う1工程: HotPepper Beautyと求人の取得方式・保存条件を確定するSource利用境界レビュー。** 外部メールによる許可依頼、API契約、Source設定変更は今回行っていない。

## Source利用境界の追加確認
後続の「進めてください」に基づき、2026-10-07に対象サービス本体の公開規約をさらに調査した。
- [HOT PEPPER Beauty ヘア/キレイ利用規約](https://cdn.p.recruit.co.jp/terms/hpb-t-1001/index.html)を確認できた。第5条1項は掲載情報等の許可を超える使用を制限し、2項3号は商用目的でのサービス利用を禁止している。従来の「規約本文を取得できず未確認」から、**一般規約だけでは本用途を許可できない**へ更新。個別許諾・契約は未確認。直接取得、転載、保存、再表示を許可済みとしない。
- [Serper Terms](https://serper.dev/terms)、更新2024-05-29を確認。B2BサービスとしてAPIを提供するがData Licenseは第三者コンテンツの権利を別扱いとする。Serperを使うことだけでHotPepper/Indeedのコンテンツ利用権を取得したとは扱わない。Serpex等の別サービスの規約を代用しない。
- 本調査は法律上の最終判断ではなく、本番自動取得を許可しない運用判断。媒体の権利者の許諾・用途/保存/再表示/保持期間の契約が確認できるまで、指定媒体の自動取得Pilotを保留する。
- 外部取得不要の条件Proposalの改善だけを次の限定工程とし、Crawler・求人現在性取得・媒体同定・Pilotを同時に開始しない。求人条件を除去・緩和せず、UNKNOWN/未検証として維持する。

## 後続の限定実装

「進めてください」に基づき、[158_PURPOSE_SENTENCE_PREVIEW.md](158_PURPOSE_SENTENCE_PREVIEW.md)の範囲で条件Proposalを拡張した。指定自然文の例と目標件数をHuman確認して保存する。上記の「コード変更なし」「指定自然文未対応」は47990b4時点の監査記録であり、後続の今回のコード変更とは区別する。

Stage 1はPARTIALを維持。限定パターンの決定的な構文解析であり、汎用AI理解、目標件数達成制御、Source取得許諾、求人現在性検証、HotPepper店舗同定、実データPilotは未完了。条件保存は送信承認を作成せず、既存UNKNOWN判定を緩和しない。

後続実装の検証HEAD `e42d8f0`、[CI 37586892513](https://github.com/team478a/leadhive_codex/actions/runs/37586892513) は全7 job成功。Backend 1,275 passed / 45 skipped / 50 subtests、E2E 74 passed / 2 skipped。Migration追加なし。限定工程は完了、媒体利用許諾・実データHuman Truth・指定Pilotは引き続き未完了。

## Stage 3の確認支援

後続の「次のタスクへ」「続けてください」に基づき、[159_INDUSTRY_ALIAS_REVIEW.md](159_INDUSTRY_ALIAS_REVIEW.md)の限定工程を実装。TargetProfileごとの別名を保存済み公式本文のHuman確認候補に使う。検索展開や自動一致判定は追加しない。Stage 3全体の自動業種検証・実データ精度を完成済みとはしない。Stage 2の地域Evidence判定は変更せず回帰確認する。Stage 4/5の外部媒体取得・求人現在性・指定Pilotは保留を維持。

検証HEAD `9ddbd85` の [CI 37590459996](https://github.com/team478a/leadhive_codex/actions/runs/37590459996) は全7 job成功。Backend 1,286 passed / 45 skipped / 50 subtests、E2E 74 passed / 2 skipped。Migration追加なし。ローカルAPI・画面・DBの正常応答、保存済み40 Raw観測の不変、outbound OFFを確認した。

## Stage 7の条件一致・不足表示

後続の「次のゴールへ」に基づき、[160_CONDITION_TARGET_SUMMARY.md](160_CONDITION_TARGET_SUMMARY.md)の限定集計を実装。最大500件の保存済み候補を既存基準で評価し、全件評価・明示目標の場合だけ不足を確定する。登録済み重複は目標から除外し、理由件数は重複ありとして表示する。部分集計を全体件数、条件一致をDM READYや独立送信先と混同しない。追加検索・条件緩和・送信を起動しない。

Stage 7全体の目標達成制御・緩和効果試算は未完了。Source利用許諾、求人現在性、店舗同定、Human Truth、指定実データPilotは保留を維持する。

検証HEAD `4ff590d` の [CI 37593499599](https://github.com/team478a/leadhive_codex/actions/runs/37593499599) は全7 job成功。Backend 1,296 passed / 45 skipped / 50 subtests、E2E 76 passed / 2 skipped。Migration追加なし。ローカル画面・DB正常、Raw観測40件と送信関連0件は不変、outbound OFF。文書のみの結果追記後にこの限定工程を停止する。
