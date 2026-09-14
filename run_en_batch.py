#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_en_batch.py
1학년 2학기 '상상' 단원 10편 -> 영어 번역 + TTS(Typecast eng) + 영상 조립 + HAMZZI(en) 채널 업로드

인니 배치(run_id_sangsang_batch.py)와 동일 구조. 차이점:
- TTS: Typecast ssfm-v30 english (한국어판과 '같은 캐릭터 보이스'를 language=eng로 호출)
  -> 03_generate_tts.py 가 story.json meta.language=en 을 보고 자동 전환
- 이름: translate_multilang 이 번역 전에 라틴 표기로 치환 (삐요->Piyo, 토토->Toto)
  ※ 채널 소개문("Piyo the chick and Toto the turtle")과 반드시 일치시킬 것
- Drive: HAMZZI 채널 토큰은 youtube 스코프만 -> 활동지/PPT 링크 없음(설명란에서 생략)

사용법:
  python run_en_batch.py                    # 상상 단원 전체(미업로드분만)
  python run_en_batch.py --unit haru        # 하루 단원
  python run_en_batch.py --limit 1      # 앞에서 N편만
  python run_en_batch.py --no-upload    # 생성만 하고 업로드는 건너뜀
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from translate_multilang import translate_story
import publish_youtube as py

PY = sys.executable

# 1편(알탐험)은 채널 첫 영상 -> 즉시 공개. 이후 주 2편(화·목 09:00 KST) 예약.
EPISODES_SANGSANG = [
    dict(src="통합교과_알에서동물이태어난다면2021_1학년_함께골라요_삐요와토토의신비한알탐험",
         unit_en="If Animals Hatched from Eggs (pp. 20-21)", schedule=None),
    dict(src="통합교과_상자에물건이들어있다면2223_1학년_함께골라요_삐요와토토의신비한상자",
         unit_en="If Something Were Inside the Box (pp. 22-23)", schedule="2026-09-16T09:00:00+09:00"),
    dict(src="통합교과_함께간다면2425p_1학년_함께골라요_어디만큼갔니삐요와토토의초록마을여행",
         unit_en="If We Went Together (pp. 24-25)", schedule="2026-09-18T09:00:00+09:00"),
    dict(src="통합교과_여러가지모양이살아난다면262_1학년_함께골라요_삐요와토토의모양나라대모험",
         unit_en="If Shapes Came Alive (pp. 26-27)", schedule="2026-09-23T09:00:00+09:00"),
    dict(src="통합교과_장난감이춤을춘다면2829p_1학년_함께골라요_띠깍과푸미의달빛무도회",
         unit_en="If Toys Started Dancing (pp. 28-29)", schedule="2026-09-25T09:00:00+09:00"),
    dict(src="통합교과_여기저기에서본다면3031p_1학년_함께골라요_삐요와토토의알록달록수수께끼",
         unit_en="If We Looked from Everywhere (pp. 30-31)", schedule="2026-09-30T09:00:00+09:00"),
    dict(src="통합교과_새로운동물이나타난다면3233_1학년_함께골라요_삐요와토토의상상동물만들기",
         unit_en="If a New Animal Appeared (pp. 32-33)", schedule="2026-10-02T09:00:00+09:00"),
    dict(src="통합교과_비눗방울이그림이된다면3435_1학년_함께골라요_퐁퐁비눗방울그림나라",
         unit_en="If Bubbles Turned into Pictures (pp. 34-35)", schedule="2026-10-07T09:00:00+09:00"),
    dict(src="통합교과_물건이악기가된다면3637p_1학년_함께골라요_통통이와두리의둥둥팅팅음악회",
         unit_en="If Everyday Things Became Instruments (pp. 36-37)", schedule="2026-10-09T09:00:00+09:00"),
    dict(src="통합교과_세상을바꿀초능력이생긴다면38_1학년_함께골라요_삐요와토토별똥별초능력",
         unit_en="If You Had a Superpower (pp. 38-39)", schedule="2026-10-14T09:00:00+09:00"),
]

# 하루 단원 — 상상 단원 예약이 끝나는 2026-10-14 다음부터 이어서 (화·목 09:00 KST)
EPISODES_HARU = [
    dict(src="통합교과_하늘의하루2223p_1학년_함께골라요_삐요와토토하늘의색을세어봐요",
         unit_en="A Day with the Sky (pp. 22-23)", schedule="2026-10-16T09:00:00+09:00"),
    dict(src="통합교과_달팽이의하루2425p_1학년_함께골라요_느리의아주특별한하루",
         unit_en="A Snail's Day (pp. 24-25)", schedule="2026-10-21T09:00:00+09:00"),
    dict(src="통합교과_건강한하루2627p_1학년_함께골라요_팔팔이와뒹굴의콩콩건강한하루",
         unit_en="A Healthy Day (pp. 26-27)", schedule="2026-10-23T09:00:00+09:00"),
    dict(src="통합교과_마음의하루2829p_1학년_함께골라요_무지의색깔하루",
         unit_en="A Day of Feelings (pp. 28-29)", schedule="2026-10-28T09:00:00+09:00"),
    dict(src="통합교과_하루저금통3031p_1학년_함께골라요_삐요와토토의반짝반짝하루저금통",
         unit_en="The Everyday Savings Jar (pp. 30-31)", schedule="2026-10-30T09:00:00+09:00"),
    dict(src="통합교과_하루의시작3233p_1학년_함께골라요_부엉이와꼬꼬의아침일과",
         unit_en="The Start of the Day (pp. 32-33)", schedule="2026-11-04T09:00:00+09:00"),
    dict(src="통합교과_모두의하루3435p_1학년_함께골라요_삐요와토토마을의하루를찾아서",
         unit_en="Everyone's Day (pp. 34-35)", schedule="2026-11-06T09:00:00+09:00"),
    dict(src="통합교과_하루세번3637p_1학년_함께골라요_까까와냠냠의골고루하루",
         unit_en="Three Times a Day (pp. 36-37)", schedule="2026-11-11T09:00:00+09:00"),
    dict(src="통합교과_해야해야나오너라3839p_1학년_함께골라요_삐요와토토의그림자밟기",
         unit_en="Come Out, Sunshine! (pp. 38-39)", schedule="2026-11-13T09:00:00+09:00"),
    dict(src="통합교과_하루의리듬4041p_1학년_함께골라요_통통이와짤랑이의하루리듬",
         unit_en="The Rhythm of the Day (pp. 40-41)", schedule="2026-11-18T09:00:00+09:00"),
]

UNITS = {
    "sangsang": dict(episodes=EPISODES_SANGSANG, series="Imagination", log="_en_batch_log.json"),
    "haru":     dict(episodes=EPISODES_HARU,     series="Our Day",     log="_en_haru_batch_log.json"),
}

# build_en_description 이 참조하는 현재 단원명 (main 에서 --unit 으로 설정)
SERIES_EN = "Imagination"

LOG_PATH = ROOT / "_en_batch_log.json"


def load_log():
    if LOG_PATH.exists():
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    return {}


def save_log(log):
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def run(cmd, cwd):
    print("\n$ " + " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError("실패(%d): %s" % (r.returncode, " ".join(str(c) for c in cmd)))


def build_en_title(story, unit_en):
    """100자 제한. 그냥 자르면 'If Animals Hatched from Eggs (pp.' 처럼 흉하게 끊기므로
    긴 순서대로 요소를 통째로 덜어낸다: 학년 표기 -> 쪽수 -> 단원명."""
    meta = story["meta"]
    grade = meta.get("grade", 1)
    story_title = (meta.get("story_title") or "").strip()
    hook = story_title if (story_title and story_title[-1] in "!?.~") else story_title + "!"

    unit_nopage = unit_en.split(" (pp.")[0].strip()
    for candidate in (
        f"{hook} | Read-Aloud Story for Grade {grade} - {unit_en}",
        f"{hook} | Read-Aloud Story - {unit_en}",
        f"{hook} | Read-Aloud Story - {unit_nopage}",
        f"{hook} | Read-Aloud Story for Grade {grade}",
        hook,
    ):
        if len(candidate) <= 100:
            return candidate
    return hook[:100]


def build_en_description(story, unit_en):
    meta = story["meta"]
    grade = meta.get("grade", 1)
    story_title = meta.get("story_title", "")
    logline = (meta.get("logline") or "").strip() or f"A story about {story_title}."
    chars = meta.get("characters", {})
    names = [chars[k]["name"] for k in ("main_1", "main_2") if chars.get(k, {}).get("name")]
    tag_title = "".join(ch for ch in story_title if ch.isalnum())
    lines = [
        f"🌟 {story_title}",
        "",
        logline,
        "",
        "A calm read-aloud story for young learners. No fast cuts, no loud effects, just a gentle "
        "voice and soft watercolor pictures, followed by a short quiz to talk about together.",
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"📚 Topic: {SERIES_EN} - {unit_en}",
        f"🎯 For: Grade {grade} (ages 6-8), classroom read-alouds and bedtime",
        f"👥 Characters: {', '.join(names)}",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "Made by a Korean elementary school teacher.",
        'English retelling of "Hamzzi\'s Storytime Journey."',
        "Free to use in class. Questions: kdhdhdbdbr@gmail.com",
        "",
        f"#ReadAloud #BedtimeStory #KidsStory #PictureBook #{tag_title} #StoriesForKids #Grade{grade}",
    ]
    return "\n".join(lines)


def build_en_tags(story):
    meta = story["meta"]
    grade = meta.get("grade", 1)
    story_title = meta.get("story_title", "")
    return ["read aloud for kids", "bedtime story", "kids story english", "classroom story",
            "picture book", "elementary story", story_title, f"grade {grade}",
            "storytime", "english story for children"][:15]


def upload_en(dst_dir: Path, story: dict, creds, schedule, unit_en: str):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    video_path = dst_dir / "video.mp4"
    thumb_path = dst_dir / "thumbnail_c.png"
    if not thumb_path.exists():
        thumb_path = dst_dir / "thumbnail_a.png"
    if not video_path.exists():
        raise RuntimeError(f"video.mp4 없음: {video_path}")

    title = build_en_title(story, unit_en)
    privacy = "private" if schedule else "public"
    status_body = {"privacyStatus": privacy, "selfDeclaredMadeForKids": True}
    if schedule:
        status_body["publishAt"] = schedule

    body = {
        "snippet": {
            "title": title,
            "description": build_en_description(story, unit_en),
            "tags": build_en_tags(story),
            "categoryId": "27",
            "defaultLanguage": "en",
        },
        "status": status_body,
    }

    youtube = build("youtube", "v3", credentials=creds)
    size_mb = video_path.stat().st_size // 1024 // 1024
    print(f"\n[YouTube-EN] 업로드: {video_path.name} ({size_mb} MB) / privacy={privacy} schedule={schedule}")
    print(f"  제목: {title}")
    media = MediaFileUpload(str(video_path), chunksize=4 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = py.resumable_upload(request, "영어 본편 업로드")
    video_id = response["id"]
    print(f"  [OK] https://youtu.be/{video_id}")

    # 썸네일 실패는 업로드 자체를 실패로 만들지 않는다 (영상은 이미 올라갔으므로 재시도하면 중복 업로드됨).
    # HAMZZI 채널은 전화 인증 전까지 맞춤 썸네일이 막혀 있음 → youtube.com/verify 후 _push_thumb_en.py 로 사후 적용.
    if thumb_path.exists():
        try:
            youtube.thumbnails().set(videoId=video_id,
                                     media_body=MediaFileUpload(str(thumb_path))).execute()
            print(f"  [OK] 썸네일 적용: {thumb_path.name}")
        except Exception as e:
            print(f"  [WARN] 썸네일 적용 실패 (영상 업로드는 정상): {e}")
            print("        → 채널 전화 인증(youtube.com/verify) 후 "
                  "python _push_thumb_en.py 로 일괄 적용하세요.")

    return video_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N편만 처리")
    ap.add_argument("--no-upload", action="store_true", help="생성만 하고 업로드 건너뜀")
    ap.add_argument("--unit", choices=list(UNITS), default="sangsang",
                    help="처리할 단원 (기본 sangsang)")
    args = ap.parse_args()

    global SERIES_EN, LOG_PATH
    cfg = UNITS[args.unit]
    SERIES_EN = cfg["series"]          # 설명란의 'Topic:' 라벨
    LOG_PATH = ROOT / cfg["log"]       # 단원별 업로드 기록 (중복 업로드 방지)
    print(f"[INFO] 단원: {args.unit} ({SERIES_EN}) / 기록: {LOG_PATH.name}")

    log = load_log()
    creds = None
    if not args.no_upload:
        creds = py.retry(lambda: py.get_credentials("en"), "인증")
        py.retry(lambda: py.verify_channel("en", creds), "채널확인")  # 2026-09-12 사고 재발 방지 — 필수, 우회 불가

    out_root = ROOT / "output"
    episodes = cfg["episodes"][:args.limit] if args.limit else cfg["episodes"]
    total = len(episodes)

    for i, ep in enumerate(episodes, 1):
        src_name = ep["src"]
        if log.get(src_name, {}).get("video_id"):
            print(f"\n[SKIP] {i}/{total} 이미 업로드됨: {log[src_name]['video_id']}")
            continue

        src_dir = out_root / src_name
        dst_dir = out_root / f"{src_name}_en"
        print("\n" + "=" * 70 + f"\n[EN {i}/{total}] {src_name}\n" + "=" * 70)

        try:
            if not (dst_dir / "story.json").exists():
                translate_story(src_dir, "en")

            # 썸네일 C 배경(언어 무관 동일 이미지) 복사
            src_c_bg = src_dir / "thumbnail_c_bg.png"
            if src_c_bg.exists() and not (dst_dir / "thumbnail_c_bg.png").exists():
                shutil.copy2(src_c_bg, dst_dir / "thumbnail_c_bg.png")

            if not (dst_dir / "video.mp4").exists():
                run(["bash", "_run_en_pipeline.sh", f"output/{src_name}_en"], cwd=ROOT)

            story = json.loads((dst_dir / "story.json").read_text(encoding="utf-8"))

            if args.no_upload:
                print(f"[생성 완료 / 업로드 생략] {dst_dir.name}")
                continue

            video_id = upload_en(dst_dir, story, creds, ep["schedule"], ep["unit_en"])
            log[src_name] = {
                "video_id": video_id,
                "url": f"https://youtu.be/{video_id}",
                "schedule": ep["schedule"],
                "uploaded_at": datetime.now().isoformat(),
            }
            save_log(log)
            print(f"\n[완료] EN {i}/{total} -> https://youtu.be/{video_id}")

        except Exception as e:
            print(f"\n[ERROR] EN {i}/{total} {src_name} 실패: {e}")
            log[src_name] = {"error": str(e), "failed_at": datetime.now().isoformat()}
            save_log(log)
            print("다음 에피소드로 계속 진행합니다 (재실행 시 실패분부터 재시도)")
            continue

    print("\n\n=== 영어 배치 종료 ===")
    for k, v in log.items():
        print(k, "->", v)


if __name__ == "__main__":
    main()
