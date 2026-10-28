# PyEmueraの実行経路と責務

PyEmuera 3.0.0 Beta 2（3.0.0b2）の入口から、評価・状態変更・出力・保存・失敗を追うための案内です。文字列の直接比較は二つの文字列の文脈を同時に評価するモデル、並べ替えは .NET Framework 相当の実装を使います。以下のパスは、ソース一式のフォルダー（`pyemuera/` があるフォルダー）からの位置です。

## 入口から実行まで

| 段階 | 主な担当モジュール | 読むべき契約 |
|---|---|---|
| CLI選択・引数・報告先 | `pyemuera/cli.py` | 通常実行、analysis、checkを分岐。既定encoding auto、max-steps 0 |
| 原バイトの読み込み | `pyemuera/source_encoding.py` | BOM優先、BOMなしCP932、不正列とEOFの本家契約 |
| ロード・関数登録 | `pyemuera/program.py`、`pyemuera/load_registration.py` | ソース位置・登録・静的診断。ユーザー関数やRANDを静的に実行しない |
| 宣言・引数の静的確認 | `pyemuera/load_arguments.py`、`pyemuera/custom_function_arguments.py` | 個数→型→descriptor等の既存優先順。動的値の評価と分ける |
| 宣言表と接続検証 | `pyemuera/registry.py`、`pyemuera/dispatcher.py` | 閉じたJSON定義。familyから静的ownerへ接続。legacy fallbackを復活させない |
| VMと式評価 | `pyemuera/runtime.py`、`pyemuera/expr.py`、`pyemuera/builtins.py` | 呼出しframe、PC、REF、短絡、評価順、RNG、副作用 |
| 各命令family | `pyemuera/dispatcher.py`と`pyemuera/specs/commands.json` | 命令に対応するowner。VM controlはVMが処理。個別の契約は `--describe 命令名` で表示 |
| 直接Python API | `pyemuera/commands.py`、`pyemuera/direct_commands.py` | 通常VMと歴史的な直接APIの契約を無条件に統一しない |

ERBをPython evalとして実行しません。構文・ASTを解釈し、参照の解決、値の評価、変更のcommitを各ownerで扱います。どの段階で失敗したかによって保持すべき先行副作用が異なるため、検査を先頭へ移して「安全な処理」に変えることも互換性変更です。

## 特に順序を維持する処理

`registry.validate_document`はdocumentのschemaを検査し、登録時の挿入順で各entryを検査し、全entry成功後にfreezeします。JSON読込時の重複キーは`_unique`、syntax closer→expression bindingの相互参照は`_validate_cross_references`が担当します。未知キー・未知kindの既存扱いをリファクタリングで厳格化しません。同時に複数の誤りがある場合の最初の診断を保持します。

`custom_function_arguments`の個数境界は、CSV scalar→CSV numeric/STRFIND→RANGE→FINDELEMENT→既定の先勝ち順です。集合の重なりを考慮し、辞書へ機械的に置き換えません。count検査を型・REF・動的評価より後へ移しません。

通常の代入、複合代入、命令の順次更新はそれぞれ本家の評価順を持ちます。途中で配列範囲外となった場合の先行書き込み、RNGの消費、RESULTの保持まで試験対象です。後置演算子やREFは値キャッシュへ変換しません。

## Consoleの二層

`pyemuera/console.py`は利用入口と処理順、`pyemuera/console_history.py`は論理行・罫線由来・履歴操作、`pyemuera/terminal_frame.py`は物理フレーム、`pyemuera/printing.py`と`pyemuera/display_elements.py`は表示要素と文字幅の投影を担当します。

logical lines・pending・logsとstdout bytes・ANSI・cursor・repaintを別軸で観測します。`write`/`flush`故障時の更新境界は `tests/test_r43_console_failures.py` などのテストで確認しています。物理表示を直すためにERB文字列やOUTPUTLOGを正規化しません。

## ソートと文化比較

`pyemuera/sort1824.py`はFramework List capacity・introsort・tie順序・比較後の順次書き込みを所有します。`pyemuera/collation1824.py`は比較器の選択、`pyemuera/collation_windows.py`はWindows NLS ABI、`pyemuera/collation_portable.py`は固定ja-JPの重みstreamと比較、`pyemuera/collation_jamo.py`はL/V/T文脈解釈を所有します。

UTF-16単位、文脈Jamo、expansion、記号word sortをUnicode正規化へ一括置換しません。文化規則をソート本体へ埋め込まず、行番号や対象fixtureの特別扱いをしません。Windows 10のflat表と保存済みの実測で制約した一般モデルを使い、旧Windowsのtransition疑似コードを現代の内部実装と同一視しません。文脈境界と記号位置には推定部分があり、既知の制限は[互換性資料](COMPATIBILITY_ja.md)に記載しています。公開NLSデータの由来は[Microsoft notice](THIRD_PARTY_MS_NLS_NOTICE_ja.md)に保持します。

## 保存・RNG・解析

`pyemuera/save_commands.py`は保存命令の評価とRESULT/flow、`pyemuera/persistence.py`と`pyemuera/native_store.py`は`.pyemuera`への保存・検証・復元、`pyemuera/random1824.py`は本家SFMTとRANDDATAの契約を担当します。原本sav保護、復元前の全体検証、atomic writeを保持します。

`pyemuera/analysis_mode.py`は本家式の非実行解析とログ投影、`pyemuera/audit.py`はCLIの静的インベントリです。静的診断を生成するためにバリアントを進行したりRNGを消費したりしません。analysisとcheckは別の利用入口です。

## 内部状態を追う

VM/Consoleの遅延キャッシュと補助属性は、creator・reader・writer・寿命・依存・無効化・途中失敗の観点で扱います。未生成と空辞書の区別、初回アクセス時のimport、private scope/REFのlive値を保ちます。キャッシュの管理主体や無効化を変更する作業は構造的リファクタリングとして独立に比較し、書式AST一致だけで安全と判断しません。

## 改修の入口

互換性の修正では、本家ソースの読み取り・本家の実行結果・.NET Framework の実測・推定モデルを区別し、根拠を[互換性資料](COMPATIBILITY_ja.md)と[参照資料一覧](SOURCES.md)で確認してください。各モジュール冒頭のdocstring、本家C#への参照、短絡・境界・副作用の理由を示すコメントを残します。テストの実行方法は、ソース一式に同梱の `README_DEVELOPERS_ja.md` を参照してください。

## Windowsの入力・出力モード境界

入力reader、SIGINT/SIGBREAKの配送、EOF、キャンセルは `pyemuera/cli_interrupts.py` と入力系モジュールが所有します。Consoleのstdout modeはstdin modeと別の資源として扱い、取得・エンジンによる変更・終了時の復元・API失敗をそれぞれ扱います。テスト環境での確認は、Windows実機での人間のキー操作やIMEの確認とは別のものです。

## 再現可能ビルド

`tools/build_pyz.py` と互換CLI `build_zipapp.py` は同じビルダーを使用します。`pyemuera/`、`licenses/`、同梱文書9点（`LICENSE`、`README_ja.md`、`ARCHITECTURE_ja.md`、`COMPATIBILITY_ja.md`、`SOURCES.md`、`THIRD_PARTY_NOTICES.md`、`THIRD_PARTY_MS_NLS_NOTICE_ja.md`、`SOURCE_AUDIT_1824.json`、`SOURCE_AUDIT_1824_v24.json`）、固定の`tools/zipapp_inputs/__main__.py`を読み、順序・時刻・ZIP属性・DEFLATE level 9を固定します。pyzに自身のSHAや生成時刻を埋め込みません。同一Python/zlibをビルド条件とし、異なるクリーンディレクトリで全バイトを照合します。
