# Geminiへの修正依頼: Crop座標は「センサー（格納）空間」が正解でした

## 結論

縦位置サンプル EM1X9697（Orientation = Rotate 270 CW、
Lightroom で手動トリミング済み）の実物検証で確定した。

**crs:Crop の座標は、表示向きではなく、ファイルに格納されている
ピクセル配列の向き（センサー空間）で記録されている。**
Gemini の当初の主張が正しく、現行 core.py の「表示基準」実装
（縦位置で X/Y を入れ替える処理）は誤り。

## 根拠（実測）

- DNG 内の記録: CropTop=0 / CropLeft=0.126482 /
  CropBottom=0.873518 / CropRight=1（格納寸法 3216x2144）
- ポゴさんが送ってくれた編集済み JPG（1873x2809）と、
  ORF 埋め込みプレビュー（フルフレーム）を画像照合し、
  表示画面上で実際に切り取られた範囲を実測した:
  表示換算で Left=0 / Top=0 / Right=0.873518 / Bottom=0.873518
  （JPG 画角を基準とした相対値）
- これは、XMP の値を「格納空間の値」として Orientation 8 の
  変換（xd = y_s, yd = 1 - x_s）で表示に直した結果と一致した。
  表示空間の値として読む候補（左を 12.6% 切る）とは
  画像照合の誤差が大きく（平均差 0.770 対 0.557）、明確に否定された

## 修正内容（_compute_aspect_transform）

1. **Orientation による軸入れ替えを廃止する。**
   変換は常に格納寸法同士で計算する。縦位置の 3:2 でも、
   横位置と同じく格納 Y 軸（Top/Bottom）側に offset が出る。
   is_vertical による分岐は不要（ログ表示用に残すのは可）。
2. **scale は寸法の絶対値ではなく、格納アスペクト比から計算する。**
   理由: 今回の DNG は縮小版（3216x2144）で
   OriginalDefaultFinalSize が無く、現行方式だと
   scale = 3216 / 5240 = 0.614 という誤った値になる。
   アスペクト比 A_j（JPG格納 w/h）と A_r（RAW格納 w/h）から:
   - A_j > A_r のとき: scale_x = 1, scale_y = A_r / A_j
   - A_j < A_r のとき: scale_y = 1, scale_x = A_j / A_r
   - offset は (1 - scale) / 2（中央窓の前提は従来どおり）
3. **RAW 側の格納寸法は有効エリアを使う**（別依頼
   GEMINI_FIX_ORF_SIZE.md の内容）: ORF は ImageWidth の
   5240x3912 ではなく Olympus CropWidth/CropHeight の
   5184x3888。アスペクト比もこちらで計算する。

マスク座標の変換も同じ格納空間の scale/offset を使う
（座標空間が Crop と同じである前提。マスク単独の実物検証は未実施）。

## 検証用の正解値

### EM1X9697（縦・3:2・手動トリミングあり）
入力 Crop: Top=0, Left=0.126482, Bottom=0.873518, Right=1
正解の出力: Top=0.055556, Left=0.126482, Bottom=0.832016, Right=1
（Muse 側で生成・検算済み。表示換算すると編集済み JPG の
実測切り抜き範囲と一致する）

### EM1X7734（横・3:2・手動トリミングあり）
入力 Crop: Top=0, Left=0, Bottom=0.931489, Right=0.931489
正解の出力: Top=0.055556, Left=0, Bottom=0.883546, Right=0.931489

### EM1X0036（縦・3:2・未トリミング）
正解の注入: Top=0.055556, Bottom=0.944444, Left=0, Right=1
（現行コードは Left/Right に注入してしまうため誤り）
