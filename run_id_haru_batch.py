#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_id_haru_batch.py
1학년 2학기 '하루' 단원 10편 -> 인도네시아어 번역 + TTS(Gemini) + 영상 조립 + 인니 채널(id) 업로드

상상 단원 배치(run_id_sangsang_batch.py)와 동일 구조. 전부 예약 발행(화/목 1편씩),
상상 단원 예약이 끝나는 다음 화요일(2026-10-13)부터 이어서 진행.
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import shutil
from translate_multilang import translate_story
import publish_youtube as py

PY = sys.executable

EPISODES = [
    dict(src="통합교과_하늘의하루2223p_1학년_함께골라요_삐요와토토하늘의색을세어봐요",
         unit_id="Sehari Bersama Langit (hlm 22-23)", schedule="2026-10-13T09:00:00+09:00"),
    dict(src="통합교과_달팽이의하루2425p_1학년_함께골라요_느리의아주특별한하루",
         unit_id="Sehari si Siput (hlm 24-25)", schedule="2026-10-15T09:00:00+09:00"),
    dict(src="통합교과_건강한하루2627p_1학년_함께골라요_팔팔이와뒹굴의콩콩건강한하루",
         unit_id="Hari yang Sehat (hlm 26-27)", schedule="2026-10-20T09:00:00+09:00"),
    dict(src="통합교과_마음의하루2829p_1학년_함께골라요_무지의색깔하루",
         unit_id="Sehari dengan Perasaan (hlm 28-29)", schedule="2026-10-22T09:00:00+09:00"),
    dict(src="통합교과_하루저금통3031p_1학년_함께골라요_삐요와토토의반짝반짝하루저금통",
         unit_id="Celengan Sehari-hari (hlm 30-31)", schedule="2026-10-27T09:00:00+09:00"),
    dict(src="통합교과_하루의시작3233p_1학년_함께골라요_부엉이와꼬꼬의아침일과",
         unit_id="Awal Hari (hlm 32-33)", schedule="2026-10-29T09:00:00+09:00"),
    dict(src="통합교과_모두의하루3435p_1학년_함께골라요_삐요와토토마을의하루를찾아서",
         unit_id="Hari Milik Semua Orang (hlm 34-35)", schedule="2026-11-03T09:00:00+09:00"),
    dict(src="통합교과_하루세번3637p_1학년_함께골라요_까까와냠냠의골고루하루",
         unit_id="Tiga Kali Sehari (hlm 36-37)", schedule="2026-11-05T09:00:00+09:00"),
    dict(src="통합교과_해야해야나오너라3839p_1학년_함께골라요_삐요와토토의그림자밟기",
         unit_id="Matahari, Matahari, Keluarlah (hlm 38-39)", schedule="2026-11-10T09:00:00+09:00"),
    dict(src="통합교과_하루의리듬4041p_1학년_함께골라요_통통이와짤랑이의하루리듬",
         unit_id="Irama Sehari-hari (hlm 40-41)", schedule="2026-11-12T09:00:00+09:00"),
]

SUBJECT_ID = "Tema Terpadu"
SERIES_ID = "Hari"
SUBUNIT_ID = "Ayo Pilih Bersama"

LOG_PATH = ROOT / "_id_haru_batch_log.json"


def load_log():
    if LOG_PATH.exists():
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    return {}


def save_log(log):
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def run(cmd, cwd):
    print(f"\n$ {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"실패({r.returncode}): {' '.join(cmd)}")


def build_id_title(story, unit_id):
    meta = story["meta"]
    grade = meta.get("grade", 1)
    semester = meta.get("semester", 2)
    story_title = (meta.get("story_title") or "").strip()
    hook = story_title if (story_title and story_title[-1] in "!?.~") else story_title + "!"
    title = f"{hook} | Kelas {grade} Semester {semester} {SERIES_ID} - {unit_id}"
    return title[:100]


def build_id_description(story):
    meta = story["meta"]
    grade = meta.get("grade", 1)
    story_title = meta.get("story_title", "")
    logline = (meta.get("logline") or "").strip()
    if not logline:
        logline = f"Cerita {story_title}"
    chars = meta.get("characters", {})
    names = [chars[k]["name"] for k in ("main_1", "main_2") if chars.get(k, {}).get("name")]
    tag_title = "".join(ch for ch in story_title if ch.isalnum())
    return f"""🌟 {story_title}

{logline}

━━━━━━━━━━━━━━━━━━
📚 Mapel: {SUBJECT_ID} - {SERIES_ID}
📖 Sesi: {SUBUNIT_ID}
🎯 Untuk: Siswa Kelas {grade} SD
👥 Tokoh: {', '.join(names)}
━━━━━━━━━━━━━━━━━━

📌 Pertanyaan? Email: kdhdhdbdbr@gmail.com

#DongengAnak #Kelas{grade} #DongengEdukasi #BukuBergambar #{tag_title} #CeritaAnak
"""


def build_id_tags(story):
    meta = story["meta"]
    grade = meta.get("grade", 1)
    story_title = meta.get("story_title", "")
    return ["DongengAnak", f"Kelas{grade}", "DongengEdukasi", "BukuBergambar",
            story_title, "CeritaAnak", "PendidikanAnak"][:15]


def upload_id(dst_dir: Path, story: dict, creds, schedule: str, unit_id: str):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    video_path = dst_dir / "video.mp4"
    thumb_path = dst_dir / "thumbnail_c.png"
    if not thumb_path.exists():
        thumb_path = dst_dir / "thumbnail_a.png"
    if not video_path.exists():
        raise RuntimeError(f"video.mp4 없음: {video_path}")

    title = build_id_title(story, unit_id)
    description = build_id_description(story)
    tags = build_id_tags(story)

    privacy = "private" if schedule else "public"
    status_body = {"privacyStatus": privacy, "selfDeclaredMadeForKids": True}
    if schedule:
        status_body["publishAt"] = schedule

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "27",
            "defaultLanguage": "id",
        },
        "status": status_body,
    }

    youtube = build("youtube", "v3", credentials=creds)
    size_mb = video_path.stat().st_size // 1024 // 1024
    print(f"\n[YouTube-ID] 업로드: {video_path.name} ({size_mb} MB) / privacy={privacy} schedule={schedule}")
    print(f"  제목: {title}")
    media = MediaFileUpload(str(video_path), chunksize=4 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = py.resumable_upload(request, "인니 본편 업로드")
    video_id = response["id"]
    print(f"  [OK] https://youtu.be/{video_id}")

    if thumb_path.exists():
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb_path))).execute()

    return video_id


def main():
    log = load_log()
    creds = py.get_credentials("id")
    py.verify_channel("id", creds)  # 2026-09-12 사고 재발 방지 — 필수, 우회 불가
    out_root = ROOT / "output"

    for i, ep in enumerate(EPISODES, 1):
        src_name = ep["src"]
        key = src_name
        if log.get(key, {}).get("video_id"):
            print(f"\n[SKIP] {i}/10 이미 업로드됨: {log[key]['video_id']}")
            continue

        src_dir = out_root / src_name
        dst_dir = out_root / f"{src_name}_id"
        print(f"\n{'='*70}\n[하루 {i}/10] {src_name}\n{'='*70}")

        try:
            if not (dst_dir / "story.json").exists():
                translate_story(src_dir, "id")

            # thumbnail_c_bg.png(Gemini 클로즈업 배경, 언어 무관 동일 이미지) 복사
            src_c_bg = src_dir / "thumbnail_c_bg.png"
            dst_c_bg = dst_dir / "thumbnail_c_bg.png"
            if src_c_bg.exists() and not dst_c_bg.exists():
                shutil.copy2(src_c_bg, dst_c_bg)

            audio_dir = dst_dir / "audio"
            if not (audio_dir / "timing.json").exists():
                run([PY, "03_generate_tts.py", "--dir", str(dst_dir)], cwd=ROOT)
            run([PY, "04_concat_audio.py", "--dir", str(dst_dir)], cwd=ROOT)
            run([PY, "05_generate_srt.py", "--dir", str(dst_dir)], cwd=ROOT)
            run([PY, "07b_generate_quiz_slides.py", "--dir", str(dst_dir)], cwd=ROOT)
            run([PY, "10_generate_thumbnail.py", "--dir", str(dst_dir)], cwd=ROOT)
            if (dst_dir / "thumbnail_c_bg.png").exists():
                run([PY, "10_generate_thumbnail.py", "--style", "c", "--dir", str(dst_dir)], cwd=ROOT)
            run([PY, "06_assemble_video.py", "--dir", str(dst_dir)], cwd=ROOT)

            story = json.loads((dst_dir / "story.json").read_text(encoding="utf-8"))
            video_id = upload_id(dst_dir, story, creds, ep["schedule"], ep["unit_id"])

            log[key] = {
                "video_id": video_id,
                "url": f"https://youtu.be/{video_id}",
                "schedule": ep["schedule"],
                "uploaded_at": datetime.now().isoformat(),
            }
            save_log(log)
            print(f"\n[완료] 하루 {i}/10 -> https://youtu.be/{video_id}")

        except Exception as e:
            print(f"\n[ERROR] 하루 {i}/10 {src_name} 실패: {e}")
            log[key] = {"error": str(e), "failed_at": datetime.now().isoformat()}
            save_log(log)
            print("다음 에피소드로 계속 진행합니다 (재실행 시 실패분부터 재시도)")
            continue

    print("\n\n=== 하루 배치 종료 ===")
    for k, v in log.items():
        print(k, "->", v)


if __name__ == "__main__":
    main()
