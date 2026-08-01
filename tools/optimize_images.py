"""掲載中の写真を再圧縮して軽くする。

なぜ:
  記事ページの LCP（一番大きい要素が描画されるまでの時間）を決めるのは
  ほぼヒーロー写真1枚。2026-08-01 時点で static/img は 348枚 40.2MB、
  中央値 169KB、200KB超が 98枚あった。Flux が返す JPEG は品質が高すぎて、
  Web 配信には過剰。品質85で再圧縮すると実測で 193KB → 77KB（40%）まで
  落ちて、目視では劣化が分からない。

やること:
  ・JPEG を quality=85 / optimize / progressive で再圧縮する
  ・縦横比とピクセル寸法は一切変えない（写真を平体・長体にしない）
  ・削減が小さいものは元のまま残す。既に圧縮済みの画像を作り直しても
    画質を捨てるだけで得がないため
  ・progressive にするのは、読み込み途中でも全体像が先に出るため
    （体感の待ち時間が短くなる）

実行:
    python3 tools/optimize_images.py          # 実行
    python3 tools/optimize_images.py --dry    # 何がどれだけ減るか見るだけ
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "static" / "img"

QUALITY = 85
# これ未満しか減らないなら触らない（再圧縮のたびに画質は落ちるため）
MIN_SAVING = 0.10


def main() -> int:
    dry = "--dry" in sys.argv
    files = sorted(IMG_DIR.glob("*.jpg")) + sorted(IMG_DIR.glob("*.jpeg"))
    if not files:
        print("対象の JPEG がありません")
        return 0

    before = after = 0
    changed = skipped = failed = 0

    for f in files:
        orig = f.stat().st_size
        before += orig
        try:
            with Image.open(f) as im:
                size = im.size
                # 透過やパレットが混ざっていても JPEG として保存できる形に揃える
                im = im.convert("RGB") if im.mode != "RGB" else im.copy()
        except Exception as e:
            print(f"  ⚠️ 読めません {f.name}: {e}")
            failed += 1
            after += orig
            continue

        tmp = f.with_suffix(f.suffix + ".opt")
        try:
            im.save(tmp, "JPEG", quality=QUALITY, optimize=True, progressive=True)
        except Exception as e:
            print(f"  ⚠️ 保存に失敗 {f.name}: {e}")
            tmp.unlink(missing_ok=True)
            failed += 1
            after += orig
            continue

        new = tmp.stat().st_size
        if new >= orig * (1 - MIN_SAVING):
            tmp.unlink()
            skipped += 1
            after += orig
            continue

        # 寸法が変わっていないことを確かめてから差し替える。
        # 縦横比が変わった画像を公開すると人物や図が歪む。
        with Image.open(tmp) as check:
            if check.size != size:
                print(f"  ⚠️ 寸法が変わったので中止 {f.name}: {size} → {check.size}")
                tmp.unlink()
                failed += 1
                after += orig
                continue

        if dry:
            tmp.unlink()
        else:
            tmp.replace(f)
        after += new
        changed += 1

    mb = 1024 * 1024
    print(f"{'（試算）' if dry else ''}"
          f"再圧縮 {changed}枚 / 据え置き {skipped}枚 / 失敗 {failed}枚")
    print(f"合計 {before/mb:.1f}MB → {after/mb:.1f}MB "
          f"（{(1 - after/before)*100:.0f}% 削減）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
