#!/usr/bin/env python3
"""전 에피소드 supporting/main 캐릭터 vs 캐시된 Typecast 보이스의 성별/나이 불일치 검수."""
import sys, os, json, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
import requests

API_KEY = os.getenv("TYPECAST_API_KEY")
resp = requests.get("https://api.typecast.ai/v2/voices", headers={"X-API-KEY": API_KEY}, timeout=30)
data = resp.json()
if isinstance(data, dict):
    data = data.get("voices") or data.get("items") or data.get("result") or []
VOICE_INFO = {v.get("voice_id"): v for v in data if isinstance(v, dict)}

MALE_KW = ["할아버지", "grandpa", "grandfather", "아저씨", "삼촌", "왕자", "우체부", "임금",
           "아빠", "아버지", "father", "dad ",
           "king", "prince", "uncle", "mailman", "postman", "wizard", "마법사", "도깨비",
           "소년", "boy", "남자", "male", " he ", "his "]
FEMALE_KW = ["할머니", "grandma", "grandmother", "아줌마", "이모", "공주", "여왕", "왕비",
             "엄마", "어머니", "mother", "mom ",
             "queen", "princess", "aunt", "witch", "마녀", "sorceress",
             "소녀", "girl", "여자", "female", " she ", "her "]

issues = []
checked = 0

for story_path in sorted(Path("output").glob("*/story.json")):
    ep_dir = story_path.parent
    try:
        story = json.loads(story_path.read_text(encoding="utf-8"))
    except Exception as e:
        continue
    meta = story.get("meta", {})
    chars = meta.get("characters", {})
    tv = meta.get("typecast_voices", {})
    if not tv:
        continue

    entries = {}
    for k, v in chars.items():
        if k in ("main_1", "main_2", "main_3") and isinstance(v, dict):
            entries[k] = v
    sup = chars.get("supporting", {})
    if isinstance(sup, dict):
        for k, v in sup.items():
            if isinstance(v, dict):
                entries[k] = v
            elif isinstance(v, dict) and v.get("name"):
                entries[v["name"]] = v

    for speaker, vinfo in tv.items():
        checked += 1
        voice_id = vinfo.get("voice_id", "")
        real = VOICE_INFO.get(voice_id, {})
        real_gender = real.get("gender", "?")
        real_age = real.get("age", "?")

        ch = entries.get(speaker)
        if not ch:
            continue
        combined = (ch.get("role", "") + " " + ch.get("appearance_en", "") + " " +
                    ch.get("species", "") + " " + ch.get("personality", "")).lower()
        explicit_gender = ch.get("gender") if ch.get("gender") in ("male", "female") else None

        expected_gender = explicit_gender
        if not expected_gender:
            if any(w in combined for w in MALE_KW):
                expected_gender = "male"
            elif any(w in combined for w in FEMALE_KW):
                expected_gender = "female"

        is_elder = any(w in combined for w in ["할아버지", "할머니", "grandpa", "grandfather",
                                                "grandma", "grandmother", "elder", "wise", "장로", "노인"])

        mismatch_gender = expected_gender and real_gender in ("male", "female") and expected_gender != real_gender
        mismatch_age = is_elder and real_age not in ("elder", "senior", "middle_age", "?")

        if mismatch_gender or mismatch_age:
            issues.append({
                "ep": ep_dir.name,
                "speaker": speaker,
                "voice_name": vinfo.get("name"),
                "voice_id": voice_id,
                "expected_gender": expected_gender,
                "real_gender": real_gender,
                "real_age": real_age,
                "is_elder": is_elder,
                "combined_snip": combined[:100],
            })

print(f"[검수 완료] {checked}개 캐릭터-보이스 매핑 확인, 불일치 {len(issues)}건\n")
for it in issues:
    print(f"- [{it['ep']}] speaker={it['speaker']} voice={it['voice_name']}({it['voice_id'][:14]}...) "
          f"실제(gender={it['real_gender']}, age={it['real_age']}) vs 기대(gender={it['expected_gender']}, elder={it['is_elder']})")
    print(f"    캐릭터 설명: {it['combined_snip']}")

Path("_voice_audit_report.json").write_text(json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n상세 리포트: _voice_audit_report.json")
