#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_id_sangsang_batch.py
1학년 2학기 '상상' 단원 10편 -> 인도네시아어 번역 + TTS(Gemini) + 영상 조립 + 인니 채널(id) 업로드

- 1~2번째(알에서 동물이/상자): 즉시 공개
- 3~10번째: 화/목 1편씩 예약 공개 (publishAt, private로 올렸다가 유튜브가 자동 공개)
- 실패한 에피소드는 로그에 error로 남기고 다음으로 진행. 재실행 시 완료분(_id_batch_log.json에
  video_id 있는 항목)은 건너뜀 -> 안전하게 재시도 가능.
"""
import argparse
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
    dict(src="통합교과_알에서동물이태어난다면2021_1학년_함께골라요_삐요와토토의신비한알탐험",
         unit_id="Jika Hewan Menetas dari Telur (hlm 20-21)", schedule=None),
    dict(src="통합교과_상자에물건이들어있다면2223_1학년_함께골라요_삐요와토토의신비한상자",
         unit_id="Jika Ada Benda di Dalam Kotak (hlm 22-23)", schedule=None),
    dict(src="통합교과_함께간다면2425p_1학년_함께골라요_어디만큼갔니삐요와토토의초록마을여행",
         unit_id="Jika Kita Pergi Bersama (hlm 24-25)", schedule="2026-09-15T09:00:00+09:00"),
    dict(src="통합교과_여러가지모양이살아난다면262_1학년_함께골라요_삐요와토토의모양나라대모험",
         unit_id="Jika Berbagai Bentuk Menjadi Hidup (hlm 26-27)", schedule="2026-09-17T09:00:00+09:00"),
    dict(src="통합교과_장난감이춤을춘다면2829p_1학년_함께골라요_띠깍과푸미의달빛무도회",
         unit_id="Jika Mainan Menari (hlm 28-29)", schedule="2026-09-22T09:00:00+09:00"),
    dict(src="통합교과_여기저기에서본다면3031p_1학년_함께골라요_삐요와토토의알록달록수수께끼",
         unit_id="Jika Kita Melihat dari Berbagai Sudut (hlm 30-31)", schedule="2026-09-24T09:00:00+09:00"),
    dict(src="통합교과_새로운동물이나타난다면3233_1학년_함께골라요_삐요와토토의상상동물만들기",
         unit_id="Jika Muncul Hewan Baru (hlm 32-33)", schedule="2026-09-29T09:00:00+09:00"),
    dict(src="통합교과_비눗방울이그림이된다면3435_1학년_함께골라요_퐁퐁비눗방울그림나라",
         unit_id="Jika Gelembung Sabun Menjadi Gambar (hlm 34-35)", schedule="2026-10-01T09:00:00+09:00"),
    dict(src="통합교과_물건이악기가된다면3637p_1학년_함께골라요_통통이와두리의둥둥팅팅음악회",
         unit_id="Jika Benda Menjadi Alat Musik (hlm 36-37)", schedule="2026-10-06T09:00:00+09:00"),
    dict(src="통합교과_세상을바꿀초능력이생긴다면38_1학년_함께골라요_삐요와토토별똥별초능력",
         unit_id="Jika Punya Kekuatan Super yang Mengubah Dunia (hlm 38-39)", schedule="2026-10-08T09:00:00+09:00"),
]

# 상상 2차분(12~20차시, bsl28~36) — 화·목 09:00 KST. 인트로·11b·애니 복사 포함 (--unit sangsang2)
EPISODES_SANGSANG2 = [
    dict(src="통합교과_우리반에공룡이나타난다면404_1학년_함께골라요_삐요와토토의쿵쿵교실공룡뿌뿌",
         unit_id="Jika Dinosaurus Muncul di Kelas Kita (hlm 40-41)", schedule="2026-11-17T09:00:00+09:00"),
    dict(src="통합교과_내가음악을만든다면4243p_1학년_함께골라요_랄라와흥얼이의기분음악회",
         unit_id="Jika Aku Membuat Musik (hlm 42-43)", schedule="2026-11-19T09:00:00+09:00"),
    dict(src="통합교과_몸으로말한다면4445p_1학년_함께골라요_재잘이와쏙쏙이의몸으로말해요",
         unit_id="Jika Kita Berbicara dengan Tubuh (hlm 44-45)", schedule="2026-11-24T09:00:00+09:00"),
    dict(src="통합교과_숨바꼭질을한다면4647p_1학년_함께골라요_꼼지와알록이의꼭꼭숨바꼭질",
         unit_id="Jika Kita Bermain Petak Umpet (hlm 46-47)", schedule="2026-11-26T09:00:00+09:00"),
    dict(src="통합교과_거꾸로생각한다면4849p_1학년_함께골라요_뾰족한날엔거꾸로꺼꾸리와대롱이",
         unit_id="Jika Kita Berpikir Terbalik (hlm 48-49)", schedule="2026-12-01T09:00:00+09:00"),
    dict(src="통합교과_거인나라에간다면5051p_1학년_함께골라요_콩알이와점점이의거인나라여행",
         unit_id="Jika Kita Pergi ke Negeri Raksasa (hlm 50-51)", schedule="2026-12-03T09:00:00+09:00"),
    dict(src="통합교과_무엇이든바꿀수있다면5253p_1학년_함께골라요_꼬리와쭈욱이의말놀이상상여행",
         unit_id="Jika Semuanya Bisa Berubah (hlm 52-53)", schedule="2026-12-08T09:00:00+09:00"),
    dict(src="통합교과_우리들의놀이터를만든다면545_1학년_함께골라요_삐요와토토의상상놀이터",
         unit_id="Jika Kita Membuat Taman Bermain Sendiri (hlm 54-55)", schedule="2026-12-10T09:00:00+09:00"),
    dict(src="통합교과_생각세고개를넘는다면5657p_1학년_함께골라요_갸웃이와톡톡이의생각세고개",
         unit_id="Jika Kita Melewati Tiga Bukit Pikiran (hlm 56-57)", schedule="2026-12-15T09:00:00+09:00"),
]

SUBJECT_ID = "Tema Terpadu"
SERIES_ID = "Imajinasi"
SUBUNIT_ID = "Ayo Pilih Bersama"

LOG_PATH = ROOT / "_id_batch_log.json"
UNITS = {
    "sangsang":  dict(episodes=EPISODES, log="_id_batch_log.json"),
    "sangsang2": dict(episodes=EPISODES_SANGSANG2, log="_id_sangsang2_batch_log.json", new_chain=True),
}


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N편만 처리")
    ap.add_argument("--no-upload", action="store_true",
                    help="생성만 하고 업로드 건너뜀 (인니 채널 미개설 상태에서 미리 제작용)")
    ap.add_argument("--unit", choices=list(UNITS), default="sangsang", help="처리할 묶음 (기본 sangsang)")
    args = ap.parse_args()

    global LOG_PATH
    cfg = UNITS[args.unit]
    LOG_PATH = ROOT / cfg["log"]
    new_chain = bool(cfg.get("new_chain"))
    print(f"[INFO] 묶음: {args.unit} / 기록: {LOG_PATH.name}")

    log = load_log()
    creds = None
    if not args.no_upload:
        creds = py.retry(lambda: py.get_credentials("id"), "인증")
        py.retry(lambda: py.verify_channel("id", creds), "채널확인")  # 2026-09-12 사고 재발 방지 — 필수, 우회 불가
    out_root = ROOT / "output"

    episodes = cfg['episodes'][:args.limit] if args.limit else cfg['episodes']
    total = len(episodes)
    for i, ep in enumerate(episodes, 1):
        src_name = ep["src"]
        key = src_name
        if log.get(key, {}).get("video_id"):
            print(f"\n[SKIP] {i}/{total} 이미 업로드됨: {log[key]['video_id']}")
            continue

        src_dir = out_root / src_name
        dst_dir = out_root / f"{src_name}_id"
        print(f"\n{'='*70}\n[{i}/{total}] {src_name}\n{'='*70}")

        try:
            if not (dst_dir / "story.json").exists():
                translate_story(src_dir, "id", copy_anim=new_chain)

            # thumbnail_c_bg.png(Gemini 클로즈업 배경, 언어 무관 동일 이미지) 복사
            src_c_bg = src_dir / "thumbnail_c_bg.png"
            dst_c_bg = dst_dir / "thumbnail_c_bg.png"
            if src_c_bg.exists() and not dst_c_bg.exists():
                shutil.copy2(src_c_bg, dst_c_bg)

            if new_chain and (dst_dir / "video.mp4").exists() and (dst_dir / "intro.json").exists():
                print(f"[SKIP-생성] 이미 완성됨(인트로 포함): {dst_dir.name}")
                story = json.loads((dst_dir / "story.json").read_text(encoding="utf-8"))
                if args.no_upload:
                    continue
                video_id = upload_id(dst_dir, story, creds, ep["schedule"], ep["unit_id"])
                log[key] = {"video_id": video_id, "url": f"https://youtu.be/{video_id}",
                            "schedule": ep["schedule"], "uploaded_at": datetime.now().isoformat()}
                save_log(log)
                continue

            audio_dir = dst_dir / "audio"
            if not (audio_dir / "timing.json").exists():
                # 의성어 효과음 1단계 (번역본의 sfx 필드/어휘표 -> audio/sfx_events.json). 이벤트 없으면 무변화, 실패해도 계속
                try:
                    run([PY, "sfx_prep.py", "--dir", str(dst_dir)], cwd=ROOT)
                except Exception as e:
                    print(f"[WARN] sfx_prep 실패, 효과음 없이 계속: {e}")
                run([PY, "03_generate_tts.py", "--dir", str(dst_dir)], cwd=ROOT)
            # TTS 세그먼트 완전성 게이트 (2026-09-14 사고 이후 필수)
            # Gemini TTS 가 간헐적으로 빈 응답을 줘 대사가 통째로 빠진 영상이 업로드된 적이 있다.
            # 빠진 것만 다시 만들어 보고, 그래도 미달이면 이 편은 조립·업로드하지 않고 건너뛴다.
            from tts_gate import ensure_complete
            if not ensure_complete(dst_dir, retries=2, python_exe=PY):
                raise RuntimeError("TTS 세그먼트 결손 — 조립·업로드 중단")

            run([PY, "sfx_prep.py", "--dir", str(dst_dir), "--pad"], cwd=ROOT)   # 효과음 자리 확보 (이벤트 없으면 통과)
            run([PY, "04_concat_audio.py", "--dir", str(dst_dir)], cwd=ROOT)
            run([PY, "sfx_mix.py", "--dir", str(dst_dir)], cwd=ROOT)             # 효과음 믹스 (이벤트 없으면 통과)
            run([PY, "05_generate_srt.py", "--dir", str(dst_dir)], cwd=ROOT)
            run([PY, "07b_generate_quiz_slides.py", "--dir", str(dst_dir)], cwd=ROOT)
            run([PY, "10_generate_thumbnail.py", "--dir", str(dst_dir)], cwd=ROOT)
            if (dst_dir / "thumbnail_c_bg.png").exists():
                run([PY, "10_generate_thumbnail.py", "--style", "c", "--dir", str(dst_dir)], cwd=ROOT)
            if new_chain:
                # ko 에서 복사된 key_slide 를 이 언어 음성 기준으로 다시 렌더 (실패해도 계속)
                try:
                    run([PY, "11b_key_scene.py", "--dir", str(dst_dir), "--force", "--reuse"], cwd=ROOT)
                except Exception as e:
                    print(f"[WARN] 11b 실패, 계속 진행: {e}")
            run([PY, "06_assemble_video.py", "--dir", str(dst_dir)], cwd=ROOT)
            if new_chain and not (dst_dir / "intro.json").exists():   # 인트로는 06 다음, 이중 부착 방지
                run([PY, "_attach_intro.py", "--dir", str(dst_dir), "--lang", "id"], cwd=ROOT)

            story = json.loads((dst_dir / "story.json").read_text(encoding="utf-8"))

            if args.no_upload:
                print(f"[생성 완료 / 업로드 생략] {dst_dir.name}")
                continue

            video_id = upload_id(dst_dir, story, creds, ep["schedule"], ep["unit_id"])

            log[key] = {
                "video_id": video_id,
                "url": f"https://youtu.be/{video_id}",
                "schedule": ep["schedule"],
                "uploaded_at": datetime.now().isoformat(),
            }
            save_log(log)
            print(f"\n[완료] {i}/{total} -> https://youtu.be/{video_id}")

        except Exception as e:
            print(f"\n[ERROR] {i}/{total} {src_name} 실패: {e}")
            log[key] = {"error": str(e), "failed_at": datetime.now().isoformat()}
            save_log(log)
            print("다음 에피소드로 계속 진행합니다 (재실행 시 실패분부터 재시도)")
            continue

    print("\n\n=== 전체 배치 종료 ===")
    for k, v in log.items():
        print(k, "->", v)


if __name__ == "__main__":
    main()
