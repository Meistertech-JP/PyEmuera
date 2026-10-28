# Post-Beta 1 Framework 比較データの生成

小規模fixtureと今回追加した検証スクリプトのSHA-256は `tools/POST_B1_SHA256.txt` に収録する。各行はSHA-256とリポジトリルートからの相対パスであり、実行前に確認できる。

保存済みr49の36,864方向をソース版portable実装で再集計し、不一致行のUTF-16単位・Jamo属性・分岐と要約を保存する場合は次を実行する。入力fixtureのSHAを検証し、出力先の上書きを拒否する。既知不一致の個数は要約に記録され、それだけでは失敗終了しない。`--repo` は評価したいソースツリーを明示するための指定であり、pyzの検証ではない。

```powershell
python tools/replay_post_b1_baseline.py --repo . --out <新しい出力ディレクトリ>
```

`post_b1_pairs_inventory.py` は公開ソースの `tests/fixtures` と `verification` から対応済み形式の比較ペアを集める。`--include-local-records` を指定した場合だけ、任意の隣接ディレクトリ `post-b1-jamo-records/oracle` も読み込む。封印中のデータを探索しないよう、名前に `holdout` を含むファイル・ディレクトリは除外する。未対応形式や比較呼び出しを記録していないソートデータ、封印された集合との非重複は保証できない。索引と manifest の対応範囲・未解決項目を確認すること。

索引には、r43・r44・r45 の指定ソート計画、r50 の受領済み6ケースと公開 native-sort 計画について、各入力配列内の全ペアも保守的な除外対象として加える。計画中の範囲外 sentinel も含む。これらは実際の比較呼び出しを観測したという意味ではなく、未実測の計画も含む。また `tests/test_r47_compatibility.py` の確認済み1ペアを追加し、そのテストソースも manifest に記録する。未対応のテストや他の公開資料・過去の全入力を網羅した保証ではない。入力の不整合や欠落は未解決項目として記録する。

Windows の .NET Framework compiler を用いた例（出力先は存在しないこと）:

```powershell
python tools/post_b1_pairs_inventory.py --output <新しい索引ディレクトリ>
python tools/post_b1_oracle_generate_indexed.py --output <新しい出力ディレクトリ> --development-seed 12345 --holdout-seed 67890 --count 1500 --csc C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
```

既に凍結した索引を使う場合は、生成コマンドに `--index <pairs.tsv>` と `--inventory-manifest <inventory.json>` を両方指定する。開発集合と最終holdoutは別seedで生成し、最終holdoutは測定後に封印する。封印は誤操作防止のための運用上の境界であり、アクセス制御ではない。最終検証前のモデル調整にholdoutを使わない。seedからも入力を再生成できるため、封印中の再生成は行わない。

入力はUTF-16LEコード単位のhex、比較値はFramework `CompareTo`、`CompareInfo.Compare` と Windows `CompareStringEx` の符号、キーは `GetSortKey` のバイト列。実測値の再現には同じ Framework と NLS プロファイルが必要で、異なる環境の結果がバイト一致する保証はない。出力には実行環境とローカルcompilerパスが含まれるため、公開する際は私的情報の混入を確認する。

このツールの標準動作は公開ソースから再実行できるよう、ローカル検証資料の索引への追加を任意にした。2026-10-28に作成した拡張索引は旧動作でローカル資料も含んでいるため、同じ入力集合を再現するには当時凍結した索引と manifest が必要となる。新しい索引を作って同じ結果になるとは限らない。

同梱の小規模開発fixtureについては、原データの大きなローカル記録がなくても次のコマンドで各比較をFrameworkに再照会できる。新しい出力先に入力・計画・生測定・集計を保存し、NLSプロファイルと3種類の直接比較符号を照合する。sort keyは同時に保存するが直接比較の代用にはしない。

`framework_independent_development_comparisons.json` は開発用seed `2026102813` の測定から現行portableと一致する15組を選択し、正逆30方向を保存した。選別済みのため母集団の一致率を表さない。`framework_separator_regression_controls.json` は、候補条件の選択後にseed `202610281947` で作ったストレス測定5,000組から、その候補によって退行した8組を選び、正逆16方向を保存した。こちらもholdoutではない。各fixtureには元の測定JSONのSHAと行番号を記録している。異なる測定集合・公開資料の未対応形式との完全な非重複は確認していない。

`framework_inline_candidate_regressions.json` は別の棄却候補が壊したストレス測定例から、6組・正逆12方向を選んだ開発用制御である。`framework_decisive_jamo_development.json` は今回の限定修正による改善と既存一致の境界から11組・正逆22方向を選んだ。いずれも選別された例であり、代表的な一致率やholdoutを示さない。検証ツールは4つのfixture、合計80方向を再測定する。

```powershell
python tools/verify_post_b1_framework_fixtures.py --csc C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe --output <新しい出力ディレクトリ>
```

出力ディレクトリが既に存在する場合、再測定を始めずにエラー終了する。検証済みの測定記録を保持するため、実行のたびに別の出力先を指定する。
