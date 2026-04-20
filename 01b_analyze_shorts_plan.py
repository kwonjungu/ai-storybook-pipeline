#!/usr/bin/env python3
"""
01b_analyze_shorts_plan.py
AI 동화책 파이프라인 — 1b단계: Shorts 구간 사전 분석

story.json 생성 직후, 이미지/TTS 생성 전에 실행합니다.
AI가 "감정적으로 가장 강한 구간"을 미리 선정 → shorts_plan.json 저장.

이 결과를 바탕으로:
  02_generate_images.py — 해당 슬라이드에 9:16 이미지 동시 생성
  09b_smart_shorts.py  — 9:16 이미지 있으면 블러 없이 최고 화질 Shorts 조립

공식 파이프라인 순서 (--with-images 사용 시):
  01_generate_story.py
  01a_evaluate_story.py --auto-improve
  01b_analyze_shorts_plan.py --with-images  ← 여기서 Shorts 구간 결정 + 이미지 생성까지!
  02a_check_images.py --auto-regen
  03_generate_tts.py
  ...

  ※ --with-images 플래그: Shorts 구간 슬라이드의 기존 이미지를 자동 삭제 후
    02_generate_images.py 실행 → 9:16 이미지가 항상 최신 Shorts 구간에 맞게 생성됨.

사용법:
  python 01b_analyze_shorts_plan.py --ep 1
  python 01b_analyze_shorts_plan.py --dir output/bsl01
  python 01b_analyze_shorts_plan.py --ep 1 --force   (재분석)
  python 01b_analyze_shorts_plan.py --ep 1 --with-images  (Shorts 구간 이미지 강제 재생성)
"""

import argparse
import json
import os
import subprocess
import sys
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

# ── TTS 시간 추정 파라미터 ─────────────────────────────────
CHARS_PER_SEC  = 3.8   # 한국어 TTS 글자/초 (보수적 추정, Supertone 기준)
MIN_SEG_DUR    = 1.2   # 세그먼트 최소 길이
SLIDE_PAUSE    = 1.0   # 슬라이드 전환 포즈
SPEAKER_PAUSE  = 0.5   # 화자 변경 포즈
SAME_PAUSE     = 0.2   # 동일 화자 포즈
COVER_DUR      = 3.0   # 표지 고정 길이

MIN_WIN_SEC = 45
MAX_WIN_SEC = 75


# ── 유틸 ─────────────────────────────────────────────────────

def purge_shorts_images(ep_dir: Path, start_slide: int, end_slide: int):
    """Shorts 구간 슬라이드 이미지(16:9 + 9:16) 삭제 → 02_generate_images.py 재생성 유도."""
    images_dir = ep_dir / "images"
    if not images_dir.exists():
        return
    deleted = []
    for n in range(start_slide, end_slide + 1):
        for suffix in ("", "_9x16"):
            p = images_dir / f"slide_{n:02d}{suffix}.png"
            if p.exists():
                p.unlink()
                deleted.append(p.name)
    if deleted:
        print(f"  [9:16 준비] Shorts 구간 이미지 삭제 ({len(deleted)}개): {', '.join(deleted)}")
    else:
        print(f"  [9:16 준비] Shorts 구간 이미지 없음 — 신규 생성됩니다.")


def resolve_ep_dir(args) -> Path:
    if args.dir:
        d = Path(args.dir)
    else:
        d = Path(__file__).parent / "output" / f"ep{int(args.ep):02d}"
    if not d.exists():
        print(f"[ERROR] 디렉토리 없음: {d}")
        sys.exit(1)
    return d


def load_story(ep_dir: Path) -> dict:
    p = ep_dir / "story.json"
    if not p.exists():
        print(f"[ERROR] story.json 없음: {p}")
        sys.exit(1)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 슬라이드 타이밍 ──────────────────────────────────────────

def estimate_slide_duration(slide: dict, voice_speed: float = 0.9) -> float:
    """TTS 텍스트 길이로 슬라이드 재생 시간을 추정합니다."""
    stype = slide.get("type", "story")
    segments = slide.get("tts_segments", [])

    if not segments:
        return COVER_DUR if stype == "cover" else 3.0

    total = 0.0
    prev_speaker = None
    for seg in segments:
        text    = seg.get("text", "").strip()
        speaker = seg.get("speaker", "narrator")
        chars   = len(text.replace(" ", ""))
        dur     = max(chars / (CHARS_PER_SEC * voice_speed), MIN_SEG_DUR)

        if prev_speaker is not None:
            total += SPEAKER_PAUSE if prev_speaker != speaker else SAME_PAUSE
        total += dur
        prev_speaker = speaker

    return round(total + SLIDE_PAUSE, 2)


def get_slide_timings(story: dict, timing_json: dict | None) -> list:
    """슬라이드별 {slide, type, start, end, duration} 목록 반환.
    timing.json이 있으면 정확한 값, 없으면 TTS 텍스트로 추정."""
    slides = story.get("slides", [])
    meta   = story.get("meta", {})

    # 내레이터 보이스 속도
    voice_speed = float(
        meta.get("supertone_voices", {}).get("narrator", {}).get("speed", 0.9)
    )

    if timing_json:
        by_slide = {t["slide"]: t for t in timing_json.get("slides", [])}
        return [
            {
                "slide":    sl["slide_number"],
                "type":     sl.get("type", "story"),
                "start":    by_slide[sl["slide_number"]]["start"],
                "end":      by_slide[sl["slide_number"]]["end"],
                "duration": by_slide[sl["slide_number"]]["duration"],
            }
            for sl in slides
            if sl["slide_number"] in by_slide
        ]

    # 추정 모드
    result, cursor = [], 0.0
    for sl in slides:
        dur = estimate_slide_duration(sl, voice_speed)
        result.append({
            "slide":    sl["slide_number"],
            "type":     sl.get("type", "story"),
            "start":    round(cursor, 2),
            "end":      round(cursor + dur, 2),
            "duration": round(dur, 2),
        })
        cursor += dur
    return result


def enumerate_windows(slide_timings: list) -> list:
    story_slides = [s for s in slide_timings if s["type"] == "story"]
    windows = []
    n = len(story_slides)
    for i in range(n):
        total = 0.0
        for j in range(i, n):
            total += story_slides[j]["duration"]
            if total > MAX_WIN_SEC:
                break
            if total >= MIN_WIN_SEC:
                windows.append({
                    "start_slide": story_slides[i]["slide"],
                    "end_slide":   story_slides[j]["slide"],
                    "start_time":  story_slides[i]["start"],
                    "end_time":    story_slides[j]["end"],
                    "duration":    round(total, 1),
                })
    return windows


# ── AI 분석 ─────────────────────────────────────────────────

def build_prompt(story: dict, windows: list, slide_timings: list) -> str:
    meta  = story.get("meta", {})
    title = meta.get("story_title", "")
    lang  = meta.get("language", "ko")

    slides_by_num = {sl["slide_number"]: sl for sl in story.get("slides", [])}
    timing_by_num = {t["slide"]: t for t in slide_timings}

    slide_lines = []
    for t in slide_timings:
        if t["type"] != "story":
            continue
        sl   = slides_by_num.get(t["slide"], {})
        segs = sl.get("tts_segments", [])
        first = segs[0].get("text", "").strip()[:70] if segs else ""
        mood  = sl.get("color_mood", "")
        slide_lines.append(
            f'  {t["slide"]}번({t["duration"]}s, {mood}): "{first}"'
        )

    win_lines = []
    for i, w in enumerate(windows):
        moods = []
        for sn in range(w["start_slide"], w["end_slide"] + 1):
            sl = slides_by_num.get(sn, {})
            if sl.get("type") == "story":
                moods.append(sl.get("color_mood", ""))
        first = slides_by_num.get(w["start_slide"], {})
        first_segs = first.get("tts_segments", [])
        first_line = first_segs[0].get("text", "").strip()[:60] if first_segs else ""
        win_lines.append(
            f'  W{i+1}: 슬라이드 {w["start_slide"]}~{w["end_slide"]} ({w["duration"]}초)'
            f' | 감정흐름: {" → ".join(moods)} | 시작: "{first_line}"'
        )

    if lang == "id":
        hook_instruction = '"hook_text":"<teks hook Bahasa Indonesia maks 15 karakter>"'
        intro = f'Cerita "{title}" — Pilih segmen terbaik untuk YouTube Shorts'
        score_section = """Kriteria skor WAJIB (total 100 poin — ambang batas: 80):
  [A] Daya tarik pembuka (hook kuat di 3 detik pertama, cegah skip): 30 poin
  [B] Ketertarikan & ketegangan (penonton penasaran sampai akhir): 25 poin
  [C] Kepentingan peristiwa (momen puncak / titik balik cerita): 25 poin
  [D] Kualitas hook keyword (judul/kata kunci menarik klik): 20 poin

Penting:
- Jika tidak ada segmen dengan skor >= 80, pilih yang tertinggi dan tandai "low_quality": true
- Segmen yang hanya berisi narasi deskriptif tanpa aksi/dialog kuat TIDAK boleh dipilih"""
        json_schema = f'"start_slide":<nomor>,"end_slide":<nomor>,"score_a":<0-30>,"score_b":<0-25>,"score_c":<0-25>,"score_d":<0-20>,"score":<total 0-100>,{hook_instruction},"reason":"<alasan>","low_quality":<true/false>'
        footer = f'Jawab hanya JSON 1 segmen terbaik (tanpa teks lain):\n{{{{{json_schema}}}}}'
        lbl_slides = "Ringkasan slide"
        lbl_windows = f"Segmen kandidat ({len(windows)})"
        lbl_note = "Catatan: start_slide/end_slide HARUS menggunakan nomor slide nyata dari kandidat di atas."
    elif lang == "es":
        hook_instruction = '"hook_text":"<frase hook en español máx 15 caracteres>"'
        intro = f'Cuento "{title}" — Seleccionar el mejor segmento para YouTube Shorts'
        score_section = """Criterios de puntuación OBLIGATORIOS (total 100 puntos — umbral: 80):
  [A] Apertura gancho (gancho fuerte en los primeros 3 seg, evitar skip): 30 puntos
  [B] Interés/tensión (mantener al espectador hasta el final): 25 puntos
  [C] Importancia del evento (momento clave / punto de giro): 25 puntos
  [D] Calidad del keyword hook (título/palabra clave que genera clics): 20 puntos

Importante:
- Si ningún segmento supera 80 puntos, elegir el más alto y marcar "low_quality": true
- No seleccionar segmentos que solo tengan narración descriptiva sin acción/diálogo fuerte"""
        json_schema = f'"start_slide":<número>,"end_slide":<número>,"score_a":<0-30>,"score_b":<0-25>,"score_c":<0-25>,"score_d":<0-20>,"score":<total 0-100>,{hook_instruction},"reason":"<razón>","low_quality":<true/false>'
        footer = f'Responde solo con JSON del mejor segmento (sin otro texto):\n{{{{{json_schema}}}}}'
        lbl_slides = "Resumen de diapositivas"
        lbl_windows = f"Segmentos candidatos ({len(windows)})"
        lbl_note = "Nota: start_slide/end_slide DEBEN usar los números reales de los candidatos de arriba."
    elif lang == "pt":
        hook_instruction = '"hook_text":"<frase hook em português máx 15 caracteres>"'
        intro = f'Conto "{title}" — Selecionar o melhor segmento para YouTube Shorts'
        score_section = """Critérios de pontuação OBRIGATÓRIOS (total 100 pontos — limite: 80):
  [A] Abertura gancho (gancho forte nos primeiros 3 seg, evitar skip): 30 pontos
  [B] Interesse/tensão (manter o espectador até o final): 25 pontos
  [C] Importância do evento (momento-chave / ponto de virada): 25 pontos
  [D] Qualidade do keyword hook (título/palavra-chave que gera cliques): 20 pontos

Importante:
- Se nenhum segmento superar 80 pontos, escolher o mais alto e marcar "low_quality": true
- Não selecionar segmentos que contenham apenas narração descritiva sem ação/diálogo forte"""
        json_schema = f'"start_slide":<número>,"end_slide":<número>,"score_a":<0-30>,"score_b":<0-25>,"score_c":<0-25>,"score_d":<0-20>,"score":<total 0-100>,{hook_instruction},"reason":"<razão>","low_quality":<true/false>'
        footer = f'Responda apenas com JSON do melhor segmento (sem outro texto):\n{{{{{json_schema}}}}}'
        lbl_slides = "Resumo dos slides"
        lbl_windows = f"Segmentos candidatos ({len(windows)})"
        lbl_note = "Nota: start_slide/end_slide DEVEM usar os números reais dos candidatos acima."
    elif lang == "en":
        hook_instruction = '"hook_text":"<hook phrase in English max 15 chars>"'
        intro = f'Story "{title}" — Select the best segment for YouTube Shorts'
        score_section = """Scoring criteria REQUIRED (total 100 pts — threshold: 80):
  [A] Hook opening (strong hook in first 3 sec, prevent skip): 30 pts
  [B] Interest/tension (keep viewer watching to the end): 25 pts
  [C] Event importance (key moment / story turning point): 25 pts
  [D] Keyword hook quality (title/keyword that drives clicks): 20 pts

Important:
- If no segment scores >= 80, pick the highest and mark "low_quality": true
- Do not select segments that contain only descriptive narration without strong action/dialogue"""
        json_schema = f'"start_slide":<number>,"end_slide":<number>,"score_a":<0-30>,"score_b":<0-25>,"score_c":<0-25>,"score_d":<0-20>,"score":<total 0-100>,{hook_instruction},"reason":"<reason>","low_quality":<true/false>'
        footer = f'Reply with JSON of the single best segment only (no other text):\n{{{{{json_schema}}}}}'
        lbl_slides = "Slide summary"
        lbl_windows = f"Candidate windows ({len(windows)})"
        lbl_note = "Note: start_slide/end_slide MUST use actual slide numbers from the candidates above."
    else:  # ko (기본)
        hook_instruction = '"hook_text":"<훅문구 최대15자>"'
        intro = f'동화 "{title}" — YouTube Shorts 최적 구간 선정'
        score_section = """점수 기준 필수 평가 (합계 100점 — 합격 기준: 80점):
  [A] 후킹 오프닝 (첫 3초 강한 대사/행동, 이탈 방지): 30점
  [B] 흥미/긴장감 (끝까지 시청하게 만드는 몰입감): 25점
  [C] 사건 중요성 (스토리 핵심 순간/전환점 포함): 25점
  [D] 키워드 후킹력 (클릭을 유발하는 제목/핵심어 추출 가능성): 20점

주의사항:
- 80점 미만이면 그 구간은 Shorts 부적합. 그나마 높은 것 선택 후 "low_quality": true 표시
- 단순 설명 나레이션만 있는 구간은 선택 금지"""
        json_schema = f'"start_slide":<번호>,"end_slide":<번호>,"score_a":<0-30>,"score_b":<0-25>,"score_c":<0-25>,"score_d":<0-20>,"score":<합계 0-100>,{hook_instruction},"reason":"<선택이유>","low_quality":<true/false>'
        footer = f'1등 구간만 JSON으로 응답 (다른 텍스트 없이):\n{{{{{json_schema}}}}}'
        lbl_slides = "슬라이드 요약"
        lbl_windows = f"후보 구간 ({len(windows)}개)"
        lbl_note = "주의: start_slide/end_slide는 반드시 위 후보 구간에 나온 실제 슬라이드 번호를 사용할 것."

    return f"""{intro}

{lbl_slides}:
{chr(10).join(slide_lines)}

{lbl_windows}:
{chr(10).join(win_lines)}

{score_section}

{lbl_note}

{footer}"""


def call_gemini(prompt: str) -> dict:
    print("[AI] Gemini 2.5 Flash로 Shorts 구간 분석 중...")
    resp = _client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json",
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        ),
    )
    raw = resp.text.strip()
    s = raw.find("{"); e = raw.rfind("}") + 1
    if s >= 0 and e > s:
        raw = raw[s:e]
    return json.loads(raw)


# ── 메인 ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Shorts 구간 사전 분석 + 4기준 품질 평가 (이미지 생성 전)")
    parser.add_argument("--ep",          type=int, help="에피소드 번호")
    parser.add_argument("--dir",         type=str, help="에피소드 디렉토리")
    parser.add_argument("--force",       action="store_true", help="기존 계획 무시하고 재분석")
    parser.add_argument("--with-images", action="store_true", help="분석 완료 후 02_generate_images.py 자동 실행")
    args = parser.parse_args()
    if not args.ep and not args.dir:
        parser.print_help(); sys.exit(1)

    ep_dir     = resolve_ep_dir(args)
    plan_path  = ep_dir / "shorts_plan.json"

    # 이미 있으면 건너뜀
    if plan_path.exists() and not args.force:
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
        lq = plan.get("low_quality", False)
        print(f"[INFO] shorts_plan.json 이미 있음 (--force로 재분석)")
        print(f"  선택 구간: 슬라이드 {plan['start_slide']}~{plan['end_slide']}")
        print(f"  점수: {plan['score']}점 {'⚠ 품질 낮음' if lq else ''} | 훅: {plan['hook_text']}")
        if args.with_images:
            print(f"[이미지 연계] Shorts 구간 이미지 초기화 후 02_generate_images.py 실행...")
            purge_shorts_images(ep_dir, plan["start_slide"], plan["end_slide"])
            img_cmd = [sys.executable, "02_generate_images.py"]
            if args.dir:  img_cmd += ["--dir", args.dir]
            elif args.ep: img_cmd += ["--ep", str(args.ep)]
            subprocess.run(img_cmd, cwd=Path(__file__).parent)
        else:
            print(f"[NEXT] 02_generate_images.py 실행 시 9:16 이미지 자동 생성됩니다.")
        return

    story = load_story(ep_dir)
    title = story.get("meta", {}).get("story_title", ep_dir.name)

    # timing.json 있으면 정확한 타이밍 활용
    timing = None
    t_path = ep_dir / "audio" / "timing.json"
    if t_path.exists():
        with open(t_path, encoding="utf-8") as f:
            timing = json.load(f)
        print("[INFO] timing.json 발견 → 정확한 타이밍 사용")
    else:
        print("[INFO] timing.json 없음 → TTS 텍스트로 시간 추정")

    slide_timings = get_slide_timings(story, timing)
    total_est = sum(t["duration"] for t in slide_timings)

    print(f"\n{'='*60}")
    print(f"  [01b] Shorts 구간 분석: {title}")
    print(f"  추정 총 길이: {total_est:.1f}초 | 슬라이드: {len(slide_timings)}개")
    print(f"{'='*60}")

    windows = enumerate_windows(slide_timings)
    print(f"[INFO] 후보 윈도우: {len(windows)}개 ({MIN_WIN_SEC}~{MAX_WIN_SEC}초)")
    if not windows:
        print("[ERROR] 적합한 구간이 없습니다.")
        sys.exit(1)

    prompt = build_prompt(story, windows, slide_timings)
    result = call_gemini(prompt)

    # AI 응답 유효성 검사 (역전 범위 / 존재하지 않는 윈도우 방지)
    ss = result.get("start_slide", 0)
    es = result.get("end_slide", 0)
    valid_window = next((w for w in windows if w["start_slide"] == ss and w["end_slide"] == es), None)
    if ss > es or valid_window is None:
        print(f"  [WARN] AI 응답 무효 (start={ss}, end={es}) → 최적 윈도우 자동 선택")
        # 점수가 가장 높은(긴) 윈도우 선택
        best = max(windows, key=lambda w: w["duration"])
        result["start_slide"] = best["start_slide"]
        result["end_slide"]   = best["end_slide"]
        print(f"  [FALLBACK] 슬라이드 {result['start_slide']}~{result['end_slide']} 선택")

    # 4기준 개별 점수 포함
    score_a = result.get("score_a", 0)
    score_b = result.get("score_b", 0)
    score_c = result.get("score_c", 0)
    score_d = result.get("score_d", 0)
    total_score = result.get("score", score_a + score_b + score_c + score_d)
    low_quality = result.get("low_quality", total_score < 80)

    plan = {
        "start_slide":   result["start_slide"],
        "end_slide":     result["end_slide"],
        "score":         total_score,
        "score_detail":  {"hook_opening": score_a, "interest": score_b, "scene_importance": score_c, "keyword_hook": score_d},
        "low_quality":   low_quality,
        "hook_text":     result.get("hook_text", ""),
        "reason":        result.get("reason", ""),
        "timing_source": "timing.json" if timing else "estimated",
        "analyzed_by":   "01b_analyze_shorts_plan",
    }

    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"  [결과] 슬라이드 {plan['start_slide']}~{plan['end_slide']} | 총점 {total_score}점 {'⚠ Shorts 품질 낮음' if low_quality else '✓ Shorts 적합'}")
    print(f"  세부: 후킹오프닝={score_a}/30  흥미={score_b}/25  사건중요성={score_c}/25  키워드후킹={score_d}/20")
    print(f"  훅: {plan['hook_text']}")
    print(f"  이유: {plan['reason']}")
    print(f"\n  저장: {plan_path}")

    # 이미지 자동 연계
    if getattr(args, "with_images", False):
        print(f"\n  [이미지 연계] Shorts 구간 이미지 초기화 후 02_generate_images.py 실행...")
        purge_shorts_images(ep_dir, plan["start_slide"], plan["end_slide"])
        img_cmd = [sys.executable, "02_generate_images.py"]
        if args.dir:
            img_cmd += ["--dir", args.dir]
        elif args.ep:
            img_cmd += ["--ep", str(args.ep)]
        subprocess.run(img_cmd, cwd=Path(__file__).parent)
    else:
        print(f"\n  [NEXT] python 02_generate_images.py --ep {args.ep or ''} --dir {args.dir or ''}")
        print(f"  → 슬라이드 {plan['start_slide']}~{plan['end_slide']} 에 9:16 이미지 자동 생성")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
