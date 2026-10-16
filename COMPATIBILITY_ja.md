# 互換性の範囲

対象は PyEmuera 3.0.0 Beta 1（`3.0.0b1`）、参照対象は Emuera1824+v24 です。ベータ版で、すべての Emuera 機能・すべてのバリアントとの完全な互換性は保証しません。

## 互換性の根拠の種類

PyEmuera の期待値は、次の種類の根拠から作っています。種類ごとに分けて扱い、異なる種類や母集団の結果を合算した「互換率」は作りません。

| 根拠 | 内容 |
| --- | --- |
| 本家ソースの読み取り | Emuera 1.8.2.4 / Emuera1824+v24 の C# ソースから、評価順序・境界・診断文を確認したもの（`SOURCE_AUDIT_1824*.json`） |
| 本家の実行結果 | 本家 Emuera.exe に中立的な ERB を実行させ、出力ログを保存したもの |
| .NET Framework の実測 | 比較・並べ替えなどを .NET Framework 4.8（ja-JP）で直接実行し、結果を保存したもの |
| 推定モデル | 公開データと実測から組み立てた再現実装（Windows 以外の文字列照合など）。実測の範囲外は推定です |
| PyEmuera 独自の試験 | 小さな独自スクリプトと、期待される結果による単体テスト |

保存した実測結果はテストの期待値として使います。期待値をエンジンの出力から作り直すことはしません。

## 文字列の比較と並べ替え

- Windows では OS の照合機能（NLS API、`CompareStringEx`）を使います。
- それ以外の環境では、Microsoft が公開している Windows 10 の照合データを元にした、`ja-JP`・既定の比較オプションの互換実装（`pyemuera/collation_portable.py`）を使います。二つの文字列を同時に評価し、.NET Framework で観測された比較結果を再現します。Unicode 正規化は行いません。
- 文字列の ARRAYSORT は .NET Framework の `Array.Sort` に相当する手順で並べます。FORWARD は比較器をそのまま、BACK は比較の引数を逆にした比較器を使います（昇順の結果を逆順にするのとは異なります）。
- ARRAYMSORT は .NET Framework の `List.Sort` に相当する手順で並べます。
- 数値の ARRAYSORT は文字列の照合を使いません。

### 既知の制限

Windows では OS の文字列照合機能を使用します。それ以外の環境では互換実装を使用します。互換実装では、一部の古ハングル（Old Hangul）・Jamo 文字列を ARRAYSORT または ARRAYMSORT で並べ替えた結果が、本家 Emuera と異なる場合があります。

Known limitation: On non-Windows platforms, rare Old Hangul/Jamo sequences may be ordered differently by the portable ja-JP collation backend. This may affect ARRAYSORT and ARRAYMSORT when sorting strings. Windows uses the native NLS backend.

この制限は、特殊な古ハングル・Jamo の組み合わせ 36,864 対を .NET Framework で比較した測定のうち、1,192 対で互換実装の比較結果が異なったものです。そのほかの照合の測定集合（日本語・英数字・記号・拡張文字などを含む）は、保存した測定結果とすべて一致しています。互換実装の照合規則は、この版で変更していません。

## 確認している範囲

- r51の3,296テストIDを維持し、Beta 1の変更に必要な回帰テストを追加しています。過去版の成績とBeta 1の新規結果は区別します。単体テストの成功は、すべてのバリアントでの互換性を意味しません。
- 本家 Emuera で実行した中立的な ERB の結果との比較（言語機能、解析モードの出力、引数、保存、ARRAYSORT の 6 条件と追加 32 条件など）
- .NET Framework で測定した文字列比較・並べ替えの結果との比較
- 既存バリアントでの動作確認（下記）

## 実際のバリアントでの動作確認

複数の Emuera 用バリアントで、起動・通常の進行・保存・読み込みなどを確認しています。確認は開発の過程で行ったもので、確認した版は項目ごとに異なります。バリアント本体・セーブ・実行記録は同梱していません。

- 『東方触手宮 Ver1.18.2修正版』：Windows 実機で、新規開始から17日目の脱出エンディングまで到達し、タイトル画面へ戻ることを確認（開発版 r16）。
- 『eratohoJ+ v1.05.5』：新規開始から2日目までの進行、セーブ・ロード、買い物、Stage1 道中戦闘、撤退などを確認。
- 『東方触手宮 Ver1.02.1』：既存の6日目のセーブから9日目まで進行。224日目の既存セーブの読み込みを確認。
- 『eratohoYM Mk-3改8proto6』：4日目の GAMEOVER 画面まで確認。
- 『eratohoM3S』：シューティングステージの実行を確認。
- 『eratohoW』：通常のゲーム画面、メニュー、イベント処理を含む決まった経路を確認。

これらは、記載した範囲・経路での確認です。各バリアントのすべての分岐や、最後までの動作を保証するものではありません。

## Windowsでの入力

Windows環境で、IMEを使った日本語入力、およびWindows Terminal（ConPTY）上での入力・中断が正常に動作することを確認しています。すべてのIME製品・バージョン・設定の組み合わせを網羅したものではありません。

## 時刻取得処理

`GETTIME`・`GETTIMES`等について、固定時計を使った単体試験、日付・秒の境界条件、時計取得と結果書き込みの順序を検証しています。ただし、本家とPyEmueraの実時計を同期させた、すべての時刻境界での一致を確認したものではありません。

ソース中の対応する試験は、`test_r40_flow_commands.R40FlowCommands.test_gettime_component_boundary_and_write_order`（年・日・秒の境界と書き込み順序）、`test_r40_flow_commands.R40FlowCommands.test_gettime_result_write_failure_prevents_eighth_sample`（結果書き込み失敗時の時計取得回数）、`test_execution_adapter_contracts.ExecutionAdapterContracts.test_gettime_retains_caller_clock_module_and_single_sample`、同クラスの `test_gettime_keeps_numeric_write_when_string_write_fails`（固定時計と副作用の順序）、`test_source_functions_a7.SourceFunctionsA7.test_gettimes_shape`（`GETTIMES()`の書式）です。過去の `flow-gettime-live` の `UNOBSERVED_CLOCK` は、未同期の実時計の厳密な値比較の制約を示す記録であり、時刻取得機能全体が未試験であることを意味しません。

## まだ確認していないこと

- すべてのバリアント、すべての分岐での動作
- すべてのIME製品・バージョン・設定の組み合わせ
- 本家とPyEmueraの実時計を同期した、すべての時刻境界での厳密な値比較
- 本家形式で書き出したセーブを、すべての場合に本家が読み込めること
- macOS での動作

## 意図して本家と異なる点

- 本家GUI固有の画像・音声・マウス操作・フォント描画は扱いません。端末自体のフォント設定は利用できます。
- セーブは `.pyemuera` に保存し、本家のセーブファイルを上書きしません。
- 対応していない命令や機能は、黙って成功扱いにせず、読み込み時または実行時にエラーとして停止します。
