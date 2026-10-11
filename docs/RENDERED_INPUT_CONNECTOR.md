# 実URL取得 → 隔離描画 → 入力専用接続

基準：main `b760d0c406ec73158bebb02cdcb211d035b26d3f`（PR #67統合、PR checks全件SUCCESS）。

## 今回追加した経路

1. PCで明示した公開HTTPSフォームURLをGET取得する。
2. robots.txt、公開IP、同一サイトの転送、HTTP降格拒否、サイズ・回数・時間制限を既存SafeFetcherで確認する。
3. 保存HTMLで営業禁止を検出したら `BLOCKED / SALES_PROHIBITED` として停止し、描画リソースは取得しない。
4. ページに記載された同一originのscript・stylesheetだけを最大8件取得する。JavaScript/CSSのContent-Typeを確認する。第三者媒体やCDNの取得を自動許可しない。
5. HTMLと取得リソースのSHA-256、取得日時、GET数をprivateファイルへ保存する。Company・FormProfile・Approval・Deliveryは変更しない。
6. 保存データを隔離ブラウザの実URL位置へ提供して描画する。ブラウザから実サイトをGETしない。
7. 描画後、入力前に保存リソースへのアクセスも含めて通信を全面停止する。明示値・選択肢・同意だけを入力して読み戻し、確認・送信ボタンを押さずに閉じる。

これは実URLからの取得とブラウザ入力を接続する開発用CLIであり、実サイトとの通信を維持したライブ入力ではない。取得後の企業サイト変更や、実サイトへの送信成功を検証するものではない。入力成功は `OFFLINE_INPUT_VERIFIED` のままとし、`executionAllowed / approvalGranted / confirmationReached / liveFetchPerformed / sent` は false を維持する。取得段階のGET数と、ブラウザ段階の `liveFetchPerformed=false` は別の指標。

## 起動方法（開発環境）

Pythonのbackend環境、Node、既存Playwright Chromiumが必要。依存追加なし。既存Windows配布ZIPやクラウドのボタンへの組み込みは今回行わない。

private request JSON：

```json
{
  "formUrl": "https://example.com/contact",
  "termsConfirmed": true,
  "values": {"会社名": "Example Company", "メールアドレス": "fixture@example.com"},
  "choices": {},
  "consents": {}
}
```

入力キーは現在の入力欄名。未確認の同意や選択肢を自動補完しない。実行前に既存LeadHiveの営業NGリスト・suppression・対象用途を確認し、禁止対象をこの単独CLIへ渡さない。単独CLIがDBの禁止状態を読み取る機能はまだない。

```powershell
# 取得は既定OFF。対象URLとGET実行範囲を確認してから有効化する。
$env:PYTHONPATH = "$PWD\backend"
$env:LEADHIVE_BROWSER_INPUT_ACQUISITION = '1'
backend\.venv\Scripts\python.exe backend/scripts/prepare_rendered_input.py `
  --request C:/private/request.json --output C:/private/acquired-new.json

# 取得処理を終えてから入力。これ以降は実サイト通信なし。
cd frontend
$env:LEADHIVE_RENDERED_INPUT = '1'
$env:LEADHIVE_RENDERED_INPUT_FILE = 'C:/private/acquired-new.json'
npm run trial:rendered-form-input
```

上記は例であり今回実企業URLへ実行していない。取得成功と入力成功は別々に確認する。CLIは既存outputを上書きしない。取得結果がBLOCKEDの場合はブラウザrunnerへ渡さない。

## 安全境界

- 取得：SafeFetcherの32リクエスト・60秒上限（robots/redirect含む）、HTML500KB、各asset500KB、合計2MB、asset8件。
- Browser：外部要求をfetchで転送せず、許可済みsnapshotを最大20回提供するだけ。service worker禁止。画像・font・mediaは取得せず省略するため見た目の完全再現は保証しない。
- 未取得script、XHR/data取得、第三者CSS、外部iframeは停止する。必要リソースがない状態を入力成功にしない。
- form.submit / requestSubmit / submit eventの暗黙遷移も停止し、GET/POST/WebSocketの通信を遮断する。WebRTC/WebTransport/Worker/SharedWorkerもこの用途外として止める。
- 入力後に営業NGやCAPTCHAが現れた場合も停止。営業NG文言を削って入力を継続しない。
- payload hashへscript/styleのhashを含める。HTMLが同じでも描画リソースが変われば別snapshotとする。
- ブラウザの安全検査だけで承認・送信権限を発行しない。既存Human承認、送信基盤、outbound設定は変更しない。
- 保存HTML・script・入力値・メール等はGit管理外のprivate領域に保存する。結果ログはhash・件数・理由だけで、入力値やHTMLを含めない。

## 制限と次工程

実企業への取得・入力は今回未実施。HTML/scriptをローカルへ保管できる利用条件を実行前に確認する。ブラウザによる未知サイトの実行を安全と認定するものではなく、本番有効化前にはOS/コンテナの通信隔離も評価する。

動的import、追加JSON、CDN、認証、外部フォーム、CAPTCHA、複雑な同意は未対応。予算外や不足リソースはHOLD相当で停止する。これを理由に入力中の通信を許可しない。

次は既存候補1社の **取得だけ** を対象・GET上限を決めて試し、保存データを隔離描画・入力へ渡す検証。送信・承認は行わない。運用UIからの依頼作成・PC配布・Coreの禁止状態との接続は別工程とする。

## 検証結果（2026-10-11）

- ブラウザ回帰：122 PASS。追加のCAPTCHA/Worker/WebRTC停止ケースを含む描画関連テスト20 PASS。
- Backend：新規Snapshotと既存scraperを合わせて23 PASS、その後の転送・予算テスト追加を含むSnapshotテスト10 PASS。
- CLI実行：合成Snapshotの日本語項目へ入力・読み戻しでき、確認・送信なし。実URLの取得CLIはdefault OFFで拒否することを確認。
- TypeScript、ESLint、build、Python Ruff/format、変更Python3ファイルのmypy：PASS。buildは既存のbundleサイズ警告あり。
- CIと異なる全app一括mypyも調査したところ、変更後とmain基準コピーの両方で83 errors / 23 files。既存の全体型検査課題は今回修正していない。CIにはこの接続の3ファイルを明示的に追加して検証する。
- 新規dependency、Migration、DB変更、デプロイ、実企業へのGET・入力、メール、Form POST、承認：0。

ローカル結果をGitHub Actionsの成功とみなさない。CIはPR checksで確認する。
