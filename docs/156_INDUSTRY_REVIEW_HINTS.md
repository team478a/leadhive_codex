# 業種確認の文章候補・Human確認支援

## 目的・基準

基準 `codex/integration@e7b03900bebd5138248049eff0d98715e49b15f3`。業種条件を人が確認するとき、保存済み公式サイト本文の該当箇所を探しやすくする。AI業種推定・キーワード出現だけでは条件MATCHにしない。新しい収集・外部GET・AI呼出・送信は行わない。

## 表示できる文章

既存の公式サイト条件が現在MATCH、Web解析がcompleted、scraped_atが24時間以内かつ未来でない場合に限定する。既存scraped_urlsに含まれ、現在の公式ドメインの安全なURLであることを検査する。初期ページはscraped_urls先頭、二次ページは既存scraperが保存した `[URL]` マーカーで区分する。出典を確認できない部分は提示しない。URLの秘密情報・query・fragment・非公式ドメインを拒否する。

条件の業種名を文字列として検索する。NFKC・大文字小文字の違いを吸収するが、同義語展開・AI・正規表現による業種推論はしない。2〜100文字の語、保存本文先頭100,000文字、最大3候補、1候補最大320文字で制限する。重複する同じ文章・URLを除く。

出典・取得日時・短い文章を返す。存在しない場合はUNAVAILABLEまたはNO_LITERAL_MATCHであり、条件のNO_MATCHではない。AIのbusiness_type・business_summaryはこの文章検索へ混ぜない。

これは確認支援用の候補であり、記載内容の真偽・業種一致・ページ内の実際の文脈を証明しない。顧客事例、求人、否定表現、別店舗の説明を含み得る。保存されたページ由来の文章はUntrusted Dataとしてプレーンテキスト表示する。命令として実行せず、HTMLを描画せず、判定や承認へ自動適用しない。

## UI・Human判断

既存のCollectionFactReviewに「業種の確認を助ける文章」を表示する。公開ページへのリンク、取得日時、候補文章と「この文章を確認欄に入れる」を提供する。

入力ボタンはsource URLとexcerptを確認欄へ入れるだけで、保存・分類・送信承認を実行しない。候補から入力した場合は「公開ページとこの企業・店舗の事業内容を確認しました」のチェック後に、人の確認結果を保存できる。チェックは会社・条件種類/値・company hash・review version・URL・文章・判定結果の組合せへ結び付け、異なる組合せへ使い回さない。URL/文章を編集するとチェックを解除する。判断不能・取消はこの追加確認で妨げない。候補がなくても従来の手入力を利用できる。

このチェックは誤操作を減らすUI上の確認であり、新しい認証証明ではない。確定APIは既存Human owner/editor限定、company hash・review version検査、24時間有効期間、追記式ledgerを再利用する。Viewerは参照のみ、Agent・別Projectは既存境界で拒否する。HumanのNO_MATCH/UNKNOWNを文章候補で復活させない。

## API・互換性

`services/industry_review_hints.py`に非保存処理を分離する。既存条件結果のINDUSTRYへ `review_hints`（status / reason / excerpts）を追加する。既存Project結果・Operation結果の双方で同じCollectionFactReviewを利用する。Model・API endpoint・Migration・dependencyの追加なし。会社・原本文・Raw Human Truth・DM・Deliveryの正本を変更しない。

## 検証

Backendでは非保存、候補があってもUNKNOWN、Human判断の優先、出典URL、本文不足、解析失敗、期限切れ・未来、AIのみ、未取得二次ページ、不正なURL一覧、正規表現入力、Untrusted Data、上限、Project・Viewer・Agentを検証する。

PC/Mobileでは候補表示 → 入力欄へ反映 → チェック前保存不可 → 人の確認保存 → 取消 → 確認待ちの流れを合成データで検証する。地域・公式サイトの取消も回帰確認する。外部アクセス・収集Operation・送信を新規E2Eで検査する。結果は最終検証後に追記する。

- Backend関連50件PASS。最終の権限・URL一覧検証を含む根拠関連52件PASS（重複あり、合計89種類の関連テスト）。
- PC/Mobile関連E2E6件PASS。確認チェックを判定結果へ結び付けた最終UIでも、業種確認の2件PASS。
- Ruff / format / mypy、Frontend typecheck / lint / build、Alembic check成功。既存bundle size警告は残る。新Migrationなし。
- ローカルAPI 127.0.0.1:18986のhealth / DB疎通 / OpenAPI確認成功。Raw Snapshot40件、Raw Human Review0件を保持。Companies / ApprovalRequest / EmailDelivery / FormDeliveryも0件のまま。outbound OFF・worker未起動。

## 制限・残課題

同義語の設定、文章の意味判定、保存されていない公式サイトの取得、求人現在性、DM根拠引渡し、実PilotのHuman Truth測定は別工程。業種別ロジックをハードコードしない。チェック成功や合成テストの成功を実データ精度・レビュー時間短縮の実測成果と解釈しない。本ゴールで停止する。
