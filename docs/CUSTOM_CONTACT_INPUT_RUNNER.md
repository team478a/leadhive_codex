# 独自JavaScript問い合わせフォームの入力専用ランナー

## 目的と基準

基準は main `58d9d927fbbe0d6ca75d0eca7e43c55725ba46f7`（PR #73統合後）。
PR #73が保持する独自DIV問い合わせ候補を、既存PCランナーで入力・読み戻しできるようにする。
送信、確認画面への遷移、Human Approval、HTTP dispatchは追加しない。

## 入力範囲

通常のformがあれば既存の単一form選択を維持する。formがない場合のみ、
contact/inquiry/問い合わせ等のid・aria-label、またはrole=formを持つコンテナを候補とする。
有効なemail、textarea、送信・確認用ボタンが必要。ボタンは操作しない。
入れ子は最小コンテナを選択し、複数候補、無名・重複項目、外部form属性、password/search、
非表示コンテナは自動入力しない。認識は入力候補の判定であり営業許可ではない。

既存のvalues/choices/consentsを使用し、選択肢・同意は推測しない。
HTMLのrequiredと既存のラベル取得を使う。独自JSだけで表現された必須ルールを完全認識する機能は未実装。
入力後に値を読み戻し、HTML標準のvalidationと構造hashを検証する。
独自JSによる業務検証・最終送信の成功を保証するものではない。

## 大きな埋め込み画像

PublicGetterのdocumentのみ、受信上限を最大8MBとする。全リクエスト合計のraw受信量も8MB以下。
保持するHTMLは500KB以下、全保持リソース合計は2MB以下を維持する。
500KBを超えるHTMLの場合のみ、img.srcにある4096文字超のPNG/JPEG/GIF/WebP/AVIF base64を`data:,`に置換する。
scripts/styles/textarea/hidden fields/同意・営業NG文/CAPTCHA/SVGを削除しない。
属性内の偽src、重複src、未閉鎖タグは保守的に保持または停止する。
JavaScript/CSSの単体500KB上限は拡大しない。新しいhelperを配布パッケージのmanifest対象に追加した。
htmlHashは画像省略後に実際に描画するsnapshotのhashであり、元HTMLのhashではない。

## 安全境界

- 同一HTTPS origin、public IPv4 DNS検証とTLS接続先固定、robots、リダイレクト拒否を維持。
- 最大32 GET、60秒、1秒間隔。画像・フォント・動画は取得しない。
- 描画後、入力前にCore ticketを再検証し、入力中は全通信を遮断。
- 営業NG・CAPTCHA・構造変更・外部通信要求・読み戻し不一致で停止。
- send/confirmation/approval/execution flagsはfalse、ボタン操作なし。
- DB/API/送信機能/Feature Flagの既定値は変更なし。実サイトアクセスなし。

## 検証

既存form-lab PlaywrightのDesktop/Mobile双方で検証する。
独自候補・通常form優先・入れ子・5項目構成・曖昧候補・禁止/CAPTCHA・自動保存遮断・構造変更・
読み戻し不一致・大容量画像・属性境界・raw/retained予算を回帰対象に含める。
TypeScript、ESLint、build、PC connectorのpytest/Ruff、配布パッケージ検証、CIを実行する。
最終結果はPRのValidation欄と最終headに対するCIを正本とする。

ローカル結果：form-lab全体166件PASS。その後追加した上限・5項目対照を含む関連30件PASS、
通常formの外部関連項目validation維持の対照2件PASS。
typecheck/lint/build成功、PC connector37件PASS、Ruff/format成功。
buildには既存のbundleサイズ警告が残る。配布と最終head全体の検証はCIも確認する。

## 残る運用確認

実サイトでの入力成功は今回のオフライン検証から推定しない。
マージ後、入力専用OFFからの限定試行を自社サイト1件で行い、読み戻し結果を取り込む工程が残る。
送信OFFを維持し、最終送信・確認操作には進まない。
