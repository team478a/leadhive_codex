# 公式サイト補完・残り75店舗の一次確認

## 結果

2026-10-05、[10店舗の試行](96_OFFICIAL_WEBSITE_COMPLETION_TRIAL.md)に続き、姫路市100店舗プロジェクトの未調査75店舗を検索し、元の店舗ページと公式情報を照合した。店舗一覧の品質改善とフォーム事前解析までを実施した。

- 一次確認75店舗、公式URL登録21店舗、確認保留54店舗。
- 全100店舗の公式URL登録は22 → 43、未登録は78 → 57。未登録57は今回の保留54と前回の保留3。
- 登録21店舗は16ドメイン。店舗数を独立した営業先数として扱わない。
- 登録21店舗をAI OFFで再解析。processed=21 / success=18 / failed=3。3店舗のERRORはすべてrobots.txtによる解析禁止。OperationJobはfailedとして保存され、成功扱いにしていない。未処理店舗は0。
- 最終連絡制御のALLOWEDは0 → 3。ただし確認画面付き2店舗を含み、送信承認・営業同意・送信成功を意味しない。
- メール送信、フォーム送信、承認済みフォーム予約はすべて0件。workerは停止を維持。

successは少なくとも1件の非ERROR解析結果を保存できたという意味。フォーム未発見・CAPTCHA・要確認も含む。全プロフィールが正常、営業DMに利用できる、とは判断しない。解析部分失敗は記録したまま、今回の一次確認とURL補完を完了した。

## 同一性確認と保留

75店舗すべてについて店舗名・地域を含む検索と、元のHotPepper店舗ページのホームページ欄を確認。候補がある場合は番地・店舗名・店舗階数または公式サイトの予約リンク先店舗IDを照合した。広域住所「兵庫県姫路市」だけでは一致と判断しない。

| 確認結果 | 件数 | 対応 |
|---|---:|---|
| 公式情報と元店舗の同一性を確認 | 21 | website_url / domainを登録 |
| 独自公式サイトを確認できず | 47 | 未登録を維持。存在しないとは断定しない |
| 候補URLはあるが取得・所在地確認ができず | 4 | 未登録を維持 |
| 専用ドメインのポータル掲載候補 | 1 | 店舗管理・現行情報を確認できず保留 |
| 同名サイトと元店舗の住所が異なる | 1 | 移転・別店舗の可能性を保留 |
| 公式ブログのみ確認 | 1 | フォーム探索用URLへ代入しない |
| 合計 | 75 | |

住所不一致の候補は、公式側の駅前町259・5階と元参照側の車崎1丁目8-17が異なる。どちらを現行とするかを推測せず未登録とした。同名の別地域の美容室も除外した。

登録根拠の例：

- [CLOUD Nine公式サイト](https://cloudnine-2.jimdosite.com/)：本店・南条店の予約リンク先がそれぞれ元店舗IDと一致。共通サイトを2店舗に登録し、店舗レコードを保持。
- [SoL公式店舗一覧](https://hairplacesol.com/)：SoLはノトヤビル1階、lonaは同2階。元参照の階数まで照合。
- [SERO東辻井店公式情報](https://hairsalon-sero.com/salon02)：店舗名・番地を照合。
- [SAKURAリバージュ公式情報](https://www.hair-sakura.co.jp/salon-rivage/)と[ビレッジ公式情報](https://www.hair-sakura.co.jp/salon-village/)：それぞれ所在地を照合。
- [ROI公式店舗情報](https://tenection.co.jp/brands/roi/)と[REINE公式店舗情報](https://tenection.co.jp/brands/reine/)：店舗名・番地・階数を照合。

登録21には公式検索インデックスの住所や公式店舗一覧で同一性を確認できた一方、個別ページの現時点の取得が失敗したケースも含む。根拠と取得状況は詳細へ分けて記録した。URL登録は到達性保証ではなく、既存SafeFetcherによる実際の取得・robots確認を別途実施している。

検索・資料照合はCodexのブラウズによる一度限りの調査。LeadHive自体にAPIキー不要の自動公式サイト発見機能を追加したわけではない。

## 更新と履歴

利用中のローカルDBのみ変更。確認済み21店舗のwebsite_url / domainを既存canonicalize_urlで補完し、同じtransactionで既存Activityにnoteを保存。根拠URL、元参照URL、確認住所、確認方法、日時、変更前後URLを記録した。Human承認や営業許可として記録していない。

Company ID・location_key・reference_url・company_name・addressは全100店舗で不変。今回未登録54店舗と対象外25店舗のwebsite_url / domainも不変。新規企業作成・店舗統合・住所や連絡先の補完は行っていない。企業編集APIがURL変更を受け付けないため、一度限りのローカル補完処理を使用した。

## フォーム再解析

既存analyze_company_forms / SafeFetcherでGETのみ実行。AI OFF、店舗間2秒待機。robots・危険URL制御を維持し、禁止先への回避アクセスや再試行は行っていない。停止中workerを起動せず、既存OperationJobに進捗と部分失敗を保存した。解析実行時間は108.39秒で、検索・照合に要した時間は含まない。月10,000件の能力へ外挿しない。

今回登録21店舗の主プロフィール分類：

| 分類 | 店舗数 |
|---|---:|
| 構造上の候補 | 1 |
| 確認画面あり | 6 |
| CAPTCHA | 3 |
| 要確認 | 2 |
| フォーム未発見 | 6 |
| 解析エラー | 3 |

要確認2は、外部サイトをactionとするフォームとmultipartのファイル送信形式。CAPTCHAは人による確認対象。フォーム未発見は既存探索範囲内の結果で、JavaScript・予約サービスなどを含むすべての連絡経路が存在しないという意味ではない。Codex支援タスクも起動していない。

全100店舗の保存済み集計：

| 指標 | 補完前 | 補完後 |
|---|---:|---:|
| 構造上の候補 | 2 | 3 |
| 確認画面あり | 0 | 6 |
| CAPTCHA | 6 | 9 |
| 要確認 | 2 | 4 |
| 解析エラー | 84 | 66 |
| フォーム未発見 | 6 | 12 |
| 最終連絡制御 ALLOWED | 0 | 3 |
| 最終連絡制御 UNCERTAIN | 91 | 81 |
| 最終連絡制御 PROHIBITED | 9 | 16 |

ERROR 66はURL未登録57と、URL登録済み9。9のうち今回のrobots禁止3、以前の結果を再取得していない6。PROHIBITED 16は共通宛先の制限であり、16店舗で営業禁止文言を検出したという意味ではない。

今回の確認画面付き6のうち4はSoL/lonaとROI/REINEの共有宛先で最終連絡制御PROHIBITED。残る2と新たな構造上の候補1がALLOWED。従来の構造上の候補2は引き続き共有宛先でPROHIBITED。プロフィールのREADYやsales_contact_status=ALLOWEDだけを使わず、evaluate_contact_permissionと承認・dispatch guardを維持する。

## 稼働確認・成果物

- API health / database=ok。企業100件、FormProfile 111 → 139、active job=0。
- worker=exited。outbound / human-approved-form / legacy-form / agent flagsすべてOFF。
- ApprovedFormDispatch / FormDelivery / EmailDeliveryは変更前後とも0。承認・送信準備・予約・外部POSTなし。
- Alembic head=fae47ac5e861。アプリコード・Schema・Migration・配布パッケージ変更なし。コード変更を伴わないため、検証は保存結果・件数不変・既存一覧Service・API health・送信件数不変に限定し、全回帰テストを今回実行したとは扱わない。

Git管理外の詳細：`dist/website-review-75-plan.json`、`dist/website-enrichment-75.json`。75店舗それぞれの参照、候補、保留理由、登録・解析結果を保持。詳細結果SHA-256: `C6013B757742E917BB051EECD492E5F45B06FC9173E2D5110F0EDC70B5D355A1`。

事前バックアップ：`dist/website-enrichment-75-before.dump`（308,819 bytes）。一度限りのスクリプト・バックアップ・店舗別詳細はGitへ含めない。[店舗別情報を除いた集計](results/website-completion-review-2026-10-05.json)と本書のみ共有する。ローカルDB補完はGit pushによって他PCへ同期されない。

## 次の優先工程

ALLOWEDとなった3店舗について、実際のフォーム用途、営業禁止表記、入力項目、送信先の法人・店舗の範囲、確認画面を送信せず検証し、営業候補として使えるかを判断する。サイト補完の比率だけで大量送信やworker再開へ進まない。
