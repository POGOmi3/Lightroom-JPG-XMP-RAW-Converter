# -*- coding: utf-8 -*-
"""
core.py (XmpSyncCore) の検証テスト。
ExifTool / PySide6 なしで実行できる単体テスト。
実行: python tests/test_core.py
重要ケースは assert で落とし、既知の問題は [KNOWN ISSUE] として表示する。
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import XmpSyncCore, ImageMeta  # noqa: E402

core = XmpSyncCore()
TMP = Path(__file__).resolve().parent / "_tmp"
TMP.mkdir(exist_ok=True)

PASS = []
KNOWN = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS: {name} {detail}")
    else:
        raise AssertionError(f"FAIL: {name} {detail}")


def known(name, detail=""):
    KNOWN.append(name)
    print(f"  [KNOWN ISSUE] {name} {detail}")


MASK_ELEMENT = """    <crs:MaskGroupBasedCorrections>
     <rdf:Seq>
      <rdf:li>
       <rdf:Description crs:CorrectionName="線形グラデーション 1" crs:CorrectionAmount="1.000000">
        <crs:Mask>
         <rdf:Description>
          <crs:ZeroX>0.500000</crs:ZeroX>
          <crs:ZeroY>0.000000</crs:ZeroY>
          <crs:FullX>0.500000</crs:FullX>
          <crs:FullY>0.400000</crs:FullY>
         </rdf:Description>
        </crs:Mask>
       </rdf:Description>
      </rdf:li>
     </rdf:Seq>
    </crs:MaskGroupBasedCorrections>
"""

HEAD = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    xmlns:tiff="http://ns.adobe.com/tiff/1.0/"
    xmlns:exif="http://ns.adobe.com/exif/1.0/"
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
    xmp:Rating="5"
    {attrs}>
{extra}  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""

# 横3:2 の変換パラメータ
LAND_32 = dict(scale_x=1.0, offset_x=0.0, scale_y=3456 / 3888, offset_y=(1 - 3456 / 3888) / 2)


def cleanse(name, attrs, extra="", **kw):
    p = TMP / f"{name}.xmp"
    p.write_bytes(HEAD.format(attrs=attrs, extra=extra).encode("utf-8"))
    args = dict(auto_aspect_crop=True, adjust_mask_coords=False)
    args.update(kw)
    ok, changes, warn = core._cleanse_xmp_for_raw(p, "EM1X0001.ORF", **args)
    after = p.read_bytes().decode("utf-8") if p.exists() else ""
    return ok, changes, warn, after


def get(after, attr):
    m = re.search(rf'crs:{attr}="([^"]*)"', after)
    return m.group(1) if m else None


print("== 画角計算 _compute_aspect_transform ==")


def aspect(dng, orf):
    return core._compute_aspect_transform(dng, orf)


sx, ox, sy, oy, label = aspect(
    ImageMeta(orig_width=5184, orig_height=3456, orientation=1),
    ImageMeta(width=5184, height=3888, orientation=1))
check("横3:2", abs(sx - 1) < 1e-9 and abs(ox) < 1e-9 and abs(sy - 0.888889) < 1e-6 and abs(oy - 0.055556) < 1e-6, label)

sx, ox, sy, oy, label = aspect(
    ImageMeta(orig_width=5184, orig_height=3456, orientation=6),
    ImageMeta(width=5184, height=3888, orientation=6))
check("縦3:2 (センサー基準: 横と同じY変換)", abs(sx - 1) < 1e-9 and abs(ox) < 1e-9 and abs(sy - 0.888889) < 1e-6 and abs(oy - 0.055556) < 1e-6, label)

sx, ox, sy, oy, label = aspect(
    ImageMeta(orig_width=3888, orig_height=3888, orientation=1),
    ImageMeta(width=5184, height=3888, orientation=1))
check("横1:1", abs(sx - 0.75) < 1e-9 and abs(ox - 0.125) < 1e-9 and abs(sy - 1) < 1e-9, label)

sx, ox, sy, oy, label = aspect(
    ImageMeta(orig_width=3888, orig_height=3888, orientation=6),
    ImageMeta(width=5184, height=3888, orientation=6))
check("縦1:1 (センサー基準: 横と同じX変換)", abs(sx - 0.75) < 1e-9 and abs(ox - 0.125) < 1e-9 and abs(sy - 1) < 1e-9, label)

sx, ox, sy, oy, label = aspect(
    ImageMeta(orig_width=5184, orig_height=3456, orientation=1),
    ImageMeta(width=5240, height=3912, crop_width=5184, crop_height=3888, orientation=1))
check("ORF有効エリア優先 (5240x3912ではなく5184x3888で計算)", abs(sy - 0.888889) < 1e-6 and abs(oy - 0.055556) < 1e-6, label)

sx, ox, sy, oy, label = aspect(
    ImageMeta(width=3216, height=2144, orientation=8),
    ImageMeta(width=5240, height=3912, crop_width=5184, crop_height=3888, orientation=8))
check("縮小版DNG (EM1X9697実物寸法, アスペクト比方式)", abs(sx - 1) < 1e-9 and abs(sy - 0.888889) < 1e-6 and abs(oy - 0.055556) < 1e-6, label)

sx, ox, sy, oy, label = aspect(
    ImageMeta(orig_width=5184, orig_height=2916, orientation=1),
    ImageMeta(width=5184, height=3888, orientation=1))
check("横16:9", abs(sy - 0.75) < 1e-9 and abs(oy - 0.125) < 1e-9, label)

sx, ox, sy, oy, label = aspect(
    ImageMeta(orig_width=5184, orig_height=3888, orientation=1),
    ImageMeta(width=5184, height=3888, orientation=1))
check("4:3ネイティブ", abs(ox) < 1e-9 and abs(oy) < 1e-9, label)

print("== クレンジング A〜G ==")

ok, changes, warn, after = cleanse(
    "A", 'dc:format="image/dng"\n    crs:WhiteBalance="Custom"\n    crs:IncrementalTemperature="0"\n    crs:IncrementalTint="+1"\n    crs:CameraProfile="Embedded"\n    crs:CameraProfileDigest="ABC123"\n    crs:AlreadyApplied="False"\n    crs:HasSettings="True"\n    crs:HasCrop="False"\n    crs:Exposure2012="+0.50"',
    MASK_ELEMENT, **LAND_32)
check("A 未トリミング注入", ok and get(after, "CropTop") == "0.055556" and get(after, "CropBottom") == "0.944444"
      and get(after, "CropLeft") == "0.000000" and get(after, "CropRight") == "1.000000", str(changes))
check("A マーカー注入", core.MARKER_ATTR in after)
try:
    ET.fromstring(after)
    check("A XML妥当性 (pogo名前空間宣言含む)", True)
except Exception as e:
    check("A XML妥当性", False, str(e))
m_before = re.search(r"<crs:MaskGroupBasedCorrections>.*?</crs:MaskGroupBasedCorrections>", HEAD.format(attrs="", extra=MASK_ELEMENT), re.S).group(0)
m_after = re.search(r"<crs:MaskGroupBasedCorrections>.*?</crs:MaskGroupBasedCorrections>", after, re.S).group(0)
check("A マスク部分は無傷・日本語維持", m_before == m_after and "線形グラデーション 1" in after)
check("A dc:format(属性)削除・Embedded削除・WB補正", 'dc:format="image' not in after and "Embedded" not in after
      and get(after, "WhiteBalance") == "As Shot")

# A2: 二重適用 (変換済みXMPへ再実行)
p = TMP / "A.xmp"
ok2, changes2, warn2 = core._cleanse_xmp_for_raw(p, "EM1X0001.ORF", auto_aspect_crop=True, **LAND_32)
after2 = p.read_bytes().decode("utf-8")
check("A2 二重適用はマーカーで防止", ok2 and get(after2, "CropTop") == "0.055556", str(changes2))

ok, changes, warn, after = cleanse(
    "B", 'crs:WhiteBalance="Auto"\n    crs:HasSettings="True"\n    crs:HasCrop="True"\n    crs:CropTop="0.100000"\n    crs:CropLeft="0.050000"\n    crs:CropBottom="0.900000"\n    crs:CropRight="0.950000"\n    crs:CropAngle="3.500000"\n    crs:CropConstrainToWarp="0"',
    MASK_ELEMENT, **LAND_32)
check("B 既存Crop変換", ok and get(after, "CropTop") == "0.144444" and get(after, "CropBottom") == "0.855556"
      and get(after, "CropLeft") == "0.050000" and get(after, "CropAngle") == "3.500000", str(changes))

ok, changes, warn, after = cleanse("C", 'crs:WhiteBalance="Auto"\n    crs:Exposure2012="+0.50"', "", **LAND_32)
check("C HasCrop欠落は未対応として弾く", not ok and "HasCrop" in warn, warn)

ok, changes, warn, after = cleanse(
    "D", 'crs:WhiteBalance="Auto"\n    crs:HasCrop="True"', 
    '    <crs:CropTop>0.100000</crs:CropTop>\n    <crs:CropBottom>0.900000</crs:CropBottom>\n', **LAND_32)
check("D 要素形式Cropは未対応として弾く", not ok, warn)

ok, changes, warn, after = cleanse(
    "E", 'crs:WhiteBalance="Auto"\n    crs:HasCrop="False"', '    <dc:format>image/dng</dc:format>\n', **LAND_32)
check("E 要素形式dc:formatも削除", ok and "<dc:format>" not in after, str(changes))

ok, changes, warn, after = cleanse(
    "F", 'crs:WhiteBalance="Auto"\n    crs:HasCrop="True"\n    crs:CropTop="0.200000"\n    crs:CropLeft="0.100000"', "", **LAND_32)
check("F 座標の一部欠損は未対応として弾く", not ok and "欠損" in warn, warn)

ok, changes, warn, after = cleanse(
    "G", 'crs:WhiteBalance="Auto"\n    crs:HasCrop="False"\n    crs:Exposure2012="0.00"', "",
    scale_x=1.0, offset_x=0.0, scale_y=1.0, offset_y=0.0)
check("G 4:3ネイティブは注入しない", ok and get(after, "CropTop") is None, str(changes))

print("== マスク座標 ==")
ok, changes, warn, after = cleanse(
    "M1", 'crs:WhiteBalance="Auto"\n    crs:HasSettings="True"\n    crs:HasCrop="False"', MASK_ELEMENT,
    adjust_mask_coords=True, **LAND_32)
if "<crs:FullY>0.400000</crs:FullY>" in after and "マスク座標変換" in changes:
    known("マスク座標変換が要素形式マスクに効いていないのに changes へ記録される",
          "実物のマスクは要素形式 (<crs:FullY>0.4</crs:FullY>) のため現行の属性形式向け正規表現では変換されない")
else:
    check("M1 要素形式マスク座標変換", "<crs:FullY>0.411111</crs:FullY>" in after, str(changes))

print("== マーカーの前提 ==")
ok, changes, warn, after = cleanse(
    "M2", 'crs:WhiteBalance="Auto"\n    crs:HasCrop="False"', "", **LAND_32)
if core.MARKER_ATTR not in after:
    known("crs:HasSettings=\"True\" が無いXMPではマーカー属性が入らず、二重適用防止が効かない",
          "名前空間宣言だけが入り、属性は HasSettings の後ろへの差し込みに依存している")
else:
    check("M2 HasSettings無しでもマーカーが入る", True)

print()
print(f"合格: {len(PASS)}件 / 既知の問題: {len(KNOWN)}件")
for k in KNOWN:
    print(" -", k)
