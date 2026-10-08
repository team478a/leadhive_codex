# Raw Human確認への引き渡し

実施日：2026-10-08。ブランチ：`codex/integration`、HEAD：`cf419fe04278728fccc012dad3018097f2476234`。165〜166の変更は未commit。

## 完了したこと

166で取得済みの検索結果を、localhost:18985の既存Raw確認機能へ取り込んだ。新規検索や外部GETは実行していない。大阪府20件・兵庫県20件の2リスト、計40 Raw Snapshotを保存。保存候補上限で採用しなかった10検索結果も含め、検索結果の誤りを隠さない。

これは、166の「保存候補30件・独立26ドメイン」と異なる集計範囲。Raw確認側のFoundは40で、30や26をそのまま分母にしない。地域別の同一Raw観測キーは各20。これは会社・店舗の同一性確定や地域横断の独立企業数ではない。

新規の非稼働TargetProfile・draft Project・RawBenchmarkを地域ごとに用意し、既存収集検証Projectの利用者へ所属させた。RawBenchmarkは通常営業・補完操作から既存Project guardで分離される。既存Projectの所有者・権限・企業・営業履歴は変更しない。

## Snapshotと集計の扱い

- 原本はprivateの`dist/provider-role-pilot-20261008T013912Z/raw-*.json`。4ファイルのSHA-256を取込前に検証。
- ページ1・2を各地域1つのRunへまとめ、requested_count20、COMPLETEDとして保存。反復検索と誤認しないよう`raw-pages-import-v1`を用い、既存の反復実行条件と一致しない。
- source、query、region、取得日時、元ページ番号、元ファイルhashを保持。URLの認証情報・query・fragmentは除去。
- snapshot_hashは取込payloadから計算し、元Source payloadのhash・原本ファイルhashは別に保持。DBへの取込hashを元ファイルhashと同一と偽らない。
- Raw住所・電話・メールは空のまま。後から確認した本文をRaw値へ補完しない。
- 公開ページ確認資料は別のprivate HTML/JSONに維持し、Raw正解ラベルや公式Identityへ変換しない。
- 取込はユーザー依頼による管理処理。モデルのcreated_by_user_idは既存所有者を参照するが、Humanレビュー・セッション・再認証・Human送信承認を代行した記録ではない。

## 検証

既存Raw reportで各地域Found20・Reviewed0・Strict Precision=nullを確認。所有者のRaw Projectアクセス境界を確認。Snapshot40件のpayloadと保存hashが一致。2回目の取込は追加Benchmark0・Snapshot0で、二重作成なし。

初回の許可した変更はProject2、TargetProfile2、RawBenchmark2、RawQueryRun2、RawLeadSnapshot40のみ。companies / operation_jobs / raw_lead_reviews / raw_review_sessions / raw_pair_reviews / form_profiles / approval_requests / email_deliveries / form_deliveriesの件数変更なし。

Web health200、画面proxy経由の未認証Raw一覧は401。実ユーザーのsession/cookieをAgent認証へ転用せず、ログインやHumanレビューを代行していない。新規Model・Migration・API・UI変更なし。既存UIの回帰結果は165に記載したものを参照し、今回の実ユーザーによる確認操作を実行済みとは扱わない。

## 操作

1. `http://localhost:18985/#raw`を開き、既存ユーザーでログイン。
2. 「検索条件・詳しい集計を見る」を開き、Raw Benchmarkで大阪府または兵庫県の「SNS関連事業者（ハッシーOEM候補・Human未確認）」を選択。
3. 公開ページを確認し、外部のお客様向けのSNS関連サービスを提供しているか、対象地域に一致するか、対象が実在・営業中かを判断。
4. 根拠と判定を記録。不明なら「判断不能」や「保存せず後で確認」を使う。検索語・地域名・提供文脈だけで正解にしない。
5. 精度は記録されたHuman結果のみから集計。地域横断の同じ対象は独立企業として水増しせず、別Project間の同一性は自動確定しない。

private確認資料：`dist/provider-role-pilot-20261008T013912Z/候補確認資料.html`。この資料は前工程の26保存ドメインのみで、全40検索結果に根拠があるわけではない。

## 停止点

Human reviewed0。Precision、地域・業種の誤り率、Human作業時間は未測定。ここから必要なのは人による正解判定であり、AIの推定をHuman Truthへ変換して続行しない。Full Benchmark・新規検索・送信・承認を開始しない。今回の追加API費用なし（API呼出し0）；前工程の検索料金が0円という意味ではない。outbound OFF、送信用worker起動なし。
