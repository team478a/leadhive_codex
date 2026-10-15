# URL提案の購入者検索語修正

## 問題
サービスを使う購入者を探す際に「美容室 SNS集客」「店舗 Instagram運用支援」などの商品・課題語が付いていた。支援業者・解説記事を検索しやすく、購入者の営業リスト作成と合わない。

## 変更
- 画面で「サービスを使う購入者」（初期値）と「代理店・OEM提携先」を選択。
- 購入者では別の構造化AI出力を使用。具体的な事業をbusiness_keywordsとして受け取り、サーバーで「業種 公式サイト」を作る。課題・購入意欲は検索語に付けず、理由の仮説として記載。
- 代理店では既存search_keywordsを維持。SNS運用代行などの事業を探せる。
- 旧APIクライアントのtarget_mode未指定はautoとして既存形式を維持。
- 選択変更で前の提案を無効化。反映・編集・保存は引き続き人間が操作。
- SSRF・robots・1ページ/AI最大1回・APIキー保護、検索/収集/送信を自動開始しない条件は変更なし。

## 検証と限界
保存済みの問題例に相当する合成出力とモックで検証。実企業ページ・検索API・AI APIは追加利用していない。業種選定自体はAIの仮説であり、公式サイトという検索語でもまとめサイトが完全に消える保証はない。既存の収集除外処理と運用フィードバックを継続する。

既存プロファイルは自動上書きしない。更新後はURLから再提案して内容を確認・保存する。収集結果の精度改善・本番反映は未確認。

## 検証コマンド
- pytest backend/tests/test_target_profile_proposal.py backend/tests/test_profile_proposal.py -q
- ruff check / ruff format --check（変更Pythonファイル）
- mypy backend/app/services/target_profile_proposal.py --follow-imports silent
- python -c "import app.main"
- npm run typecheck / npm run lint / npm run build
- npx playwright test --config operator-guide.config.ts operator-tests/operator-guide.spec.ts

新しい大規模AI基盤・DB変更・本番デプロイは含まない。

## 結果
関連Backend 16件成功、画面24件成功（PC/スマートフォン）。Ruff・format・mypy・API import・Frontend typecheck/lint/build成功。全Backend再実行と実AIの提案品質評価は未実施。CIはPR最終headで別途確認。
