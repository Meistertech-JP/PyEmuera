# GitHub のソースから PyEmuera を実行・検証する

[日本語 README](README.md) / [English README](README_en.md)

この文書は PyEmuera **3.0.0 Beta 1（`3.0.0b1`）** のリポジトリ直下から作業するための補足です。配布 ZIP の `source/` の中身が、GitHub では直下にあります。以下のコマンドは、`pyproject.toml` と `run_pyemuera.py` があるディレクトリで実行してください。`cd source` は不要です。

[既存の開発者ガイド](README_DEVELOPERS_ja.md)にある「一つ上のフォルダー」は配布 ZIP の配置を指します。clone の親ディレクトリに配布用バッチやサンプルがあるという意味ではありません。既存ガイドは公開 ZIP のビルド入力でもあるため、その内容を維持しています。

## 環境と配置

- ゲーム実行は Python 3.10 以上と、文字表示・入力が可能なターミナルが必要です。全単体テストと検証作業には Python 3.11 以上を使用してください。一部の試験は `hashlib.file_digest` や `tomllib` を使います。
- エンジンと単体テストは標準ライブラリのみを使います。wheel / sdist の作成には `build` と setuptools 77 以上が別途必要です。
- Windows 10 と Linux に測定履歴があります。r51 の OS・Python 別成績は開発版の履歴であり、Beta 1 の全環境再試験結果ではありません。Windows 11 は動作対象ですが、十分な実機検証は未完了です。Python 3.15 以降は未確認です。
- macOS・Android（Termux など）でも Python 3.10 以上と適切なターミナルがあれば動作する可能性がありますが、実機未検証です。標準ライブラリのみの実装でも、プラットフォーム固有の入力処理・端末制御には制限があり得るため、起動・入出力・互換性は保証しません。Termux は Android 上の実行環境の例であり、PyEmuera は Android ネイティブアプリではありません。動作報告は [GitHub Issues](https://github.com/Meistertech-JP/PyEmuera/issues) へ、Python のバージョン、ターミナル、入力・表示状況を添えてお寄せください。
- `python` は用途に合う Python を指すものとします。Linux 等では必要に応じて `python3` に読み替えてください。原バイト再現には後述の固定環境が必要です。

| リポジトリ内の場所 | 用途 |
| --- | --- |
| [run_pyemuera.py](run_pyemuera.py)、[pyemuera/](pyemuera/) | ソース直接実行とエンジン本体 |
| [PyEmuera.pyz](PyEmuera.pyz) | 収録済みの Beta 1 エンジン。一部のテストも直接使用 |
| [examples/smoke/](examples/smoke/) | リポジトリ用サンプル。配布 ZIP では `sample/` にも配置 |
| [tests/](tests/)、[verification/](verification/) | 単体テスト、fixture、保存済みの比較データ |
| [tools/](tools/) | テスト runner、ビルド・検証用スクリプト |
| [packaging/public/](packaging/public/) | 配布 ZIP の文書・バッチ原稿と選定規則 |
| [pyproject.toml](pyproject.toml) | インストール・wheel・sdist の設定 |

## ソース実行・サンプル・静的チェック

```console
python run_pyemuera.py --version
python run_pyemuera.py --help
python run_pyemuera.py "バリアントフォルダー"
python run_pyemuera.py examples/smoke --inputs examples/smoke/replay.txt --no-wait
python run_pyemuera.py examples/smoke --check
python run_pyemuera.py "バリアントフォルダー" --check --report ../check-result-01.json
```

`--check` はゲームを開始せず、読み込み・登録・宣言を検査します。問題なしは終了コード 0、問題ありは 2 です。全経路の動作確認にはなりません。レポートには未使用の出力名を使ってください。相対パスはコマンドの実行ディレクトリが基準です。

サンプルやテストの実行により、`examples/smoke/.pyemuera/` や Python のキャッシュ等が作られることがあります。バリアントの保存先と診断オプションは[既存 README](README_ja.md)にあります。

## 収録済み pyz で全単体テストを実行する

リポジトリ直下には `PyEmuera.pyz` が収録されています。無変更の Beta 1 を検証するときは、このファイルをそのまま使います。事前に再ビルドしたり上書きしたりする必要はありません。

```console
python tools/run_final_tests_r47.py --pyz PyEmuera.pyz --baseline-ids verification/b1/r51_test_ids.json --out ../test-result-01/result.json
```

[runner](tools/run_final_tests_r47.py) は指定 pyz からエンジンを読み込み、既存の[基準テストID一覧](verification/b1/r51_test_ids.json)の欠落を検出します。UTF-8 モードを子プロセスにも適用し、標準入力を空にしてキーボード入力待ちを防ぎます。JSON と同名の `.log` に、全ID・成否・スキップ理由・失敗詳細を保存します。終了コード 0 と `successful: true` を確認し、FAIL / ERROR / SKIP の内訳も読んでください。出力は実行ごとに別ディレクトリへ保存します。

**ソースを変更した場合、収録済み pyz の成功は変更後ソースの検証にはなりません。** また、`test_r35_diagnostics` は `--pyz` の指定に加えてリポジトリ直下の `PyEmuera.pyz` を直接実行します。変更版の全テストは、原本を保管した別の開発用コピーで、直下の pyz と `--pyz` の両方を変更版に揃えて実施してください。

ソース側の一部テストを実行する例（PowerShell）：

```powershell
$env:PYTHONUTF8 = '1'
python -m unittest discover -s tests -t tests -p "test_r50_arraysort.py" -v
```

Linux では `PYTHONUTF8=1 python -m unittest discover -s tests -t tests -p "test_r50_arraysort.py" -v` と実行できます。入力処理を含む試験には全テスト runner の使用を推奨します。

割り込み処理の `test_r45_windows_interrupts.WindowsInterruptR45.test_repeated_signal_during_cancellation_preserves_first_receipt` には断続的な失敗の履歴があります。最初の失敗ログを保存し、再実行結果とは分けて記録してください。別の失敗をこの既知事象として扱わないでください。詳細は[既存の開発者ガイド](README_DEVELOPERS_ja.md)にあります。

## Beta 1 の pyz と公開 ZIP を原バイトで再現する

固定ビルド環境は **Windows / Python 3.12.10 / zlib 1.3.1 / ZIP DEFLATE レベル 9** です。`python` がこの環境を指していることを確認します。

```console
python -c "import sys,zlib; print(sys.version); print('zlib build:',zlib.ZLIB_VERSION,'runtime:',zlib.ZLIB_RUNTIME_VERSION)"
```

[pyz ビルダー](tools/build_pyz.py)はメンバー順・日時・属性・圧縮設定を固定します。[公開 ZIP 生成スクリプト](tools/assemble_public.py)は[選定規則](packaging/public/selection.json)に従ってファイルを選び、pyz の全メンバー内容がソースと一致するか確認します。出力先はリポジトリ外に置きます。特に `assemble_public.py --out` は**まだ存在しないディレクトリ**を指定する必要があります。

```console
python tools/build_pyz.py --out ../b1-rebuild-01/PyEmuera-3.0.0b1.pyz
python tools/assemble_public.py --pyz ../b1-rebuild-01/PyEmuera-3.0.0b1.pyz --out ../b1-public-01
```

これで再生成するのは別出力です。収録済みの `PyEmuera.pyz` はそのまま保持できます。`build_zipapp.py` は同じ pyz ビルダーを呼ぶ互換入口です。

収録済み pyz を使用して公開 ZIP だけを再生成する場合は、別の未使用ディレクトリを指定します。公開 ZIP 自体の圧縮にも同じ固定環境が必要です。

```console
python tools/assemble_public.py --pyz PyEmuera.pyz --out ../b1-public-from-bundled-01
```

照合する原本の SHA-256：

| ファイル | SHA-256 |
| --- | --- |
| `PyEmuera-3.0.0b1.pyz`（収録名 `PyEmuera.pyz` も同じ内容） | `305fcf27c723b9ca155ac087928f993eb32b141288fee689b0a621c0f337f1a7` |
| `PyEmuera-3.0.0b1.zip` | `df2f302490b638a6f7e74313bc40f98d36dfe7e0515e202f26deae7d5bc319a3` |

PowerShell での確認例：

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath PyEmuera.pyz
Get-FileHash -Algorithm SHA256 -LiteralPath ../b1-rebuild-01/PyEmuera-3.0.0b1.pyz
Get-FileHash -Algorithm SHA256 -LiteralPath ../b1-public-01/PyEmuera-3.0.0b1.zip
```

別の Python・zlib（zlib-ng を含む）では、展開内容が同一でも圧縮後の SHA が変わることがあります。環境情報とメンバー内容の比較を記録してください。固定環境で不一致なら、原因を確認するまで原本との一致を主張しないでください。

`README_ja.md` はパッケージ設定・公開 ZIP 選定・pyz への収録に使います。改名や編集は成果物を変えます。`README_DEVELOPERS_ja.md` も公開 ZIP の選定対象です。一方、追加した `README.md`、`README_en.md`、この補足文書は、既存の pyz 収録一覧・公開 ZIP 選定規則に含まれていません。規則を変更せずにビルドすれば、これら3文書は pyz と公開 ZIP に混入しません。

## wheel / sdist と通常インストール

次は開発用仮想環境で実行する例です。PowerShell では、リポジトリ直下から：

```powershell
python -m venv ../pyemuera-venv
& ../pyemuera-venv/Scripts/python.exe -m pip install build "setuptools>=77"
& ../pyemuera-venv/Scripts/python.exe -m build --outdir ../python-dist-01
& ../pyemuera-venv/Scripts/python.exe -m pip install ../python-dist-01/pyemuera_experimental-3.0.0b1-py3-none-any.whl
& ../pyemuera-venv/Scripts/pyemuera.exe --version
```

Linux では：

```console
python -m venv ../pyemuera-venv
../pyemuera-venv/bin/python -m pip install build "setuptools>=77"
../pyemuera-venv/bin/python -m build --outdir ../python-dist-01
../pyemuera-venv/bin/python -m pip install ../python-dist-01/pyemuera_experimental-3.0.0b1-py3-none-any.whl
../pyemuera-venv/bin/pyemuera --version
```

`python-dist-01` に wheel（`.whl`）と sdist（`.tar.gz`）が作られます。ソースから通常インストールする場合は、仮想環境の Python で `python -m pip install .` を実行します。ビルド用パッケージの取得にはインターネット接続が必要です。setuptools のビルドで作られる `build/` や `*.egg-info/` 等は作業用生成物です。原本を保全したい場合は別の作業コピーで実施してください。

インストール版を使用する照合確認は、同じ仮想環境の Python で次を実行します。

```console
python tools/verify_arraysort_native.py --installed --out ../arraysort-installed-01
```

上の `python` は仮想環境の Python のパスに読み替えてください。wheel / sdist は公開配布 ZIP とは別の成果物で、この文書ではパッケージアーカイブの SHA 一致は定義していません。

## 互換性と報告

全単体テストの成功、保存済みの本家測定との比較、実ゲームの確認履歴は、それぞれ確認範囲が異なります。6バリアントの履歴を Beta 1 での全経路再試験として扱わず、[互換性資料](COMPATIBILITY_ja.md)の範囲を参照してください。Windows 以外の古ハングル／Jamo 照合差分、実時計の厳密比較の未完了などは[既知の制限](packaging/public/KNOWN_ISSUES_ja.txt)にあります。

不具合は [GitHub Issues](https://github.com/Meistertech-JP/PyEmuera/issues) へ、環境・再現手順・期待値・実際の結果を記載してください。私的ログ、認証情報、個人情報、ゲーム本文、許可のないバリアント本体やセーブを添付しないでください。[使い方ガイドの10章](packaging/public/HOW_TO_USE_ja.txt)に共有前の確認事項があります。

本体は [MIT License](LICENSE) です。第三者資料は[第三者の権利表示](THIRD_PARTY_NOTICES.md)、[Microsoft NLS データの条件](THIRD_PARTY_MS_NLS_NOTICE_ja.md)、[ライセンス原文](licenses/)に従います。[参照資料](SOURCES.md)と[アーキテクチャ](ARCHITECTURE_ja.md)も参照してください。
