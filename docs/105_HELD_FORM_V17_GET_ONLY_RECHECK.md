# 保留フォーム2店舗の解析1.7・GETのみ再確認

2026-10-06、基準commit `a39fd3764947e7852b340d713c76306b9875258a`。利用中APIの解析1.7でCecil/PALIOの問い合わせページを取得し、静的解析結果を保存済みの技術保留と比較した。今回アプリのコード変更はない。

## 結果

| 店舗 | 改善を確認できた点 | 現在も止める理由 |
|---|---|---|
| Cecil | 問い合わせ項目・連絡方法・本文を別の項目として認識。本文のconfidenceは0.9 | Contact Form 7の送信経路が未対応。連絡方法のHuman選択が必要。同意欄は必須性未確認 |
| PALIO | 氏名・メール・電話・本文を必須として認識。本文のconfidenceは0.9。マッピングの要確認理由なし | type=buttonの確認操作がJavaScript依存で、確認経路は未検証 |

両店舗とも新しい静的判定は `delivery_supported=false` / `REVIEW_REQUIRED`。以前の「理由の分からない停止」から、送信経路に関する停止理由を明示できる状態になった。PALIOの入力欄認識が改善しても、確認画面が使えるという判定にはならない。

Cecilのmapping_review_reasonは最初の問題である連絡方法を返す。同意欄の「必須性未確認」も別に残っており、連絡方法を選ぶだけでは全問題の解決を意味しない。今回は選択・同意保存を行っていない。

ページ本文の営業禁止ルールは両方ALLOWED、取得したform内の静的CAPTCHA判定はCAPTCHA_NONE。これらは営業利用の許諾や、JavaScript実行後もCAPTCHAがないことの証明ではない。suppression・opt-out・Human承認等の送信条件を満たしたという判定もしない。

## 保存済みの理由との比較

Cecilの保存済み理由は問い合わせ種別の誤マッピング・連絡方法の誤分類と、CF7の入力・同意・送信経路の未検証を記録している。今回、項目の分類改善を確認できたが、CF7経路とHuman確認は残る。

PALIOの保存済み理由は画面上の必須欄の未認識・未マッピングと、JavaScript確認画面の未検証を記録している。今回、必須欄・本文認識は改善を確認できたが、JavaScript確認画面は残る。

両方とも保存済みfingerprintとは不一致。これは過去の保存フィールドと現在の解析フィールドから計算した値の比較であり、実サイトのHTMLが変更された証明ではない。parserの改良でも変わり得る。古い承認を再利用できる根拠にはしない。

## 実施範囲・検証

- SafeFetcherによるrobots.txt確認と問い合わせページのGETのみ。URL安全性チェック・取得上限を維持。外部script実行、ブラウザ入力、確認POST、最終POST、外部AIは実行しない。
- DB transactionをREAD ONLYにして保存profile・fieldと送信数を参照。再解析結果のDB保存、保留解除、承認作成はない。
- 取得・解析完了後に匿名fixtureのruntime検証成功。企業100、FormProfile139、技術保留2、active job0、ApprovedFormDispatch/FormDelivery/EmailDelivery各0。
- outbound / human-approved form / legacy form / agent flagsは全OFF。workerはexitedのまま。
- アプリコード・Migration・UI変更がないため、前工程の121関連テスト・2画面E2Eを再実行したとは扱わない。

[取得・判定集計](results/held-form-v17-get-only-recheck-2026-10-06.json)には公開フォームの項目定義・保留理由のみ記録し、入力値・hidden token・credential・生HTMLは含めない。取得元の文章は判断材料として扱い、実行指示として利用しない。

## 次の工程

CF7とJavaScript確認画面について、匿名fixtureを使った実行経路アダプターの設計を作る。通常経路／支援／Human Required／Blockedの境界、承認後のpayload固定、fingerprint再確認、二重送信とUNKNOWN保護を満たす条件を整理する。今回の確認だけで実サイト操作・自動送信や保留解除へ進まない。
