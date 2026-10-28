# PyEmuera 3.0.0 Beta 2 開発者向けガイド

このソース用 ZIP には PyEmuera `3.0.0b2` のソースコード、単体テスト、テスト用データ、ビルド用スクリプトが入っています。実行用 ZIP は別です。

バリアントを遊ぶ場合は、実行用 ZIP の `PyEmuera.pyz` と起動用バッチを使います。使い方は実行用 ZIP の `README_ja.txt` と `HOW_TO_USE_ja.txt` を参照してください。

以下のコマンドは、特に断りがなければ、`pyproject.toml` のあるソースのフォルダー（GitHubでcloneした場合も同じ）で実行します。Windows では `python` の代わりに `py -3` も使えます。

## 必要な Python

| 用途 | 必要なバージョン | 確認実績のある環境（例） |
| --- | --- | --- |
| バリアントの実行（`PyEmuera.pyz`、ソースからの実行、インストール版） | 3.10 以上 | Windows 10、Linux x86_64で動作確認 |
| 単体テスト、ビルド・検証用スクリプト | 3.11 以上 | Windows 10のPython 3.12、LinuxのPython 3.13で実行 |
| wheel / sdist の作成、`pip install` | 3.10 以上と、ビルド用ツール（下記） | Pythonのパッケージング環境が必要 |

- バリアントの実行と単体テストには、Python 標準ライブラリ以外のパッケージは使いません。
- 単体テストと一部のスクリプトは `hashlib.file_digest`（3.11 以上）を使います。Python 3.10 で全テストを実行すると、配布用スクリプトのテストがエラーになり、`tomllib` を使うテストはスキップされます。これはテスト用の要件で、バリアントの実行には 3.10 で問題ありません。
- Python 3.15 以降は確認していません。

## ディレクトリ構成

```
./
├─ pyemuera/              エンジン本体（Python パッケージ）
│  ├─ specs/              命令・関数・構文・変数の定義（JSON。実行時に読み込む）
│  └─ resources/          Windows 以外で使う日本語照合データと、その権利表示
├─ tests/                 単体テスト（unittest）
│  └─ fixtures/           テストの期待値と入力データ（本家・.NET Framework の測定結果を含む）
├─ verification/          テストと検証用スクリプトが読む、保存済みの測定結果
│  ├─ r50/native-arraysort/  本家 Emuera で ARRAYSORT を実行したときの原ログ
│  └─ b1/r51_test_ids.json   r51の3,296テストID（削除・改名の検出用）
├─ tools/                 ビルド・テスト・検証用スクリプト（下記）
├─ examples/smoke/        サンプルバリアント（テストでも使用）
├─ packaging/public/      公開ZIPの利用者向け文書・起動用バッチの原稿と、収録ファイルの選定規則
├─ licenses/              第三者のライセンス文書
├─ PyEmuera.pyz           テスト用 pyz（一部のテストが直接実行します）
├─ run_pyemuera.py        ソースから直接起動するためのスクリプト
├─ build_zipapp.py        pyz ビルドの互換スクリプト（tools/build_pyz.py と同じ処理）
├─ pyproject.toml         パッケージ設定（wheel / sdist / pip 用）
├─ README_DEVELOPERS_ja.md  この文書
└─ *.md / SOURCE_AUDIT_*.json  pyz に同梱される文書（下記）
```

主なモジュールの役割は `ARCHITECTURE_ja.md` に説明があります。

## ソースから直接実行する

```console
python run_pyemuera.py "バリアントフォルダー"
python run_pyemuera.py --help
```

`PyEmuera.pyz` と同じオプションが使えます。例：同梱サンプルを入力の再生で最後まで動かす。

```console
python run_pyemuera.py examples/smoke --inputs examples/smoke/replay.txt --no-wait
```

（実行すると `examples/smoke/.pyemuera/` が作られることがあります。）

## 単体テストを実行する

### 全テスト

```console
python tools/run_final_tests_r47.py --pyz PyEmuera.pyz --baseline-ids verification/b1/r51_test_ids.json --out ../test-result/result.json
```

- `--pyz` で指定した pyz からエンジンを読み込んでテストします（ソースの `pyemuera/` は使いません）。ソースを変更した場合は、先に pyz をビルドし（次の章）、そのファイルを `--pyz` に指定してください。なお `test_r35_diagnostics` は、このフォルダーの `PyEmuera.pyz` を直接実行します。ソースを変更したときは、原本を保管した別の開発用コピーで、直下の `PyEmuera.pyz` と `--pyz` の両方を変更後の pyz に揃えてテストしてください。
- `--baseline-ids` の一覧にあるテストIDが一つでも見つからない場合は、実行前に停止します（テストの削除や改名を検出するためです）。
- 結果は `--out` の JSON（全テストID・成否・スキップ理由・失敗の詳細）と、同名の `.log`（詳細なログ）に保存されます。`--out` はこのフォルダーの外を指定することをおすすめします。
- 画面の最後に要約が表示され、`"successful": true` で終了コード 0 なら全件成功です。失敗・エラーが1件でもあれば終了コードは 1 です。
- テストはテストデータを UTF-8 として読みます。runner は Python の UTF-8 モード（環境変数 `PYTHONUTF8=1`）で自分自身を起動し直すため、日本語版 Windows（CP932）でもそのまま実行できます。
- 全テストには数分かかります。途中で `[PyEmuera warning] ...` が多数表示されますが、テストが意図的に起こしている警告です。
- テストの実行中に `examples/smoke/.pyemuera/` などが作られることがあります。

### 一部のテストだけを実行する

ソースの `pyemuera/` を使って、テストファイル単位で実行できます。Windows では、先に Python の UTF-8 モードを有効にしてください（コマンド プロンプト：`set PYTHONUTF8=1`、PowerShell：`$env:PYTHONUTF8=1`）。テストが起動する PyEmuera にも引き継がれるよう、`-X utf8` ではなく環境変数で指定します。

```console
python -m unittest discover -s tests -t tests -p "test_r50_arraysort.py"
python -m unittest discover -s tests -t tests -p "test_r50_*.py" -v
```

Windows のコマンド プロンプトで実行すると、入力処理を検査する一部のテストがキーボード入力を待って止まることがあります。標準入力を空にして実行してください（コマンド プロンプト：末尾に `< nul`、Linux：`< /dev/null`）。全テストの runner は、この処理を自動で行います。

### 単体テスト結果の確認

Beta 2ではWindows・Linuxで全単体テストを実行しています。実行環境によってSKIP数が異なるため、結果のJSONにあるIDごとの結果・理由を確認してください。過去の開発リビジョンの集計を現在の実行結果として扱わないでください。

### 既知の不安定なテスト

割り込み処理を検証する `test_r45_windows_interrupts.WindowsInterruptR45.test_repeated_signal_during_cancellation_preserves_first_receipt` は、実行タイミングによってまれに失敗することがあります。r50・r51の反復試験では、それぞれ300回中2回の失敗を観測しました。SIGINTの配送とスレッド開始の競合が疑われますが、原因は確定しておらず、この版で割り込み処理は改修していません。

該当テストが失敗した場合は、最初の失敗ログを保存してから、対象テストを単独で再実行してください。再実行で成功しても、最初の失敗記録は残してください。対象を単独で実行する例：

```console
python -m unittest discover -s tests -t tests -p "test_r45_windows_interrupts.py" -k test_repeated_signal_during_cancellation_preserves_first_receipt -v
```

これは通常プレイの中断失敗率を示す値ではありません。実利用への影響がないとも断定していません。異なる失敗をこの既知事象にまとめず、最初の結果と再実行結果を分けて記録します。

## pyz をビルドする

```console
python tools/build_pyz.py --out ../build/PyEmuera.pyz
```

- 生成した pyz の SHA-256 が表示されます。
- ファイルの順序・日時・属性・圧縮条件を固定しているため、同じソースと同一のPython・圧縮実装・ビルド設定では同じバイト列の pyz ができます。pyz に自分自身の SHA-256 や生成日時は書き込みません。
- 配布 pyz の SHA-256 は、実行用 ZIP に付属するチェックサムで確認してください。
- 圧縮には Python に組み込まれた zlib を使用します。Python・zlibの実装が違うとZIP全体のSHA-256が変わる場合があります。内容の同一性を調べる場合は、pyzのメンバーごとのハッシュも確認してください。

### pyz に同梱される文書

次のファイルは pyz の中にも入るため、内容を変えると pyz の SHA-256 が変わります。

`LICENSE`、`README_ja.md`、`ARCHITECTURE_ja.md`、`COMPATIBILITY_ja.md`、`SOURCES.md`、`THIRD_PARTY_NOTICES.md`、`THIRD_PARTY_MS_NLS_NOTICE_ja.md`、`SOURCE_AUDIT_1824.json`、`SOURCE_AUDIT_1824_v24.json`、`licenses/` 以下

## 通常の Python パッケージとしてインストールする

仮想環境（venv）へのインストールをおすすめします。

```console
python -m venv ../venv
```

仮想環境を有効にします。

- Windows：`..\venv\Scripts\activate`
- Linux：`source ../venv/bin/activate`

インストールします。

```console
python -m pip install .
pyemuera --version
pyemuera "バリアントフォルダー"
```

- `pip install .` は、ビルド用に setuptools 77 以上を自動で取得するため、インターネット接続が必要です。
- インストールされるのはエンジン（`pyemuera` パッケージ）と `pyemuera` コマンドです。命令定義（`specs/`）と照合データ（`resources/`）も含まれます。

wheel と sdist を作る場合は、ビルド用ツール `build` を使います。

```console
python -m pip install build
python -m build --outdir ../dist
```

`../dist` に `.whl`（wheel）と `.tar.gz`（sdist）ができます。

```console
python -m pip install ../dist/pyemuera_experimental-3.0.0b2-py3-none-any.whl
```

インストールした PyEmuera で、文字列の並べ替えが本家の記録と一致するかを確認できます（インストールした仮想環境の Python で実行します。ソースの `pyemuera/` ではなく、インストールされたものを使って確認します）。

```console
python tools/verify_arraysort_native.py --installed --out ../arraysort-installed
```

## 配布物について

実行用 ZIP とソース用 ZIP は別の配布物です。公開用の `PyEmuera.pyz` をソースから生成した後、次のコマンドで2種類のZIPとSHA-256一覧を生成できます。出力先はソースの外側に指定してください。

```console
python tools/build_release_archives.py --out ../beta2-dist
```

公開用の分割ZIPは `packaging/public/source-files.txt` に列挙されたソースだけを含み、作業ディレクトリの未登録ファイルは取り込みません。

`tools/assemble_public.py` と `packaging/public/selection.json` は、旧来の一体型ZIPを作る互換ツールです。現在の正式な分割配布物には使用しません。

## 補助スクリプト（tools/）

| ファイル | 内容 | 必要な環境 |
| --- | --- | --- |
| `build_pyz.py` | pyz のビルド | Python 3.10 以上 |
| `build_release_archives.py` | 実行用・ソース用ZIPとSHA-256一覧の生成 | Python 3.10 以上 |
| `run_final_tests_r47.py` | 全テストの実行と記録 | Python 3.11 以上 |
| `assemble_public.py` | 公開ZIPの生成 | Python 3.10 以上 |
| `verify_arraysort_native.py` | 文字列 ARRAYSORT を、本家 Emuera の保存済み原ログ（6 条件と 32 条件）と比較 | Python 3.10 以上 |
| `replay_new_framework_r49.py` | 互換照合の比較結果・並べ替えを、保存済みの .NET Framework 測定結果と比較 | Python 3.10 以上 |
| `*.cs` | .NET Framework / Windows の比較・並べ替えを測定するプログラム（期待値の作成に使ったもの） | Windows、.NET Framework 4.8 の `csc.exe` |
| そのほかの `.py` | テストが読み込む補助モジュール（過去の検証で使った比較・梱包処理） | テストから使用 |

```console
python tools/verify_arraysort_native.py --pyz PyEmuera.pyz --out ../arraysort-check
python tools/replay_new_framework_r49.py --out ../collation-replay.json
```

- `verify_arraysort_native.py` は、既定の照合（Windows では OS、それ以外では互換実装）と、互換実装を強制した場合の両方を実行し、`summary.json` に実行した OS を記録します。Windows で互換実装を強制した結果は、Linux での実行結果の代わりにはなりません。
- `replay_new_framework_r49.py` は互換実装を使います。結果と終了コードは実行した版の記録で確認してください。比較結果の記録では、実行した版とfixtureを必ず明示してください。
- `.cs` の測定プログラムは、ビルドやテストには必要ありません。各ファイル冒頭のコメントにコンパイル方法があります。生成した実行ファイルは配布していません。

## 互換性の検証方針

- 参照対象は Emuera1824+v24 です。期待値は、本家ソースの読み取り、本家 Emuera の実行結果、.NET Framework の実測から作り、種類を区別して扱います（`COMPATIBILITY_ja.md`）。
- 期待値をエンジンの出力から作り直すことはしません。互換性の修正では、本家の実測と推定モデルを区別し、根拠となる資料を `SOURCES.md` に記録します。
- 本家と異なる挙動を意図的に選んだ箇所や、未対応の機能は、成功を装わずにエラーとして扱います。
- テストの成功は、すべてのバリアントでの互換性を意味しません。

## 既知の制限

- 文字列の照合は、Windows では OS の NLS API（`CompareStringEx`）を、それ以外では互換実装（`pyemuera/collation_portable.py`、`collation_jamo.py`）を使います。固定した Windows 10、ja-JP、NLS 0x60305 の Jamo 比較 36,864 方向では、互換実装と保存された .NET Framework の測定結果が 36,864/36,864 で一致しました。この測定範囲外や他の Windows・NLS 環境での完全互換は保証しません。比較の一致は全ての並べ替え結果の一致を意味しません。
- 利用者が照合方式を切り替える設定はありません。
- Windows環境で、IMEを使った日本語入力、およびWindows Terminal（ConPTY）上での入力・中断が正常に動作することを確認しています。すべてのIME製品・バージョン・設定の組み合わせを網羅したものではありません。
- macOSでの動作は確認していません。
- 時刻取得処理は固定時計、日付・秒境界、結果書き込み順序を試験しています。`test_r40_flow_commands.R40FlowCommands.test_gettime_component_boundary_and_write_order` と `test_gettime_result_write_failure_prevents_eighth_sample` が対応する試験です。`GETTIMES()`の書式は `test_source_functions_a7.SourceFunctionsA7.test_gettimes_shape` で確認します。本家とPyEmueraの実時計を同期させたすべての境界での厳密な値比較を確認したものではありません（`COMPATIBILITY_ja.md`）。

## 検証用メタデータを生成する

`tools/build_release_status.py --tests 結果.json --out ../CAPABILITIES.json` で現行ソースと実行結果からメタデータを生成します。複数環境の結果には `--tests` を繰り返します。受入後に `--beta-accepted` を指定できます。これはリリースの検証メタデータで、過去版の `CAPABILITIES.json` や歴史的な監査・ゲート記録を現行結果として流用しません。β受入の判定は公開操作が済んだことを意味しません。

## ファイル名の rNN / aN について

テスト・ツール・テストデータのファイル名にある `r43`、`a8` などは、その機能や測定を追加した開発段階の番号です。テストIDの互換性を保つため、名前は変更していません。`Oracle` は本家や .NET Framework で測定した期待値、`Holdout` は照合モデルの調整に使わずに後から評価した測定集合を指します。

## 出典とライセンス

- PyEmuera 本体は MIT License（`LICENSE`）です。
- 第三者の権利表示はソースの `THIRD_PARTY_NOTICES.md` と実行用 ZIP の `THIRD_PARTY_NOTICES.txt` にあります。
- `tests/fixtures/r44_native_diagnostics/` には、テストで原文と照合するため、Emuera のソースファイル 5 点を改変せずに収録しています。これらは PyEmuera の MIT License ではなく、Emuera のライセンス（`licenses/Emuera1824.txt`）に従います。
- 照合データ（`pyemuera/resources/`）は Microsoft の公開データを元にしています（`THIRD_PARTY_MS_NLS_NOTICE_ja.md`）。生成に使ったスクリプトはこの配布物に含まれていないため、配布物だけから照合データを作り直すことはできません。
- 参照した資料は `SOURCES.md` にあります。テストデータにバリアント本体やバリアントの文章は含まれていません。
