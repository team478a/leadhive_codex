# 提供者の文脈ヒントと収集成長の分離

作業日：2026-10-08。ブランチ：`codex/integration`。基準：`cf419fe04278728fccc012dad3018097f2476234`。

## 目的

業種語があるだけでは、対象サービスの提供者とは限らない。自社利用、講座、記事、行政ページ、社名の記載を人が区別しやすくする。また、確認待ちが増えている検索を「新規候補なし」として終了しない。

## 確認ヒント

既存の保存済み公式サイト本文・TargetProfile別名・24時間の根拠有効期間を再利用する。新規検索・AI呼び出しは行わない。本文候補に提供・受託、自社利用、授業、記事、行政ドメイン、社名の文脈ヒントを付ける。混在する文脈は併記し、候補を除外しない。

最大100,000文字、最大60文章候補を調べ、提供文脈だけを持つ候補を優先して最大3件表示する。これは語句による確認補助であり、意味理解や自動正解判定ではない。ページ前半に大量の言及があると後続ページを候補化できないことがある。

業種別の語彙は既存TargetProfile設定に置き、CoreにSNS業種専用の判定を追加しない。各ヒントの`confirmed`は常にfalse。業種条件・Human Truth・営業可否・送信承認の確定には使わない。

UIは文章・出典・取得日時と文脈の注意点を表示する。Human確認チェック、確認保存、Project権限、Agent拒否、取消・失効の既存境界を維持する。

## 収集の停止判定

`collection_inventory`で対象ジョブ群の保存済み候補と条件状態を取得する。目標達成は従来どおりMATCH件数で判定する。一方、ページ継続は新しい候補IDが増えたかで判定する。REVIEW_REQUIREDやNO_MATCHの新規候補もDiscoveryの成長として扱う。重複だけのページでは次の検索語へ進む。

既存の最大500件目標、API試行上限50回、APIエラー・キャンセル・再開・Suppression・まとめサイト除外の境界は変更しない。確認待ちの多い検索では以前よりAPI回数が増える可能性があるが、上限は維持する。

条件付き収集の進捗には条件一致、発見候補、確認待ち、条件不一致を分けて表示する。発見候補は収集ジョブ由来で保存された、duplicate/excludedでないレコード数であり、検索APIのRaw Hit総数とは異なる。確認待ちを条件一致や送信可能件数に加算しない。旧進捗データには従来の表示を維持し、未保存の内訳は未集計とする。

## 検証

- 隔離した新規PostgreSQL `_test` DB。既存店舗データ・収集成果物は変更しない。
- Backend関連回帰：105件PASS。提供文脈・混在文脈・不明、異なる業種、公式根拠失効、他Project/Viewer/Agent、確認待ち/不一致の収集成長、重複停止、API上限、取消等。
- Alembic upgrade head / model差分check：テスト起動時に成功。Model・Migration変更なし。
- Ruff check/format：app/tests成功。
- mypy：変更Service3ファイル、既存CI同様の`--check-untyped-defs --follow-imports=silent`で成功。
- Frontend typecheck / lint / build：成功。既存のチャンクサイズ警告あり。
- API import成功、E2E用隔離APIの起動・health確認成功。
- Desktop/Mobile Playwright：4件PASS。文脈ヒントの表示、Human確認必須、旧進捗互換、条件一致0件と確認待ち/不一致内訳を確認。
- GitHub Actionsの既存mypy対象に新規ヒントServiceを追加。remote CIは未実行。

通常のmypy（import先も確認）では変更対象外の`services/scraper.py:316`にBeautifulSoupのhref型に関する既存エラー2件がある。CIと同じ対象範囲の検証結果とは分離する。

## 安全と限界

実検索・追加収集・AI解析・メール・Form POST・Human承認を今回実行していない。送信用workerを起動していない。API/E2E起動ではoutbound OFF。試験内の収集結果は合成データとmockであり、実収集精度の測定値ではない。

ローカル配布済みアプリへの反映・GitHub CI確認・commit/pushは本作業に含めていない。新規Model、Migration、依存追加、外部サービス設定変更なし。

次に実測する際は同条件のRaw SnapshotとHuman Truthを使い、提供者の誤認・確認時間・API回数を比較する。今回のテスト件数を実際のPrecision改善と解釈しない。
