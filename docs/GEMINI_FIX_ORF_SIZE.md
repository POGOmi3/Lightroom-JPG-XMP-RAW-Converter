# Geminiへの修正依頼: ORF の寸法取得（実物検証で発見）

## 発見した問題

実物 ORF（EM1X7734.ORF）でツールを end-to-end 実行したところ、
画角計算に小さいが系統的なズレが出た。

- ExifTool が ORF の `ImageWidth / ImageHeight` として返すのは
  センサーの全読み出し寸法 **5240 x 3912**
- しかし Camera Raw が実際に使う有効画素エリアは
  **5184 x 3888** で、ORF 内の Olympus メーカーノート
  `CropWidth / CropHeight`（および `CropLeft / CropTop`）に記録されている

現行の `_batch_read_metadata` は ImageWidth を使うため、
この ORF では offset が X=0.0053 / Y=0.0583 と計算された
（正しくは X=0 / Y=0.055556）。画面の約 0.5% 分、左端が
切れていないはずなのに切れる等のズレになる。

## 修正内容

`_batch_read_metadata` で取得タグに Olympus の CropWidth / CropHeight を追加し、
RAW（ORF）側の寸法は以下の優先順で決める。

1. CropWidth / CropHeight がある場合はそれを有効寸法とする
2. 無い場合は従来どおり ImageWidth / ImageHeight

- ExifTool の JSON 取得では `-Olympus:CropWidth` / `-Olympus:CropHeight`
  のようにグループ指定すると、他グループの同名タグと混ざらない
- DNG 側（JPG 由来）の寸法取得は現行のままでよい
  （OriginalDefaultFinalSize 優先 → ImageWidth フォールバック。
  実物の別サンプルでは OriginalDefaultFinalSize が無い書き出しもあり、
  その場合も ImageWidth=5184x3456 で正しく読めた）

## 検証方法

- EM1X7734 のペアで再実行し、ログの画角表示が
  `[横 3:2 (offX=0.0000, offY=0.0556)]` になること
- 生成 XMP の Crop が Top=0.055556 / Left=0 / Bottom=0.883546 /
  Right=0.931489 になること（Muse 側で計算済みの正解値）

## ついでに確認できたこと（修正不要）

- フルサイズ書き出しの DNG（OriginalDefaultFinalSize なし）でも
  抽出・変換は正常に動いた
- WhiteBalance="Custom" かつ Temperature なしの実物サンプルで、
  As Shot への補正が想定どおり発動した
