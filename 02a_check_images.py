#!/usr/bin/env python3
"""
02a_check_images.py
AI 동화책 파이프라인 — 2a단계: 이미지 품질 자동 점검

02_generate_images.py 직후 실행.
Gemini Vision이 각 슬라이드 이미지를 스토리 텍스트와 대조하여 검사:

점검 항목:
  [H] 할루시네이션     — 프롬프트와 무관한 객체/배경 등장
  [E] 비교육성        — 폭력적·무섭거나 아동에게 부적절한 내용
  [T] 텍스트 노출     — 이미지 내 읽을 수 있는 글자/말풍선 (CLAUDE.md 규칙 위반)
  [C] 캐릭터 불일치   — 인물 수·외형이 story.json 설명과 다름
  [Q] 화질 문제       — 매우 어둡거나 흐리거나 부자연스러운 색감

점수 체계 (슬라이드별 100점):
  합격: 75점 이상 (--min-score 조정 가능)

사용법:
  python 02a_check_images.py --ep 1
  python 02a_check_images.py --dir output/id01
  python 02a_check_images.py --dir output/id01 --auto-regen   (불합격 이미지 재생성)
  python 02a_check_images.py --dir output/id01 --slides 3 7  (특정 슬라이드만)
  python 02a_check_images.py --dir output/id01 --force        (이미 검사된 것도 재검사)
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    print("[ERROR] GEMINI_API_KEY가 .env에 없습니다.")
    sys.exit(1)

_client = genai.Client(api_key=GEMINI_API_KEY)

DEFAULT_MIN_SCORE = 75
MAX_IMAGE_BYTES   = 4 * 1024 * 1024   # 4MB


# ── 이미지 인코딩 ─────────────────────────────────────────────

def load_image_b64(path: Path) -> tuple[str, str]:
    """이미지 파일 → (base64, mime_type). 4MB 초과 시 None 반환."""
    if not path.exists():
        return None, None
    data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        # 너무 크면 축소 시도 (pillow 있을 경우)
        try:
            from PIL import Image
            import io
            img = Image.open(path)
            img.thumbnail((1024, 1024))
            buf = io.BytesIO()
            img.save(buf, format='PNG', optimize=True)
            data = buf.getvalue()
        except Exception:
            pass
    return base64.b64encode(data).decode(), "image/png"


# ── 평가 프롬프트 ─────────────────────────────────────────────

def build_species_check(characters: dict, lang: str) -> str:
    """캐릭터 종(species) 불일치 검사 지시문 생성."""
    if not characters:
        return ""

    species_lines = []
    non_human_species = {
        # 동물 → 특징 설명
        "코끼리": "큰 회색 코(trunk), 넓적한 귀, 두꺼운 회색 피부 — 사람 얼굴 절대 불가",
        "토끼": "긴 귀, 털, 작은 코 — 사람 얼굴 절대 불가",
        "다람쥐": "둥근 귀, 털, 덥수룩한 꼬리 — 사람 얼굴 절대 불가",
        "햄스터": "작은 귀, 털, 통통한 볼 — 사람 얼굴 절대 불가",
        "곰": "둥근 귀, 털, 납작한 코 — 사람 얼굴 절대 불가",
        "고양이": "뾰족한 귀, 수염, 세로 눈동자 — 사람 얼굴 절대 불가",
        "개": "늘어진 귀, 긴 코, 털 — 사람 얼굴 절대 불가",
        "여우": "뾰족한 귀, 긴 주둥이, 털 — 사람 얼굴 절대 불가",
        "elephant": "prominent trunk, large floppy grey ears, thick grey skin — NO human face allowed",
        "rabbit": "long upright ears, fur, small nose — NO human face allowed",
        "squirrel": "rounded ears, fur, bushy tail — NO human face allowed",
        "hamster": "small ears, fur, chubby cheeks — NO human face allowed",
    }

    def get_species_check(char_info):
        sp = char_info.get("species", "").lower()
        name = char_info.get("name", "캐릭터")
        for key, desc in non_human_species.items():
            if key in sp:
                return (name, key, desc)
        return None

    chars = {}
    if "main_1" in characters:
        chars["main_1"] = characters["main_1"]
    if "main_2" in characters:
        chars["main_2"] = characters["main_2"]
    # 동적 키 (elephant_echo, child_girl 등)
    for k, v in characters.items():
        if isinstance(v, dict) and "species" in v and k not in chars:
            chars[k] = v

    for ckey, cinfo in chars.items():
        check = get_species_check(cinfo)
        if check:
            name, sp, desc = check
            if lang == "ko":
                species_lines.append(f"⚠ 종(species) 하네스: '{name}'는 {sp}입니다 → 이미지에서 반드시 {desc} 확인")
            else:
                species_lines.append(f"⚠ Species harness: '{name}' is a {sp} → image MUST show {desc}")

    if not species_lines:
        return ""

    if lang == "ko":
        return "\n\n[종 불일치 검사 — 최우선 실패 조건]\n" + "\n".join(species_lines) + "\n사람 얼굴이나 인간 코·입이 동물 캐릭터에게 보이면 [C] 0점 처리."
    else:
        return "\n\n[Species Mismatch Check — PRIORITY FAILURE]\n" + "\n".join(species_lines) + "\nIf animal character has human-like face/nose/mouth, score [C] = 0."


def build_check_prompt(slide: dict, lang: str, characters: dict = None) -> str:
    snum     = slide.get("slide_number", 0)
    prompt   = slide.get("image_prompt", "")[:400]
    segs     = slide.get("tts_segments", [])
    story_tx = " ".join(s.get("text", "") for s in segs)[:200]
    species_note = build_species_check(characters or {}, lang)

    if lang == "id":
        return f"""Kamu adalah pengulas kualitas gambar untuk buku cerita anak usia 6-8 tahun.
Periksa gambar berikut berdasarkan deskripsi yang seharusnya:

Deskripsi yang diharapkan: "{prompt}"
Teks cerita slide ini: "{story_tx}"
{species_note}

Evaluasi gambar dengan 5 kriteria (total 100 poin):
[H] Tidak ada halusinasi (objek/latar yang tidak diminta): 25 poin
[E] Layak untuk anak (tidak ada konten kekerasan/menakutkan): 25 poin
[T] Tidak ada teks/tulisan yang terlihat di gambar: 20 poin
[C] Karakter sesuai deskripsi (jumlah, penampilan, species): 20 poin — 0 jika wajah manusia muncul pada karakter hewan
[Q] Kualitas visual baik (tidak gelap/blur/warna aneh): 10 poin

Berikan HANYA JSON:
{{"score": <0-100>, "score_h": <0-25>, "score_e": <0-25>, "score_t": <0-20>, "score_c": <0-20>, "score_q": <0-10>,
 "issues": ["<masalah 1 jika ada>", "<masalah 2 jika ada>"],
 "passed": <true/false>, "regen_needed": <true jika score<75>}}"""
    else:
        return f"""당신은 초등학교 저학년 동화책 이미지 품질 검토 전문가입니다.
아래 이미지를 설명과 대조하여 검사하세요.

기대 이미지 설명: "{prompt}"
이 슬라이드 스토리 텍스트: "{story_tx}"
{species_note}

5개 기준으로 평가 (합계 100점):
[H] 할루시네이션 없음 (요청하지 않은 객체/배경 미등장): 25점
[E] 교육적 적합성 (폭력·공포·부적절 요소 없음): 25점
[T] 텍스트 미노출 (이미지 내 글자/말풍선 없음): 20점
[C] 캐릭터 일치 (인물 수·외형·종 일치): 20점 — 동물 캐릭터에 사람 얼굴 등장 시 0점
[Q] 화질 양호 (너무 어둡지 않고, 자연스러운 색감): 10점

JSON만 응답 (다른 텍스트 없이):
{{"score": <0-100>, "score_h": <0-25>, "score_e": <0-25>, "score_t": <0-20>, "score_c": <0-20>, "score_q": <0-10>,
 "issues": ["<문제1>", "<문제2>"],
 "passed": <true/false>, "regen_needed": <true if score<75>}}"""


# ── Gemini Vision 호출 ────────────────────────────────────────

def check_image_with_llm(slide: dict, image_path: Path, lang: str, characters: dict = None) -> dict:
    """단일 이미지 LLM 점검. 결과 dict 반환."""
    b64, mime = load_image_b64(image_path)
    if b64 is None:
        return {"score": 0, "issues": ["이미지 파일 없음 또는 로드 실패"], "passed": False, "regen_needed": True}

    prompt = build_check_prompt(slide, lang, characters)

    for attempt in range(3):
        try:
            resp = _client.models.generate_content(
                model=os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash"),
                contents=[
                    genai_types.Part.from_bytes(data=base64.b64decode(b64), mime_type=mime),
                    genai_types.Part.from_text(text=prompt),
                ],
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                    thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
                ),
            )
            raw = resp.text.strip()
            s = raw.find("{"); e = raw.rfind("}") + 1
            if s >= 0 and e > s:
                result = json.loads(raw[s:e])
                result["score"] = max(0, min(100, int(result.get("score", 50))))
                return result
        except Exception as ex:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return {"score": 50, "issues": [f"LLM 호출 실패: {ex}"], "passed": True, "regen_needed": False}

    return {"score": 50, "issues": ["응답 파싱 실패"], "passed": True, "regen_needed": False}


# ── 이미지 재생성 (특정 슬라이드) ────────────────────────────

def regenerate_slides(ep_dir: Path, slide_nums: list):
    """특정 슬라이드 이미지 삭제 후 02_generate_images.py 재실행."""
    images_dir = ep_dir / "images"
    for n in slide_nums:
        for suffix in ("", "_9x16"):
            p = images_dir / f"slide_{n:02d}{suffix}.png"
            if p.exists():
                p.unlink()
                print(f"    삭제: {p.name}")
    # 재생성 — 소량 재생성이므로 배치 큐 대기 없는 실시간 모드 사용
    # (캐릭터 시트는 characters/에 남아 있어 레퍼런스 일관성 유지됨)
    cmd = [sys.executable, "02_generate_images.py", "--dir", str(ep_dir), "--realtime"]
    print(f"  [재생성] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=Path(__file__).parent)
    if result.returncode != 0:
        print(f"  [ERROR] 이미지 재생성 실패 (exit={result.returncode}) — 수동 확인 필요")


# ── 유틸 ─────────────────────────────────────────────────────

def resolve_ep_dir(args) -> Path:
    if args.dir:
        d = Path(args.dir)
    else:
        d = Path(__file__).parent / "output" / f"ep{int(args.ep):02d}"
    if not d.is_absolute():
        d = Path(__file__).parent / d
    if not d.exists():
        print(f"[ERROR] 디렉토리 없음: {d}"); sys.exit(1)
    return d


# ── 메인 ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="이미지 품질 LLM 자동 점검 (할루시네이션·비교육성·텍스트·캐릭터·화질)")
    parser.add_argument("--ep",         type=int,   help="에피소드 번호")
    parser.add_argument("--dir",        type=str,   help="에피소드 디렉토리")
    parser.add_argument("--slides",     type=int,   nargs="+", help="검사할 슬라이드 번호 (미지정 시 전체)")
    parser.add_argument("--auto-regen", action="store_true", help="불합격 슬라이드 자동 재생성")
    parser.add_argument("--min-score",  type=int,   default=DEFAULT_MIN_SCORE, help=f"합격 점수 (기본: {DEFAULT_MIN_SCORE})")
    parser.add_argument("--force",      action="store_true", help="이미 검사된 슬라이드도 재검사")
    args = parser.parse_args()

    if not args.ep and not args.dir:
        parser.print_help(); sys.exit(1)

    ep_dir    = resolve_ep_dir(args)
    story_path = ep_dir / "story.json"
    check_path = ep_dir / "image_check.json"

    if not story_path.exists():
        print(f"[ERROR] story.json 없음: {story_path}"); sys.exit(1)

    story      = json.loads(story_path.read_text(encoding='utf-8'))
    lang       = story.get("meta", {}).get("language", "ko")
    slides     = story.get("slides", [])
    characters = story.get("meta", {}).get("characters", {})
    images_dir = ep_dir / "images"

    # 기존 결과 로드
    prev_results = {}
    if check_path.exists() and not args.force:
        try:
            prev_results = {r["slide"]: r for r in json.loads(check_path.read_text(encoding='utf-8')).get("slides", [])}
        except Exception:
            pass

    # 검사 대상 슬라이드 필터
    target_slides = [sl for sl in slides if sl.get("type") == "story"]
    if args.slides:
        target_slides = [sl for sl in target_slides if sl["slide_number"] in args.slides]

    print(f"\n{'='*60}")
    print(f"  [02a] 이미지 품질 점검: {story.get('meta',{}).get('story_title','')}")
    print(f"  대상 슬라이드: {len(target_slides)}장 | 합격 기준: {args.min_score}점")
    print(f"{'='*60}")

    # 1. 사전 분류: 건너뜀 / 이미지 없음 / LLM 점검 대상
    skip_map  = {}   # slide_num → prev result (이미 합격)
    no_image  = []   # slide_num
    llm_queue = []   # (slide, img_path)

    for sl in target_slides:
        n = sl["slide_number"]
        img_path = images_dir / f"slide_{n:02d}.png"
        if n in prev_results and prev_results[n].get("passed") and not args.force:
            skip_map[n] = prev_results[n]
        elif not img_path.exists():
            no_image.append(n)
        else:
            llm_queue.append((sl, img_path))

    for n, r in skip_map.items():
        print(f"  슬라이드 {n:02d}: 이미 합격 ({r['score']}점) — 건너뜀")
    for n in no_image:
        print(f"  슬라이드 {n:02d}: 이미지 없음 — 건너뜀")

    # 2. 병렬 LLM 점검
    llm_results = {}
    if llm_queue:
        print(f"\n  [병렬 점검] {len(llm_queue)}장 동시 처리 중...")
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {
                pool.submit(check_image_with_llm, sl, img_path, lang, characters): sl["slide_number"]
                for sl, img_path in llm_queue
            }
            for future in as_completed(futures):
                n = futures[future]
                result = future.result()
                result["slide"]  = n
                result["passed"] = result["score"] >= args.min_score
                llm_results[n]   = result
                status = "✓" if result["passed"] else "✗"
                issues_str = " | ".join(result.get("issues", []))[:60]
                print(f"  슬라이드 {n:02d}: {status} {result['score']}점  {issues_str}")

    # 3. 결과 통합 (target_slides 원래 순서 유지)
    results = []
    failed_slides = []

    for sl in target_slides:
        n = sl["slide_number"]
        if n in skip_map:
            results.append(skip_map[n])
        elif n in no_image:
            r = {"slide": n, "score": 0, "passed": False, "regen_needed": True, "issues": ["이미지 파일 없음"]}
            results.append(r)
            failed_slides.append(n)
        elif n in llm_results:
            r = llm_results[n]
            results.append(r)
            if not r["passed"]:
                failed_slides.append(n)

    # 결과 저장
    total     = len(results)
    passed_n  = sum(1 for r in results if r.get("passed"))
    avg_score = round(sum(r.get("score", 0) for r in results) / total, 1) if total else 0

    check_data = {
        "total_slides": total,
        "passed":       passed_n,
        "failed":       total - passed_n,
        "avg_score":    avg_score,
        "slides":       results,
    }
    check_path.write_text(json.dumps(check_data, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n  결과: {passed_n}/{total} 합격 | 평균 {avg_score}점")
    if failed_slides:
        print(f"  불합격 슬라이드: {failed_slides}")

    # 자동 재생성
    regen_list = [n for n in failed_slides if results[next(i for i,r in enumerate(results) if r["slide"]==n)].get("regen_needed", True)]
    if regen_list and args.auto_regen:
        print(f"\n  [자동 재생성] 슬라이드 {regen_list} 이미지 재생성 중...")
        regenerate_slides(ep_dir, regen_list)
        # 재생성된 슬라이드 재검사
        print(f"  재생성 후 재검사 중...")
        for sl in [s for s in target_slides if s["slide_number"] in regen_list]:
            n        = sl["slide_number"]
            img_path = images_dir / f"slide_{n:02d}.png"
            result   = check_image_with_llm(sl, img_path, lang, characters)
            result["slide"]  = n
            result["passed"] = result["score"] >= args.min_score
            # 결과 업데이트
            for i, r in enumerate(results):
                if r["slide"] == n:
                    results[i] = result
                    break
            status = "✓" if result["passed"] else "✗ (여전히 미달)"
            print(f"    슬라이드 {n:02d}: {status} {result['score']}점")
        # 최종 저장
        check_data["slides"] = results
        check_path.write_text(json.dumps(check_data, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n  결과 저장: {check_path}")
    print(f"\n  [NEXT] python 03_generate_tts.py --ep {args.ep or ''} --dir {args.dir or ''}")
    print(f"{'='*60}")

    if failed_slides and not args.auto_regen:
        print(f"\n  미달 슬라이드를 재생성하려면: --auto-regen 플래그 추가")
        sys.exit(1)


if __name__ == "__main__":
    main()
