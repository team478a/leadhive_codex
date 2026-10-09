# 工程3: 企業情報抽出・公式サイト照合・問い合わせ探索

作成: 2026-10-09。基準: `codex/raw-offline-comparison-20261009@f97b262778050f30056552f10258f6706bb8d181`（PR #8のmerge commit）。実装branch: `codex/collection-site-extraction`。工程4・全国展開・外部Pilotは対象外。

## 実装したこと

- `site_extraction.py`: 単一のOrganization/Corporation/LocalBusiness/HairSalonのJSON-LD（@graph含む）を優先。複数組織の最初の名前を自社として選ばない。名称のmetadata/title fallbackは候補情報として記録する。
- メール: mailtoのURLエンコードを処理。画像・CSS・JS拡張子、連続ドット等を除外。存在確認・到達性の確認はしない。
- 電話: 全角を正規化し、括弧形式とハイフン形式に対応。TELを優先しFAXを除外。国内10/11桁のみ。国際形式・難読化メールは未対応。
- 住所: JSON-LD PostalAddress、address要素、所在地/住所/郵便番号の明示箇所を優先。対応地域だけの文章から所在地を作らない。TEL等の後続文を住所へ混入させない。一般本文fallbackは未確認候補。
- `PageData.field_evidence`: value/source_url/method/verified=false。複数ページの補完で、採用した値の出典を維持する。取得失敗はcrawl_errorsに残す。
- `website_match`: 更新前の企業情報で照合。ページ名称や電話の競合はREVIEW_REQUIRED。名前・ドメインだけでCONFIRMEDにしない。解析によりidentityが変わった場合は旧hashの根拠をREVIEW_REQUIREDとして残し、更新した情報から自己確認を作らない。
- `website_evidence.py`: 既存LeadSiteEvidenceとLeadSourceObservationを再利用。元の収集操作がある場合のみwebsite観測を追加。Raw hit/snapshotは書き換えない。値が変化していない再解析は同一facts hashの観測を重複保存しない。

## 問い合わせ探索

`contact_discovery.py`をWeb解析・Form Intelligenceから利用する。保存済み問い合わせ先、トップページの明示リンク、問い合わせ案内から入力ページ、同一サイトiframe、推測パスの順で探索する。推測パスは実リンクが尽きてから使う。ループ・深さ・件数を制限する。

Form Intelligenceは最大8追加ページ・深さ3。実DOMの問い合わせフォームを検出し、password/searchフォーム等を除外する。ページ中の元form_indexは維持し、既存のfingerprint・手動マッピング・STALE処理と整合させる。Web解析の追加ページ上限4は増やしていない。通常の会社概要/サービス等を取得し、その中の問い合わせ導線を残り予算で辿る。

取得前URLと転送後URLを解析ログへ保存する。相対リンクの解決は転送後URLを使う。別サイトiframeは追わない。HubSpot/Formrun/Google Forms/Typeform/Tayori/Microsoft Formsのscript/iframeマーカーは埋め込み候補として区別し、DOM確認済みとは扱わない。JavaScriptを実行するブラウザ探索・外部埋め込み実体取得は今回追加していない。

既存FormAnalysisLog.detailsで次を記録し、企業詳細の解析ログで表示する。

| finding | 意味 |
|---|---|
| DOM_CONTACT_FORM_NOT_FOUND | 取得HTMLで問い合わせフォームを検出できない。サイト全体に存在しない証明ではない |
| EMBEDDED_FORM_UNVERIFIED | 外部埋め込みマーカーあり。表示後の実DOM未確認 |
| FETCH_FAILED | 取得不能。フォームの有無は不明 |

## 取得上限・安全境界

SafeFetcherはrobots/redirectを含め32 HTTP要求まで。同一ホストは要求開始を1秒以上離す。開始から60秒経過後は新規要求を拒否する（実行中要求には既存HTTP timeoutが適用される）。各転送先のpublic URL検証とrobots確認を行う。サイズ・転送5回上限は維持する。

既存のWeb解析/Form Intelligence実行経路の改善であり、Raw BenchmarkからCompletionを自動起動する接続を追加しない。検索API上限、収集scheduler、Raw分類、AI設定、project権限、手動保護、営業禁止、CAPTCHA、Human承認、送信機能は維持する。HTMLは命令ではなく抽出対象データ。フォームが見つかることは営業許可・送信READY・Human承認を意味しない。

## DB・互換性

Migration追加なし。最新revision `2f178bf991d0`を維持する。既存read API `/api/companies/{id}/lead-completion`のsite_evidence/source_observationsとForm Intelligence logsで確認可能。新しい送信API・設定dependencyは追加しない。名前競合や解析中のidentity変更で確認保留が増える可能性があるが、精度を良く見せるために判定を緩めない。

## 検証

- 既存関連Backend回帰50件成功（追加テスト導入前の確認）。追加後のscraper/Form Intelligence/抽出/ナビゲーション44件成功、住所切り分け追加後のscraper/抽出/ナビゲーション24件成功。
- Offline collection replay45件成功。検索の再現比較を維持。
- 新規テスト: 画像メール/FAX/全角/対応地域負例、JSON-LD graph、複数組織、電話/名称競合、robots転送拒否、32要求上限、段階リンク/iframe/予算/外部リンク/元form_index、外部埋め込み、自己確認防止・website観測・送信なし。
- Ruff/check/format、変更serviceのmypy、Frontend typecheck/lint/build成功。
- Playwright既存フォーム画面 + 新しい診断表示: Desktop/Mobile 2件成功。ローカル専用test DB・合成fixtureのみ。
- CIのbackend-lintへ変更serviceのmypyを追加。全Backend、migration往復/model diff、E2E、HTTP lab、Windows packageはPRのGitHub Actions結果で確認する。

## 未検証と次工程

実サイトGET、Serper/AIの有料実行、実データ精度評価、Human Truth作成、実送信は今回行っていない。収集件数・公式サイト精度・フォーム発見率の改善を実データで証明したとは主張しない。

PR3の判定はオフライン検証に基づくCONDITIONAL GO。merge後、G1小規模Pilotの対象・上限・費用・Human評価条件を具体化し、承認された範囲で現行/改善版を比較して停止する。結果に重大問題があれば工程4/5へ自動的に進まない。
