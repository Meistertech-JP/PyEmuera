# PyEmuera（ぱみゅーら）

**PyEmuera 3.0.0 Beta 2 candidate B2-RC1 (`3.0.0b2.dev1`)**

[English](README_en.md)

PyEmuera は、Emuera 用のバリアント（ERB・CSV で作られたゲーム）を
文字だけの画面で動かす、Python 製の独立した高互換実装です。

バリアントのファイルを書き換えずにそのまま読み込めます。
現時点では、画像・音声・マウス操作・フォント描画は扱いません。

Emuera専用バリアントが動くeramakerだと思ってください。

参照対象は **Emuera1824+v24** です。ERH にも対応しています。本家 Emuera の公式版ではなく、独立した実装です。β版のため、すべての機能・バリアントとの完全互換性は保証しません。

## ダウンロードと起動

B2-RC1 は Beta 2 の候補です。ゲームの実行には実行用 ZIP を使います。ソースコードは別のソース用 ZIP です。実行用 ZIP は全体を展開してください。GitHub が自動生成する `Source code (zip)` / `Source code (tar.gz)` は開発者向けのソースアーカイブです。

Python 3.10 以上を用意し、展開先で実行します（Python 本体は同梱していません）。

```console
python PyEmuera.pyz --version
python PyEmuera.pyz "バリアントフォルダー"
```

`バリアントフォルダー` は、`ERB` と `CSV` が入っているフォルダーです。Windows では、そのフォルダーを展開先の `Start_PyEmuera.bat` にドラッグしても起動できます。Linux では上のコマンドを使います。環境によっては `python` を `python3` に読み替えてください。

配布 ZIP のサンプルは、展開先から次のように実行できます。

```console
python PyEmuera.pyz sample --inputs sample/replay.txt --no-wait
```

詳しい使い方は ZIP 内の `HOW_TO_USE_ja.txt`、または[使い方ガイドの原稿](packaging/public/HOW_TO_USE_ja.txt)を参照してください。

## 実行環境

| 用途 | 必要な環境 |
| --- | --- |
| バリアントの実行（pyz・ソース・インストール版） | Python 3.10 以上、文字表示・入力が可能なターミナル |
| 開発・全単体テスト・検証作業 | Python 3.11 以上 |

実行と単体テストは Python 標準ライブラリだけを使います。追加のランタイムライブラリや .NET、実行中のダウンロードは不要です。wheel / sdist の作成には別途 `build` と setuptools 77 以上が必要です。

ただし、Python とターミナルが存在するだけで、あらゆる環境・バリアントの動作を保証するものではありません。プラットフォーム固有の入力処理・端末制御等には制限があり得るため、未確認環境は未確認として扱います。

Windows 10 と Linux で測定履歴があります。r51 の履歴では、ゲーム実行を Windows 10 の Python 3.12・3.14、Linux の Python 3.10〜3.14 で確認しています。この履歴は B2-RC1 の全環境再試験を示すものではありません。Python 3.15 以降も未確認です。

### その他の環境

Windows 11も動作対象ですが、十分な実機検証は完了していません。
PyEmueraはPython標準ライブラリのみで動作するため、macOSやAndroid（Termuxなど）でも、Python 3.10以上と適切なターミナルが利用できれば動作する可能性があります。
ただし、macOS・Androidでの実機検証はまだ行っていません。起動・入出力・互換性を保証するものではありません。
これらの環境での動作報告も歓迎します。

Termux は Android 上の実行環境の例です。PyEmuera を Android ネイティブアプリとして提供しているという意味ではありません。

## ソースから実行する

GitHub のリポジトリにはソースコードを配置しています。以下は clone したリポジトリ直下で実行します。

```console
python run_pyemuera.py --version
python run_pyemuera.py "バリアントフォルダー"
python run_pyemuera.py examples/smoke --inputs examples/smoke/replay.txt --no-wait
python run_pyemuera.py examples/smoke --check
```

`--check` は読み込み・登録・宣言の静的検査です。最後まで遊べることの証明にはなりません。サンプル実行では `examples/smoke/.pyemuera/` が作られることがあります。

テスト・pyz ビルド・Python パッケージ作成は、[GitHub から開発するための補足](DEVELOPING_ON_GITHUB_ja.md)と[開発者ガイド](README_DEVELOPERS_ja.md)を参照してください。ソースを変更した場合は、検証対象の pyz も同じソースからビルドしてください。

## 対応範囲と既知の制限

- 文字の論理出力と端末への表示を扱います。本家 GUI の画像・背景・音声・マウス操作・フォント描画・ピクセル配置は対象外です。端末そのもののフォント設定は利用できます。EE / EM などの拡張版専用機能も対象外です。
- Windows は OS の NLS 照合機能、それ以外は同梱の `ja-JP` 互換実装を使います。固定した Windows 10、ja-JP、NLS 0x60305 の Jamo 比較 36,864 対では、互換実装と保存された .NET Framework の測定結果が 36,864/36,864 で一致しました。この測定範囲外や他の Windows・NLS 環境での完全互換は保証しません。
- Windows の IME 日本語入力と Windows Terminal（ConPTY）での入力・中断には確認実績がありますが、すべての IME 製品・版・設定の組み合わせは網羅していません。
- セーブはバリアント内の `.pyemuera/` に保存し、本家のセーブ自体は上書きしません。本家形式の読込・書出しは、すべての変数・バリアントでの完全な相互互換を保証しません。
- 時刻取得は固定時計や境界条件を試験していますが、同期した本家と PyEmuera の実時計による全境界の厳密比較は未完了です。割り込みテストには断続的な失敗の記録があります。
- 未対応の命令や機能は、読み込み時または実行時にエラーで停止します。

詳細は[互換性資料](COMPATIBILITY_ja.md)、[既知の制限](packaging/public/KNOWN_ISSUES_ja.txt)、[開発者向け補足](DEVELOPING_ON_GITHUB_ja.md)にあります。

## 実際のバリアントでの確認実績

以下は**異なる開発リビジョンで確認した履歴**です。B2-RC1 で全経路を再試験した結果ではなく、各バリアントの全分岐・完全動作を保証するものでもありません。

| バリアント | 確認した範囲 |
| --- | --- |
| 東方触手宮 Ver1.18.2修正版 | 開発版 r16、Windows 実機で新規開始から17日目の脱出エンディングへ到達し、タイトル画面へ戻ることを確認 |
| 東方触手宮 Ver1.02.1 | 既存の6日目セーブから9日目まで進行。224日目の既存セーブのロードを確認（1日目から224日目までの通しプレイではありません） |
| eratohoJ+ v1.05.5 | 新規開始から2日目までの進行、保存・読込、購入、Stage1 道中戦闘、撤退 |
| eratohoYM Mk-3改8proto6 | 4日目の GAMEOVER 画面へ到達（通常のゲームクリアではありません） |
| eratohoM3S | シューティングステージの実行 |
| eratohoW | 通常メニュー・ゲーム画面・イベント処理を含む固定経路の実行 |

根拠と範囲は[互換性資料](COMPATIBILITY_ja.md)を参照してください。表中のバリアント本体・セーブ・実行記録は同梱していません。収録サンプルは独立したデモです。

## ライセンスと出典

PyEmuera 本体は [MIT License](LICENSE) です。第三者資料にはそれぞれの条件が適用され、PyEmuera の MIT ライセンスで置き換えません。

- [第三者の権利表示](THIRD_PARTY_NOTICES.md)：Emuera 由来のテスト用ソース5点、SFMT 関連、Microsoft Reference Source、Unicode 関連データなど。
- [Microsoft NLS 照合データの出典と利用条件](THIRD_PARTY_MS_NLS_NOTICE_ja.md)と[ライセンス原文](licenses/)。
- [参照資料](SOURCES.md)、[アーキテクチャ](ARCHITECTURE_ja.md)、[既存のパッケージ用 README](README_ja.md)。


### SFMT参照元のMIT許諾

`pyemuera/random1824.py` が参照するHOBARA由来の部分には、[Rei HOBARAの公式配布ページ](https://www.rei.to/random.html)で示されるMITの選択肢を適用します。Copyright (C) Rei HOBARA 2007。[公式MIT条文](https://www.rei.to/MITL.txt)の許諾・条件・免責は、同梱の [LICENSE](LICENSE) にある同一の本文に対応します。PyEmuera本体のMIT宣言から第三者の許諾を作り出すものではありません。

この対応は、次の Beta 1 の固定原本にも適用します。B2-RC1 のハッシュではありません。ZIP直下の `THIRD_PARTY_NOTICES.txt` と `LICENSE.txt`、その `source/` 内、および単独pyz内の `THIRD_PARTY_NOTICES.md` と `LICENSE` に、著作権表示と許諾本文を収録しています。

| 配布原本 | SHA-256 |
| --- | --- |
| `PyEmuera-3.0.0b1.zip` | `df2f302490b638a6f7e74313bc40f98d36dfe7e0515e202f26deae7d5bc319a3` |
| `PyEmuera-3.0.0b1.pyz` | `305fcf27c723b9ca155ac087928f993eb32b141288fee689b0a621c0f337f1a7` |

## 不具合報告

[GitHub Issues](https://github.com/Meistertech-JP/PyEmuera/issues) に、PyEmuera の版、OS・端末・Python の版、バリアント名と版、再現手順、期待した結果と実際の結果、エラーメッセージを記載してください。可能であれば、ゲーム本文を含まない最小の再現例を添えてください。

調査用記録の取り方と共有前の確認事項は、[使い方ガイドの10章](packaging/public/HOW_TO_USE_ja.txt)にあります。私的ログ、認証情報、個人情報・ユーザー名を含む絶対パス、入力した名前、ゲーム本文をそのまま投稿しないでください。バリアント本体や私的セーブを無断で添付せず、共有できない記録は送らずに状況を文章で説明してください。
