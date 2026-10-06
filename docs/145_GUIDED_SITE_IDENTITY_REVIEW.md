# 公式サイト・Identity確認の改善

## ゴールと測定根拠

Benchmark後の最初の改善として、登録サイトを持つLeadのHuman照合を進めやすくする。固定100店舗ではIDENTITY_UNCERTAINが43件（BLOCKEDを除いた確認対象42件）で、複数の停止理由が重なる。単独potential_unlockは0であり、このUI改善によるDM READY増加を予測・実証したとは扱わない。

公式サイト未登録57件の再検索や、実店舗のHuman確認を代理で実施する工程は含めない。過去BaselineとBenchmark JSONは変更しない。

## 操作手順

1. Dashboardの固定リストを集計し、Identity確認の理由で作業キューを絞る。対象の企業詳細を開く。
2. 「リスト完成の根拠」→「企業・店舗と公式サイトを確認する」を開く。登録されている名称・住所・電話・サイト候補を比較対象として確認する。
3. Humanが実際に公式ページを確認したときだけ、そのページの名称と番地を含む住所または電話、根拠URL、公開情報を入力する。登録値は観察欄へ自動コピーされない。
4. 「入力内容の照合をプレビュー」で一致・不一致を確認する。プレビューは保存済み情報と入力の比較だけで、公開ページへアクセスしない。プレビューが一致しても確認記録は未保存。
5. 記録可能な一致になったら、公開ページで根拠を確認したチェックを入れ、「照合確認を記録」を押す。
6. 元の固定リストへ戻って再集計する。Identity以外の停止理由、用途確認、DM準備、送信承認は別途必要。

入力を変更するとプレビューと確認チェックが失効する。不一致は登録情報・対象店舗の取り違えを調べ、確認条件を緩めて解消しない。住所・電話が未登録の場合、この照合だけで確認済みにできない。登録情報の訂正にも根拠が必要。

## APIと既存互換性

`GET /api/companies/{id}/lead-completion` に `identity_target`（company_name/address/phone/website_url）を追加。

`POST /api/companies/{id}/site-identity-reviews/preview` は既存確認APIと同じ入力schemaを使用。Human session・owner/editor・Project境界を必要とし、Agent/Bearerは403、viewer/他Projectは404。expected_hash・expected_review_versionが古い場合409。秘密情報付きURL・他ドメイン・private URL・不正な入力は既存基準で422。

返却：comparison、reasons、can_record、review_recorded=false、live_site_checked=false、execution_allowed=false。確認イベント・Approval・Deliveryを作成しない。成功判定を変更せず、保存APIと同じdeterministic比較・URL検証を共有する。

実保存は引き続き既存APIがProjectロック下でhash/version、現在の登録情報、URL、名称＋住所/電話を再検証する。プレビューは承認tokenや権限証明ではない。UIのチェックはHumanへの確認導線であり、既存APIの認証やサーバー側検証の代替ではない。既存API clientのschemaは変更しない。

7日の失効、対象変更によるSTALE、取消とappend-only ledgerは維持。Humanによる同一性確認は営業許可・DM READY・送信承認と区別する。

## 変更範囲と安全

Model・Migration追加なし。稼働DBのupgrade、worker起動、外部GET/検索/AI、実企業の確認保存、承認、メール/Form送信は行わない。outbound OFFを維持。稼働中の旧containerへの配布は別工程で、コードpushだけでは現在の稼働画面に反映されない。

追加検索API/AI費用は0。Humanの確認時間短縮はまだ未測定。これからの作業時間は既存LeadReviewSessionで計測し、実際の結果だけで評価する。

## 品質確認

- Backend：一致・矛盾・情報不足、preview非保存、送信/承認なし、hash/version競合、Agent/viewer/他Project拒否を試験。既存Identity・LeadCompletion・Sendability回帰も確認。
- Frontend：Desktop/Mobileで登録情報表示、観察欄が空、不一致理由、未保存表示、Humanチェック必須、入力変更で失効、記録・取消と送信なしを検証。
- Ruff/format、mypy対象追加、Frontend typecheck/lint/build、GitHub Actionsの全既存検証を使用。

完了後は、この改善を導入した環境でHumanが確認する工程と、別途許可を要する限定的な公式サイト発見検証を次候補とする。100店舗への外部アクセスは自動開始しない。
