# PyEmuera

PyEmuera は、Emuera 用のバリアント（ERB・CSV で作られたゲーム）を
文字だけの画面で動かす、Python 製の独立した高互換実装です。
バリアントのファイルを書き換えずにそのまま読み込めます。
現時点では、画像・音声・マウス操作・フォント描画は扱いません。

Emuera専用バリアントが動くeramakerだと思ってください。

フォント描画は本家GUI固有の機能を指し、端末そのもののフォント設定は利用できます。ERHにも対応し、本家 Emuera と同じ評価順序・状態変化・保存・文字出力になることを目標にしています。

この版は **PyEmuera 3.0.0 Beta 2（`3.0.0b2`）** です。ベータ版で、すべての Emuera 機能・すべてのバリアントでの互換性は保証しません。確認できている範囲と、まだ確認していない条件は [COMPATIBILITY_ja.md](COMPATIBILITY_ja.md) にまとめています。

PyEmuera は Emuera の公式版ではなく、Emuera やバリアントの作者による承認を受けたものではありません。

## 参照している本家 Emuera

参照対象は **Emuera1824+v24** です。EE・EM などの拡張版専用の機能は対象外です。命令・式関数・構文・変数の登録は、同梱の JSON 定義（`pyemuera/specs/`）で管理しています。対応していない処理を、黙って成功扱いにすることはしません。

本家 GUI の画像・音声・マウス操作・フォントの描画は対象外です。PyEmuera は文字の論理出力と端末への表示を扱います。

## 動作環境

- Python 3.10 以上（Python 本体は同梱しません）
- Windows または Linux の端末。実行には Python 標準ライブラリだけを使い、追加のパッケージ、.NET、実行中のダウンロードは必要ありません。
- 文字列の比較（並べ替え）は、Windows では OS の照合機能（NLS API）を使います。それ以外の環境では、Microsoft が公開している Windows 10 の照合データを元にした、同梱の `ja-JP` 互換実装を使います。

## 起動方法

```console
python PyEmuera.pyz --version
python PyEmuera.pyz --help
python PyEmuera.pyz "バリアントフォルダー"
```

「バリアントフォルダー」は、`ERB` と `CSV` が入っているフォルダーです。

ERB・ERH・CSV・設定ファイルは、BOM があればそれに従い、BOM がなければ CP932（Shift_JIS）として読みます。`--encoding utf-8` などの指定は、この既定の判定を上書きする明示的な設定です。

VM の命令数は既定で無制限です（`--max-steps 0` も無制限）。正の数を指定すると、その数で停止します。

不具合調査用の記録は、まだ存在しないファイル名を指定して出力します。

```console
python PyEmuera.pyz "バリアントフォルダー" --session-report session-01.json --error-report error-01.json
```

`--inputs` は入力の再生、`--record-inputs` は実際に受け付けた入力の記録です。入力の記録は指定したときだけ作られ、入力した文字がそのまま含まれます。

## 事前確認と解析

```console
python PyEmuera.pyz "バリアントフォルダー" --check --report check-01.json
```

`--check` はバリアントを開始せずに、読み込み・登録・宣言の静的な確認だけを行います。終了コードは、問題が見つからなければ 0、見つかれば 2 です。バリアントが最後まで動くことの証明にはなりません。

```console
python PyEmuera.pyz --analysis "バリアントフォルダー/ERB" --analysis-root "バリアントフォルダー"
python PyEmuera.pyz --analysis "対象A.ERB" "対象B.ERB" --analysis-root "バリアントフォルダー" --analysis-log "analysis-01.log"
```

`--analysis` は本家の解析モードに相当する出力（UTF-16LE BOM・CRLF の `Analysis.log`）を作ります。出力先を指定しない場合は、バリアントフォルダーに `Analysis.log` を書き込みます。既存のファイルを残したい場合は `--analysis-log` で別の場所を指定してください。

## ファイルの書き込み先

PyEmuera は、バリアントの ERB・ERH・CSV・設定ファイルと、本家のセーブデータ（`.sav`）を書き換えません。ゲーム中に作られるファイルは、バリアントフォルダーの中の `.pyemuera` に置きます。

| 場所 | 内容 |
| --- | --- |
| `.pyemuera/saves` | PyEmuera 形式（JSON）のセーブ（既定） |
| `.pyemuera/native-saves` | `--save-format emuera-text` / `emuera-binary` を指定したときのセーブ |
| `.pyemuera/deleted-saves` | ゲームがセーブを削除したときの記録（本家のセーブ自体は消しません） |
| `.pyemuera/logs` | バリアントが OUTPUTLOG で出力したログ |
| `.pyemuera/character-data`、`text-root`、`text-sav` | バリアントが保存したキャラクターデータ・テキストファイル |

このほか、`--report`・`--session-report`・`--error-report`・`--record-inputs`・`--trace-report`・`--profile-vm` で指定した JSON ファイルは、指定した場所に作られます（相対パスは、コマンドを実行したフォルダーからの位置です）。これらの JSON ファイルは、バリアントの `ERB`・`CSV`・`.pyemuera` の中には作れず、同名のファイルがあると上書きせずに停止します（`--overwrite-reports` で上書き）。`--analysis` の `Analysis.log` は、指定した場所、または指定がなければバリアントフォルダーに作られます。

## セーブ

既存の本家セーブ（`save00.sav` など）は自動で読み込みます。PyEmuera で保存した内容は `.pyemuera` に書かれ、本家のセーブには書き戻しません。同じ番号のセーブを保存すると `.pyemuera` 側が更新されるため、バックアップするときは `.pyemuera` も含めてください。

```console
python PyEmuera.pyz "バリアントフォルダー" --save-format json
python PyEmuera.pyz "バリアントフォルダー" --save-format emuera-text
python PyEmuera.pyz "バリアントフォルダー" --save-format emuera-binary
```

本家形式での書き出しは、すべての変数・すべてのバリアントで本家が読み込めることを確認したものではありません。乱数の状態は、既定の `--native-rng source` ではバリアントの `DUMPRAND`・`INITRAND` によってだけ同期します。`--native-rng restore` は自動で復元する拡張機能です。

## 既知の制限

- Windows では OS の文字列照合機能を使います。それ以外の環境では互換実装を使います。固定した Windows 10、ja-JP、NLS 0x60305 の Jamo 比較 36,864 方向では、互換実装と保存された .NET Framework の測定結果が 36,864/36,864 で一致しました。この測定範囲外や他の Windows・NLS 環境での完全互換は保証しません。
- Windows環境で、IMEを使った日本語入力、およびWindows Terminal（ConPTY）上での入力・中断が正常に動作することを確認しています。すべてのIME製品・バージョン・設定の組み合わせを網羅したものではありません。
- 詳細は [COMPATIBILITY_ja.md](COMPATIBILITY_ja.md) を参照してください。

## バリアントを遊ぶだけの場合

実行用 ZIP とソース用 ZIP は別です。通常の起動には実行用 ZIP の `PyEmuera.pyz` と起動用バッチを使用します。ソース用 ZIP は開発・テスト・ビルドに使います。

## 関連文書

- [ARCHITECTURE_ja.md](ARCHITECTURE_ja.md)：実行の流れと、モジュールごとの役割
- [COMPATIBILITY_ja.md](COMPATIBILITY_ja.md)：互換性の確認範囲（動作を確認したバリアントを含む）と既知の制限
- [SOURCES.md](SOURCES.md)：参照資料と実装の根拠
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)：第三者の権利表示
- [THIRD_PARTY_MS_NLS_NOTICE_ja.md](THIRD_PARTY_MS_NLS_NOTICE_ja.md)：Microsoft 照合データの出典と利用条件

## ライセンス

PyEmuera 本体は [MIT License](LICENSE) です。第三者のデータと、第三者のソースを参考にした部分は、それぞれ元の条件に従います（[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、`licenses/`）。
