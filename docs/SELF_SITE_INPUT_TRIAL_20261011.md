# 自社サイト入力専用試行と外部フォント停止の修正

## 基準と結果

- 基準 main: `26791de580514971929738bde6340df09ed00767`（PR #74 merge）。
- 対象: 管理者が許可した自社サイト `https://stock-business.me/` 1件。
- staging API を基準 commit へ更新。収集worker・送信workerは変更していない。
- 独自JavaScript窓口の入力5項目を検出。営業可否は未確認、HTTP送信は未対応を維持。
- 入力専用PCランナーは `TECHNICAL_UNKNOWN / NETWORK_REQUIRED` で入力前に停止。
- 実ページ入力0、確認0、送信0、Human Approval0。成功とは報告しない。
- ページ観測2 GET（robotsとトップ）、原因診断2 GET。検索・AI APIは利用していない。
- staging `OUTBOUND_ENABLED=false` を維持し、試行後に `LIVE_FORM_INPUT_ENABLED=false` へ復帰・反映済み。

## 原因の実証

実ページの保持HTML hash:
`9e8f64ef483f842b8142a107a699367ca45910b64d7d7240a29cfdc8b513ce95`。
原因診断で取得したHTMLも同じhash。入力なし・全通信を遮断した再生で、トップ文書の次に
`https://fonts.googleapis.com/css2` のstylesheet要求が1件発生した。
この要求は外部へ送られず遮断され、入力前のNETWORK_REQUIREDを発生させた。

Googleの[CSS API仕様](https://developers.google.com/fonts/docs/css2)でフォント指定用endpointを確認した。
フォーム操作に必要な未知CSSと文字装飾用CSSが同じ停止理由になっていた。
一般の外部CSSを安全と判断したわけではない。

## 限定修正

`frontend/form-lab/offline-input.ts` の明示的なsnapshot/rendered入力経路だけで、次を省略する。

- GETのstylesheet要求。
- HTTPS、正確な `fonts.googleapis.com`、`/css` または `/css2`。
- credentials・異常port・fragmentなし、2048文字以下。
- 空でない限定文字のfamily指定と任意の単一display指定。未知parameterは拒否。
- **外部取得しない**。ローカルで空CSSを返し、標準フォントで描画する。

省略件数は `omittedDecorativeRequests` に分離する。既存の画像・font・media省略も同じカウンタへ記録。
入力前のrendering payload hashは `cached-resources-v2-font-omission` として区別する。
標準アーカイブ経路の拒否は維持。
入力開始後はフォントCSSも含め全通信を遮断して停止する。
未知CSS、同名別ドメイン、script、iframe、fetch、POST、WebSocket、worker、CAPTCHA、営業禁止、
必須値、構造変更、読み戻し不一致の制御は維持する。
DB・API・Human Approval・本番送信経路・Feature Flagの既定値は変更しない。

## 保存HTMLによる比較（実ページ再入力ではない）

同じHTML hash、同じ入力内容を使い、修正前は入力なしのNETWORK_REQUIREDを再現した。
修正後は以下を実測した。

| 条件 | 結果 | 入力・読み戻し | 危険通信の遮断 | 装飾CSS省略 | 確認/送信/承認 | 時間 |
|---|---|---:|---:|---:|---|---:|
| 保存HTML・PC幅 | OFFLINE_INPUT_VERIFIED | 5項目 | 0 | 1 | すべて0 | 952ms |
| 保存HTML・スマホ幅 | OFFLINE_INPUT_VERIFIED | 5項目 | 0 | 1 | すべて0 | 1068ms |

この結果は現在の実サイトでの入力成功、送信能力、営業許可を意味しない。
詳細HTML・入力専用token・事業者の入力値はGit管理外に保存し、集計だけを公開する。
クラウドには実ページ試行の未送信PC報告と原因の活動メモを保存した。

## 検証

- 新規の限定endpoint・省略・未知通信拒否・入力後通信拒否・営業禁止/CAPTCHA維持テスト10件成功（PC/スマホ）。
- `npm run test:form-browser-poc`: 182件成功。既存の通常/custom入力、rendered、live、public GET、hash/byte budget、送信停止を含む。
- `npm run build`（typecheck含む）、`npm run lint`: 成功。既存のbundleサイズ警告あり。
- 同じ保存HTMLのPC/スマホ検証2件成功。新たな実サイトGETは行っていない。
- PR最終headのCI結果はPR Checksを正本とする。

基準mainのCIは初回Backendテスト開始前にPostgreSQLイメージ取得で
`public.ecr.aws` の `toomanyrequests: Data limit exceeded` に遭遇した。
E2Eほか11 jobは成功。失敗jobだけ1回再実行し、結果をCI run
[38125675168](https://github.com/team478a/leadhive_codex/actions/runs/38125675168)で追跡する。
Backend差分がないため、この基盤エラーと本修正の機能検証を混同しない。

## 次工程

限定修正をレビュー用PRへ提出する。自動merge・本番配置・実ページ再入力は行わない。
merge後、1社だけの短期限ticketを新規発行し、入力・読み戻し・送信前停止を再確認する。
送信テストは別工程であり、この試行から自動的に進まない。

別途UIで、非同期に取得したprofileが入力専用selectの表示に出ても内部未選択のままで、
明示的な再選択が必要な点を観測した。今回の限定修正には混ぜず、未解決の操作上の課題として残す。
