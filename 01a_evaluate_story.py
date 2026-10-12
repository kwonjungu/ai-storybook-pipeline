#!/usr/bin/env python3
"""
01a_evaluate_story.py
AI 동화책 파이프라인 — 1a단계: 스토리 품질 다중 평가 에이전트

story.json 생성 직후, 01b_analyze_shorts_plan.py 전에 실행합니다.
3개 독립 평가 에이전트가 병렬로 채점 → 점수 미달 시 개선점 포함해 스토리 자동 재생성.

평가 기준 (100점):
  교육성 (35점): 교과 연계, 교훈, 가치관 전달, 연령 적합성
  재미성 (35점): 유머, 긴장감, 캐릭터 매력, 스토리 몰입감
  개연성 (30점): 인과관계, 캐릭터 행동 일관성, 사건의 논리적 흐름

합격 기준: 기본 75점 (--min-score 로 조정)
재생성 방식: 각 에이전트의 개선 피드백을 통합 → Gemini에 개선 지시 → 재평가

파이프라인 순서:
  01_generate_story.py
  01a_evaluate_story.py  ← 여기
  01b_analyze_shorts_plan.py
  02_generate_images.py
  ...

사용법:
  python 01a_evaluate_story.py --ep 1
  python 01a_evaluate_story.py --dir output/id01
  python 01a_evaluate_story.py --dir output/id01 --auto-improve
  python 01a_evaluate_story.py --dir output/id01 --auto-improve --max-cycles 3 --min-score 80
  python 01a_evaluate_story.py --dir output/id01 --force   (재평가)
"""

import argparse
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

load_dotenv()

EVAL_MODEL    = "claude-haiku-4-5-20251001"   # 평가 (빠름/저비용)
IMPROVE_MODEL = "claude-sonnet-4-6"            # 스토리 개선 (고품질)

# Claude Code 중첩 세션 방지를 위해 CLAUDECODE 환경변수 제거
_CLAUDE_ENV = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}


def _call_claude_cli(prompt: str, model: str, timeout: int = 120) -> str:
    """Claude Code CLI를 서브프로세스로 호출하고 stdout을 반환합니다."""
    result = subprocess.run(
        ["claude", "-p", "--model", model],
        input=prompt,
        capture_output=True,
        encoding="utf-8",
        timeout=timeout,
        env=_CLAUDE_ENV,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI 오류: {result.stderr.strip()[:200]}")
    return result.stdout.strip()

DEFAULT_MIN_SCORE  = 88
MAX_TEXT_PREVIEW   = 3000   # 평가용 스토리 요약 길이


# ── 스토리 요약 추출 ──────────────────────────────────────────

def summarize_story(story: dict, lang: str) -> str:
    """평가 프롬프트용 스토리 요약 텍스트 생성."""
    meta   = story.get("meta", {})
    title  = meta.get("story_title", "")
    slides = story.get("slides", [])

    lines = [f'제목: "{title}"', f'언어: {lang}', ""]
    for sl in slides:
        if sl.get("type") != "story":
            continue
        segs = sl.get("tts_segments", [])
        for seg in segs:
            speaker = seg.get("speaker", "narrator")
            text    = seg.get("text", "").strip()
            if text:
                lines.append(f'[{speaker}] {text}')
    full = "\n".join(lines)
    return full[:MAX_TEXT_PREVIEW] + ("..." if len(full) > MAX_TEXT_PREVIEW else "")


# ── 3개 평가 에이전트 프롬프트 ───────────────────────────────

def _prompt_educational(story_text: str, lang: str) -> str:
    if lang == "id":
        return f"""Kamu adalah evaluator ahli konten pendidikan anak usia dini.
Evaluasi dongeng berikut dari segi NILAI PENDIDIKAN.

Dongeng:
{story_text}

Kriteria penilaian (total 35 poin):
- Relevansi kurikulum / nilai pembelajaran (15 poin)
- Pesan moral yang jelas dan positif (10 poin)
- Kesesuaian bahasa dan konten untuk usia 6-8 tahun (10 poin)

Berikan hanya JSON:
{{"score": <0-35>, "feedback": "<ringkasan 2 kalimat>", "improvements": ["<perbaikan 1>", "<perbaikan 2>"]}}"""
    else:
        return f"""당신은 초등학교 저학년 교육 콘텐츠 전문 평가관입니다.
다음 동화를 교육성 관점에서 평가하세요.

동화:
{story_text}

평가 기준 (합계 35점):
- 교과 연계성 및 학습 목표 달성도 (15점)
- 교훈/가치관의 명확성과 긍정성 (10점)
- 초등 2학년 수준의 언어 및 내용 적합성 (10점)

JSON만 응답 (다른 텍스트 없이):
{{"score": <0-35>, "feedback": "<2문장 요약>", "improvements": ["<개선점1>", "<개선점2>"]}}"""


def _prompt_entertainment(story_text: str, lang: str) -> str:
    if lang == "id":
        return f"""Kamu adalah evaluator ahli hiburan dan narasi cerita anak.
Evaluasi dongeng berikut dari segi DAYA HIBURAN.

Dongeng:
{story_text}

Kriteria penilaian (total 35 poin):
- Kemenarikan karakter dan dialog (15 poin)
- Ketegangan, humor, atau momen emosional (10 poin)
- Alur cerita yang membuat pembaca ingin tahu lebih (10 poin)

Berikan hanya JSON:
{{"score": <0-35>, "feedback": "<ringkasan 2 kalimat>", "improvements": ["<perbaikan 1>", "<perbaikan 2>"]}}"""
    else:
        return f"""당신은 아동 스토리텔링 및 엔터테인먼트 전문 평가관입니다.
다음 동화를 재미성 관점에서 평가하세요.

동화:
{story_text}

평가 기준 (합계 35점):
- 캐릭터 매력과 대화의 생동감 (15점)
- 긴장감, 유머, 감동적 순간의 존재 (10점)
- 다음 내용이 궁금해지는 스토리 흐름 (10점)

JSON만 응답 (다른 텍스트 없이):
{{"score": <0-35>, "feedback": "<2문장 요약>", "improvements": ["<개선점1>", "<개선점2>"]}}"""


def _prompt_coherence(story_text: str, lang: str) -> str:
    if lang == "id":
        return f"""Kamu adalah evaluator ahli struktur narasi dan konsistensi cerita.
Evaluasi dongeng berikut dari segi KOHERENSI dan KELOGISAN.

Dongeng:
{story_text}

Kriteria penilaian (total 30 poin):
- Hubungan sebab-akibat yang jelas antar peristiwa (12 poin)
- Konsistensi karakter (tindakan sesuai kepribadian) (10 poin)
- Alur cerita yang mengalir natural tanpa lompatan tiba-tiba (8 poin)

Berikan hanya JSON:
{{"score": <0-30>, "feedback": "<ringkasan 2 kalimat>", "improvements": ["<perbaikan 1>", "<perbaikan 2>"]}}"""
    else:
        return f"""당신은 서사 구조 및 스토리 일관성 전문 평가관입니다.
다음 동화를 개연성 관점에서 평가하세요.

동화:
{story_text}

평가 기준 (합계 30점):
- 사건 간 인과관계의 명확성 (12점)
- 캐릭터 행동의 일관성 (성격에 맞는 선택과 반응) (10점)
- 자연스러운 스토리 흐름 (돌발적 전개 없음) (8점)

JSON만 응답 (다른 텍스트 없이):
{{"score": <0-30>, "feedback": "<2문장 요약>", "improvements": ["<개선점1>", "<개선점2>"]}}"""


# ── Claude 호출 (단일 에이전트) ────────────────────────────

def _call_agent(agent_name: str, prompt: str, max_score: int) -> dict:
    """에이전트 한 개 호출 (Claude Code CLI). 실패 시 기본값 반환."""
    for attempt in range(3):
        try:
            raw = _call_claude_cli(prompt, model=EVAL_MODEL, timeout=120)
            s = raw.find("{"); e = raw.rfind("}") + 1
            if s >= 0 and e > s:
                result = json.loads(raw[s:e])
                result["score"] = max(0, min(max_score, int(result.get("score", 0))))
                result["agent"] = agent_name
                return result
        except Exception as ex:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                print(f"  [WARN] {agent_name} 에이전트 실패: {ex}")
    return {"score": max_score // 2, "feedback": "평가 실패", "improvements": [], "agent": agent_name}


# ── 병렬 평가 실행 ───────────────────────────────────────────

def evaluate_story_parallel(story: dict) -> dict:
    """3개 에이전트 병렬 실행. 결과 통합 반환."""
    lang         = story.get("meta", {}).get("language", "ko")
    story_text   = summarize_story(story, lang)

    agents = [
        ("교육성", _prompt_educational(story_text, lang),   35),
        ("재미성", _prompt_entertainment(story_text, lang), 35),
        ("개연성", _prompt_coherence(story_text, lang),     30),
    ]

    results = {}
    print("\n  [병렬 평가] 3개 에이전트 동시 실행 중...")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_call_agent, name, prompt, max_s): name
            for name, prompt, max_s in agents
        }
        for future in as_completed(futures):
            name   = futures[future]
            result = future.result()
            results[name] = result
            print(f"    ✓ {name}: {result['score']}점 — {result.get('feedback', '')[:60]}")

    total = sum(r["score"] for r in results.values())
    return {
        "total": total,
        "교육성": results.get("교육성", {}),
        "재미성": results.get("재미성", {}),
        "개연성": results.get("개연성", {}),
    }


# ── 개선 프롬프트 생성 + 재생성 ──────────────────────────────

def _build_improve_prompt(story: dict, eval_result: dict, lang: str) -> str:
    meta   = story.get("meta", {})
    title  = meta.get("story_title", "")

    # story 타입 슬라이드만 JSON 직렬화 (quiz/cover 등 제외)
    story_slides = [sl for sl in story.get("slides", []) if sl.get("type") == "story"]
    slides_json  = json.dumps(story_slides, ensure_ascii=False)
    if len(slides_json) > 6000:
        slides_json = slides_json[:6000] + "..."

    # 개선점 수집
    improvements = []
    for area in ("교육성", "재미성", "개연성"):
        for item in eval_result.get(area, {}).get("improvements", []):
            improvements.append(f"[{area}] {item}")
    imp_text = "\n".join(f"  - {i}" for i in improvements)

    if lang == "id":
        return f"""Kamu adalah penulis dongeng anak profesional.
Perbaiki slide-slide dongeng berikut berdasarkan masukan evaluator.

Judul saat ini: "{title}"

Slide asli (tipe story saja, {len(story_slides)} slide):
{slides_json}

Masukan evaluator:
{imp_text}

Petunjuk:
1. Terapkan semua perbaikan. Kembalikan HANYA slide tipe story.
2. Sertakan semua field: slide_number, type, image_prompt, tts_segments, dll.
3. Pertahankan jumlah slide ({len(story_slides)} slide).
4. Gunakan hanya titik dan koma di tts_segments[].text. Dilarang: \u2026, \u2014, \u2015.
5. Pastikan speaker = voice pada setiap segmen TTS.

Output HANYA JSON array ([{{...}}, {{...}}], tidak ada teks lain):"""
    else:
        return f"""당신은 초등학교 저학년용 동화 전문 작가입니다.
아래 동화 슬라이드 JSON을 평가단의 피드백을 반영하여 개선하세요.

현재 제목: "{title}"

원본 슬라이드 JSON (story 타입만, {len(story_slides)}장):
{slides_json}

평가단 개선 요청:
{imp_text}

작업 지침:
1. 개선점을 반영하여 story 타입 슬라이드만 다시 작성하세요.
2. slide_number, type, image_prompt, tts_segments 등 모든 필드를 포함하세요.
3. 슬라이드 수는 원본({len(story_slides)}장)과 동일하게 유지하세요.
4. tts_segments[].text는 마침표·쉼표만 허용. \u2026, \u2014, \u2015 사용 금지.
5. 각 세그먼트의 speaker 값과 voice 값을 반드시 동일하게 맞추세요.
6. 소리 흉내 감탄("쿵! 쿵!", "찰칵!")을 단독 문장·대사로 쓰지 말고 narrator 세그먼트의 "sfx" 필드로 적으세요 (예: "sfx":[{{"type":"thump","where":"start","count":2}}]; type=thump/shutter/clap/pop/pop_pop/sparkle/flutter/swish/roll, where=start/end/after+after_text/word+word). 원본에 이미 있는 sfx 필드는 유지하고, emotion에 소리 묘사("발소리를", "~소리를 살려서")는 쓰지 마세요.

JSON 배열만 출력 ([{{...}}, {{...}}] 형식, 다른 텍스트 없이):"""


def _extract_json_array(raw: str) -> list | None:
    """LLM 응답에서 첫 번째 유효한 JSON 배열을 추출.

    `find("[") ~ rfind("]")` 방식은 배열 앞뒤(또는 배열 사이)에 설명 문구나
    두 번째 배열이 섞이면 'Extra data' 로 실패한다. raw_decode 로 각 '[' 위치에서
    파싱을 시도해 가장 긴(=본문) 배열을 고른다.
    """
    dec = json.JSONDecoder()
    best = None
    idx = raw.find("[")
    while idx != -1:
        try:
            val, _ = dec.raw_decode(raw[idx:])
            if isinstance(val, list) and val and (best is None or len(val) > len(best)):
                best = val
        except ValueError:
            pass
        idx = raw.find("[", idx + 1)
    return best


def improve_story(story: dict, eval_result: dict, ep_dir: Path) -> dict | None:
    """평가 결과를 바탕으로 스토리 개선 후 story.json 업데이트. 성공 시 새 story 반환."""
    lang   = story.get("meta", {}).get("language", "ko")
    prompt = _build_improve_prompt(story, eval_result, lang)

    print(f"\n  [개선] Claude Sonnet에 스토리 재생성 요청 중...")
    try:
        raw = _call_claude_cli(prompt, model=IMPROVE_MODEL, timeout=1500)

        # JSON 배열 파싱 (LLM이 story 슬라이드 배열만 반환)
        improved_slides = _extract_json_array(raw)
        if improved_slides is None:
            print("  [WARN] 개선 응답에서 JSON 배열을 찾을 수 없음")
            return None

        if not isinstance(improved_slides, list) or not improved_slides:
            print("  [WARN] 개선 응답이 빈 배열이거나 잘못된 형식")
            return None

        # story 타입만 걸러내기 (방어적)
        improved_story = [sl for sl in improved_slides if sl.get("type", "story") == "story"]
        if not improved_story:
            print("  [WARN] 개선된 story 슬라이드 없음")
            return None

        # 원본 비-story 슬라이드 보존 (quiz, intro, outro 등)
        original_non_story = [sl for sl in story["slides"] if sl.get("type") != "story"]

        # [Fix 5] 슬라이드 수 변화 감지 + 고아 이미지 삭제
        old_nums = {sl["slide_number"] for sl in story["slides"] if sl.get("type") == "story"}
        new_nums = {sl["slide_number"] for sl in improved_story}
        removed  = old_nums - new_nums
        if removed:
            images_dir = ep_dir / "images"
            for n in sorted(removed):
                for suffix in ("", "_9x16"):
                    p = images_dir / f"slide_{n:02d}{suffix}.png"
                    if p.exists():
                        p.unlink()
                        print(f"  [정리] 이미지 삭제: {p.name}")
            print(f"  [경고] 슬라이드 수 변화 {len(old_nums)}\u2192{len(new_nums)}장. 이미지 재생성 필요.")

        # 병합: 개선된 story 슬라이드 + 원본 non-story 슬라이드 (번호 순 정렬)
        merged = sorted(improved_story + original_non_story, key=lambda x: x.get("slide_number", 999))

        new_story = dict(story)
        new_story["slides"] = merged

        # 백업 후 저장
        story_path = ep_dir / "story.json"
        backup     = ep_dir / "story_prev.json"
        if story_path.exists():
            # Windows에서 Path.rename은 대상이 이미 있으면 실패 → os.replace로 덮어쓰기
            os.replace(story_path, backup)

        with open(story_path, "w", encoding="utf-8") as f:
            json.dump(new_story, f, ensure_ascii=False, indent=2)

        print(f"  [개선 완료] story.json 업데이트 (이전 버전: story_prev.json)")
        return new_story

    except Exception as e:
        print(f"  [ERROR] 스토리 개선 실패: {e}")
        return None


# ── 평가 결과 저장 ───────────────────────────────────────────

def save_eval(ep_dir: Path, eval_result: dict, cycle: int, passed: bool):
    record = {
        "cycle":    cycle,
        "total":    eval_result["total"],
        "passed":   passed,
        "교육성":  {"score": eval_result["교육성"].get("score"), "feedback": eval_result["교육성"].get("feedback")},
        "재미성":  {"score": eval_result["재미성"].get("score"), "feedback": eval_result["재미성"].get("feedback")},
        "개연성":  {"score": eval_result["개연성"].get("score"), "feedback": eval_result["개연성"].get("feedback")},
    }
    path = ep_dir / "story_eval.json"
    history = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding='utf-8'))
            history  = existing if isinstance(existing, list) else [existing]
        except Exception:
            pass
    history.append(record)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')


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


def grade(score: int) -> str:
    if score >= 95: return "S"
    if score >= 85: return "A"
    if score >= 75: return "B"
    if score >= 60: return "C"
    return "F"


# ── 메인 ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="스토리 품질 다중 평가 에이전트 (교육성·재미성·개연성)")
    parser.add_argument("--ep",          type=int, help="에피소드 번호")
    parser.add_argument("--dir",         type=str, help="에피소드 디렉토리")
    parser.add_argument("--auto-improve",action="store_true", help="점수 미달 시 자동 개선 재생성")
    parser.add_argument("--max-cycles",  type=int, default=3,              help="최대 재생성 횟수 (기본: 3)")
    parser.add_argument("--min-score",   type=int, default=DEFAULT_MIN_SCORE, help=f"합격 점수 (기본: {DEFAULT_MIN_SCORE})")
    parser.add_argument("--force",       action="store_true", help="기존 평가 무시하고 재평가")
    args = parser.parse_args()

    if not args.ep and not args.dir:
        parser.print_help(); sys.exit(1)

    ep_dir     = resolve_ep_dir(args)
    eval_path  = ep_dir / "story_eval.json"
    story_path = ep_dir / "story.json"

    # 이미 합격 평가 있으면 건너뜀
    if eval_path.exists() and not args.force:
        try:
            history = json.loads(eval_path.read_text(encoding='utf-8'))
            last    = history[-1] if isinstance(history, list) else history
            if last.get("passed"):
                print(f"[INFO] story_eval.json 이미 있음 — 합격 (총점 {last['total']}점)")
                print(f"  교육성: {last['교육성']['score']}점  재미성: {last['재미성']['score']}점  개연성: {last['개연성']['score']}점")
                print(f"[NEXT] python 01b_analyze_shorts_plan.py --ep {args.ep or ''} --dir {args.dir or ''}")
                return
        except Exception:
            pass

    if not story_path.exists():
        print(f"[ERROR] story.json 없음: {story_path}"); sys.exit(1)

    story = json.loads(story_path.read_text(encoding='utf-8'))
    title = story.get("meta", {}).get("story_title", ep_dir.name)

    best_score = 0
    best_story = story

    for cycle in range(1, args.max_cycles + 1):
        print(f"\n{'='*60}")
        print(f"  [01a] 스토리 평가 Cycle {cycle}/{args.max_cycles}: {title}")
        print(f"{'='*60}")

        eval_result = evaluate_story_parallel(story)
        total       = eval_result["total"]
        passed      = total >= args.min_score

        print(f"\n  ┌─ 평가 결과 ──────────────────────────────┐")
        print(f"  │  교육성: {eval_result['교육성'].get('score', 0):2d}/35점")
        print(f"  │  재미성: {eval_result['재미성'].get('score', 0):2d}/35점")
        print(f"  │  개연성: {eval_result['개연성'].get('score', 0):2d}/30점")
        print(f"  │  ─────────────────────────────────────── │")
        print(f"  │  총점:   {total:2d}/100점  등급: {grade(total)}  {'✓ 합격' if passed else '✗ 미달'}")
        print(f"  └──────────────────────────────────────────┘")

        save_eval(ep_dir, eval_result, cycle, passed)

        if total > best_score:
            best_score = total
            best_story = story

        if passed:
            print(f"\n  합격 기준({args.min_score}점) 달성!")
            break

        # 미달 처리
        print(f"\n  미달 ({total}점 < {args.min_score}점). 개선 필요 항목:")
        for area in ("교육성", "재미성", "개연성"):
            for imp in eval_result[area].get("improvements", []):
                print(f"    [{area}] {imp}")

        if not args.auto_improve:
            print(f"\n  --auto-improve 플래그 없음. 재생성 건너뜀.")
            break

        if cycle >= args.max_cycles:
            print(f"\n  최대 순환 횟수({args.max_cycles}) 도달. 최고 점수 버전 유지.")
            break

        # 자동 개선 재생성
        improved = improve_story(story, eval_result, ep_dir)
        if improved:
            story = improved
        else:
            print("  스토리 개선 실패. 현재 버전 유지.")
            break

    # 최고 점수 버전을 실제 story.json에 반영
    # (best_story는 메모리에만 있었으므로, 마지막 사이클이 더 낮은 점수여도
    #  디스크에는 그 버전이 남아 있던 버그를 방지)
    try:
        on_disk = json.loads(story_path.read_text(encoding='utf-8'))
    except Exception:
        on_disk = None
    if on_disk != best_story:
        discarded = ep_dir / "story_discarded.json"
        if on_disk is not None:
            with open(discarded, "w", encoding="utf-8") as f:
                json.dump(on_disk, f, ensure_ascii=False, indent=2)
        with open(story_path, "w", encoding="utf-8") as f:
            json.dump(best_story, f, ensure_ascii=False, indent=2)
        print(f"\n  [복원] 최고 점수({best_score}점) 버전을 story.json에 기록")
        print(f"         마지막 사이클 버전은 story_discarded.json 으로 보관")

    # 최종 결과
    print(f"\n{'='*60}")
    if best_score >= args.min_score:
        print(f"  [최종] 합격  — 총점 {best_score}점 (기준: {args.min_score}점)")
    else:
        print(f"  [최종] 미달  — 최고 점수 {best_score}점 (기준: {args.min_score}점)")
        print(f"  story.json은 현재 상태로 진행하거나 수동으로 수정하세요.")
    print(f"  평가 기록: {ep_dir / 'story_eval.json'}")
    print(f"\n  [NEXT] python 01b_analyze_shorts_plan.py --ep {args.ep or ''} --dir {args.dir or ''}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
