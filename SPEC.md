# 仕様メモ

## 目的

クラウド版 Lightroom で JPG に行った選別・現像を、同名 RAW（.ORF）へ
引き継ぐ。写真データ自体は加工しない。扱うのは XMP サイドカーのみ。

## ワークフロー

1. ユーザーが作業フォルダを指定（.dng と .ORF が同居）
2. ExifTool で .dng から XMP を抽出する。必ず `-xmp -b` のバイナリ抽出を
   使い、UTF-8 のまま扱う（テキスト出力を経由すると日本語のマスク名が
   文字化けする）
3. ファイル名末尾の連番サフィックス（`_6` 等）を除去し、同名 .ORF と照合
4. XMP を RAW 用に書き換える（下記）
5. 成功したペアについてのみ、オプションで .dng をごみ箱へ移動

## XMP 書き換え仕様

### 削除・補正するタグ

- `dc:format`（属性形式・要素形式の両方）
- `tiff:ImageWidth` / `tiff:ImageLength` / `exif:PixelXDimension` /
  `exif:PixelYDimension` / `photoshop:EmbeddedXMPDigest`（両形式）
- `crs:CameraProfile="Embedded"` と `crs:CameraProfileDigest`
  （名前付きプロファイルは残す）
- `crs:AlreadyApplied="True"` → `"False"`（保険）
- `crs:WhiteBalance="Custom"` かつ絶対値 `crs:Temperature` が無い場合は
  `"As Shot"` へ変更
- `crs:RawFileName` は対応する .ORF 名へ書き換え

### 画角（アスペクト比）補正

- 定数は使わない。写真ごとに DNG と ORF の寸法・Orientation を
  ExifTool の JSON 一括出力で取得し、軸ごとに計算する
  - `scale = JPG寸法 / RAW寸法`、`offset = (1 - scale) / 2`
  - X 軸は CropLeft / CropRight、Y 軸は CropTop / CropBottom に適用
  - 変換式は `new = offset + old × scale`
- 未トリミング（Crop 座標なし）の場合は、offset から画角枠を注入する
- 両軸とも offset がほぼ 0（4:3 ネイティブ撮影）の場合は何もしない
- 寸法が取得できない写真は、補正をスキップして警告を出す
- 縦位置の軸モデル（表示基準／センサー基準）は実機確認で確定させる
  （docs/VERIFICATION_2026-11-18.md 参照）。現行実装は表示基準

### 対象外として弾く XMP

以下は「未処理」として報告し、成功に数えない。

- `crs:HasCrop` 属性が存在しない
- Crop が要素形式で書かれている
- Crop 座標（Top/Left/Bottom/Right）の一部だけが存在する

### 二重適用防止

変換済み XMP には `pogo:RawSyncApplied="True"` マーカー
（名前空間 `http://ns.pogo.studio/xmp/1.0/`）を付け、再処理時に
検知して座標変換をスキップする。

## 安全設計

- ExifTool 呼び出しは shell を通さず引数リスト形式、1 ファイルずつ。
  寸法取得のみ JSON 一括（100 ファイルずつのチャンク）
- 既存 XMP は `<元名>.xmp.bak_YYYYMMDD_HHMMSS` にバックアップ
- 最終配置は `Path.replace()`、書き戻しは `write_bytes`（CRLF 化防止）
- 同名 RAW に対応する DNG が複数の場合は衝突として処理しない
- 処理は GUI と分離した `XmpSyncCore` で行い、進捗コールバックと
  中断チェックを受け付ける

## ビルド方針（予定）

- PyInstaller の onedir 形式（ExifTool 同梱のため onefile は使わない）
- `exiftool.exe` と `exiftool_files` は実行ファイルと同じ階層に配置し、
  リポジトリには含めない
