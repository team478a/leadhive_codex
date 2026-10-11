# ブラウザ入力専用モード

## 目的と範囲

main `caae88446d9c177419d30064f9ba18a4acc42f84` を基準に、既存 Playwright PoC に入力専用モードを追加する。保存HTMLでは外部リソース要求を全遮断するため入力前に停止したケースを受け、描画と入力の通信境界を分けて検証する。

これは localhost の所有する模擬フォーム限定の実装である。実サイトURLを渡すと既存の loopback 検証で拒否する。本番UI、worker、Human Approval、Delivery へ接続しない。既存の保存HTML runner は変更しない。

## 操作

`frontend/form-lab/browser-poc.ts` の既存 `runPoc` に末尾の `inputOnly` 引数を追加。既定 false は従来の模擬確認画面テストを維持する。

入力専用モードでは以下を行う。

1. 新規・未認証のブラウザcontextで、登録済みlocalhostの robots・利用条件・フォームを取得する。
2. JavaScript描画に必要な模擬scriptを、シナリオごとの明示的GET許可リストから読み込む。リダイレクトは追従せず、POSTと未登録URLは常に拒否する。
3. 営業NG、CAPTCHA、フォーム・入力欄の曖昧さ、必須値・選択肢・同意を確認する。値や同意を推測しない。
4. 入力前に通信を全面停止する。登録済みURLへのGETも拒否し、自動保存や暗黙送信を防ぐ。WebSocketも接続前に閉じる。
5. 明示された値を入力し、各操作後に営業NG・CAPTCHA・フォーム構造・通信違反を再確認する。
6. ボタンを押さずにブラウザの入力値と妥当性を読み戻す。確認画面への遷移も行わない。
7. contextを閉じ、理由・hash・操作数・時間を記録する。

`FIXTURE_INPUT_VERIFIED` / `inputReadbackVerified=true` は模擬フォームでの入力・読み戻しを表す。`executionAllowed=false`、`salesAuthorization=UNKNOWN` を維持し、承認や送信許可を発行しない。

## 検証方法

```powershell
cd frontend
npm run test:form-browser-poc -- input-only.spec.ts
npm run test:form-browser-poc
npm run typecheck
npm run lint
npm run build
```

新規テストは desktop/mobile で以下を検証する。

- HTML、動的生成、確認画面付き、iframe、必須選択、明示同意、外部scriptで生成される7種類の模擬入力欄。
- 営業NG・入力後に現れる営業NG・CAPTCHA・構造変更で停止。
- 自動POST保存・同一URLへの自動GET・入力イベントによるform.submitを通信前に拒否。
- 必須値不明、password、無効なメール、未確認同意を停止。
- 通信凍結後のGET/WebSocketを拒否。

成功テストでも確認・送信クリックなし、模擬サーバーのPOST受信0を検証する。実行結果は既存CIの form-browser-poc job に含まれ、秘密情報やAI APIを必要としない。

## 実運用へ残る範囲

実サイトへの入力成功は未検証。この変更だけでクラウドUIから実企業フォームへ入力できる状態にはならない。

次工程は実サイト用の入力専用connectorを設計・実装し、限定した対象で入力前停止と通信遮断を確認すること。公開IP・DNS再検証、サイト別robotsと利用条件、リダイレクト、第三者script・iframeの取得範囲、動的な営業NG表示、フォーム用途と同意内容を検証する必要がある。模擬利用条件や単純な営業NG正規表現を本番の判定基盤として流用しない。

入力イベントだけで外部送信するサイトは、通信凍結により停止する。通信が必要だからといって入力中のPOSTやGETを許可するfallbackは追加しない。既存の承認・実送信経路への接続、CAPTCHA回避、実企業への送信は今回の対象外。

## ローカル検証結果（2026-10-11）

- 回帰テスト全体：102 PASS。その後、操作方式をhashへbindする変更と2ケースを追加し、影響するブラウザpreview・入力専用テスト84 PASSを確認。
- 入力専用テスト：40ケース（20 × desktop/mobile）。7種類 × 2画面で入力・読み戻しを確認し、残りは停止制御・hash境界の検証。
- TypeScript typecheck、ESLint、production build：PASS。buildに既存のbundleサイズ警告あり。
- 新規依存、DB変更、Migration、Production deployment、実企業へのアクセス・入力・送信：なし。

CI結果はPRのchecksを正本とする。本書のローカルPASSをGitHub Actions成功として扱わない。
