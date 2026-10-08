# CF7候補の限定静的観察・解析隔離

## 基準と今回のゴール

基準 `codex/integration@43acfc7`。既存の対象ページLive Checkで取得したHTMLについて、CF7の構造候補を追加アクセスなしで検証し、取得条件・保存範囲・解析停止条件を明確にする。実サイトCF7 Adapterの登録や送信は行わない。

## 取得の条件と範囲

既存Human owner/editorの `POST /api/form-profiles/{id}/live-check` を再利用。Project境界、Agent/mixed principal拒否、ViewerのPOST拒否、1分間の再確認制限を維持。対象は保存されたFormProfile URLとform_indexのみ。今回新しいURL入力API、探索Job、常駐workerを追加しない。

既存TargetFetcherのrobots確認、公開アドレス確認、HTTPの上限/timeout/TLS検証を維持。CF7のREST root/endpoint、JS、別ページへ追加GETしない。RESTリンクはHTML内の同一HTTPS originかつ `/wp-json/` rootの存在を調べるだけ。RESTの稼働・受付可否・バージョン対応は未検証。既存GETがredirectした場合、この追加解析では元フォームのCF7証拠を生成しない。

既存FetcherにはDNS確認とHTTP接続の間でresolverを再利用する構造がある。DNS pinningを伴うCF7専用production transportとして完成したと判断しない。redirectも既存挙動を維持している。この工程は取得範囲を広げず、既存GETの応答を検査する追加機能である。次の限定取得工程ではpinning、固定origin/path、redirect拒否、共有deadlineを管理下Transportと照合する必要がある。

## 解析隔離

`cf7_static_parser.py` はアプリ・DB・ネットワークのimportを持たないstdlib HTMLParser。HTMLを命令として解釈せず、JavaScriptやサイト指定コードを実行しない。

`cf7_static_inspection.py` が `python -I` の別プロセスへstdinで渡す。OSのSystemRoot/WINDIR以外は環境変数を継承せず、APIキー/DB/SMTP設定を子へ渡さない。Windowsではウィンドウを表示しない。shellや任意プログラム起動をサイトに指定させない。

上限: HTML UTF-8 256KiB、form 20、tag 10,000、名前付きcontrol 100/form、項目名100文字、実行5秒、返却JSON 2KiB。超過・重複attribute/hidden marker・入れ子/閉じられていないform・例外は固定失敗へ変換。内部例外・stderr・HTML断片は保存/表示しない。実行結果もstrict schemaで再検証する。

これはプロセス分離・入出力上限であり、OSレベルのネットワーク/filesystem sandboxやハードメモリ隔離ではない。その保証を主張しない。既存の一般構造比較・営業禁止・CAPTCHA解析全体もこの子プロセスへ移したわけではない。

## 返却・保存する情報

- CF7候補/非CF7/指定formなし/解析失敗/上限超過。
- 数字とドットだけのversion候補、form IDの形式確認boolean。
- `_wpcf7`、`_wpcf7_version`、`_wpcf7_locale`、`_wpcf7_unit_tag` の基本4hidden markerの存在。
- POST/enctypeの形式確認、name不足件数、file欄件数、限定対応外control件数、form件数。
- 同一origin REST rootリンクの存在、base指定の有無。
- `execution_allowed=false / eligible_for_approval=false` 固定。

完全なCF7契約やhidden tokenの有効性を確認した意味ではない。候補を検出しても実送信対応済みにしない。name不足/file/特殊項目のあるフォームは後続の限定対応を決めるための診断にとどめる。

HTML本文、URL、項目名、hidden値、本文・個人情報、token、cookieはこの追加診断へ保存しない。既存FormAnalysisLogの `target_live_check` 内に集計/booleanのみ保存。既存GETで再表示し、24時間鮮度・source_binding変更を既存ロジックで確認する。過去のlogに追加診断がない場合はnull。新Model/Migration/API/dependencyなし。

元HTMLは取得・子プロセスのメモリ/pipeで使用し、ファイル保存しない。子終了後に保持しないが、メモリの暗号学的消去保証はない。既存診断logの全体削除/保持期限管理は今回変更しない。組織共有DBへ展開する場合の保持・削除方針は別工程。

## Core・Human境界

CF7候補、解析失敗/上限超過を検出した場合、通常ProfileのREADYを維持せずREVIEW_REQUIRED・delivery_supported=falseへ停止。既存営業禁止・CAPTCHA・構造不一致の停止を優先。Profile field・手動確認済み値・fingerprintを追加診断で上書きしない。

Human Approval、CF7Observation/管理下候補契約、Transport、SendAttemptへ接続しない。既存Managed Lab flagを実サイト用に緩めない。前工程の保存観察Core holdも維持。

## UI

既存「現在のフォームを確認」の結果へ「CF7の静的構造確認」を表示。追加ボタン・追加操作なし。候補version、基本マーカー、同一サイトRESTリンク、未対応項目数を確認できる。期限切れ/情報変更後は過去観察と表示し、送信対応・許可・承認と混同しない。

## 検証と停止点

合成HTML・専用テストDBのみ。今回の実サイトGET・検索/AI・承認・Email/Form送信は0件。稼働対象2社の新しいCF7観察はまだ取得していない。Human確認済みや実サイト動作確認済みとして扱わない。

初回テストは54PASS/2ERROR。長大なparametrized HTMLがpytest IDに展開されたfixture問題を短いIDで修正。存在しないテストファイル指定も修正し、最終対象で再実行した。数値は下記に記録。

- 最終Backend関連84件PASS（27.47秒）。隔離プロセス実行、timeout、サイズ・重複・marker・script非実行、出力秘密情報除去、RESTリンク限定、実API保存/再読取、失敗時READY解除、既存permission/フォーム診断を検証。
- Ruff・format・mypy（新規parser/wrapper/Live Checkの3ファイル）成功。
- Frontend typecheck・lint・build成功。既存bundleサイズ警告あり。
- PC/Mobile Playwright4件PASS（1.8分）。CF7候補/version/未検証表示、古い構造の警告、既存確認・Viewer・送信不可の回帰を確認。Mobile screenshotでも表示を確認。画面の応答はfixtureであり実サイトではない。
- 専用DBの既存Migration upgrade・Alembic model diff確認成功。追加Migrationなし。
- ローカルAPIをoutbound OFFで起動確認。通常worker未起動、Company26/Raw80/Review0/Approval0/Email0/Form0件は再起動前後不変。GitHub Actionsは未pushのため今回成功未確認。

次は固定対象の限定GETをDNS pinning・redirect拒否・deadline付きで安全に取得する境界を検証し、その後2社の診断を測定する。実POSTや送信承認へは進まない。
