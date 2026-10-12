#!/usr/bin/env python3
"""
shrink_assets.py
파이프라인 끝단 자동 축소 — 업로드 딜레이·Drive 부담 감소

무엇을 줄이나:
  1. 그림책 PPTX: 임베드된 2MB급 PNG를 JPEG(q85)로 재압축 (34MB → 수 MB)
     - 투명 알파가 실제로 쓰인 이미지는 PNG 그대로 보존
     - 변환 후 python-pptx로 열어 구조 검증 → 통과해야만 원본 교체
  2. 에피소드 폴더의 잔여 batch_images_*.jsonl 삭제 (편당 수십 MB)

통합 지점:
  - 08_generate_book_pptx.py: save 직후 자동 호출 (새 산출물은 태생부터 작게)
  - publish_youtube.py: Drive 업로드 직전 자동 호출 (기존 산출물 안전망)

사용법 (단독 실행):
  python shrink_assets.py --dir output/bsl01        # 한 에피소드
  python shrink_assets.py --all                     # output/* 전체 일괄
  python shrink_assets.py --all --dry-run           # 예상 절감만 출력
"""

import argparse
import io
import shutil
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

JPEG_QUALITY = 85
MAX_PX       = 1600          # 긴 변 상한 (원본 1344px는 그대로 통과)
MIN_BYTES    = 300 * 1024    # 이보다 작은 이미지는 건드리지 않음


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f}MB"


def _has_real_alpha(im) -> bool:
    """실제로 투명 픽셀이 있는지 (알파 채널 존재만으로 판단하지 않음)."""
    if im.mode == "P":
        im = im.convert("RGBA")
    if "A" not in im.getbands():
        return False
    lo, _hi = im.getchannel("A").getextrema()
    return lo < 255


def shrink_pptx(pptx_path: Path, quality: int = JPEG_QUALITY,
                max_px: int = MAX_PX, dry_run: bool = False) -> tuple[int, int]:
    """PPTX 내부 미디어 PNG → JPEG 재압축. (원본크기, 결과크기) 반환.

    zip을 통째로 다시 쓰면서 media/*.png를 JPEG로 바꾸고,
    모든 XML/rels의 참조 파일명과 [Content_Types].xml을 함께 갱신한다.
    결과물은 python-pptx로 열어 검증 후에만 원본을 교체한다.
    """
    from PIL import Image

    pptx_path = Path(pptx_path)
    src_size = pptx_path.stat().st_size

    rename = {}   # 'ppt/media/image3.png' -> 'ppt/media/image3.jpeg'
    blobs = {}    # 최종 zip 항목

    with zipfile.ZipFile(pptx_path) as zin:
        for info in zin.infolist():
            name = info.filename
            data = zin.read(name)
            if ("/media/" in name and name.lower().endswith(".png")
                    and len(data) >= MIN_BYTES):
                try:
                    im = Image.open(io.BytesIO(data))
                    if not _has_real_alpha(im):
                        im = im.convert("RGB")
                        if max(im.size) > max_px:
                            im.thumbnail((max_px, max_px), Image.LANCZOS)
                        buf = io.BytesIO()
                        im.save(buf, "JPEG", quality=quality, optimize=True)
                        jpg = buf.getvalue()
                        if len(jpg) < len(data):
                            new_name = name[:-4] + ".jpeg"
                            rename[name] = new_name
                            blobs[new_name] = jpg
                            continue
                except Exception as e:
                    print(f"  [WARN] {name} 변환 실패, 원본 유지: {e}")
            blobs[name] = data

    if not rename:
        return src_size, src_size

    # XML/rels 참조 갱신 (media/imageN.png → media/imageN.jpeg)
    base_map = {old.rsplit("/", 1)[-1]: new.rsplit("/", 1)[-1]
                for old, new in rename.items()}
    for name in list(blobs):
        if name.endswith((".xml", ".rels")):
            txt = blobs[name].decode("utf-8")
            for ob, nb in base_map.items():
                txt = txt.replace("media/" + ob, "media/" + nb)
            if name == "[Content_Types].xml" and 'Extension="jpeg"' not in txt:
                txt = txt.replace(
                    "</Types>",
                    '<Default Extension="jpeg" ContentType="image/jpeg"/></Types>')
            blobs[name] = txt.encode("utf-8")

    if dry_run:
        est = sum(len(v) for v in blobs.values())
        return src_size, est

    tmp = pptx_path.with_name(pptx_path.name + ".shrink_tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in blobs.items():
            zout.writestr(name, data)

    # 구조 검증 — 열리지 않으면 원본을 건드리지 않는다
    try:
        from pptx import Presentation
        Presentation(str(tmp))
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(f"  [WARN] 축소본 검증 실패, 원본 유지: {e}")
        return src_size, src_size

    shutil.move(str(tmp), str(pptx_path))
    return src_size, pptx_path.stat().st_size


def clean_episode_junk(ep_dir: Path, dry_run: bool = False) -> int:
    """잔여 batch_images_*.jsonl 삭제. 확보한 바이트 수 반환."""
    freed = 0
    for p in Path(ep_dir).glob("batch_images_*.jsonl"):
        freed += p.stat().st_size
        if not dry_run:
            p.unlink()
    return freed


def shrink_episode(ep_dir: Path, dry_run: bool = False, verbose: bool = True) -> int:
    """한 에피소드 폴더의 산출물 축소. 절감 바이트 수 반환."""
    ep_dir = Path(ep_dir)
    saved = 0
    for pptx in sorted(ep_dir.glob("*.pptx")):
        old, new = shrink_pptx(pptx, dry_run=dry_run)
        if new < old:
            saved += old - new
            if verbose:
                tag = "(dry-run) " if dry_run else ""
                print(f"  [PPTX] {tag}{pptx.name}: {_mb(old)} → {_mb(new)}")
    junk = clean_episode_junk(ep_dir, dry_run=dry_run)
    if junk and verbose:
        tag = "(dry-run) " if dry_run else ""
        print(f"  [JSONL] {tag}잔여 배치 파일 정리: {_mb(junk)}")
    return saved + junk


def main():
    ap = argparse.ArgumentParser(description="파이프라인 끝단 산출물 자동 축소")
    ap.add_argument("--dir", type=str, help="에피소드 폴더 (예: output/bsl01)")
    ap.add_argument("--all", action="store_true", help="output/* 전체 일괄")
    ap.add_argument("--dry-run", action="store_true", help="변경 없이 예상 절감만")
    args = ap.parse_args()

    if args.dir:
        targets = [Path(args.dir)]
    elif args.all:
        targets = sorted(p for p in Path("output").iterdir() if p.is_dir())
    else:
        ap.error("--dir 또는 --all 필요")

    total = 0
    for ep in targets:
        print(f"[{ep.name}]")
        total += shrink_episode(ep, dry_run=args.dry_run)
    print()
    print(f"총 절감: {_mb(total)}" + (" (dry-run, 실제 변경 없음)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
