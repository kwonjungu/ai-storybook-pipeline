#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_crop_thumb_c_bg.py
thumbnail_c_bg.png 를 '상반신 클로즈업 + 오른쪽 텍스트 자리' 구도로 결정적으로 재조립한다.

왜 이렇게까지 하나 (2026-09-13):
  스타일 C 규칙은 "두 주인공 상반신 클로즈업, 캐릭터는 왼쪽, 오른쪽은 텍스트 자리"인데
  실제 c_bg 26장 중 21장이 전신샷이었다. 프롬프트를 아무리 세게 써도
  ("다리·발은 프레임 밖", "머리만 그려라") 이미지 모델이 계속 전신을 그린다.
  레퍼런스로 붙이는 캐릭터 시트가 전신이라 그 구도로 끌려가는 것으로 보인다.
  4라운드 재생성 실험에서도 4번 다 전신 → 생성 단계에서 싸우는 걸 포기하고 후처리로 확정한다.

방법:
  1) rembg 로 캐릭터만 누끼 (11_animate_scenes 가 쓰는 것과 같은 라이브러리)
  2) 캐릭터 바운딩박스의 위쪽 UPPER_RATIO 만 남긴다 (= 가슴에서 잘린 상반신)
  3) 원본 오른쪽 빈 영역의 색을 행마다 샘플링해 같은 팔레트의 깨끗한 배경을 다시 만든다
  4) 상반신을 왼쪽(CHAR_CENTER_X)에 두고 프레임 아래 모서리에 걸치게 배치 → 1920x1080 저장
  원본은 thumbnail_c_bg_full.png 로 보존 (--restore 로 되돌림)

  python _crop_thumb_c_bg.py --only 알에서
  python _crop_thumb_c_bg.py --from-audit --audit-json _thumb_c_audit_v2.json
  python _crop_thumb_c_bg.py --all
  python _crop_thumb_c_bg.py --restore --all
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageFilter

OUT_W, OUT_H = 1920, 1080
BG_NAME = "thumbnail_c_bg.png"
FULL_NAME = "thumbnail_c_bg_full.png"
LANG_SUFFIXES = ("_en", "_id", "_pt", "_es")

HEAD_TOP = 0.10         # 머리 꼭대기가 놓일 세로 위치 (프레임 높이 대비)
GROUP_W = 0.74          # 캐릭터 무리가 차지할 가로 비율 (나머지 오른쪽이 텍스트 자리)
GROUP_H_MAX = 1.02      # 무리 높이가 프레임 높이의 이 배율을 넘으면 높이에 맞춰 축소
GAP = 0.015             # 두 캐릭터 사이 간격 (프레임 가로 대비)
LEFT_MARGIN = 0.03      # 왼쪽 여백
UPPER_KEEP = 0.78       # 무리 높이 중 남길 위쪽 비율 (아래 = 다리·발, 잘라냄)
_session = None
# 2026-09-14 00:00 (KST) 이후 mtime = 오늘 새벽 배치로 덮인 c_bg
REGEN_CUTOFF = __import__('datetime').datetime(2026, 9, 14, 0, 0).timestamp()


def cutout(img: Image.Image) -> Image.Image:
    """rembg 로 캐릭터만 남긴 RGBA."""
    global _session
    from rembg import remove, new_session
    if _session is None:
        _session = new_session("isnet-general-use")
    return remove(img, session=_session).convert("RGBA")


def rebuild_background(img: Image.Image, alpha=None) -> Image.Image:
    """원본과 같은 팔레트의 깨끗한 배경을 다시 만든다.

    가운데 영역은 캐릭터(그리고 렌더본을 쓸 땐 텍스트)가 있어 샘플로 못 쓴다.
    → 위쪽 띠와 아래쪽 띠를 '열별'로 뽑아 세로로 보간한다. 가로 변화(햇빛 등)는 살고
      캐릭터·글자는 섞이지 않는다.
    """
    W, H = img.size
    src = img.convert("RGB")
    band = max(4, int(H * 0.07))
    top = src.crop((0, 0, W, band)).resize((OUT_W, 1), Image.LANCZOS)
    bot = src.crop((0, H - band, W, H)).resize((OUT_W, 1), Image.LANCZOS)
    strip = Image.new("RGB", (OUT_W, 2))
    strip.paste(top, (0, 0))
    strip.paste(bot, (0, 1))
    bg = strip.resize((OUT_W, OUT_H), Image.BICUBIC)
    return bg.filter(ImageFilter.GaussianBlur(18))


def split_characters(rgba):
    """알파 마스크의 연결 성분 = 개별 캐릭터. 큰 것부터 최대 3개를 잘라 돌려준다.

    두 주인공이 멀찍이 떨어져 그려지면(원본 대부분이 그렇다) 그 사이 빈 배경 때문에
    무리 전체가 가로로 넓어져 크게 키울 수 없다. → 각자 잘라내 어깨를 붙여 다시 배치한다.
    """
    import numpy as np
    from scipy import ndimage

    a = np.array(rgba.getchannel("A"))
    lab, n = ndimage.label(a > 24)
    if n == 0:
        return []
    sizes = ndimage.sum(a > 24, lab, range(1, n + 1))
    order = sorted(range(1, n + 1), key=lambda i: -sizes[i - 1])
    # 렌더본을 소스로 쓰면 제목 글자(흰색+검은 테두리)도 성분으로 잡힌다.
    # 캐릭터는 색이 있고 글자는 무채색 → 성분 평균 채도로 걸러낸다.
    rgb = np.array(rgba.convert("RGB")).astype("float32")
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)

    parts = []
    biggest = sizes[order[0] - 1]
    for idx in order[:4]:
        if sizes[idx - 1] < biggest * 0.12:      # 부스러기 제외
            continue
        m = lab == idx
        if float(sat[m].mean()) < 0.13:          # 무채색 덩어리 = 글자
            continue
        ys, xs = np.where(lab == idx)
        box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        piece = rgba.crop(box)
        # 다른 성분이 섞여 들어온 부분은 지운다
        m = (lab[box[1]:box[3], box[0]:box[2]] == idx).astype("uint8") * 255
        from PIL import Image as _I
        piece.putalpha(_I.fromarray(np.minimum(np.array(piece.getchannel("A")), m)))
        parts.append((box[0], piece))
    parts.sort(key=lambda t: t[0])               # 원래 좌우 순서 유지
    return [p for _, p in parts]


def recompose(src: Path, dst: Path, mask_right: bool = False) -> bool:
    from PIL import Image as _I
    img = Image.open(src).convert("RGB")

    # 렌더본을 소스로 써도 마스킹하지 않는다: 오른쪽 제목 글자는 획마다 작은 성분이라
    # split_characters 의 크기 필터(가장 큰 성분의 12% 미만 제외)에서 걸러진다.
    # 예전엔 오른쪽을 통째로 가렸다가 캐릭터(토토)까지 잘려 세로로 싹둑 잘린 썸네일이 나왔다.
    rgba = cutout(img)
    if not rgba.getchannel("A").getbbox():
        print("    [SKIP] 캐릭터를 분리하지 못함")
        return False

    parts = split_characters(rgba)
    if not parts:
        print("    [SKIP] 캐릭터 성분 없음")
        return False

    # 어깨를 붙여 한 덩어리로 (사이 빈 배경 제거) — 바닥 정렬
    gap_px = int(OUT_W * GAP)
    group_w = sum(p.width for p in parts) + gap_px * (len(parts) - 1)
    group_h = max(p.height for p in parts)
    group = _I.new("RGBA", (group_w, group_h), (0, 0, 0, 0))
    x = 0
    for p in parts:
        group.paste(p, (x, group_h - p.height), p)
        x += p.width + gap_px

    # 다리·발 제거: 무리의 위쪽 UPPER_KEEP 만 남긴다 (규칙: 하반신은 프레임 밖)
    group = group.crop((0, 0, group.width, max(1, int(group.height * UPPER_KEEP))))

    # 확대: 가로는 GROUP_W 까지, 세로는 프레임을 꽉 채우되 GROUP_H_MAX 를 넘지 않게
    scale = (OUT_W * GROUP_W) / group.width
    if group.height * scale > OUT_H * GROUP_H_MAX:
        scale = (OUT_H * GROUP_H_MAX) / group.height
    group = group.resize((max(1, int(group.width * scale)),
                          max(1, int(group.height * scale))), Image.LANCZOS)

    canvas = rebuild_background(img, None)
    left = int(OUT_W * LEFT_MARGIN)
    # 아래 모서리에 걸치게(=가슴에서 잘린 느낌). 무리가 프레임보다 짧으면 바닥 정렬,
    # 길면 머리 위 여백만 남기고 나머지는 프레임 밖으로 내보낸다.
    # 아래 모서리에 붙인다(= 몸통이 프레임 아래에서 잘린 구도).
    # 무리가 프레임보다 크면 0에 붙여 머리부터 보이게 하고 나머지는 아래로 흘려보낸다.
    top = max(0, OUT_H - group.height)
    canvas.paste(group, (left, top), group)
    canvas.save(dst)
    print(f"    [OK] 캐릭터 {len(parts)}개 → 무리 {group.width}x{group.height} "
          f"(확대 {scale:.2f}x, 화면높이의 {group.height/OUT_H:.0%})")
    return True


def targets(args):
    dirs = sorted(p.parent for p in Path("output").glob(f"*/{BG_NAME}"))
    if not args.include_lang:
        dirs = [d for d in dirs if not any(d.name.endswith(s) for s in LANG_SUFFIXES)]
    if args.only:
        dirs = [d for d in dirs if args.only in d.name]
    if args.from_audit:
        p = Path(args.audit_json)
        if not p.exists():
            print(f"[ERROR] {p} 없음 — python _audit_thumb_c.py 먼저 실행")
            sys.exit(1)
        fails = {k for k, v in json.loads(p.read_text(encoding="utf-8")).items() if v.get("issues")}
        dirs = [d for d in dirs if d.name in fails]
    return dirs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--from-audit", action="store_true")
    ap.add_argument("--audit-json", default="_thumb_c_audit_v2.json")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--include-lang", action="store_true", help="_en/_id 폴더도 직접 처리")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--force", action="store_true", help="이미 처리된 것도 원본에서 다시")
    ap.add_argument("--group-w", type=float, default=None,
                    help="캐릭터 무리 가로 비율 (기본 0.74). 오른쪽 텍스트 자리가 좁으면 낮춘다")
    ap.add_argument("--upper-keep", type=float, default=None,
                    help="무리에서 남길 위쪽 비율 (기본 0.78). 다리가 남으면 낮춘다")
    ap.add_argument("--use-rendered", action="store_true",
                    help="c_bg 대신 렌더본에서 캐릭터를 되살림 (글자 잔상 주의)")
    args = ap.parse_args()

    global GROUP_W, UPPER_KEEP
    if args.group_w:
        GROUP_W = args.group_w
    if args.upper_keep:
        UPPER_KEEP = args.upper_keep

    if not (args.only or args.from_audit or args.all):
        print("[ERROR] --only / --from-audit / --all 중 하나 필요")
        sys.exit(1)

    dirs = targets(args)
    print(f"[INFO] 대상 {len(dirs)}개\n")
    done = 0
    for i, d in enumerate(dirs, 1):
        bg, full = d / BG_NAME, d / FULL_NAME
        print(f"[{i}/{len(dirs)}] {d.name[:46]}")
        if args.restore:
            if full.exists():
                bg.write_bytes(full.read_bytes())
                print("    [복원]")
                done += 1
            continue
        if full.exists() and not args.force:
            print("    [SKIP] 이미 처리됨")
            continue
        # 소스 고르기: 오늘 새벽 배치로 덮인 폴더는 c_bg 원본이 유실됐고 재생성본은 캐릭터가
        # 틀어진 것이 섞여 있다 → 그 경우 8/23 렌더본(thumbnail_c.png)에서 캐릭터를 되살린다.
        # 기본은 c_bg 를 소스로 쓴다. 렌더본(thumbnail_c.png)은 제목 글자가 캐릭터에 붙어
        # 누끼에 잔상이 남으므로 --use-rendered 를 명시할 때만 쓴다.
        rendered = d / "thumbnail_c.png"
        use_rendered = args.use_rendered and rendered.exists()
        if use_rendered:
            print("    [소스] 렌더본 thumbnail_c.png (재생성분 대체)")
            if not full.exists():
                full.write_bytes(rendered.read_bytes())
        elif not full.exists():
            full.write_bytes(bg.read_bytes())
        if recompose(full, bg, mask_right=use_rendered):
            done += 1

    print(f"\n=== {done}개 처리 ===")
    if not args.restore and done:
        print("재점검: python _audit_thumb_c.py --json _thumb_c_audit_v3.json")
        print("언어판 반영: python _fix_thumb_c.py --propagate")


if __name__ == "__main__":
    main()
