# Phase 3：ライブ評価の承認用計画

状態：未実行・承認待ち。2026-10-09時点。基準main `79d5255db19573ce94143de35d1e986f197fdc83`。オフライン結果は `PHASE3_COLLECTION_PERFORMANCE_REPORT.md` を参照。

## 1. 最初に承認を求める範囲

対象：大阪府・兵庫県のSNS運用代行会社。最終評価目標は各100社だが、初回は少量Pilotで停止する。

固定query（地域文字列だけ変更）：

1. SNS運用代行 会社
2. SNS運用支援 会社
3. Instagram運用代行 会社

**初回収集Pilot：Serperのみ、3query × 2地域 × page1、各10hit要求。最大6 API attempt、Raw最大60hit。retryも6に含める。** 不足時に別query・追加page・Places等を勝手に実行しない。すべての取得結果をRawとして保持し、重複整理後20〜30候補をHuman reviewへ渡す。候補が少なければ実数を報告する。

この段階では実企業サイトGETなし、AIなし、Completionなし。元のSerper organic title/link/snippetとquery/page/timestampを非公開成果物に保持する。検索結果だけで確認できないHuman評価軸はUNREVIEWED/UNCERTAIN。Human labelをAIで代用しない。

## 2. 費用と実行前条件

[Serper公式料金](https://serper.dev/)のStarter表示は50,000 credits/$50、$1/1,000 queries（2026-10-09確認）。既存creditをこの単価で消費すると仮定した場合、6成功queryは**$0.006、税別の参考値**。ユーザーの実契約単価・残高は未確認なので、実費はnull。新規購入の最低Starter支払$50は、6query分の消費額とは別である。

実行前にsecretを表示せず、利用可能なkey、契約単価、残高、requestのcredit条件を確認する。Starterと異なる料金を勝手に仮定しない。[利用条件](https://serper.dev/terms)・第三者情報の保存/使用権を確認し、企業個別データをGitへ公開しない。

提案する費用上限：**API credit消費$1.00以内、かつ6attempt以内**。6attemptでは通常この金額には達しないが、単価/credit条件を確認できない場合は停止する。追加購入・subscription・上限拡大は別承認。インフラ/人手費用は未測定null、0円としない。

## 3. 問い合わせ先・公式サイト確認は別承認

初回Raw Pilot確認後、必要ならHumanが選んだ最大30候補に対して、合計最大300 HTTP GET（1site最大10、robots/redirect含む）を承認対象にする。トップから同一サイトの問い合わせ導線へ辿る。公開URL/IP、安全なredirect、robots、host間隔、timeout、全体budgetを強制する。既存fetcherの1操作内上限だけでは全体300の保証にならないため、評価harness側で全体budgetを検証する準備が必要。

検索API追加0、AI0、入力/POST0、JS操作0、CAPTCHA操作0。外部掲載やSNSへの深掘り・推測大量path・proxy・回避操作なし。拒否/timeout/robots blockは結果として保存し、成功に繰り上げない。問い合わせ存在と技術送信可能と営業許可を別に判定する。このGET stageは初回6requestの承認に含めない。

## 4. 100社目標の比較を行う場合

少量Pilot提出後、再承認が必要。2種類の評価を混ぜない。

### A. 同じRawによる方式比較

同じ3query・2地域・最大5page、合計最大30 API attemptで共有Rawを取得し、全方式に同一入力を渡す案。最大名目300hitであり100社/地域を保証しない。途中のbudget/取得失敗を記録。Source返却のtitle/snippet欠落を防ぎ、ページ未取得はMISSING、provider空レスポンスはEMPTYと区別する。

全方式の候補化・重複・停止・Raw保存を比較する。比較harnessの旧版全経路とfair DB runner接続は未完成であり、別途コード変更承認が必要。投影のみの結果を全体比較と言わない。

### B. 実際の検索スケジュール比較

従来、fair-v1、旧版それぞれ、地域別100社目標・同じquery・空の独立評価状態で実行する案。上限は**各方式×各地域50attempt、全体300attempt**。追加source・追加調査はOFF、MUSTによる想定外追加調査もない条件に固定する。

比較用旧版adapterの実装承認・検証が前提。旧版に上限を付ける場合、その差を記録して「旧版無制限」の性能とは言わない。fairは既定OFFなので評価専用processで有効化し、本番設定を変更しない。num/pageはまず各方式の実装値を記録し、同一num10の対照評価と分離する。retry/recoveryもattempt数に含める。

検索の時間変動を完全には排除できないため、方式実行順を記録・交互化し、Run別入力を保存する。共有Raw比較Aは制御差、独立ライブBは実検索能力と時点変動を含む結果、と分ける。

Starter参考単価なら300成功queryは$0.30税別。AとBを両方行えば最大330attempt、参考$0.33。実単価確認・$1.00消費上限・追加購入禁止のまま、**このFull評価は今回実行しない**。必要なGETも別上限/承認とする。

## 5. 計測と停止

Raw hits、unique候補（domain/企業Human同一性を分離）、適合企業、公式サイト精度、問い合わせ存在率、attempt/成功credit回数、elapsed time、実測費用、停止reason、未取得page/未判定候補を保持する。query/source/method/run/region/commit/input hashも固定する。

Human：実在、SNSサービス提供、公式サイト、営業対象適合、問い合わせ先存在を5軸で確認。未入力・FAIL・UNCERTAINを区別。Evidenceとreview secondsを記録。レビューが終わらなければprecision=null。

全体予算到達、Raw保存失敗、hash不整合、想定外外部request、認証/権限不備、送信系への接続があれば即停止。低い精度を理由に判定を緩めない。

outbound OFFの隔離評価環境とcollection専用processを確認し、SMTP/Form/Codex/Approval生成経路を起動しない。稼働中営業project/workerを使わない。API keyや企業個別情報はprivate保存、公開成果物は集計だけ。

## 6. 次の判断

承認対象はまず「6attemptの検索のみPilot」。その結果を提出して停止する。GET、100社比較、改善実装、PR、マージ、デプロイ、営業送信をまとめて承認されたとは扱わない。
