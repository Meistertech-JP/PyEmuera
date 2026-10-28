# PyEmuera（ぱみゅーら）

**PyEmuera 3.0.0 Beta 2（`3.0.0b2`）** · [English](README_en.md)

PyEmuera は、Emuera 用のバリアント（ERB・ERH・CSV で作られたゲーム）を、文字だけのターミナルで動かす Python 製の独立した互換エンジンです。バリアントのゲームファイルは原則として変更せずに読み込みます。

Emuera 専用バリアントが動く eramaker のようなものと考えてください。互換性の参照対象は **Emuera1824+v24** です。本家の公式版ではありません。

画像・音声・マウス操作・本家GUIのフォント描画はサポートしていません。β版のため、すべての命令やゲームの完全な互換性は保証しません。

## ダウンロードと起動

[Releases](https://github.com/Meistertech-JP/PyEmuera/releases) から **`PyEmuera-3.0.0b2-runtime.zip`** を取得して展開してください。ソースコードとテストは **`PyEmuera-3.0.0b2-source.zip`** に分けて配布します。GitHub が自動生成する `Source code` アーカイブは実行用ZIPではありません。

Python 3.10 以上が必要です（Python自体は同梱していません）。Windowsではバリアントフォルダーを `Start_PyEmuera.bat` にドラッグ＆ドロップできます。ターミナルからも実行できます。

```console
python PyEmuera.pyz --help
python PyEmuera.pyz "バリアントフォルダー"
python PyEmuera.pyz sample --inputs sample/replay.txt --no-wait
```

Linuxなどで `python` コマンドがない場合は `python3` を使用してください。バリアントフォルダーには通常 `ERB` と `CSV` が入っています。

使い方の詳細は実行用ZIP内の **`HOW_TO_USE_ja.txt`**、起動オプション・保存先・解析機能の仕様は[詳細ガイド](README_ja.md)を参照してください。

## 動作環境と互換性

| 項目 | 対応と確認範囲 |
| --- | --- |
| 実行 | Python 3.10以上、文字表示・入力が可能なターミナル |
| 開発・全単体テスト | Python 3.11以上 |
| Windows | Windows 10で実機検証。Windows 11は十分な実機検証が未完了 |
| Linux | x86_64のLinux実機・仮想環境で検証。環境により端末入力の挙動は異なる |
| その他 | macOS・Android（Termuxなど）は未検証 |

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
