==============================================================
 PyEmuera 3.0.0 Beta 1（ぱみゅーら）
 技術バージョン 3.0.0b1
==============================================================

PyEmuera は、Emuera 用のバリアント（ERB・CSV で作られたゲーム）を
文字だけの画面で動かす、Python 製の独立した高互換実装です。
バリアントのファイルを書き換えずにそのまま読み込めます。
現時点では、画像・音声・マウス操作・フォント描画は扱いません。

Emuera専用バリアントが動くeramakerだと思ってください。

対象は本家Emuera1824+v24です。対応範囲と既知の制限は、
同梱の KNOWN_ISSUES_ja.txt と source/COMPATIBILITY_ja.md をご覧ください。
フォント描画は本家GUI固有の描画機能を指し、端末のフォント設定は利用できます。

PyEmuera は Emuera の公式版ではなく、Emuera の作者やバリアントの作者とは
関係ありません。ベータ版です。すべてのバリアントが正しく動くことは
保証しません。


■ はじめての方へ

  使い方は HOW_TO_USE_ja.txt に、順番に説明しています。
  コマンド操作に慣れていない方は、まずそちらを読んでください。


■ 3ステップで始める（Windows）

  1. Python 3.10 以上を入れる（HOW_TO_USE_ja.txt の2章）
  2. この ZIP を右クリックして「すべて展開」する
  3. バリアントフォルダー（ERB と CSV が入っているフォルダー）を
     Start_PyEmuera.bat の上にドラッグ＆ドロップする

  最初は、付属の「sample」フォルダーで動作を確認するのがおすすめです。


■ 動作環境

  ・Windows 10 / Windows 11、または Linux
  ・Python 3.10 以上（Python 本体は同梱していません）
  ・ほかに追加でインストールするものはありません。
    PyEmuera はインターネットに接続しません。


■ 対応範囲

  ・参照している本家：Emuera1824+v24
  ・文字の表示と入力に対応しています。
  ・本家GUIの画像・音声・マウス操作・フォント描画は再現しません。
  ・Emuera の拡張版（EE / EM）専用の機能には対応していません。
  ・対応していない命令が使われている場合は、黙って進めずにエラーで停止します。

  既知の制限は KNOWN_ISSUES_ja.txt にまとめています。


■ 動作を確認したバリアント

  開発の過程で、次のバリアントで起動・進行・保存・読み込みなどを確認しています
  （確認した版は項目ごとに異なります。バリアント本体は同梱していません）。

  ・東方触手宮 Ver1.18.2修正版
      Windows 実機で、新規開始から17日目の脱出エンディングまで到達し、
      タイトル画面へ戻ることを確認（開発版 r16）
  ・eratohoJ+ v1.05.5
      新規開始から2日目までの進行、セーブ・ロード、買い物、
      Stage1 道中戦闘、撤退など
  ・東方触手宮 Ver1.02.1
      既存の6日目のセーブから9日目まで進行、224日目の既存セーブの読み込み
  ・eratohoYM Mk-3改8proto6
      4日目の GAMEOVER 画面まで
  ・eratohoM3S
      シューティングステージの実行
  ・eratohoW
      通常のゲーム画面、メニュー、イベント処理を含む決まった経路

  これらは記載した範囲での確認です。各バリアントのすべての分岐や、
  最後までの動作を保証するものではありません。


■ 同梱ファイル

  PyEmuera.pyz            PyEmuera 本体（Python で実行するファイル）
  Start_PyEmuera.bat      バリアントを起動する
  Check_PyEmuera.bat      バリアントを始めずに、読み込めるかを確認する
  Diagnose_PyEmuera.bat   不具合報告用の記録を取りながら起動する
  sample\                 動作確認用のサンプルバリアント（独自作成・非成人向け）
  README_ja.txt           この文書
  HOW_TO_USE_ja.txt       使い方ガイド
  KNOWN_ISSUES_ja.txt     既知の制限
  CHANGELOG_ja.txt        変更履歴
  LICENSE.txt             PyEmuera のライセンス（MIT License）
  THIRD_PARTY_NOTICES.txt 第三者の権利表示
  licenses\               第三者のライセンス文書
  SHA256SUMS.txt          同梱ファイルのチェックサム（SHA-256）
  source\                 開発者向け：ソースコード・テスト・ビルド用の一式
                          （遊ぶだけなら不要です。source\README_DEVELOPERS_ja.md）


■ バリアントのファイルとセーブデータ

  PyEmuera は、バリアントの ERB / CSV / 設定ファイルや、Emuera のセーブデータを
  書き換えません。セーブはバリアントフォルダー内の「.pyemuera\saves」に保存します。
  Emuera のセーブデータ（save00.sav など）は自動で読み込みます。
  PyEmuera が作るファイルの一覧は HOW_TO_USE_ja.txt の7章にあります。


■ バリアントを遊ぶだけの場合

  source フォルダーは、PyEmuera本体の開発・テスト・ビルド用です。
  これらを行わない場合は、削除して構いません。
  通常の起動には、ZIP直下の PyEmuera.pyz と起動用バッチを使用します。
  ライセンスと第三者の権利表示（LICENSE.txt、THIRD_PARTY_NOTICES.txt、
  licenses フォルダー）は残してください。
  配布物全体のチェックサムの照合は、source フォルダーを削除する前に行ってください。


■ 開発者の方へ

  source フォルダーに、ソースコード、単体テスト、テスト用データ、
  PyEmuera.pyz を作り直すためのスクリプトが入っています。
  テストとビルドの方法は source\README_DEVELOPERS_ja.md を見てください。
  コマンドラインの全オプションは「python PyEmuera.pyz --help」で確認できます。


■ ライセンス

  PyEmuera 本体は MIT License です（LICENSE.txt）。
  一部に第三者のデータや、第三者のソースを参考にした実装を含みます。
  また、source フォルダーのテスト用データには、Emuera のソースファイルが
  5点（無改変）含まれ、それらは Emuera のライセンスに従います。
  詳しくは THIRD_PARTY_NOTICES.txt と licenses フォルダーを見てください。

  バリアント本体、Emuera 本体（Emuera.exe）は含んでいません。
