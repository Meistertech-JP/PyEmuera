# 文字列比較の検証ツール

固定された .NET Framework の比較結果を使い、portable 照合実装を検証できます。期待値は実行環境の Windows、Framework、ja-JP および NLS のバージョンに依存します。別環境で同じ結果になる保証はありません。テスト用データとスクリプトの SHA-256 は `tools/POST_B1_SHA256.txt` にあります。

## 保存済みデータの再生

次のコマンドは保存済みの36,864方向についてソースの portable 実装を評価します。Git の履歴を参照するため、Git checkout で実行してください。ソース ZIP の展開先では実行できません。出力先には存在しないディレクトリを指定します。これは pyz の検証ではありません。

```powershell
python tools/replay_post_b1_baseline.py --repo . --out <新しい出力ディレクトリ>
```

## Windows での測定

次のコマンドは同梱 fixture の80方向を .NET Framework で再測定します。これらは選別された回帰例であり、一般的な一致率を示すものではありません。出力先は実行ごとに新しいディレクトリを指定してください。

```powershell
python tools/verify_post_b1_framework_fixtures.py --csc C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe --output <新しい出力ディレクトリ>
```

`post_b1_pairs_inventory.py` と `post_b1_oracle_generate_indexed.py` は入力集合の索引と測定データの生成に使用できます。各スクリプトの `--help` に引数を示します。入力は UTF-16LE コード単位、直接比較の結果は符号で記録されます。単独の SortKey と直接比較の結果は別の情報です。測定結果には実行環境の情報が含まれるため、共有前に内容を確認してください。
