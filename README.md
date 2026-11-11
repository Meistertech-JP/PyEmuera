# PyEmuera（ぱみゅーら）

**PyEmuera 3.0.0（`3.0.0`）** · [English](README_en.md)

PyEmuera は、Emuera 用のバリアント（ERB・ERH・CSV で作られたゲーム）を、文字だけのターミナルで動かす Python 製の独立した互換エンジンです。バリアントのゲームファイルは原則として変更せずに読み込みます。

Emuera 専用バリアントが動く eramaker のようなものと考えてください。互換性の参照対象は **Emuera1824+v24** です。本家の公式版ではありません。

画像・音声・マウス操作・本家GUIのフォント描画はサポートしていません。

## どうしてPythonで？

本家EmueraはWindowsを中心に発展してきたため、Windows以外の環境で動かすにはいくつかのハードルがありました。細かな挙動を調べたり修正したりするにもC#コードの変更と再ビルドが必要で、文字列処理など一部の動作は.NETランタイムやOSの実装に依存するため、アプリケーションのソースコードだけでは追いきれないこともあります。

PyEmueraは、既存のEmuera用バリアントを活かしながら、**動作を読み、変更し、試しやすい実行環境**を目指して作られました。Pythonならソースを変更して再コンパイルなしに試すことができ、文字の入出力は標準入力・標準出力を通じて外部のプログラムからも扱えます。

AIを活用したバリアントの制作・動作検証、プレイの自動化、外部ツールとの連携、そして新しい遊び方の開拓にも使えます。**PyEmueraは、Emueraを遊ぶためだけでなく、Emueraで新しいことをするための実行環境です。**

複数のバリアントの固定入力経路で、**Beta 3比26.7～35.0%の実行時間短縮と、入力応答の改善**を確認しました。本家仕様へ合わせる互換修正も含めた版全体の比較です。効果はバリアントや経路により異なります。[測定条件](README_ja.md#性能の確認範囲)を参照してください。

## ダウンロードと起動

[Releases](https://github.com/Meistertech-JP/PyEmuera/releases) から **`PyEmuera-3.0.0-runtime.zip`** を取得して展開してください。ソースコードとテストは **`PyEmuera-3.0.0-source.zip`** に分けて配布します。GitHub が自動生成する `Source code` アーカイブは実行用ZIPではありません。

Python 3.10 以上が必要です（Python自体は同梱していません）。Windowsではバリアントフォルダーを `Start_PyEmuera.bat` にドラッグ＆ドロップできます。ターミナルからも実行できます。

```console
python PyEmuera.pyz "バリアントフォルダー"
```

同梱のZORKERBと散歩帳を起動する例：

```console
python PyEmuera.pyz ZORKERB
python PyEmuera.pyz sample --inputs sample/replay.txt --no-wait
```

Linuxなどで `python` コマンドがない場合は `python3` を使用してください。バリアントフォルダーには通常 `ERB` と `CSV` が入っています。

実行用 ZIP には「ぱみゅーら散歩帳」（`sample/`）と [ZORKERB r29](https://github.com/Meistertech-JP/ZORKERB/releases/tag/r29)（`ZORKERB/`）を同梱しています。ZORKERB は1970年代の大型計算機で生まれたテキストアドベンチャー Zork を起源とする、Zork の非公式 ERB 移植です。ZORKERB r29 が対応するのは ZORK I です。入力は英語で、Z-machine や Frotz は必要ありません。Windows では `ZORKERB` フォルダーを `Start_PyEmuera.bat` にドラッグ＆ドロップできます。権利とライセンスは同梱の `ZORKERB/LICENSE`、`ZORKERB/THIRD_PARTY_NOTICES.md` および `ZORKERB/licenses/` を参照してください。

使い方の詳細は実行用ZIP内の **`HOW_TO_USE_ja.txt`**、起動オプション・保存先・解析機能の仕様は[詳細ガイド](README_ja.md)を参照してください。

## 3.0.0 の主な変更

- 変数・参照・添字に対する重複した検査を減らしました。実行時間の変化はバリアントや経路によって異なります。
- raw文字列代入では、リテラル部分の境界にあるASCII空白を本家に合わせて処理し、全角空白（U+3000）と展開値の空白を保持します。
- 新規状態の `NEXTCOM`・`PREVCOM` は0です。`BEGIN TRAIN` で-1になる動作とは区別しています。
- `SAVEDATA` は保存成功時に `RESULT` を上書きしません（引数評価による変更は維持します）。
- システムメニューでは入力した文字列をそのまま一度だけ表示し、不正な入力では再入力を求めます。

## 動作環境と互換性

| 項目 | 対応と確認範囲 |
| --- | --- |
| 実行 | Python 3.10以上、文字表示・入力が可能なターミナル |
| 開発・全単体テスト | Python 3.11以上 |
| Windows | 過去版を含む確認例はWindows 10。Windows 11は十分な実機検証が未完了 |
| Linux | 過去版を含む確認例はx86_64の実機・仮想環境。環境により端末入力の挙動は異なる |
| その他 | macOS・Android（Termuxなど）は未検証 |

表の確認例は現行3.0.0の全環境での合格を示すものではありません。

PyEmueraの実行時依存はPython標準ライブラリのみです。追加の.NETや外部Pythonパッケージは必要ありません。

文字列の並べ替えには、WindowsではOSのNLS機能、それ以外では同梱された固定の `ja-JP` 照合データと互換実装を使用します。Windows 10／NLS `0x60305` の保存済み.NET Framework測定に対し、古ハングル・Jamo比較36,864方向がすべて一致しています。これはUnicode全域やすべてのWindows版の完全互換性を意味しません。

本家GUI固有の表示、入力機能、セーブの完全な相互互換性などについては、[互換性と確認範囲](COMPATIBILITY_ja.md)と実行用ZIPの `KNOWN_ISSUES_ja.txt` に記載しています。

## ソースからの実行と開発

```console
python run_pyemuera.py --help
python run_pyemuera.py examples/smoke --inputs examples/smoke/replay.txt --no-wait
```

[開発者ガイド](README_DEVELOPERS_ja.md)にテスト、ソースからのビルド、配布物の生成方法をまとめています。[アーキテクチャ](ARCHITECTURE_ja.md)と[照合状態機械の説明](docs/portable-jamo-state-machine.md)も参照できます。

## ライセンス・不具合報告

PyEmuera本体は[MIT License](LICENSE)です。第三者の素材・資料にはそれぞれの条件が適用されます。詳細は[第三者の権利表示](THIRD_PARTY_NOTICES.md)、[Microsoft NLSデータの出典と条件](THIRD_PARTY_MS_NLS_NOTICE_ja.md)、[参照資料](SOURCES.md)をご覧ください。

不具合は[GitHub Issues](https://github.com/Meistertech-JP/PyEmuera/issues)へ、PyEmueraの版、OS・Pythonの版、バリアント名と版、再現手順、期待結果と実際の結果を添えて報告してください。ログに含まれる個人情報・入力内容・ゲーム本文やセーブデータは共有前に確認してください。
