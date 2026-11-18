import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

try:
    from send2trash import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False


@dataclass
class ImageMeta:
    """ExifToolから取得した画像寸法・回転メタデータ"""
    width: int = 0
    height: int = 0
    orig_width: int = 0
    orig_height: int = 0
    orientation: int = 1  # EXIF Orientation (1=Normal, 6=Rotate 90 CW, 8=Rotate 270 CW, etc.)

    @property
    def is_valid(self) -> bool:
        return (self.orig_width > 0 and self.orig_height > 0) or (self.width > 0 and self.height > 0)

    def get_effective_size(self) -> Tuple[int, int]:
        """OriginalDefaultFinalSizeがあれば優先し、なければImageWidth/Heightを返す"""
        if self.orig_width > 0 and self.orig_height > 0:
            return self.orig_width, self.orig_height
        return self.width, self.height


@dataclass
class ProcessResult:
    """GUIへ返す処理結果の構造体"""
    success_files: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unmatched_xmp: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    cancelled: bool = False


class XmpSyncCore:
    # 二重適用防止用のカスタム属性マーカー
    MARKER_NS = 'xmlns:pogo="http://ns.pogo.studio/xmp/1.0/"'
    MARKER_ATTR = 'pogo:RawSyncApplied="True"'

    def __init__(self, exiftool_path: Optional[Path] = None):
        self.exiftool_path = self._resolve_exiftool(exiftool_path)

    def _resolve_exiftool(self, custom_path: Optional[Path]) -> str:
        """ExifToolの探索順: 1. 指定パス -> 2. アプリと同階層 -> 3. 環境変数PATH"""
        if custom_path and custom_path.exists():
            return str(custom_path)
        local_exe = Path(__file__).resolve().parent / "exiftool.exe"
        if local_exe.exists():
            return str(local_exe)
        return "exiftool"

    def process_folder(
        self,
        folder_path: Path,
        auto_aspect_crop: bool = True,
        adjust_mask_coords: bool = False,
        trash_source_dng: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> ProcessResult:
        result = ProcessResult()
        if not folder_path.exists() or not folder_path.is_dir():
            result.errors.append(f"フォルダが存在しません: {folder_path}")
            return result

        # 大文字・小文字の重複を防ぐためセットで正規化収集
        dng_files = sorted({p.resolve() for p in folder_path.iterdir() if p.is_file() and p.suffix.lower() == ".dng"})
        orf_map = {p.stem.upper(): p.resolve() for p in folder_path.iterdir() if p.is_file() and p.suffix.lower() == ".orf"}

        if not dng_files:
            result.errors.append("フォルダ内に .dng ファイルが見つかりません。")
            return result

        result.logs.append(f"検出: DNG {len(dng_files)}枚 / ORF {len(orf_map)}枚")

        # 連番サフィックス（_6, _11等）の除去と衝突チェック
        target_map: Dict[str, List[Tuple[Path, str]]] = {}
        for dng in dng_files:
            normalized_stem = re.sub(r"_[0-9]+$", "", dng.stem)
            key = normalized_stem.upper()
            target_map.setdefault(key, []).append((dng, normalized_stem))

        # 処理対象ペアの確定
        valid_pairs: List[Tuple[Path, Path]] = []
        for key, items in target_map.items():
            if len(items) > 1:
                names = ", ".join([item[0].name for item in items])
                msg = f"[衝突スキップ] 同一RAWに対応する複数DNGが存在します: {names}"
                result.conflicts.append(msg)
                result.logs.append(msg)
                continue

            dng_path, normalized_stem = items[0]
            if key not in orf_map:
                msg = f"[マッチなし] 対応するORFがありません: {dng_path.name} (想定: {normalized_stem}.ORF)"
                result.unmatched_xmp.append(msg)
                result.logs.append(msg)
                continue

            valid_pairs.append((dng_path, orf_map[key]))

        total_pairs = len(valid_pairs)
        if total_pairs == 0:
            result.logs.append("処理可能なDNGとORFのペアがありませんでした。")
            return result

        # 画角自動補正がONの場合、対象ファイルの寸法・Orientationを一括プリフェッチ
        meta_cache: Dict[Path, ImageMeta] = {}
        if auto_aspect_crop:
            if progress_callback:
                progress_callback(0, total_pairs, "ExifToolで画像寸法・画角情報を一括解析中...")
            files_to_inspect = [p for pair in valid_pairs for p in pair]
            meta_cache = self._batch_read_metadata(files_to_inspect, result)

        # 1ファイルずつ抽出・書き換えを実行
        for idx, (dng_path, orf_path) in enumerate(valid_pairs, start=1):
            if cancel_check and cancel_check():
                result.cancelled = True
                result.logs.append("[中断] ユーザーによって処理が中断されました。")
                break

            if progress_callback:
                progress_callback(idx, total_pairs, f"処理中 ({idx}/{total_pairs}): {dng_path.name}")

            final_xmp_path = folder_path / f"{orf_path.stem}.xmp"
            temp_xmp_path = folder_path / f"__temp_{dng_path.stem}.xmp"

            # Step 1: ExifToolでDNGから一時XMPをバイナリ抽出
            if not self._extract_xmp_single(dng_path, temp_xmp_path, result):
                continue

            # Step 2: 画角比（scale / offset）の算出
            aspect_info_str = "画角補正OFF"
            scale_x, offset_x, scale_y, offset_y = 1.0, 0.0, 1.0, 0.0
            if auto_aspect_crop:
                dng_meta = meta_cache.get(dng_path)
                orf_meta = meta_cache.get(orf_path)
                if dng_meta and orf_meta and dng_meta.is_valid and orf_meta.is_valid:
                    scale_x, offset_x, scale_y, offset_y, aspect_info_str = self._compute_aspect_transform(dng_meta, orf_meta)
                else:
                    aspect_info_str = "寸法取得失敗(画角補正スキップ)"
                    result.warnings.append(f"[警告] 寸法が読めないため画角補正をスキップ: {dng_path.name}")

            # Step 3: XMPタグのクレンジング＆Crop変換
            try:
                is_supported, modified_changes, warn_msg = self._cleanse_xmp_for_raw(
                    temp_xmp_path,
                    orf_path.name,
                    auto_aspect_crop=(auto_aspect_crop and "スキップ" not in aspect_info_str),
                    scale_x=scale_x,
                    offset_x=offset_x,
                    scale_y=scale_y,
                    offset_y=offset_y,
                    adjust_mask_coords=adjust_mask_coords
                )
            except Exception as e:
                result.errors.append(f"[XMP書換エラー] {dng_path.name}: {e}")
                if temp_xmp_path.exists():
                    temp_xmp_path.unlink()
                continue

            if not is_supported:
                # 要修正2: 対象外形式の場合は無言で成功にせず警告ログへ出し、一時ファイルを破棄
                msg = f"[未処理スキップ] {dng_path.name}: {warn_msg}"
                result.warnings.append(msg)
                result.logs.append(msg)
                if temp_xmp_path.exists():
                    temp_xmp_path.unlink()
                continue

            if warn_msg:
                result.warnings.append(f"[注意] {dng_path.name}: {warn_msg}")

            # Step 4: 既存の同名XMPがある場合は .xmp で終わらない名前でバックアップ
            if final_xmp_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = folder_path / f"{final_xmp_path.name}.bak_{timestamp}"
                shutil.copy2(final_xmp_path, backup_path)
                result.logs.append(f"[バックアップ] 既存XMPを退避: {backup_path.name}")

            # Step 5: Path.replace() で確実に上書き配置
            temp_xmp_path.replace(final_xmp_path)
            result.success_files.append(final_xmp_path.name)
            changes_str = ", ".join(modified_changes) if modified_changes else "変更なし"
            result.logs.append(f"[成功] {dng_path.name} -> {final_xmp_path.name} [{aspect_info_str}] ({changes_str})")

            # Step 6: 3条件（抽出成功＋RAW一致＋書換成功）を満たした場合のみごみ箱へ移動
            if trash_source_dng:
                if HAS_SEND2TRASH:
                    try:
                        send2trash(str(dng_path))
                        result.logs.append(f"[ごみ箱移動] {dng_path.name}")
                    except Exception as e:
                        result.errors.append(f"[ごみ箱移動失敗] {dng_path.name}: {e}")
                else:
                    result.errors.append("[警告] send2trash未導入のためDNG削除をスキップしました。")

        return result

    def _batch_read_metadata(self, file_paths: List[Path], result: ProcessResult) -> Dict[Path, ImageMeta]:
        """ExifToolのJSON出力で対象ファイルの寸法とOrientationを一括取得する"""
        meta_map: Dict[Path, ImageMeta] = {}
        if not file_paths:
            return meta_map

        # 引数長制限を避けるため100ファイルずつチャンク実行
        chunk_size = 100
        for i in range(0, len(file_paths), chunk_size):
            chunk = file_paths[i:i + chunk_size]
            cmd = [
                self.exiftool_path,
                "-charset", "filename=UTF8",
                "-j", "-n",
                "-ImageWidth", "-ImageHeight",
                "-OriginalDefaultFinalSize",
                "-ExifImageWidth", "-ExifImageHeight",
                "-Orientation",
                *[str(p) for p in chunk]
            ]
            try:
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                proc = subprocess.run(cmd, capture_output=True, check=False, creationflags=creationflags)
                if proc.stdout:
                    data_list = json.loads(proc.stdout.decode("utf-8", errors="replace"))
                    for item in data_list:
                        src = Path(item.get("SourceFile", "")).resolve()
                        w = int(item.get("ImageWidth") or item.get("ExifImageWidth") or 0)
                        h = int(item.get("ImageHeight") or item.get("ExifImageHeight") or 0)
                        orient = int(item.get("Orientation") or 1)

                        orig_w, orig_h = 0, 0
                        orig_str = str(item.get("OriginalDefaultFinalSize", "")).strip()
                        if " " in orig_str:
                            parts = orig_str.split()
                            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                                orig_w, orig_h = int(parts[0]), int(parts[1])

                        meta_map[src] = ImageMeta(
                            width=w, height=h,
                            orig_width=orig_w, orig_height=orig_h,
                            orientation=orient
                        )
            except Exception as e:
                result.warnings.append(f"[メタデータ一括取得警告] {e}")

        return meta_map

    def _compute_aspect_transform(
        self, dng_meta: ImageMeta, orf_meta: ImageMeta
    ) -> Tuple[float, float, float, float, str]:
        """
        DNG(JPG)とORF(RAW)の表示寸法から、X軸・Y軸それぞれの scale と offset を計算する。
        Muse仕様に基づき、Orientationを考慮した表示寸法で比較する。
        """
        jpg_w, jpg_h = dng_meta.get_effective_size()
        raw_w, raw_h = orf_meta.get_effective_size()

        # Orientation 5,6,7,8 は90度/270度回転（縦位置）
        is_vertical = (dng_meta.orientation in (5, 6, 7, 8)) or (orf_meta.orientation in (5, 6, 7, 8))
        if dng_meta.orig_width == 0 and jpg_w < jpg_h:
            is_vertical = True

        # センサー上の長辺・短辺に一度正規化（長辺=L, 短辺=S）
        jpg_L, jpg_S = max(jpg_w, jpg_h), min(jpg_w, jpg_h)
        raw_L, raw_S = max(raw_w, raw_h), min(raw_w, raw_h)

        # アスペクト比の人間向けラベル判定
        ratio = jpg_L / jpg_S if jpg_S > 0 else 1.333
        if abs(ratio - 1.5) < 0.03:
            aspect_name = "3:2"
        elif abs(ratio - (16.0 / 9.0)) < 0.04:
            aspect_name = "16:9"
        elif abs(ratio - 1.0) < 0.03:
            aspect_name = "1:1"
        elif abs(ratio - (4.0 / 3.0)) < 0.03:
            aspect_name = "4:3"
        else:
            aspect_name = f"{jpg_L}:{jpg_S}"

        orient_label = "縦" if is_vertical else "横"

        # センサー基準での長辺スケールと短辺スケール
        scale_L = min(1.0, jpg_L / raw_L) if raw_L > 0 else 1.0
        scale_S = min(1.0, jpg_S / raw_S) if raw_S > 0 else 1.0

        # 表示寸法ベースでのX軸(Left/Right)・Y軸(Top/Bottom)への割り当て
        # ※縦位置で座標軸がどちらのモデル（表示基準／センサー基準）かは
        #   実物サンプルでの実機確認が別途必要（REVIEW参照）
        if is_vertical:
            # 縦位置: 表示上のX軸(左右)が短辺(S)、Y軸(上下)が長辺(L)
            scale_x, scale_y = scale_S, scale_L
        else:
            # 横位置: 表示上のX軸(左右)が長辺(L)、Y軸(上下)が短辺(S)
            scale_x, scale_y = scale_L, scale_S

        offset_x = (1.0 - scale_x) / 2.0
        offset_y = (1.0 - scale_y) / 2.0

        info_str = f"{orient_label} {aspect_name} (offX={offset_x:.4f}, offY={offset_y:.4f})"
        return scale_x, offset_x, scale_y, offset_y, info_str

    def _extract_xmp_single(self, dng_path: Path, out_xmp_path: Path, result: ProcessResult) -> bool:
        """shellを通さず引数リスト形式で1ファイルずつExifToolを呼び出す"""
        cmd = [
            self.exiftool_path,
            "-charset", "filename=UTF8",
            "-xmp", "-b",
            str(dng_path)
        ]
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            proc = subprocess.run(cmd, capture_output=True, check=False, creationflags=creationflags)
            if proc.returncode != 0 or not proc.stdout:
                err_text = proc.stderr.decode("utf-8", errors="replace").strip()
                result.errors.append(f"[抽出失敗] {dng_path.name}: {err_text}")
                return False

            out_xmp_path.write_bytes(proc.stdout)
            return True
        except Exception as e:
            result.errors.append(f"[ExifTool実行エラー] {dng_path.name}: {e}")
            return False

    def _cleanse_xmp_for_raw(
        self,
        xmp_path: Path,
        target_orf_name: str,
        auto_aspect_crop: bool = True,
        scale_x: float = 1.0,
        offset_x: float = 0.0,
        scale_y: float = 1.0,
        offset_y: float = 0.0,
        adjust_mask_coords: bool = False
    ) -> Tuple[bool, List[str], str]:
        """
        戻り値: (is_supported: bool, changes: List[str], warning_message: str)
        """
        raw_bytes = xmp_path.read_bytes()
        content = raw_bytes.decode("utf-8")
        changes: List[str] = []
        warn_msg = ""

        # 要修正3: 二重適用チェック
        already_synced = (self.MARKER_ATTR in content)
        if already_synced:
            return True, ["変換済みXMPのためスキップ"], ""

        # 要修正2: 対象外構造の検査
        # (1) 要素形式の <crs:CropTop> 等が含まれている場合は未対応として弾く
        if re.search(r"<crs:Crop(?:Top|Left|Bottom|Right|Angle)>", content):
            return False, [], "Cropタグが要素形式(<crs:Crop...>)のため未対応"

        # (2) crs:HasCrop 属性自体が存在しないXMPは未対応として弾く
        if 'crs:HasCrop="' not in content and "<crs:HasCrop>" not in content:
            return False, [], "crs:HasCrop属性が存在しないXMP形式のため未対応"

        # 1. dc:format の削除（属性形式・要素形式の両対応）
        new_content, n1 = re.subn(r'\s+dc:format="image/[^"]*"', '', content)
        new_content, n2 = re.subn(r'\s*<dc:format>image/[^<]*</dc:format>', '', new_content)
        if (n1 + n2) > 0:
            content = new_content
            changes.append("dc:format削除")

        # 2. crs:AlreadyApplied="True" -> "False"
        new_content, n = re.subn(r'crs:AlreadyApplied="True"', 'crs:AlreadyApplied="False"', content)
        if n > 0:
            content = new_content
            changes.append("AlreadyApplied=False")

        # 3. crs:CameraProfile="Embedded" と CameraProfileDigest の削除
        if 'crs:CameraProfile="Embedded"' in content:
            content = re.sub(r'\s+crs:CameraProfile="Embedded"', '', content)
            content = re.sub(r'\s+crs:CameraProfileDigest="[^"]*"', '', content)
            changes.append("EmbeddedProfile削除")

        # 4. WBがCustomかつ絶対値(crs:Temperature)が無い場合は As Shot へ変更
        if 'crs:WhiteBalance="Custom"' in content and 'crs:Temperature=' not in content:
            content = content.replace('crs:WhiteBalance="Custom"', 'crs:WhiteBalance="As Shot"')
            changes.append("WB=As Shot補正")

        # 5. JPG固有の寸法・ダイジェストタグ削除（属性形式・要素形式の両対応）
        for tag in [
            "tiff:ImageWidth", "tiff:ImageLength",
            "exif:PixelXDimension", "exif:PixelYDimension",
            "photoshop:EmbeddedXMPDigest"
        ]:
            new_content, n_attr = re.subn(rf'\s+{tag}="[^"]*"', '', content)
            new_content, n_elem = re.subn(rf'\s*<{tag}>[^<]*</{tag}>', '', new_content)
            if (n_attr + n_elem) > 0:
                content = new_content
                changes.append(f"{tag}削除")

        # 6. crs:RawFileName がある場合は対象の .ORF 名に書き換え
        if 'crs:RawFileName="' in content:
            content = re.sub(
                r'crs:RawFileName="[^"]*"',
                f'crs:RawFileName="{target_orf_name}"',
                content
            )
            changes.append(f"RawFileName={target_orf_name}")

        # 7. Crop（切り抜き）座標の検査と変換
        crop_keys = ["CropTop", "CropLeft", "CropBottom", "CropRight"]
        found_crops = {k: re.search(rf'crs:{k}="([0-9.+-]+)"', content) for k in crop_keys}
        present_count = sum(1 for m in found_crops.values() if m is not None)

        # 要修正2: 4つの座標のうち一部だけ存在する破損状態はエラーとしてスキップ
        if 0 < present_count < 4:
            return False, [], f"Crop座標が一部欠損しています(4個中{present_count}個のみ存在)"

        needs_aspect_shift = (abs(offset_x) > 1e-4) or (abs(offset_y) > 1e-4)

        if present_count == 4:
            # パターンB: 既に手動トリミングされている場合
            if auto_aspect_crop and needs_aspect_shift:
                old_top = float(found_crops["CropTop"].group(1))
                old_bottom = float(found_crops["CropBottom"].group(1))
                old_left = float(found_crops["CropLeft"].group(1))
                old_right = float(found_crops["CropRight"].group(1))

                new_top = offset_y + (old_top * scale_y)
                new_bottom = offset_y + (old_bottom * scale_y)
                new_left = offset_x + (old_left * scale_x)
                new_right = offset_x + (old_right * scale_x)

                content = re.sub(r'crs:CropTop="[0-9.+-]+"', f'crs:CropTop="{new_top:.6f}"', content)
                content = re.sub(r'crs:CropBottom="[0-9.+-]+"', f'crs:CropBottom="{new_bottom:.6f}"', content)
                content = re.sub(r'crs:CropLeft="[0-9.+-]+"', f'crs:CropLeft="{new_left:.6f}"', content)
                content = re.sub(r'crs:CropRight="[0-9.+-]+"', f'crs:CropRight="{new_right:.6f}"', content)
                changes.append("既存Crop座標変換")
            content = content.replace('crs:HasCrop="False"', 'crs:HasCrop="True"')
        else:
            # パターンA: 未トリミング（HasCrop="False"）の場合
            if auto_aspect_crop and needs_aspect_shift:
                crop_attrs = (
                    f'crs:CropTop="{offset_y:.6f}"\n'
                    f'   crs:CropLeft="{offset_x:.6f}"\n'
                    f'   crs:CropBottom="{1.0 - offset_y:.6f}"\n'
                    f'   crs:CropRight="{1.0 - offset_x:.6f}"\n'
                    f'   crs:CropAngle="0"\n'
                    f'   crs:CropConstrainToWarp="0"\n'
                    f'   crs:HasCrop="True"'
                )
                content = content.replace('crs:HasCrop="False"', crop_attrs)
                changes.append("初期画角Crop注入")
            else:
                changes.append("4:3ネイティブ(Crop注入不要)")

        # 8. 改善提案5: マスク座標の変換または警告出力
        has_masks = "<crs:MaskGroupBasedCorrections>" in content
        if has_masks and auto_aspect_crop and needs_aspect_shift:
            if adjust_mask_coords:
                # ZeroX, FullX を X軸変換、ZeroY, FullY を Y軸変換
                for x_tag in ["ZeroX", "FullX"]:
                    content = re.sub(
                        rf'crs:{x_tag}="([0-9.+-]+)"',
                        lambda m: f'crs:{x_tag}="{offset_x + float(m.group(1)) * scale_x:.6f}"',
                        content
                    )
                for y_tag in ["ZeroY", "FullY"]:
                    content = re.sub(
                        rf'crs:{y_tag}="([0-9.+-]+)"',
                        lambda m: f'crs:{y_tag}="{offset_y + float(m.group(1)) * scale_y:.6f}"',
                        content
                    )
                changes.append("マスク座標変換")
            else:
                warn_msg = "マスクが含まれています（マスク位置補正OFFのため最大約5.6%ズレる可能性があります）"

        # 9. 要修正3: 二重適用防止マーカーの注入
        if self.MARKER_NS not in content:
            content = content.replace(
                'xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"',
                f'xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"\n    {self.MARKER_NS}'
            )
        content = content.replace(
            'crs:HasSettings="True"',
            f'crs:HasSettings="True"\n   {self.MARKER_ATTR}'
        )

        # 改善提案6: WindowsでのCRLF化を防ぐため write_bytes でUTF-8バイナリ書き戻し
        xmp_path.write_bytes(content.encode("utf-8"))
        return True, changes, warn_msg
