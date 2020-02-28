[神戸市「献立表」のオープンデータ](https://www.city.kobe.lg.jp/a54017/kosodate/gakko/school/lunch/kyusyoku/kondatehyo.html)を iCalendar ファイルに変換しています。

[最新版](https://hkwi.github.io/kcsl/)を取得できます。PDF からのデータ抽出で計算量が重すぎるので最新版の生成は Travis では行っておらず、リモートのマシンで行っています。

```
python3 -m kcsl
```

[![Build Status](https://travis-ci.org/hkwi/kcsl.svg?branch=master)](https://travis-ci.org/hkwi/kcsl) 


ubuntu では `poppler-utils`, `poppler-data` package もインストールしてください。

# License
プログラムは Apache 2.0 ライセンス、データは CC-BY ライセンスにします。
