# Lightroom（クラウド版）JPG → RAW引き継ぎツール
## Geminiへの共有メモ（Muse案・参考資料）

この資料は Muse が整理した設計案です。**確定仕様ではありません。**
実装の進め方やコードの書き方は Gemini 側の判断を優先してください。
特に Crop 書き換えの対象タグは、実物の XMP サンプルで検証するまで仮説です。

---

## 1. ツールの目的

- カメラ（Olympus OM-D E-M1X）で RAW（.ORF）＋JPG で記録する
- 現場では JPG のみをスマホへ転送し、Lightroom Mobile／クラウド版 Lightroom で
選別（レーティング）・トリミング・簡易現像を行い即納する
- 帰宅後の本納品で、JPG で行った選別・編集を同名の RAW（.ORF）へ引き継ぎたい
- クラウド版 Lightroom には JPG → RAW への一括同期機能がないため、これを自動化する

## 2. 想定ワークフロー

1. ユーザーが作業フォルダをドラッグ＆ドロップする
- フォルダ内には、クラウド版 Lightroom から「オリジナル＋設定」で
書き出した `.dng` と、SDカードからコピーした未編集 `.ORF` が入っている
2. 実行ボタンを押すと、別スレッドで以下を自動実行する
- Step 1: ExifTool で `.dng` から `.xmp` を一括抽出
- Step 2: `.xmp` のファイル名を正規化（末尾の `_6` / `_11` 等の連番除去）
し、同名 `.ORF` とのマッチングを確認
- Step 3: `.xmp` 内部のタグを RAW 用に書き換える（下記 3. 参照）
- Step 4: オプション ON の時だけ、抽出元の `.dng` を片付ける
3. 成功枚数・マッチしなかったファイル・エラー内容をログ表示する

技術スタック想定:
- Windows 10 / 11、Python、PySide6（ドラッグ＆ドロップ可能な GUI）
- 最終的に PyInstaller で配布。ExifTool の同梱都合上、onefile ではなく
onedir 形式を Muse は推奨（`exiftool.exe` と同階層に `exiftool_files`
フォルダが必須なため）

## 3. Crop（切り抜き）消失対策の XMP タグ書き換え

抽出した XMP をそのまま.ORF に当てると、レーティングや基本補正は
反映されるが、Crop と角度補正（Straighten）が破棄される現象がある。

### 書き換え候補（優先順）

- `crs:AlreadyApplied`: `True` → `False`
- Muse の本命候補。JPG 由来 XMP では「編集は焼き込み済み」と
書かれていることが多く、RAW 側で Crop を読み直さない原因に
なり得ると考えている。**未検証の仮説。**
- `crs:RawFileName`: `EM1X8714.JPG` → 対応する `EM1X8714.ORF` へ書き換え。
対応 RAW が無い場合は削除し、ログに残す
- `crs:HasCrop`: Crop 座標があるのに `False`／欠落なら `True` に直す。
座標が無い場合は座標を作らない
- `crs:CameraProfile`: 値が `Embedded` の時だけ削除する。
`Adobe Color` 等の名前付きプロファイルは残す

### 削除候補（JPG 固有情報）

- `dc:format`（`image/jpeg`）
- `tiff:ImageWidth` / `tiff:ImageLength`
- `exif:PixelXDimension` / `exif:PixelYDimension`
- `photoshop:EmbeddedXMPDigest` 等の digest 系

理由: RAW と JPG で形式・寸法が食い違うと、Lightroom が安全のため
Crop を落とす可能性があるため。消しても現像パラメーターは失われず、
RAW を開いた時に RAW 側の値で再生成される想定。

### 絶対に消さないもの

- `crs:CropTop / CropLeft / CropBottom / CropRight / CropAngle / CropConstrainToWarp`
- 0〜1 の割合座標なので、ピクセル換算で再計算しないこと
- `xmp:Rating`、ラベル、露出・色温度等の現像パラメーター一式、
レンズ補正の有効／無効フラグ

### 保留（検証で判断）

- Upright の変換データ `crs:UprightTransform_*`:
ピクセル基準の変換のため寸法差で壊れる可能性があるが、
使用頻度が不明なため第1版では消さない
- `tiff:Orientation`: JPG と RAW で一致する想定で第1版では残す

### 検証方法（実装前に 1 組で切り分けたい）

左右非対称な切り抜き＋角度補正＋レーティング5＋露出補正を付けた
写真を 1 枚用意し、別フォルダで 4 種類を試す。

- 無加工（Crop が消えることの再確認）
- A: `AlreadyApplied` だけ直す
- B: A ＋ 寸法・形式・`RawFileName` の処理
- C: B ＋ `CameraProfile=Embedded` の削除

どれで Crop が残るかで、必要最小限の書き換えを決める。

## 4. 安全設計（Muse からの希望）

- DNG 削除は初期値オフ。対象は「抽出成功＋RAW と一致＋書き換え成功」の
3 条件を満たしたファイルだけに限定する
- 削除方法は完全消去ではなく Windows のごみ箱行きを第1版の標準にしたい
- 既存の同名 XMP がある場合は、無言で上書きせず日時付きバックアップを取る
- `_6` と `_11` が同じ RAW に対応する衝突は、上書きせずエラーとしてログに出す
- ExifTool は 1 ファイルずつ、shell を通さず引数リスト形式で呼ぶ
（引数長制限と日本語パスの回避）。`-charset filename=UTF8` を付ける
- ExifTool の探索順: アプリと同階層 → 設定で指定されたパス → PATH

## 5. コア処理の考え方（参考スケッチ）

- 画面（PySide6）と処理係（core）は分離する。処理係は GUI なしで
テストできる形にする
- XMP の書き換えは、XML を全文パースして組み直さず、属性単位の
置換・削除に留める（Adobe 製 XMP の書式・名前空間を壊さないため）。
要素形式（`<crs:CropTop>...</crs:CropTop>`）の併記にも対応する
- 処理結果は「成功／マッチなし／エラー／変更内容ログ」の形で
構造化して GUI へ返す

詳細な試作コードは、Muse とのサイドチャット
「Lightroom JPG→RAW引き継ぎツール」の直前の回答にあります。

## 6. Gemini へのお願いとして Muse が添えたいこと

- 上記 3. は仮説です。実物サンプルで異なる構造（属性形式でない等）が
あれば、そちらを正として設計を変えてください
- 分かる範囲で、どのタグ処理を採用／不採用にしたかと、その理由を
返してもらえると、Muse 側で差分と検証観点を整理しやすくなります
- 返ってきたコードは Muse 側で、対象外の処理が変わっていないか、
XMP が壊れていないかの検証を行います
