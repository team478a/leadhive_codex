# フォーム一覧から次の確認作業を案内

基準 `6c8d38755697369153a85a10d74b086de55e3d21`。
Branch `codex/form-readiness-next-actions`。開始時PR #15はOPEN/CI一部実行中だったため、この変更はPR #15と独立して既存のフォーム集計画面へ追加した。企業詳細内の案内はPR #15を参照。

## 動作

企業一覧の「フォーム候補の集計」に、既存のcategoryと連絡制御statusから「次にすること」を表示する。

- 連絡制御PROHIBITED: 分類がcandidateでも、禁止・Suppression・配信停止の理由確認を最優先。送信へ進めないことを明記。
- ALLOWED以外の未確定status: 連絡制御の理由確認を先に案内。候補表示を営業許可へ繰り上げない。
- ALLOWED: 未解析/必須mapping/CAPTCHA/確認画面/変更検出/取得失敗/フォーム未検出/旧解析の各分類に応じて、既存の企業詳細で確認する内容を示す。
- categoryの営業禁止・連絡禁止も、他項目の修正で解除できる扱いにしない。
- 不明な分類は安全に詳細確認へ案内。送信準備完了と推測しない。
- 読込中と表示範囲に該当なしを区別して表示する。

判定・件数・category・権限を変更する機能ではない。説明を読む/絞り込むことはHumanレビュー完了・送信承認ではない。既存の詳細ボタン、保存・Human記録、送信前のCore safety確認を維持する。CAPTCHAはHuman Requiredであり、Codex支援等の回避対象にしない。

## 検証

Frontend typecheck/lint/build成功。Desktop/Mobileの既存form-readiness E2E 2件成功。禁止の連絡制御がcandidate分類より優先、未確定連絡制御、CAPTCHA/確認画面/未検出/禁止、不明category、空ページ/ページ遷移、API書込0、モバイル横幅を確認した。

専用test DB・合成fixtureのみ使用。実データ/実サイト/有料API/AI/実承認/送信を使用していない。API/Backend/Model/Migration/dependencyに変更なし。ビルドの既存bundle size警告は残る。

## 互換性・次工程

PR #15と変更ファイルが異なり、どちらも既存画面の表示改善。新しい取得・自動解析・レビュー確定・承認・送信を接続しない。GitHub全体CIは提出PRで確認する。自動merge/deployを行わない。

次は既存Humanレビューを実データで実施する工程と、新規Raw収集の適合率を測る工程を区別して判断する。表示の改善だけで未確認データが正解/READYになったとは扱わない。
