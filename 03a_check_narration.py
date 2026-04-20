#!/usr/bin/env python3
"""
03a_check_narration.py
AI 동화책 파이프라인 — 3a단계: 나레이션 스크립트 LLM 자동 점검

03_generate_tts.py 직후 실행.
TTS 세그먼트 텍스트 전체를 LLM이 검토하여 문제를 탐지합니다.

점검 항목:
  [S] 화자 혼입       — 나레이터 서술문이 대화 세그먼트에 포함 (가장 흔한 버그)
  [L] 언어 일관성     — 에피소드 언어(ko/id)와 다른 언어 텍스트 혼재
  [A] 연령 적합성     — 초등 저학년에 부적절한 표현 (공포·폭력·어려운 어휘)
  [F] 흐름/자연스러움 — 슬라이드 간 이야기 흐름 단절 또는 어색한 전환
  [C] 특수문자        — …, —, ―, · 사용 (TTS 발음 오류 유발)

자동 수정 가능:
  - 특수문자 자동 치환 (…→, —→,)
  - speaker/voice 불일치 자동 교정

사용법:
  python 03a_check_narration.py --ep 1
  python 03a_check_narration.py --dir output/id01
  python 03a_check_narration.py --dir output/id01 --auto-fix
  python 03a_check_narration.py --dir output/id01 --force
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    print("[ERROR] GEMINI_API_KEY가 .env에 없습니다."); sys.exit(1)

_client = genai.Client(api_key=GEMINI_API_KEY)

SPECIAL_CHARS = re.compile(r'[…—―·•]')
HANGUL_RE     = re.compile(r'[\uAC00-\uD7A3]')

# 내레이터 서술문 혼입 패턴
LEAKAGE_KO = re.compile(
    r'(라고\s*(말했|외쳤|소리쳤|속삭였|물었|답했|웃었|울었)'
    r'|이라며|이라고\s*(했|말했|소리쳤)'
    r'|목소리로|표정으로|눈물을\s*흘리며'
    r'|웃으며|찡그리며|고개를\s*끄덕이며)'
)
LEAKAGE_ID = re.compile(
    r'(bisik\s+\w+|kata\s+\w+|seru\w*\s+\w+|ucap\w*\s+\w+'
    r'|jawab\w*\s+\w+|tanya\w*\s+\w+|ujar\w*\s+\w+'
    r'|bisiknya|serunya|katanya|ujarnya|jawabnya|sambil\s+\w+nya)'
)


# ── 스크립트 텍스트 추출 ────────────────────────────────────

def extract_script(story: dict) -> list:
    """슬라이드별 세그먼트 정보를 플랫 리스트로 추출."""
    items = []
    for sl in story.get("slides", []):
        if sl.get("type") != "story":
            continue
        for i, seg in enumerate(sl.get("tts_segments", [])):
            items.append({
                "slide": sl["slide_number"],
                "seg":   i,
                "speaker": seg.get("speaker", "narrator"),
                "voice":   seg.get("voice",   "narrator"),
                "text":    seg.get("text", "").strip(),
            })
    return items


# ── 규칙 기반 빠른 점검 (LLM 전 사전 필터) ──────────────────

def rule_check(items: list, lang: str) -> list:
    """규칙 기반 이슈를 즉시 탐지. LLM 없이 처리 가능한 것들."""
    issues = []
    leakage_re = LEAKAGE_ID if lang == "id" else LEAKAGE_KO

    for item in items:
        sl, seg, sp, vo, text = item["slide"], item["seg"], item["speaker"], item["voice"], item["text"]

        # [C] 특수문자
        if SPECIAL_CHARS.search(text):
            issues.append({"code": "C", "slide": sl, "seg": seg, "speaker": sp,
                "msg": f"특수문자 감지: {text[:50]}", "auto_fixable": True, "severity": "WARN"})

        # [S] 화자 혼입 (규칙)
        if sp != "narrator" and leakage_re.search(text):
            issues.append({"code": "S", "slide": sl, "seg": seg, "speaker": sp,
                "msg": f"내레이터 서술 혼입 의심 [{sp}]: {text[:60]}", "auto_fixable": False, "severity": "ERROR"})

        # speaker/voice 불일치
        if sp != vo:
            issues.append({"code": "V", "slide": sl, "seg": seg,
                "msg": f"speaker({sp})≠voice({vo}) 불일치", "auto_fixable": True, "severity": "ERROR"})

        # [L] 언어 불일치 (한글 포함 여부)
        has_hangul = bool(HANGUL_RE.search(text))
        if lang == "id" and has_hangul:
            issues.append({"code": "L", "slide": sl, "seg": seg, "speaker": sp,
                "msg": f"인도네시아어 에피소드에 한글 포함: {text[:50]}", "auto_fixable": False, "severity": "ERROR"})
        elif lang == "ko" and not has_hangul and len(text) > 5:
            # 짧은 효과음 등은 제외
            if not re.match(r'^[A-Za-z\s!?.]+$', text):
                pass  # 혼합 문자 허용
    return issues


# ── LLM 심층 점검 ────────────────────────────────────────────

def llm_deep_check(story: dict, lang: str) -> list:
    """LLM이 전체 스크립트를 읽고 흐름 및 연령적합성 점검."""
    items    = extract_script(story)
    title    = story.get("meta", {}).get("story_title", "")

    # 스크립트 텍스트 압축
    script_lines = []
    for it in items:
        script_lines.append(f"[슬라이드{it['slide']}-{it['speaker']}] {it['text']}")
    script_text = "\n".join(script_lines)[:3000]

    if lang == "id":
        prompt = f"""Kamu adalah editor naskah cerita anak profesional.
Periksa naskah TTS dongeng "{title}" berikut ini.

Naskah:
{script_text}

Cari masalah berikut dan laporkan semua yang ditemukan:
[A] Bahasa tidak sesuai usia (terlalu menakutkan/kekerasan/kosakata sulit untuk anak 6-8 tahun)
[F] Alur tidak natural (lompatan cerita, transisi aneh antar slide, inkonsistensi)
[S] Teks narasi di segmen dialog (narrator mendeskripsikan aksi dalam dialog karakter)

Berikan HANYA JSON array (kosong jika tidak ada masalah):
[{{"code":"<A/F/S>","slide":<nomor>,"msg":"<deskripsi masalah>","severity":"<ERROR/WARN>"}}]"""
    else:
        prompt = f"""당신은 초등학교 저학년 동화 스크립트 전문 편집자입니다.
"{title}" 동화의 TTS 스크립트를 검토하세요.

스크립트:
{script_text}

아래 문제를 모두 찾아서 보고하세요:
[A] 연령 부적합 표현 (초등 1~2학년에 무서운/폭력적/어려운 어휘)
[F] 흐름 부자연스러움 (이야기 갑작스러운 전환, 슬라이드 간 연결 어색함, 내용 불일치)
[S] 나레이터 텍스트 대화 혼입 (화자 세그먼트에 "라고 말했다" 같은 서술문 포함)

JSON 배열만 응답 (문제 없으면 빈 배열 []):
[{{"code":"<A/F/S>","slide":<번호>,"msg":"<문제 설명>","severity":"<ERROR/WARN>"}}]"""

    for attempt in range(3):
        try:
            resp = _client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                    thinking_config=genai_types.ThinkingConfig(thinking_budget=512),
                ),
            )
            raw = resp.text.strip()
            s = raw.find("["); e = raw.rfind("]") + 1
            if s >= 0 and e > s:
                result = json.loads(raw[s:e])
                return result if isinstance(result, list) else []
        except Exception as ex:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                print(f"  [WARN] LLM 심층 점검 실패: {ex}")
    return []


# ── 자동 수정 ────────────────────────────────────────────────

def auto_fix_story(story: dict, issues: list, ep_dir: Path) -> tuple[bool, list]:
    """자동 수정 후 (수정 여부, 수정된 슬라이드 번호 리스트) 반환."""
    modified        = False
    modified_slides = set()
    slides          = story.get("slides", [])

    for sl in slides:
        sl_num = sl.get("slide_number", 0)
        for seg in sl.get("tts_segments", []):
            # 특수문자 치환
            original = seg.get("text", "")
            fixed = original.replace("…", ",").replace("—", ",").replace("―", ",").replace("·", " ").replace("•", " ")
            if fixed != original:
                seg["text"] = fixed
                modified = True
                modified_slides.add(sl_num)

            # speaker/voice 불일치 수정 (voice를 speaker에 맞춤)
            if seg.get("speaker") != seg.get("voice"):
                seg["voice"] = seg["speaker"]
                modified = True
                modified_slides.add(sl_num)

    if modified:
        story_path = ep_dir / "story.json"
        backup     = ep_dir / "story_narcheck_prev.json"
        if story_path.exists():
            story_path.rename(backup)
        story_path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"  [자동 수정] story.json 업데이트 (백업: {backup.name})")

        # 수정된 슬라이드의 오디오 파일 삭제 (TTS 재생성 필요)
        audio_dir     = ep_dir / "audio"
        deleted_audio = []
        if audio_dir.exists():
            for n in sorted(modified_slides):
                for p in audio_dir.glob(f"slide_{n:02d}*.wav"):
                    p.unlink()
                    deleted_audio.append(p.name)

        if deleted_audio:
            print(f"  [오디오 무효화] {len(deleted_audio)}개 삭제: {', '.join(deleted_audio)}")
            print(f"  ⚠ TTS 재생성 필요: python 03_generate_tts.py --dir {ep_dir}")

    return modified, sorted(modified_slides)


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
    parser = argparse.ArgumentParser(description="나레이션 스크립트 LLM 품질 점검 (화자혼입·언어·연령·흐름·특수문자)")
    parser.add_argument("--ep",       type=int, help="에피소드 번호")
    parser.add_argument("--dir",      type=str, help="에피소드 디렉토리")
    parser.add_argument("--auto-fix", action="store_true", help="자동 수정 가능 이슈 즉시 수정")
    parser.add_argument("--force",    action="store_true", help="이미 점검된 결과 무시하고 재점검")
    args = parser.parse_args()

    if not args.ep and not args.dir:
        parser.print_help(); sys.exit(1)

    ep_dir     = resolve_ep_dir(args)
    story_path = ep_dir / "story.json"
    check_path = ep_dir / "narration_check.json"

    # 기존 결과 있으면 건너뜀
    if check_path.exists() and not args.force:
        prev = json.loads(check_path.read_text(encoding='utf-8'))
        errors = sum(1 for i in prev.get("issues", []) if i.get("severity") == "ERROR")
        print(f"[INFO] narration_check.json 이미 있음 — 오류 {errors}건 (--force로 재검사)")
        if errors > 0:
            print("  이슈 목록:")
            for iss in prev.get("issues", [])[:10]:
                print(f"    [{iss['code']}] 슬라이드{iss.get('slide','?')}: {iss['msg']}")
        return

    if not story_path.exists():
        print(f"[ERROR] story.json 없음: {story_path}"); sys.exit(1)

    story = json.loads(story_path.read_text(encoding='utf-8'))
    lang  = story.get("meta", {}).get("language", "ko")
    title = story.get("meta", {}).get("story_title", ep_dir.name)
    items = extract_script(story)

    print(f"\n{'='*60}")
    print(f"  [03a] 나레이션 점검: {title}")
    print(f"  세그먼트: {len(items)}개 | 언어: {lang}")
    print(f"{'='*60}")

    # 1. 규칙 기반 빠른 점검
    print("  [1] 규칙 기반 점검 중...")
    rule_issues = rule_check(items, lang)
    for iss in rule_issues:
        icon = "✗" if iss["severity"] == "ERROR" else "⚠"
        print(f"    {icon} [{iss['code']}] 슬라이드{iss['slide']}-seg{iss['seg']}: {iss['msg']}")

    # 2. LLM 심층 점검
    print("  [2] LLM 심층 점검 중 (흐름·연령·화자혼입)...")
    llm_issues = llm_deep_check(story, lang)
    for iss in llm_issues:
        icon = "✗" if iss.get("severity") == "ERROR" else "⚠"
        print(f"    {icon} [{iss.get('code','?')}] 슬라이드{iss.get('slide','?')}: {iss.get('msg','')[:60]}")

    all_issues = rule_issues + [dict(i, auto_fixable=False) for i in llm_issues]
    error_count = sum(1 for i in all_issues if i.get("severity") == "ERROR")
    warn_count  = sum(1 for i in all_issues if i.get("severity") == "WARN")

    # 결과 저장
    result_data = {
        "title":   title,
        "lang":    lang,
        "errors":  error_count,
        "warns":   warn_count,
        "passed":  error_count == 0,
        "issues":  all_issues,
    }
    check_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n  결과: 오류 {error_count}건 / 경고 {warn_count}건  →  {'✓ 합격' if error_count == 0 else '✗ 수정 필요'}")
    print(f"  저장: {check_path}")

    # 자동 수정
    if all_issues and args.auto_fix:
        fixable = [i for i in all_issues if i.get("auto_fixable")]
        if fixable:
            print(f"\n  [자동 수정] {len(fixable)}건 수정 중...")
            _, modified_slides = auto_fix_story(story, fixable, ep_dir)
            if modified_slides:
                print(f"  수정된 슬라이드: {modified_slides}")
        else:
            print(f"  자동 수정 가능 이슈 없음 — 수동 확인 필요")

    print(f"\n  [NEXT] python 04_concat_audio.py --ep {args.ep or ''} --dir {args.dir or ''}")
    print(f"{'='*60}")

    if error_count > 0 and not args.auto_fix:
        print(f"\n  수정하려면: --auto-fix 플래그 추가")
        sys.exit(1)


if __name__ == "__main__":
    main()
