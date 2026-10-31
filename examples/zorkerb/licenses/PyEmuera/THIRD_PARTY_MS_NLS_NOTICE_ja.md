# Microsoft NLS 公開照合データの出典と利用条件

`pyemuera/resources/nls_ja_windows10.bin.zlib`は、Microsoftが公開するWindows 10 Sorting Weight Tableの部分データを、ja-JP比較器に必要な構造へ変換したものです。PyEmuera自身のMIT表記によって、Microsoft原データの権利を置き換えません。

根拠は[MS-UCODEREF公開ページのIntellectual Property Rights Notice](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-ucoderef/4a045e08-fc29-4f22-baf4-16f38c2825fb)です。Copyrights条項は、記載技術の実装のための複製、実装へ必要な文書部分の配布、schema/IDL/code sampleの変更有無を問わない実装内配布を許可し、その許可を参照先文書にも適用しています。

[同仕様3.1.5.2.3.1](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-ucoderef/226ad305-8a0b-469e-b30d-630c931faad2)は[公式Sorting Weight Tables](https://www.microsoft.com/en-us/download/details.aspx?id=10921)を参照します。2024-04-23版Appendix Aの注記3は、Windows 10に対応するファイル名を明示しています。この参照関係と条項を、必要部分を利用する根拠として記録しています。Open Specificationsは一律のMITデータライセンスではなく、特許・商標等の権利は別の条項です。

生成物は全BMPのDEFAULT、ja-JPの7073例外、一般EXPANSION/COMPATIBILITYとJamo関連データの部分抽出です。他cultureの例外・contraction、全原文、Windows OSから取り出したsortdefault.nlsは配布していません。原表SHA-256は`81fcfa1e5ed3e3a94d329959ff7d97d522ddf9d653d2c4d6ddcccc5cd4df663f`です。

コピーした許諾条項と出典URLは、standalone pyzにも含められる`pyemuera/resources/MS_OPEN_SPECIFICATIONS_NOTICE.txt`へ保存しています。このデータは、原表のSHA-256を固定した生成スクリプトで開発時に作成したものです。生成スクリプトはこの配布物に含まれていないため、配布物だけからデータを再生成することはできません。原表の入手先URL・SHA-256・収録件数は`pyemuera/resources/nls_ja_windows10.json`に記載しています。実行時の外部ダウンロードはありません。

Wineの公開実装と生成器はLGPL-2.1-or-laterで、masterの生成データはWindows 11表を使用します。研究上の比較資料として確認しましたが、Wineコード・バイナリデータはPyEmueraへ取り込んでいません。ReactOSコード/データも取り込んでいません。移植実装の設計はMicrosoft公開仕様の段階と公開重み値を基にしています。
