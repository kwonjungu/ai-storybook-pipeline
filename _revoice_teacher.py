#!/usr/bin/env python3
"""특정 에피소드의 'teacher' speaker만 재캐스팅 + 관련 오디오/영상 재생성 준비.
(narrator/child_boy/child_girl 등 이미 정상인 보이스는 건드리지 않음)
"""
import sys, os, json, importlib.util
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# 03_generate_tts.py는 파일명이 숫자로 시작해 일반 import 불가 → 파일 경로로 로드
spec = importlib.util.spec_from_file_location("gen_tts", "03_generate_tts.py")
gen_tts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen_tts)

TARGETS = [
    "통합교과_세상을바꿀초능력이생긴다면38_1학년_함께골라요_삐요와토토별똥별초능력",
    "통합교과_하늘의하루2223p_1학년_함께골라요_삐요와토토하늘의색을세어봐요",
    "통합교과_물건이악기가된다면3637p_1학년_함께골라요_통통이와두리의둥둥팅팅음악회",
    "통합교과_하루세번3637p_1학년_함께골라요_까까와냠냠의골고루하루",
    "통합교과_하루의리듬4041p_1학년_함께골라요_통통이와짤랑이의하루리듬",
    "통합교과_하루저금통3031p_1학년_함께골라요_삐요와토토의반짝반짝하루저금통",
]
SPEAKER = "teacher"
api_key = os.getenv("TYPECAST_API_KEY")

# recommend_voice()가 쓰는 /v1/voices/recommendations 응답엔 gender/age가 안 실려서
# _norm_voice가 항상 "?"로 채움 → 실제 성별 검증을 못 함. /v2/voices 전체 목록으로 별도 대조.
import requests as _rq
_resp = _rq.get("https://api.typecast.ai/v2/voices", headers={"X-API-KEY": api_key}, timeout=30)
_data = _resp.json()
if isinstance(_data, dict):
    _data = _data.get("voices") or _data.get("items") or _data.get("result") or []
REAL_VOICE_INFO = {v.get("voice_id"): v for v in _data if isinstance(v, dict)}


def revoice_one(folder: str):
    ep_dir = Path("output") / folder
    story_path = ep_dir / "story.json"
    story = json.loads(story_path.read_text(encoding="utf-8"))

    old = story["meta"]["typecast_voices"].get(SPEAKER, {})
    used_ids = {v["voice_id"] for k, v in story["meta"]["typecast_voices"].items() if k != SPEAKER}

    criteria = gen_tts.build_dynamic_criteria(SPEAKER, story)
    query = gen_tts.build_voice_query(SPEAKER, story)
    chosen = gen_tts.recommend_voice(api_key, query, used_ids)
    how = "맥락추천"

    # 맥락추천 응답엔 gender/age가 안 실려서 실제 카탈로그 대조로 성별 검증
    if chosen:
        real = REAL_VOICE_INFO.get(chosen["voice_id"], {})
        want_gender = criteria.get("gender")
        real_gender = real.get("gender")
        if want_gender and real_gender and want_gender != real_gender:
            print(f"  [무시] 맥락추천 '{chosen['name']}'은 실제 {real_gender} — 요구({want_gender})와 불일치, 점수폴백으로 전환")
            chosen = None
        elif real:
            chosen = {**chosen, "gender": real.get("gender", chosen.get("gender")),
                      "age": real.get("age", chosen.get("age"))}

    if not chosen:
        how = "점수폴백"
        all_voices = gen_tts.fetch_voices(api_key)
        candidates = [(gen_tts.score_voice(v, criteria), v) for v in all_voices if v["voice_id"] not in used_ids]
        candidates = [(s, v) for s, v in candidates if s > 0]
        candidates.sort(key=lambda x: -x[0])
        chosen = candidates[0][1] if candidates else None

    if not chosen:
        print(f"[FAIL] {folder}: 새 보이스를 찾지 못함")
        return None

    print(f"[{folder}]")
    print(f"  이전: {old.get('name')} (voice_id={old.get('voice_id','')[:14]}...)")
    print(f"  신규: {chosen['name']} (gender={chosen.get('gender')}, age={chosen.get('age')}) [{how}] criteria={criteria}")

    # story.json meta 갱신
    story["meta"]["typecast_voices"][SPEAKER] = {
        "voice_id": chosen["voice_id"], "name": chosen["name"],
        "gender": chosen.get("gender", "?"), "age": chosen.get("age", "?"),
    }
    story_path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")

    # audio/voice_selection.json 파일 캐시도 동기화
    vsel_path = ep_dir / "audio" / "voice_selection.json"
    if vsel_path.exists():
        vsel = json.loads(vsel_path.read_text(encoding="utf-8"))
        vsel[SPEAKER] = {
            "voice_id": chosen["voice_id"], "name": chosen["name"],
            "gender": chosen.get("gender", "?"), "age": chosen.get("age", "?"),
            "speed": criteria.get("speed", 1.0),
        }
        vsel_path.write_text(json.dumps(vsel, ensure_ascii=False, indent=2), encoding="utf-8")

    # teacher 세그먼트가 있는 slide/seg 찾아서 관련 wav 삭제 (재생성 유도)
    removed = []
    for slide in story.get("slides", []):
        sn = slide.get("slide_number")
        has_teacher = any(seg.get("speaker") == SPEAKER for seg in slide.get("tts_segments", []))
        if not has_teacher:
            continue
        for idx, seg in enumerate(slide.get("tts_segments", [])):
            if seg.get("speaker") == SPEAKER:
                p = ep_dir / "audio" / f"slide_{sn:02d}_seg_{idx:02d}.wav"
                if p.exists():
                    p.unlink()
                    removed.append(p.name)
        # 슬라이드 합본도 삭제 (04에서 재생성)
        p2 = ep_dir / "audio" / f"slide_{sn:02d}.wav"
        if p2.exists():
            p2.unlink()
            removed.append(p2.name)

    for extra in ["full_audio.wav"]:
        p3 = ep_dir / "audio" / extra
        if p3.exists():
            p3.unlink()
            removed.append(extra)

    print(f"  삭제된 오디오 파일: {removed}")
    return folder


if __name__ == "__main__":
    done = []
    for folder in TARGETS:
        r = revoice_one(folder)
        if r:
            done.append(r)
    print("\n=== 재캐스팅 완료 에피소드 ===")
    for d in done:
        print(" -", d)
