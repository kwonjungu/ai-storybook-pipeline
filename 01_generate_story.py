"""
01_generate_story.py
Claude Code CLI(claude -p, 현재 세션 모델)로 동화 스토리 JSON을 생성합니다.

한국어 모드 (기본):
  python 01_generate_story.py --ep N
  python 01_generate_story.py --dir output/bsl03

인도네시아어 모드:
  python 01_generate_story.py --dir output/id01 --lang id
  python 01_generate_story.py --dir output/id01 --lang id --theme "petualangan kelinci di hutan"
"""

import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import subprocess
from dotenv import load_dotenv

# Claude Code 중첩 세션 방지를 위해 CLAUDECODE 환경변수 제거
_CLAUDE_ENV = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

# ── .env 로드 ──────────────────────────────────────────────
load_dotenv()

# ── Gemini TTS 보이스 (인도네시아어) ──────────────────────
GEMINI_TTS_VOICES = {
    "narrator":   {"voice_name": "Kore",   "speed": 0.95},
    "child_girl": {"voice_name": "Puck",   "speed": 1.0},
    "child_boy":  {"voice_name": "Fenrir", "speed": 1.0},
    "teacher":    {"voice_name": "Charon", "speed": 0.9},
    "default":    {"voice_name": "Aoede",  "speed": 1.0},
}

# ── 한국어 보이스 캐스팅 안내 ─────────────────────────────
# Supertone API 종료(2026-08-31)로 사전 보이스 선택 제거.
# 한국어 보이스는 03_generate_tts.py가 Typecast 추천 API로
# 캐릭터 맥락(성격·종족·역할)에 맞게 자동 캐스팅합니다.

# ── BSL 에피소드 목록 (바슬즐 / 통합교과 시리즈) ──────────
# 키: 출력 폴더 이름 (예: "bsl03" → output/bsl03)
BSL_EPISODES = {
    "bsl27": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "하루",
        "unit": "", "unit_title": "하루의 리듬 (40-41p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "새로운 주인공의 특별편. 리듬을 좋아하는 아기 너구리 '통통'과 방울 소리를 좋아하는 아기 여우 "
            "'짤랑'이 주인공. 통통이는 노래 '나의 하루'를 부르며 아침부터 저녁까지 자신의 하루를 "
            "리듬악기 소리로 표현해 보고 싶어 한다. 아침엔 활기차게 일어나는 소리를 탬버린으로(통통통), "
            "낮엔 신나게 뛰노는 소리를 마라카스로(차르르), 오후 간식 시간엔 맑은 소리를 트라이앵글로(딩동), "
            "저녁엔 차분히 하루를 정리하는 소리를 캐스터네츠로(딱딱) 표현하며 악기를 하나씩 배워 나간다. "
            "짤랑이는 방울 소리를 좋아해서 처음엔 아무 때나 흔들어 리듬이 엉망이 되지만, 통통이와 함께 "
            "'나의 하루' 노랫말에 맞춰 박자 맞추는 연습을 하며 저녁 생활(씻기, 정리하기, 내일 준비하기, "
            "잠자리 들기)에 어울리는 느리고 차분한 리듬을 찾아간다. "
            "친구와 함께 악기 소리를 주고받으며 '내 하루도 리듬이 있구나, 저녁엔 느리고 차분한 리듬이 "
            "어울리는구나'를 깨닫는다. 마지막엔 이 닦기·잠옷 갈아입기·인사하기 같은 바른 저녁 습관을 "
            "리듬에 맞춰 신나게 실천하고, 편안한 마음으로 하루를 마무리한다. "
            "'하루에는 저마다 다른 리듬이 있고, 그 리듬에 맞춰 바르게 생활하면 하루가 더 즐거워진다'는 "
            "메시지. 마지막에 '너의 저녁 시간은 어떤 리듬일까? 어떤 악기 소리와 어울릴까?'라고 묻는 "
            "열린 결말. 1학년 눈높이, 리듬 의성어·의태어(통통, 딩동, 딱딱, 차르르)를 풍부하게."
        ),
        "world_setting": "daily_rhythm_instruments",
        "world_desc": (
            "하루의 시간마다 다른 리듬이 흐르는 집과 마당 — 아침 햇살 아래 탬버린, 한낮의 마라카스, "
            "오후의 트라이앵글, 저녁 별빛 아래 캐스터네츠와 아늑한 잠자리"
        ),
        "character_type": (
            "NEW main characters for this special episode (NOT the chick and turtle): "
            "main_1 Tongtong — a cheerful baby raccoon with a round fluffy ringed tail, big round eyes, "
            "soft grey-brown fur with a dark mask marking around the eyes, holding or wearing a small "
            "tambourine, energetic playful expression; "
            "main_2 Jjallang — a gentle baby fox with fluffy orange-and-white fur, a fluffy tail tip, "
            "bright eyes, wearing a tiny jingle bell charm around the neck, calm sweet expression. "
            "CRITICAL: all characters must have cute ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "warm scenes that shift tone with time of day (bright morning to soft glowing evening), "
            "rounded adorable animal character designs, gentle musical motifs (tambourine, triangle, "
            "castanets, maracas), clean warm colors, storybook composition, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl26": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "하루",
        "unit": "", "unit_title": "해야 해야 나오너라 (38-39p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "삐요와 토토 시리즈. 어느 화창한 오후, 마당에서 놀던 삐요와 토토가 처음으로 자기 그림자를 "
            "발견하고 깜짝 놀란다. 그림자가 자기를 따라 이리저리 움직이는 게 신기해서 궁금해하다가, "
            "해님이 구름 뒤에 숨어 그림자가 흐릿해지자 '해야 해야 나오너라 뒷동산에 나오너라'라는 노래를 "
            "신나게 부르며 해님을 불러낸다. 해님이 다시 나오자 그림자가 다시 선명해지고, 해가 있어야만 "
            "그림자가 생긴다는 것과 해를 등지는 쪽으로 그림자가 길게 생긴다는 것을 자연스럽게 깨닫는다. "
            "신이 난 두 친구는 그림자밟기 놀이를 한다: 서로 도망다니며 상대의 그림자를 밟으면 술래가 "
            "바뀌는 놀이. 처음엔 무작정 쫓아가다 넘어질 뻔하지만, 몸을 낮추거나 재빠르게 방향을 바꾸는 "
            "요령을 터득하며 점점 더 신나게 논다. 실컷 뛰어놀아 몸이 노곤해지자 둘은 나란히 앉아 몸을 "
            "편안하게 하는 마무리 체조(기지개 켜기, 팔다리 털기, 깊게 숨쉬기)를 함께 하며 오후를 차분히 "
            "마무리한다. 체조를 마친 뒤 서로 오늘 함께 놀아줘서 고맙다고, 그림자밟기를 잘한다고 칭찬을 "
            "주고받는다. '해가 있어야 그림자가 생기고, 친구와 함께 놀면 오후가 더 즐거워진다'는 메시지 "
            "+ 몸과 마음을 편안히 마무리하는 습관. 마지막에 '너는 오늘 오후에 무엇을 하며 놀았어? 네 "
            "그림자는 어떤 모양이었어?'라고 묻는 열린 결말. 1학년 눈높이, 놀이 의성어·의태어(살금살금, "
            "폴짝, 후다닥)를 풍부하게."
        ),
        "world_setting": "afternoon_shadow_play",
        "world_desc": (
            "햇살 가득한 오후의 마당과 뒷동산 — 길게 늘어지는 그림자, 구름 사이로 비치는 햇빛, "
            "잔디밭과 나무 그늘"
        ),
        "character_type": (
            "the SAME two main characters as previous episodes, identical designs: "
            "main_1 Ppiyo — a small fluffy round yellow chick with soft downy feathers, tiny orange "
            "beak and orange feet, big sparkling black eyes, wearing a little red mini backpack, "
            "short flappy wings, bright curious energetic expression; "
            "main_2 Toto — a small green baby turtle with a rounded shell patterned with soft teal "
            "and moss green hexagons, gentle calm eyes, wearing a small sky blue neckerchief, "
            "friendly relaxed smile, sturdy tiny legs. "
            "Clear long soft-edged shadows cast on the ground beneath the characters. "
            "CRITICAL: all characters must have ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "warm golden-hour afternoon sunlight with long soft shadows, rounded adorable animal "
            "character designs, clean warm colors, storybook composition, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl25": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "하루",
        "unit": "", "unit_title": "하루 세 번 (36-37p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "새로운 주인공의 특별편. 주인공은 좋아하는 것만 먹으려는 편식쟁이 아기 여우 '까까'와 "
            "뭐든 골고루 잘 먹는 튼튼한 아기 하마 '냠냠'. "
            "까까는 달콤한 간식만 먹고 채소는 쏙 빼놓다가, 하루 세 끼(아침·점심·저녁)를 골고루 먹는 "
            "냠냠을 보며 건강한 식사를 배운다. "
            "아침엔 밥과 국·달걀(든든하게), 점심엔 알록달록 채소와 고기(골고루), 저녁엔 따뜻한 밥과 생선(가볍게). "
            "각 끼니마다 '이 음식은 우리 몸에서 무슨 일을 할까?'를 자연스럽게 알려 준다 "
            "(채소는 몸을 튼튼하게, 밥은 힘을 주고, 물은 상쾌하게). "
            "간식만 먹던 까까가 배가 아파 시무룩했다가, 세 끼를 골고루 먹으니 힘이 불끈 나는 걸 느낀다. "
            "'하루 세 끼를 골고루 먹으면 튼튼하고 신나는 하루가 된다'는 식습관 교육 메시지 + 약속. "
            "마지막에 '너는 오늘 무엇을 골고루 먹었어? 내일 식판에 어떤 음식을 담고 싶어?'라고 묻는 열린 결말. "
            "1학년 눈높이, 먹는 의성어·의태어(냠냠, 아삭아삭, 후루룩, 꿀꺽)를 풍부하게."
        ),
        "world_setting": "three_meals_day",
        "world_desc": (
            "따뜻한 식사의 하루 — 아침 식탁의 밥과 국, 알록달록 점심 식판, 저녁의 생선과 밥, "
            "부엌과 식탁, 건강한 음식들이 가득한 정겨운 풍경"
        ),
        "character_type": (
            "NEW main characters for this special episode (NOT the chick and turtle): "
            "main_1 Kkakka — a picky little fox cub with fluffy orange fur, a white belly, big cute eyes, "
            "often pouting, gradually learning to enjoy healthy food; "
            "main_2 Nyamnyam — a sturdy cheerful baby hippo with smooth grey skin, a big friendly mouth, "
            "bright happy eyes, loves eating everything, healthy and strong. "
            "CRITICAL: all characters must have cute ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "warm appetizing mealtime scenes with colorful healthy food, rounded adorable animal character "
            "designs, clean fresh colors, storybook composition, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl23": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "하루",
        "unit": "", "unit_title": "하루의 시작 (32-33p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "새로운 주인공의 특별편. 주인공은 아침잠이 아주 많은 꼬마 올빼미 '부엉'과 "
            "일찍 일어나는 부지런한 아기 닭 '꼬꼬'. (밤에 활동하는 올빼미가 아침 일과를 배우는 반전 설정) "
            "밤새 놀던 부엉이 아침이 되어도 못 일어나자, 꼬꼬가 '멋진 하루는 아침 일과에서 시작해!'라며 "
            "자기만의 아침 일과를 하나씩 보여 준다: 눈뜨고 기지개(쭈욱), 세수하고 양치(뽀득), "
            "옷 입기(척척), 아침밥 냠냠, 가방 챙기기(착!). "
            "부엉도 꼬꼬를 따라 아침 일과를 만들어 보며 '아침을 잘 시작하니 하루가 상쾌해!'라고 느낀다. "
            "둘의 아침 일과가 조금씩 다르다는 것도 자연스럽게 보여 준다(순서·방법이 달라도 괜찮아). "
            "'하루를 기분 좋게 시작하려면 나만의 아침 일과가 필요하다'는 생활 습관 메시지. "
            "마지막에 '너의 아침 일과는 어때? 하루를 어떻게 시작하고 싶어?'라고 묻는 열린 결말. "
            "1학년 눈높이, 아침 의성어·의태어(쭈욱, 뽀득, 척척, 하암)를 풍부하게."
        ),
        "world_setting": "morning_routine_home",
        "world_desc": (
            "아침 햇살이 드는 아늑한 집 — 창으로 스미는 금빛 햇살, 이불과 침대, 세면대, "
            "옷걸이, 아침 식탁, 현관의 가방, 상쾌한 아침 공기"
        ),
        "character_type": (
            "NEW main characters for this special episode (NOT the chick and turtle): "
            "main_1 Bueong — a sleepy fluffy baby owl with big round drowsy eyes, soft grey-brown feathers, "
            "tiny tufts on the head, often yawning, cozy and adorable; "
            "main_2 Kkokko — a bright energetic baby chick-rooster with fluffy yellow feathers, a tiny red comb, "
            "wide-awake cheerful eyes, always tidy and ready. "
            "CRITICAL: all characters must have cute ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "warm golden morning light home scenes, rounded adorable animal character designs, "
            "clean fresh colors, storybook composition, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl24": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "하루",
        "unit": "", "unit_title": "모두의 하루 (34-35p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "삐요와 토토 시리즈. 두 친구가 동물 마을을 돌아다니며 '저마다 다른 하루'를 보내는 이웃들을 만난다. "
            "이른 새벽부터 빵을 굽는 곰 아저씨 제빵사(반죽 조물조물), 아이들을 가르치는 여우 선생님(또박또박), "
            "우편물을 배달하는 토끼 우체부(콩콩), 아픈 동물을 돌보는 판다 의사 선생님(토닥토닥), "
            "밤에 마을을 지키는 부엉이 야경꾼(부엉부엉). "
            "각자 하는 일과 시간이 다르지만, 모두의 하루가 모여 마을이 따뜻하게 돌아간다는 것을 보여 준다. "
            "'낮에 일하는 사람도, 밤에 일하는 사람도 다 있어서 우리 마을이 편안하구나!' "
            "'사람마다(동물마다) 하루가 다르고, 저마다의 하루가 모두 소중하다'는 공동체 존중 메시지. "
            "가족의 하루도 살짝 담는다(엄마·아빠·할머니의 서로 다른 하루). "
            "마지막에 '네 주변 사람들은 어떤 하루를 보낼까? 누구의 하루가 궁금해?'라고 묻는 열린 결말. "
            "1학년 눈높이, 다양한 직업 의성어·의태어(조물조물, 콩콩, 토닥토닥)를 풍부하게."
        ),
        "world_setting": "everyones_day_village",
        "world_desc": (
            "다 함께 살아가는 동물 마을 — 새벽 빵집, 학교, 우체국, 병원, 밤을 지키는 망루, "
            "낮과 밤이 어우러진 정겨운 마을 풍경, 여러 직업의 동물들"
        ),
        "character_type": (
            "the SAME two main characters as previous episodes, identical designs: "
            "main_1 Ppiyo — a small fluffy round yellow chick with soft downy feathers, tiny orange "
            "beak and orange feet, big sparkling black eyes, wearing a little red mini backpack, "
            "short flappy wings, bright curious energetic expression; "
            "main_2 Toto — a small green baby turtle with a rounded shell patterned with soft teal "
            "and moss green hexagons, gentle calm eyes, wearing a small sky blue neckerchief, "
            "friendly relaxed smile, sturdy tiny legs. "
            "Supporting: various working animal neighbors (bear baker, fox teacher, rabbit postman, "
            "panda doctor, owl night-watch). "
            "CRITICAL: all characters must have ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "warm community village scenes showing different jobs day and night, rounded adorable animal "
            "character designs, clean warm colors, storybook composition, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl22": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "하루",
        "unit": "", "unit_title": "하루 저금통 (30-31p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "삐요와 토토 시리즈. 두 친구가 반짝이는 '하루 저금통'을 선물받는다. 이 저금통은 돈이 아니라 "
            "'오늘 실천한 좋은 습관'을 넣으면 반짝이는 별 동전이 쌓이는 마법 저금통! "
            "두 친구는 하루 동안 좋은 습관을 하나씩 실천하며 별 동전을 모은다: "
            "① 아침에 스스로 일어나기(딩동!), ② 장난감 정리하기(차곡차곡), ③ 친구에게 고마워 인사하기(방긋), "
            "④ 골고루 먹기(냠냠), ⑤ 잠자기 전 이 닦기(뽀득뽀득). "
            "습관을 실천할 때마다 저금통에서 반짝! 별 동전이 떨어지는 소리가 난다. "
            "처음엔 귀찮아하던 삐요도 저금통이 점점 반짝이자 뿌듯해하며 신나게 실천한다. "
            "밤이 되어 저금통을 열어 보니 별 동전이 가득! '작은 습관도 매일 모으면 반짝이는 보물이 되는구나!' "
            "'좋은 습관을 꾸준히 실천하면 나도 반짝반짝 자란다'는 습관 형성 메시지 + 실천 다짐(꼭꼭 약속해). "
            "마지막에 '너는 오늘 어떤 좋은 습관을 저금했어? 내일은 어떤 습관을 모아 볼까?'라고 묻는 열린 결말. "
            "1학년 눈높이, 실천 의성어·의태어(차곡차곡, 반짝, 뽀득뽀득)를 풍부하게."
        ),
        "world_setting": "habit_piggybank_day",
        "world_desc": (
            "따뜻한 하루의 집과 마을 — 반짝이는 별 동전이 쌓이는 마법 저금통, 정돈된 방, "
            "아침 햇살 드는 부엌, 별이 뜨는 밤 창가"
        ),
        "character_type": (
            "the SAME two main characters as previous episodes, identical designs: "
            "main_1 Ppiyo — a small fluffy round yellow chick with soft downy feathers, tiny orange "
            "beak and orange feet, big sparkling black eyes, wearing a little red mini backpack, "
            "short flappy wings, bright curious energetic expression; "
            "main_2 Toto — a small green baby turtle with a rounded shell patterned with soft teal "
            "and moss green hexagons, gentle calm eyes, wearing a small sky blue neckerchief, "
            "friendly relaxed smile, sturdy tiny legs. "
            "A magical piggybank that glows with collected star coins. "
            "CRITICAL: all characters must have ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "warm cozy home-and-habit scenes with sparkling star-coin effects, rounded adorable animal "
            "character designs, clean warm colors, storybook composition, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl17": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "하루",
        "unit": "", "unit_title": "하늘의 하루 (22-23p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "삐요와 토토 시리즈. 두 친구가 언덕에서 '하루 동안 하늘이 어떻게 변하는지' 지켜보는 하루 관찰 이야기. "
            "이른 아침(분홍빛 노을과 옅은 안개)→한낮(새파란 하늘, 뭉게구름, 눈부신 해)→저녁(주황빛 노을)→"
            "밤(짙은 남색 하늘, 반짝이는 별과 둥근 달)으로 하늘색이 시간에 따라 변하는 것을 관찰한다. "
            "각 시간마다 '지금 하늘은 무슨 색일까? 무엇이 보일까?'를 묻고 색을 이야기한다. "
            "낮 하늘은 밝고 포근한 인상파 그림(모네풍 밝은 붓터치)처럼, 밤 하늘은 별이 소용돌이치는 그림(고흐 '별이 빛나는 밤'풍)처럼 "
            "표현해 명화 감상 요소를 자연스럽게 녹인다. "
            "밤이 되자 '해와 달이 된 오누이' 이야기처럼 해와 달이 하늘에서 번갈아 뜨고 진다는 것을 깨닫는다. "
            "'하늘은 하루 종일 색을 바꾸며 그림을 그린다'는 감성적 메시지. "
            "마지막에 '너는 오늘 하늘에서 어떤 색을 보았어? 낮과 밤 중 어떤 하늘이 더 좋아?'라고 시청자에게 묻는 열린 결말. "
            "1학년 눈높이, 색과 빛을 표현하는 의성어·의태어(반짝반짝, 뭉게뭉게, 붉으락)를 풍부하게."
        ),
        "world_setting": "sky_all_day",
        "world_desc": (
            "하루 동안 색이 변하는 하늘 아래 언덕 — 분홍빛 새벽하늘, 새파란 낮 하늘과 하얀 뭉게구름, "
            "주황빛 저녁노을, 별이 소용돌이치는 짙은 남색 밤하늘과 둥근 달"
        ),
        "character_type": (
            "the SAME two main characters as previous episodes, identical designs: "
            "main_1 Ppiyo — a small fluffy round yellow chick with soft downy feathers, tiny orange "
            "beak and orange feet, big sparkling black eyes, wearing a little red mini backpack, "
            "short flappy wings, bright curious energetic expression; "
            "main_2 Toto — a small green baby turtle with a rounded shell patterned with soft teal "
            "and moss green hexagons, gentle calm eyes, wearing a small sky blue neckerchief, "
            "friendly relaxed smile, sturdy tiny legs. "
            "CRITICAL: all characters must have ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "expressive painterly skies inspired by impressionism (Monet daytime, Van Gogh Starry Night at "
            "night), rounded adorable animal character designs, clean luminous colors, "
            "storybook composition, inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl18": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "하루",
        "unit": "", "unit_title": "달팽이의 하루 (24-25p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "새로운 주인공의 특별편. 주인공은 세상에서 제일 느긋한 꼬마 달팽이 '느리'와 "
            "부지런하고 재빠른 개미 친구 '바지런'. "
            "느리의 아주 특별한 하루를 따라간다: 아침 이슬 마시기, 촉촉한 나뭇잎 위를 스르륵 기어가기, "
            "빗방울 피해 버섯 아래 쉬기, 무지개 보기, 그리고 밤에 별을 보며 잠들기. "
            "바지런은 '왜 이렇게 느려? 빨리빨리!' 하지만, 느리는 천천히 가기에 아침 이슬의 반짝임도, "
            "작은 꽃의 향기도, 무지개의 일곱 색도 다 볼 수 있다는 걸 보여 준다. "
            "결국 바지런도 느리 곁에서 천천히 걸으며 '느리게 가니까 안 보이던 게 보이네!'라고 깨닫는다. "
            "'느려도 괜찮아, 천천히 가면 더 많이 보고 느낄 수 있어'라는 따뜻한 메시지 (다름의 존중). "
            "'달팽이의 하루' 동요처럼 스르륵스르륵 리듬감 있는 반복 표현을 살린다. "
            "마지막에 '너의 하루는 어떤 속도였어? 천천히 걸으며 무엇을 보고 싶어?'라고 묻는 열린 결말. "
            "1학년 눈높이, 느긋한 의태어(스르륵, 살금살금, 느릿느릿)를 풍부하게."
        ),
        "world_setting": "snail_slow_day_garden",
        "world_desc": (
            "이슬 맺힌 아침 정원 — 촉촉한 초록 나뭇잎과 이슬방울, 알록달록 꽃, 빨간 버섯, "
            "비 온 뒤 무지개, 반딧불과 별이 뜨는 밤 풀숲"
        ),
        "character_type": (
            "NEW main characters for this special episode (NOT the chick and turtle): "
            "main_1 Neuri — a tiny adorable snail with a glossy swirled pastel-pink and cream shell, "
            "gentle sleepy eyes, a soft smile, tiny antennae with round tips, slow and serene; "
            "main_2 Bajireon — a small energetic red ant with big bright eyes, thin legs always in motion, "
            "a tiny leaf backpack, quick and cheerful. "
            "CRITICAL: all characters must have cute ANIMAL/insect faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "dewy close-up garden scenes with sparkling water droplets and macro nature detail, "
            "rounded adorable tiny creature designs, fresh luminous colors, gentle morning light, "
            "storybook composition, inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl19": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "상상",
        "unit": "", "unit_title": "세상을 바꿀 초능력이 생긴다면 (38-39p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "삐요와 토토 시리즈. 어느 날 하늘에서 반짝이는 별똥별 조각이 떨어지고, 그것을 만진 삐요와 토토에게 "
            "각자 특별한 '초능력'이 생긴다! 두 친구는 동물 마을의 작은 슈퍼히어로가 된다. "
            "삐요의 초능력은 '무엇이든 빠르게 도와주는 번개 날개'(슝!), 토토의 초능력은 '무엇이든 튼튼하게 지키는 바위 등껍질'(꽝!). "
            "두 친구는 초능력으로 마을의 곤란한 일들을 하나씩 돕는다: "
            "① 나무에 걸린 아기 새를 삐요가 번개처럼 날아 구하고, ② 무너지려는 다리를 토토가 등껍질로 받치고, "
            "③ 홍수로 떠내려가는 물건을 둘이 힘을 합쳐 구한다. "
            "하지만 초능력을 뽐내다 실수도 한다(너무 빨라서 부딪히고, 너무 세서 망가뜨림) — "
            "'힘은 남을 돕는 데 써야 멋진 거야'라는 것을 배운다. "
            "'세상을 바꾸는 건 대단한 초능력이 아니라, 남을 돕는 따뜻한 마음'이라는 메시지. "
            "마지막에 별똥별 힘이 사라져도 서로 돕는 마음은 그대로임을 깨닫고, "
            "'너에게 초능력이 생긴다면 무엇으로 세상을 도울래?'라고 시청자에게 묻는 열린 결말. "
            "1학년 눈높이, 신나는 액션 의성어(슝, 꽝, 번쩍)를 풍부하게."
        ),
        "world_setting": "animal_superhero_town",
        "world_desc": (
            "동물 마을 — 아기자기한 집들과 나무, 개울과 다리, 별똥별이 떨어지는 밤하늘, "
            "삐요·토토가 슈퍼히어로 망토(작은 별무늬)를 두른 활기찬 마을 풍경"
        ),
        "character_type": (
            "the SAME two main characters, identical designs, but each wearing a tiny star-patterned "
            "superhero cape: main_1 Ppiyo — a small fluffy round yellow chick with soft downy feathers, "
            "tiny orange beak and orange feet, big sparkling black eyes, wearing a little red mini backpack "
            "AND a small red star cape, short flappy wings glowing with lightning, bright energetic expression; "
            "main_2 Toto — a small green baby turtle with a rounded shell patterned with soft teal and moss "
            "green hexagons, gentle calm eyes, sky blue neckerchief AND a small blue star cape, sturdy legs. "
            "CRITICAL: all characters must have ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache with "
            "dynamic comic-style action motion lines and sparkle effects, rounded adorable animal superhero "
            "designs, vivid bright colors, energetic heroic composition, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl20": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "하루",
        "unit": "", "unit_title": "건강한 하루 (26-27p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "새로운 주인공의 특별편. 주인공은 활력이 넘치는 꼬마 강아지 '팔팔이'와 "
            "달콤한 간식과 낮잠을 좋아하는 느긋한 아기 판다 '뒹굴'. "
            "뒹굴이 자꾸 축 처지고 힘이 없자, 팔팔이가 '건강한 하루'를 함께 보내자고 제안한다. "
            "하루 동안 규칙적인 운동을 하나씩 실천한다: 아침 기지개와 줄넘기(콩콩), 점심 뒤 산책(뚜벅뚜벅), "
            "친구들과 공놀이(통통), 저녁에 스트레칭(쭉쭉). "
            "운동할 때마다 뒹굴의 몸이 점점 가벼워지고 기분이 좋아지는 것을 보여 준다 "
            "(운동하면 힘이 나고 기분이 좋아진다는 것). "
            "처음엔 힘들어하던 뒹굴도 '몸을 움직이니까 정말 상쾌해!'라며 활짝 웃는다. "
            "'매일 조금씩 몸을 움직이면 건강하고 즐거운 하루가 된다'는 메시지, 운동 습관 형성. "
            "마지막에 '너는 오늘 어떤 운동을 했어? 내일은 어떤 운동을 해볼까?'라고 묻는 열린 결말. "
            "1학년 눈높이, 활기찬 운동 의성어·의태어(콩콩, 쭉쭉, 통통, 헉헉)를 풍부하게."
        ),
        "world_setting": "healthy_day_playground",
        "world_desc": (
            "밝고 활기찬 하루 — 아침 햇살 드는 마당, 줄넘기와 공, 초록 공원 산책길, "
            "친구들과 뛰노는 놀이터, 저녁 스트레칭하는 아늑한 방"
        ),
        "character_type": (
            "NEW main characters for this special episode (NOT the chick and turtle): "
            "main_1 Palpali — a lively little puppy with fluffy cream-and-brown fur, floppy ears, "
            "a big bright grin, a red sporty headband, always bouncing with energy; "
            "main_2 Dwinggul — a chubby sleepy baby panda with soft black-and-white fur, droopy happy eyes, "
            "a round tummy, cozy and relaxed, gradually becoming more energetic. "
            "CRITICAL: all characters must have cute ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "energetic sunny sport-and-play scenes with motion lines, rounded adorable animal character "
            "designs, vivid fresh colors, storybook composition, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl21": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "하루",
        "unit": "", "unit_title": "마음의 하루 (28-29p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "새로운 주인공의 특별편. 주인공은 마음을 색으로 느끼는 신기한 아기 카멜레온 '무지'와 "
            "다정한 곰 친구 '포근'. 무지는 기분에 따라 몸 색깔이 변한다. "
            "무지의 하루 동안 여러 마음이 색으로 나타난다: 아침에 설렐 땐 노란색, "
            "친구와 다퉈 속상할 땐 파란색, 무서울 땐 보라색, 신나게 놀 땐 초록색, "
            "그리고 포근에게 위로받아 행복할 땐 따뜻한 분홍색. "
            "포근은 무지의 여러 색(마음)을 '어떤 색이든 다 소중한 네 마음이야'라며 있는 그대로 받아 준다. "
            "무지는 '슬픈 파란색도, 무서운 보라색도 내 마음이구나. 마음마다 색이 다 달라서 예뻐!'라고 깨닫는다. "
            "'하루 동안 여러 가지 마음이 드는 건 자연스러운 일, 모든 마음(색)은 다 소중하다'는 정서 교육 메시지. "
            "마지막에 '너의 오늘 마음은 무슨 색이야? 그 색으로 그림을 그려 볼까?'라고 묻는 열린 결말. "
            "1학년 눈높이, 색과 감정을 잇는 부드러운 표현을 풍부하게."
        ),
        "world_setting": "color_emotion_day",
        "world_desc": (
            "마음이 색으로 물드는 하루 — 파스텔 색이 번지는 하늘과 들판, 색색의 꽃과 나비, "
            "무지의 몸 색이 노랑·파랑·보라·초록·분홍으로 변하는 감성적인 풍경"
        ),
        "character_type": (
            "NEW main characters for this special episode (NOT the chick and turtle): "
            "main_1 Muji — a cute baby chameleon whose body color changes with emotion (yellow when excited, "
            "blue when sad, purple when scared, green when playful, pink when happy), big round expressive eyes, "
            "a curly tail, gentle friendly face; "
            "main_2 Pogeun — a soft warm-hearted honey-brown bear with a cozy scarf, gentle caring eyes, "
            "a comforting smile. "
            "CRITICAL: all characters must have cute ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache with "
            "expressive color-mood washes reflecting emotions, rounded adorable animal character designs, "
            "gentle luminous pastel colors, storybook composition, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl14": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "상상",
        "unit": "", "unit_title": "새로운 동물이 나타난다면 (32-33p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "삐요와 토토 시리즈. 비 오는 날 다락방에서 낡은 그림책을 발견한 두 친구. "
            "책 속에는 옛날 사람들이 상상한 동물들이 그려져 있다 — 사자 몸에 뿔이 달린 '해태', "
            "사자 몸에 사람 얼굴을 한 '스핑크스'. "
            "'옛날 사람들도 동물을 합쳐서 새로운 동물을 상상했구나!' 깨달은 두 친구는 "
            "'우리만의 새로운 동물 만들기' 놀이를 시작한다: "
            "① 코끼리의 긴 코 + 토끼의 큰 귀 + 오리의 물갈퀴 = '코토리' (물가에서 코로 물 뿌리며 노는 동물), "
            "② 기린의 긴 목 + 펭귄의 턱시도 몸 = '기링귄' (높은 나뭇잎도 먹고 얼음에서 미끄럼도 타는 동물), "
            "각 조합마다 '어떤 특징을 가져올까? 이 동물은 무엇을 잘할까? 어디에 살까?'를 묻고 상상한다. "
            "그날 밤 꿈속에서 두 친구가 만든 상상 동물들이 진짜로 나타나 함께 노는 판타지 장면. "
            "'동물의 특징을 합치면 세상에 없는 새 친구가 태어난다'는 상상의 즐거움이 핵심. "
            "마지막에 '너라면 어떤 동물과 어떤 동물을 합쳐 볼래? 새 동물의 이름도 지어 봐!'라고 "
            "시청자에게 묻는 열린 결말. 1학년 눈높이의 짧은 문장과 의성어·의태어를 풍부하게."
        ),
        "world_setting": "imaginary_animal_workshop",
        "world_desc": (
            "비 오는 날의 아늑한 다락방 — 낡은 그림책과 호롱불 같은 스탠드, 창밖의 빗방울, "
            "꿈 장면에서는 파스텔 구름 위 상상 동물들의 놀이터, 무지개 미끄럼틀과 솜사탕 나무"
        ),
        "character_type": (
            "the SAME two main characters as previous episodes, identical designs: "
            "main_1 Ppiyo — a small fluffy round yellow chick with soft downy feathers, tiny orange "
            "beak and orange feet, big sparkling black eyes, wearing a little red mini backpack, "
            "short flappy wings, bright curious energetic expression; "
            "main_2 Toto — a small green baby turtle with a rounded shell patterned with soft teal "
            "and moss green hexagons, gentle calm eyes, wearing a small sky blue neckerchief, "
            "friendly relaxed smile, sturdy tiny legs. "
            "Imaginary combined animals: Kotori — an elephant-trunked bunny-eared duck-footed cute creature; "
            "Giringuin — a long giraffe-necked penguin-bodied creature. All cute, rounded, friendly. "
            "CRITICAL: all characters must have ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "cozy rainy-day attic scenes transitioning to dreamy pastel cloud world, "
            "rounded adorable animal character designs, gentle lighting, "
            "storybook composition with clear focal points, "
            "NEUTRAL to COOL color temperature with no yellow-amber cast, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl15": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "상상",
        "unit": "", "unit_title": "비눗방울이 그림이 된다면 (34-35p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "새로운 주인공의 특별편 (삐요·토토와 다른 독립 이야기). "
            "주인공은 물놀이라면 자다가도 벌떡 일어나는 장난꾸러기 아기 수달 '보글이'와 "
            "그림 그리기를 좋아하는 꼼꼼한 꼬마 너구리 화가 '방울이'. "
            "맑은 오후 개울가 마당에서 비눗방울 놀이를 하던 두 친구. "
            "방울이가 물감을 섞은 비눗물을 만들자, 후! 불 때마다 알록달록 색깔 비눗방울이 떠오른다. "
            "그런데 신기한 일이! 비눗방울이 종이에 톡 하고 터질 때마다 동글동글 예쁜 그림 자국이 남는다. "
            "① 빨간 방울 하나가 터지면 동그라미 무늬, ② 방울 여러 개를 겹쳐 터뜨리면 꽃 모양, "
            "③ 파란 방울을 줄줄이 터뜨리면 뭉게구름과 파도가 된다. "
            "두 친구는 비눗방울 그림으로 '상상의 세계'를 만든다 — 비눗방울 꽃밭, 비눗방울 바다, "
            "비눗방울 무지개 성. 그림이 완성되자 마법처럼 그림 속 세계로 퐁! 하고 들어가 "
            "비눗방울 나라를 여행하는 판타지 장면 (동글동글 투명한 성, 방울 물고기, 무지개 다리). "
            "안전 요소도 살짝: '비눗물은 눈과 입에 닿지 않게 조심!' 한 마디. "
            "'물감과 비눗방울이 만나면 세상에 하나뿐인 그림이 된다'는 미술 표현의 즐거움이 핵심. "
            "마지막에 '너라면 비눗방울로 어떤 세계를 그리고 싶어?'라고 묻는 열린 결말. "
            "1학년 눈높이, 의성어·의태어(퐁퐁, 동동, 톡!, 후!) 풍부하게."
        ),
        "world_setting": "bubble_painting_world",
        "world_desc": (
            "햇살 좋은 마당과 하얀 도화지 — 알록달록 물감 비눗방울들, 방울이 터져 생긴 동그라미 무늬들, "
            "판타지 장면에서는 투명하고 영롱한 비눗방울 나라: 방울 성, 방울 물고기, 무지개 다리, "
            "빛이 통과하는 반투명 파스텔 색감"
        ),
        "character_type": (
            "NEW main characters for this special episode (NOT the chick and turtle): "
            "main_1 Bogeuli — a playful baby otter with sleek chocolate-brown fur, a cream belly, "
            "round sparkling eyes, tiny webbed paws, wearing a yellow rubber-duck float ring around his waist, "
            "mischievous joyful grin; "
            "main_2 Bangwuli — a careful little raccoon painter with soft grey fur, a black eye-mask pattern, "
            "a fluffy striped tail, wearing a paint-splattered mint apron and holding a small brush, "
            "thoughtful gentle smile. "
            "CRITICAL: all characters must have ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache "
            "with translucent iridescent bubble textures and playful paint-splash circle motifs, "
            "rounded adorable animal character designs, luminous clean colors, "
            "storybook composition with clear focal points, "
            "NEUTRAL to COOL color temperature with no yellow-amber cast, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl16": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "상상",
        "unit": "", "unit_title": "물건이 악기가 된다면 (36-37p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "새로운 주인공의 특별편 (삐요·토토와 다른 독립 이야기). "
            "주인공은 뭐든 두드리며 리듬을 타는 꼬마 다람쥐 '통통이'와 "
            "수줍지만 노래를 잘하는 아기 곰 '두리'. "
            "숲속 마을 음악회가 열리는 날, 그런데 악기 창고가 텅 비어 있다! "
            "악기가 없어 모두 속상해할 때, 통통이가 실수로 냄비를 두드리자 '둥둥!' 멋진 소리가 난다. "
            "'물건도 악기가 될 수 있어!' 두 친구는 마을 곳곳에서 소리 나는 물건을 찾아 모으고, "
            "수줍던 두리도 물건 악기 반주에 용기를 내어 노래를 부르게 된다(성장 요소): "
            "① 부엌의 냄비와 주걱 — 둥둥 북소리, ② 유리병에 물을 다르게 담아 — 팅팅 실로폰 소리 "
            "(물이 많으면 낮은 소리, 적으면 높은 소리라는 발견!), ③ 빨래판과 나무 막대 — 드르륵 기타 소리, "
            "④ 상자와 뚜껑 — 쿵쿵 짝짝 리듬. "
            "물건마다 '무슨 소리가 날까?' 먼저 상상해 보고 두드려 확인하는 재미를 반복. "
            "친구들과 '물건 악기 밴드'를 만들어 다 함께 신나는 음악회를 연다 — "
            "둥둥! 팅팅! 드르륵! 쿵쿵 짝짝! 리듬감 있는 의성어의 향연. "
            "'귀 기울이면 세상 모든 물건이 악기가 된다'는 메시지. "
            "마지막에 '네 방에 있는 물건은 어떤 소리가 날까? 두드려서 상상해 봐!'라고 묻는 열린 결말. "
            "1학년 눈높이, 소리 의성어를 최대한 풍부하고 리듬감 있게."
        ),
        "world_setting": "found_object_orchestra",
        "world_desc": (
            "숲속 마을의 야외 음악회 무대 — 나무 그루터기 무대, 색색 깃발 장식, "
            "냄비·유리병·빨래판·상자로 만든 알록달록 물건 악기들, 반딧불이 조명이 켜지는 저녁 음악회"
        ),
        "character_type": (
            "NEW main characters for this special episode (NOT the chick and turtle): "
            "main_1 Tongtongi — a small energetic squirrel with fluffy russet fur, a big bushy tail, "
            "bright shiny eyes, holding two little wooden drumsticks, wearing a tiny red bandana, "
            "always bouncing to a rhythm; "
            "main_2 Duri — a shy round baby bear with soft honey-brown fur, small ears, "
            "warm bashful eyes, wearing a cozy striped scarf, gentle sweet expression. "
            "Supporting: cheerful village animal friends joining the found-object band. "
            "CRITICAL: all characters must have ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "lively village concert scenes with musical notes and rhythm motifs floating in the air, "
            "rounded adorable animal character designs, warm evening festival lights kept clean and bright, "
            "storybook composition with clear focal points, "
            "NEUTRAL to COOL color temperature with no yellow-amber cast, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl13": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "상상",
        "unit": "", "unit_title": "여기저기에서 본다면 (30-31p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "삐요와 토토 시리즈 — 호기심 많은 아기 병아리 '삐요'와 느긋한 꼬마 거북 '토토'가 다시 주인공. "
            "어느 날 두 친구가 언덕 너머로 보이는 '알록달록 둥근 것'을 발견한다. "
            "삐요는 언덕 위에서 보고 '거대한 사탕이야!', 토토는 풀숲 아래에서 보고 '알록달록 산이야!'라고 "
            "서로 다르게 주장하며 티격태격한다. "
            "정체를 알아내려 두 친구는 '여기저기에서' 보기로 한다: "
            "① 가까이 다가가 보기 — 커다란 천의 줄무늬만 보임, "
            "② 멀리 떨어져 보기 — 전체 모양이 둥실 떠 있는 것을 발견, "
            "③ 위에서 내려다보기 — 친절한 기러기 아주머니 등에 타고 하늘에서 보니 둥근 지붕에 바구니가 달림, "
            "④ 아래에서 올려다보기 — 바구니 아래에서 보니 불꽃이 후욱! "
            "정체는 바로 알록달록 열기구! 보는 위치마다 전혀 다르게 보였다는 것을 깨닫는다. "
            "'같은 것도 어디에서 보느냐에 따라 다르게 보여. 그래서 친구의 눈으로도 봐야 해!'라는 메시지. "
            "각 장면에서 '위에서 보면', '아래에서 보면', '가까이서 보면', '멀리서 보면' 같은 위치 표현을 "
            "자연스럽게 대사에 녹여 주세요. 배경에 따라 물건이 달라 보이는 재미도 한 장면 넣어 주세요 "
            "(예: 구름 배경에선 솜사탕 같고, 바다 배경에선 커다란 공 같아 보임). "
            "마지막에 두 친구가 열기구를 타고 마을을 내려다보며 '너희 집은 위에서 보면 어떤 모습일까? "
            "상상해 봐!'라고 시청자에게 묻는 열린 결말. "
            "1학년 눈높이의 짧고 리듬감 있는 문장, 의성어·의태어를 풍부하게 사용하세요."
        ),
        "world_setting": "perspective_balloon_adventure",
        "world_desc": (
            "맑은 가을 하늘의 언덕 마을 — 초록 언덕과 들꽃, 언덕 너머 알록달록 줄무늬 열기구, "
            "뭉게구름 떠 있는 파란 하늘, 위에서 내려다본 조그만 마을 지붕들과 꼬불꼬불 길"
        ),
        "character_type": (
            "the SAME two main characters as previous episodes, identical designs: "
            "main_1 Ppiyo — a small fluffy round yellow chick with soft downy feathers, tiny orange "
            "beak and orange feet, big sparkling black eyes, wearing a little red mini backpack, "
            "short flappy wings, bright curious energetic expression; "
            "main_2 Toto — a small green baby turtle with a rounded shell patterned with soft teal "
            "and moss green hexagons, gentle calm eyes, wearing a small sky blue neckerchief, "
            "friendly relaxed smile, sturdy tiny legs. "
            "Supporting: a kind mother wild goose who gives them a ride, a cheerful balloon pilot animal. "
            "CRITICAL: all characters must have ANIMAL faces and bodies — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "crisp autumn sky scenery with dynamic perspective compositions (bird's eye, worm's eye, "
            "close-up, far view), rounded adorable animal character designs, gentle sunlight, "
            "storybook composition with clear focal points, "
            "NEUTRAL to COOL color temperature with no yellow-amber cast, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl12": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "상상",
        "unit": "", "unit_title": "장난감이 춤을 춘다면 (28-29p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "새로운 주인공의 특별편 (삐요·토토 시리즈와 다른 독립 이야기). "
            "주인공은 아이 방의 장난감 둘 — 씩씩하지만 춤이 서툰 꼬마 태엽 로봇 '띠깍'과 "
            "부드럽고 상냥한 솜인형 토끼 '푸미'. "
            "아이가 깊이 잠든 밤, 달빛이 창으로 스며들면 오르골이 스르르 열리며 장난감들이 깨어난다. "
            "오늘 밤은 일 년에 한 번 열리는 '장난감 무도회' 날! "
            "두 가지 음악이 차례로 흐른다: "
            "① 씩씩한 행진곡 — 쿵쿵! 짝짝! 블록 병정들이 지그재그로 행진하고 곧은 선, 뾰족한 선이 "
            "바닥에 반짝반짝 그려진다. "
            "② 사탕 요정의 춤 — 사뿐사뿐, 빙글빙글, 발레리나 인형이 돌 때마다 구불구불 부드러운 곡선이 "
            "반짝이며 그려진다. "
            "움직임마다 서로 다른 '선'이 마법처럼 바닥에 그려지는 것이 이 이야기의 핵심 장치 "
            "(빠른 음악=곧고 뾰족한 선, 느리고 예쁜 음악=부드러운 곡선 — 음악을 선으로 표현하기). "
            "띠깍은 태엽 몸이 뻣뻣해 춤이 서툴러 부끄러워하지만, 푸미가 '네 몸이 내는 소리도 음악이야!'라고 "
            "용기를 준다. 띠깍은 자기만의 '띠깍띠깍 로봇 춤'을 추고, 지그재그 번쩍이는 멋진 선이 그려져 "
            "모두의 박수를 받는다 — '나만의 움직임도 멋진 표현'이라는 메시지. "
            "새벽이 오면 장난감들은 살금살금 제자리로 돌아가고, 아침에 아이는 바닥에 남은 희미한 "
            "반짝이 선을 발견하며 고개를 갸웃한다. "
            "마지막에 '너의 장난감도 밤에 춤을 출까? 어떤 춤을 출 것 같아?'라고 시청자에게 묻는 열린 결말. "
            "1학년 눈높이의 짧고 리듬감 있는 문장, 의성어·의태어(쿵쿵, 사뿐사뿐, 빙글빙글, 띠깍띠깍)를 "
            "풍부하게 사용하세요."
        ),
        "world_setting": "toy_room_night_ball",
        "world_desc": (
            "달빛이 스며드는 밤의 아이 방 — 별 모양 야광 스티커가 붙은 벽, 알록달록 장난감 상자, "
            "황금빛으로 빛나는 오르골, 블록 성과 그림책 탑, 폭신한 러그 무도회장, "
            "움직임을 따라 바닥에 반짝이며 그려지는 마법의 선들"
        ),
        "character_type": (
            "NEW main characters for this special episode (NOT the chick and turtle): "
            "main_1 Ttikkak — a small boxy wind-up tin robot toy with a round silver head, big warm "
            "glowing amber eyes, a large golden wind-up key on his back, sky blue and cream body with "
            "tiny rivets, stiff but endearing movements; "
            "main_2 Pumi — a soft plush bunny doll with cream fluffy fabric, long floppy ears with "
            "pink inner lining, a stitched smile, button eyes, wearing a tiny mint tutu skirt. "
            "Supporting: block soldier toys marching, a graceful ballerina doll, a golden music box. "
            "All are TOYS with toy-like materials (tin, plush, wood) — cute, rounded, friendly."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "magical moonlit night nursery with warm glowing highlights and sparkling magical line trails, "
            "rounded adorable toy character designs, dreamy but clean colors, "
            "storybook composition with clear focal points, "
            "NEUTRAL to COOL color temperature overall with selective warm glow accents, "
            "inspired by modern Korean picture books for 7-year-olds and the Nutcracker ballet"
        ),
    },
    "bsl10": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "상상",
        "unit": "", "unit_title": "함께 간다면 (24-25p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "삐요와 토토 시리즈 3편. 호기심 많은 아기 병아리 '삐요'와 느긋한 꼬마 거북 '토토'가 "
            "수박 축제가 열리는 '초록 마을'로 처음 함께 여행을 떠나는 지역 여행 이야기. "
            "전래동요 '어디만큼 강가'의 반복 문답을 여행의 리듬으로 사용한다: "
            "길을 갈 때마다 삐요가 '어디만큼 갔니?' 하고 물으면 토토가 '당당 멀었다!'(아직 멀었다) 하고 답하고, "
            "장소에 도착할 때마다 '○○에 왔다!' 하고 외친다. (동요 자체는 도입에서 흥얼거리는 동기 유발 수준으로만.) "
            "여행 경로는 우리 지역의 정겨운 풍경 네 곳: "
            "① 반짝이는 강가 — 징검다리를 하나씩 함께 건너기, "
            "② 넓은 논밭 — 소가 써레로 흙을 고르는 모습 구경(농기구 이름 자연스럽게), "
            "③ 왁자지껄 마을 장터 — 고소한 냄새, 알록달록 과일 구경, "
            "④ 안개 낀 산고개 — 앞이 안 보여 삐요가 무서워하자, 토토의 등껍질에 손을 얹고 "
            "토토의 목소리만 듣고 한 걸음씩 따라 걷는다(잘 듣고 따라가기, 신뢰와 경청). "
            "마침내 초록 마을 도착 — '초록 마을에 도착했다!' 함께 외치고, 축제에서 시원한 수박을 나눠 먹는다. "
            "'혼자 가면 멀지만 함께 가면 즐겁다'는 것을 깨닫는 따뜻한 결말. "
            "마지막에 '다음엔 어디로 함께 가 볼까? 너라면 어디로 가고 싶어?'라고 시청자에게 묻는다. "
            "'어디만큼 갔니?'-'당당 멀었다!' 문답을 최소 3번 반복해 리듬감을 만들고, "
            "1학년 눈높이의 짧은 문장과 의성어·의태어를 풍부하게 사용하세요."
        ),
        "world_setting": "korean_countryside_journey",
        "world_desc": (
            "여름날 한국 시골 여행길 — 징검다리 놓인 반짝이는 강가, 초록 벼가 자라는 넓은 논밭과 "
            "써레를 끄는 순한 소, 알록달록 천막이 늘어선 마을 장터, 뽀얀 안개가 내려앉은 산고개 숲길, "
            "그리고 수박 깃발이 펄럭이는 축제 마을"
        ),
        "character_type": (
            "the SAME two main characters as previous episodes, identical designs: "
            "main_1 Ppiyo — a small fluffy round yellow chick with soft downy feathers, tiny orange "
            "beak and orange feet, big sparkling black eyes, wearing a little red mini backpack, "
            "short flappy wings, bright curious energetic expression; "
            "main_2 Toto — a small green baby turtle with a rounded shell patterned with soft teal "
            "and moss green hexagons, gentle calm eyes, wearing a small sky blue neckerchief, "
            "friendly relaxed smile, sturdy tiny legs. "
            "Supporting: a gentle big ox pulling a wooden harrow in the rice field, cheerful market animals. "
            "CRITICAL: all characters must have ANIMAL faces and bodies — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "warm Korean countryside summer scenery with clear blue sky, rounded adorable animal character designs, "
            "gentle sunlight, storybook composition with clear focal points, "
            "NEUTRAL to COOL color temperature with no yellow-amber cast, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl11": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "상상",
        "unit": "", "unit_title": "여러 가지 모양이 살아난다면 (26-27p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "삐요와 토토 시리즈 4편. 어느 날 밤, 벽에 비친 이상한 그림자를 보고 잠에서 깬 삐요와 토토. "
            "그림자의 정체는 살아 움직이는 세 모양 친구 — 데굴데굴 구르는 '동글이'(동그라미), "
            "반듯반듯 걷는 '네모난'(네모), 콕콕 뾰족한 '세모미'(세모)! "
            "모양 친구들이 두 친구를 '모양 나라'로 초대한다. "
            "모양 나라에서는 모든 것이 세 가지 모양으로 이루어져 있다: "
            "동그라미 해와 바퀴, 네모 집과 창문, 세모 지붕과 산. "
            "그런데 모양 나라에 폭풍이 지나가 마을이 흩어져 버렸다! "
            "삐요와 토토는 모양 친구들과 함께 흩어진 조각들을 조합해 마을을 다시 만든다: "
            "동그라미+세모=아이스크림, 네모+세모=집, 동그라미 두 개+네모=수레처럼 "
            "모양을 합치면 새로운 것이 태어나는 즐거움을 보여 준다. "
            "각 장면에서 '주변에서 동그라미(네모/세모)를 찾아볼까?' 하는 관찰 표현을 자연스럽게 녹여 주세요. "
            "마지막에 완성된 '나만의 모양 나라'를 보며 모양 친구들과 작별하고, "
            "'너라면 동그라미, 네모, 세모로 무엇을 만들고 싶어?'라고 시청자에게 묻는 열린 결말. "
            "1학년 눈높이의 짧은 문장, 의성어·의태어(데굴데굴, 반듯반듯, 콕콕)를 풍부하게 사용하세요."
        ),
        "world_setting": "living_shapes_land",
        "world_desc": (
            "상상의 모양 나라 — 동그라미 해와 뭉게구름, 네모난 알록달록 집들과 창문, 세모 지붕과 "
            "세모 산맥, 파스텔톤 색종이 같은 풍경, 밤 장면에서는 벽에 비친 신비한 모양 그림자"
        ),
        "character_type": (
            "the SAME two main characters as previous episodes, identical designs: "
            "main_1 Ppiyo — a small fluffy round yellow chick with soft downy feathers, tiny orange "
            "beak and orange feet, big sparkling black eyes, wearing a little red mini backpack, "
            "short flappy wings, bright curious energetic expression; "
            "main_2 Toto — a small green baby turtle with a rounded shell patterned with soft teal "
            "and moss green hexagons, gentle calm eyes, wearing a small sky blue neckerchief, "
            "friendly relaxed smile, sturdy tiny legs. "
            "Supporting shape characters: Donggeuli — a cheerful bouncy red CIRCLE with a smiling face and stubby arms; "
            "Nemonan — a calm sturdy blue SQUARE with a friendly face; "
            "Semomi — a lively pointy yellow TRIANGLE with a mischievous smile. "
            "Shape characters are simple flat geometric shapes with cute faces and small limbs. "
            "CRITICAL: animal characters must have ANIMAL faces — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache "
            "with playful paper-craft flat shape elements, clean pastel colors, rounded adorable "
            "character designs, gentle lighting, storybook composition with clear focal points, "
            "NEUTRAL to COOL color temperature with no yellow-amber cast, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl09": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "상상",
        "unit": "", "unit_title": "상자에 물건이 들어 있다면 (22-23p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "전편 '삐요와 토토의 신비한 알 탐험'의 주인공, 호기심 많은 아기 병아리 '삐요'와 "
            "느긋한 꼬마 거북 '토토'가 다시 등장하는 시리즈 2편. "
            "어느 아침, 두 친구의 집 앞에 리본이 묶인 '신비한 상자'가 놓여 있다. "
            "바로 열어보려는 삐요를 토토가 말리며 '열기 전에 무엇인지 맞혀 보자!'고 제안한다. "
            "두 친구는 오감을 하나씩 사용해 상자 속 물건을 탐구한다: "
            "① 눈 — 상자의 작은 구멍으로 살짝 들여다보기(초록빛이 보여!), "
            "② 귀 — 흔들어 소리 듣기(통통! 묵직한 소리), "
            "③ 코 — 냄새 맡기(달콤하고 시원한 향기), "
            "④ 손 — 구멍에 손을 넣어 만져보기(매끈매끈 동글동글), "
            "⑤ 입 — 마지막에 열어서 맛보기. "
            "감각마다 얻은 단서를 서로 알려 주며 '함께 단서를 모으면 답에 가까워진다'는 협동을 배우고, "
            "단서를 종합해 상상한 답(수박!)을 외친 뒤 상자를 열어 확인한다 — 정답! 시원한 수박을 나눠 먹는다. "
            "각 감각 장면에서 '눈으로 관찰해요', '귀로 들어요' 같은 오감 표현을 자연스럽게 대사에 녹여주세요. "
            "마지막에 리본이 묶인 두 번째 상자가 하나 더 발견되고, 흔들면 사각사각 소리가 난다. "
            "'이 상자에는 무엇이 들어 있을까? 너도 오감으로 상상해 봐!'라고 시청자에게 묻는 열린 결말로 끝난다. "
            "1학년 눈높이의 짧고 리듬감 있는 문장, 의성어·의태어를 풍부하게 사용하세요."
        ),
        "world_setting": "sensory_box_adventure",
        "world_desc": (
            "맑은 여름 아침의 아늑한 언덕집 마당 — 나무 문 앞 돌계단, 알록달록 리본이 묶인 "
            "커다란 나무 상자, 꽃이 핀 울타리, 풀잎에 맺힌 이슬, 파란 하늘과 뭉게구름"
        ),
        "character_type": (
            "the SAME two main characters as the previous episode, identical designs: "
            "main_1 Ppiyo — a small fluffy round yellow chick with soft downy feathers, tiny orange "
            "beak and orange feet, big sparkling black eyes, wearing a little red mini backpack, "
            "short flappy wings, bright curious energetic expression; "
            "main_2 Toto — a small green baby turtle with a rounded shell patterned with soft teal "
            "and moss green hexagons, gentle calm eyes, wearing a small sky blue neckerchief, "
            "friendly relaxed smile, sturdy tiny legs. "
            "CRITICAL: all characters must have ANIMAL faces and bodies — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "clean fresh summer morning colors with clear blue sky, rounded adorable animal character designs, "
            "gentle sunlight, storybook composition with clear focal points, "
            "NEUTRAL to COOL color temperature with no yellow-amber cast, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl07": {
        "grade": 1, "semester": 2, "subject": "통합교과", "series": "상상",
        "unit": "", "unit_title": "알에서 동물이 태어난다면 (20-21p)", "sub_unit": "함께 골라요",
        "achievement_standard": "",
        "story_direction": (
            "호기심 많은 아기 병아리 '삐요'와 느긋한 꼬마 거북 '토토'가 "
            "반짝이는 '신비한 알 지도'를 주워 알 탐험을 떠난다. "
            "지도를 따라 세 장소를 차례로 방문한다: "
            "① 높은 나무 위 둥지 — 작고 얼룩덜룩한 알(메추라기·오리 같은 새 알), "
            "② 연못가 물풀 속 — 투명 젤리 같은 알 뭉치(개구리·도롱뇽 알), "
            "③ 따뜻한 모래사장 — 동그란 알(거북 알). "
            "장소마다 두 친구는 '이곳은 어디일까? 알 모습은 어떨까? 여기서 태어나는 동물은 어떤 특징이 있을까?'를 "
            "묻고 상상한 뒤, 알이 깨어나며 진짜 동물을 만나 특징(날개, 물속 헤엄, 단단한 등껍질)을 자연스럽게 배운다. "
            "'알이 발견된 장소와 태어나는 동물은 서로 관련이 있다'는 것을 대화로 깨닫게 해주세요. "
            "마지막에 무지개빛으로 반짝이는 '신비한 알' 하나를 발견하는데, 무엇이 태어날지 아무도 모른다. "
            "두 친구가 각자 상상의 동물(예: 구름 날개 무지개 용)을 신나게 상상하다가, "
            "알이 살짝 흔들리며 '너는 무엇이 태어날 것 같아?'라고 시청자에게 묻는 열린 결말로 끝난다. "
            "1학년 눈높이의 짧고 리듬감 있는 문장으로, 상상하는 즐거움이 가득하게 구성하세요."
        ),
        "world_setting": "egg_expedition_nature",
        "world_desc": (
            "맑은 봄날의 자연 탐험길 — 초록 잎이 무성한 큰 나무와 폭신한 둥지, "
            "물풀과 수련잎이 떠 있는 반짝이는 연못, 조개껍데기가 흩어진 따뜻한 황금빛 모래사장, "
            "그리고 언덕 위 풀숲에 놓인 무지개빛으로 반짝이는 신비한 알"
        ),
        "character_type": (
            "cute animal children explorers: a small fluffy yellow chick with a tiny backpack (curious, energetic) "
            "and a little green turtle with a patterned shell (calm, thoughtful), "
            "meeting egg-born animals — mother quail bird, cheerful frog, baby sea turtles. "
            "CRITICAL: all characters must have ANIMAL faces and bodies — NOT human faces."
        ),
        "art_style_en": (
            "bright cheerful Korean children's picture book illustration, soft watercolor and gouache, "
            "clean fresh spring colors with clear blue sky, rounded adorable animal character designs, "
            "gentle sunlight, storybook composition with clear focal points, "
            "NEUTRAL to COOL color temperature with no yellow-amber cast, "
            "inspired by modern Korean picture books for 7-year-olds"
        ),
    },
    "bsl06": {
        "grade": 2, "semester": 1, "subject": "통합교과", "series": "마을",
        "unit": "", "unit_title": "우리 마을 이곳저곳 (22-23p)", "sub_unit": "함께 골라요",
        "achievement_standard": "[2슬06-02]",
        "story_direction": (
            "드넓은 초원에서 혼자 살던 어린 사자 '레오'가 처음으로 용기를 내어 동물 마을 장터에 찾아간다. "
            "마을에 사자가 나타나자 동물들은 두려워 숨거나 도망가고, 레오는 슬프고 외로워진다. "
            "하지만 겁 없는 토끼 소녀 '미나'가 먼저 말을 걸고, 레오의 손을 잡고 장터 곳곳을 함께 둘러본다. "
            "빵집, 꽃가게, 꿀 가게, 생선 가게 등 마을의 다양한 장소를 방문하면서 "
            "레오는 자신의 힘으로 상인들을 돕고, 동물 상인들은 레오가 사납지 않고 친절하다는 것을 알게 된다. "
            "각 가게마다 무엇을 팔고 어떤 일을 하는지 자연스럽게 대화에 녹여주세요. "
            "마지막에 레오는 '마을에는 내가 좋아하는 장소들이 생겼어!'라고 기뻐하며 마을의 소중한 친구가 된다. "
            "주토피아처럼 의인화된 동물들이 사는 활기찬 장터 마을이 배경. "
            "어린이들이 우리 마을의 다양한 장소와 그곳에서 일하는 사람(동물)들의 역할을 자연스럽게 익히도록 구성하세요."
        ),
        "world_setting": "zootopia_animal_market_town",
        "world_desc": (
            "주토피아 스타일의 활기찬 동물 마을 장터 — 알록달록 천막이 가득한 시장 골목, "
            "따뜻한 햇살이 비치는 넓은 광장, 꿀 항아리가 쌓인 여우 가게, "
            "신선한 생선과 과일을 파는 곰 할머니 가판대, 갓 구운 빵 냄새 가득한 빵집, "
            "색색깔 꽃다발이 넘치는 꽃가게, 저 멀리 보이는 황금빛 초원"
        ),
        "character_type": (
            "Zootopia-inspired anthropomorphic animals: brave young lion cub exploring the market town for the first time, "
            "fearless rabbit girl as guide, kind fox vendor selling honey and vegetables, warm elderly bear vendor selling fish and fruit. "
            "CRITICAL: all animals must have ANIMAL faces (lion snout, rabbit ears, fox ears, bear muzzle) — NOT human faces. "
            "Bodies standing upright wearing clothes like Zootopia characters."
        ),
        "art_style_en": (
            "Zootopia-inspired vibrant anthropomorphic animal illustration, colorful bustling market town setting, "
            "bright saturated warm afternoon sunlight, detailed expressive animal character designs, "
            "CRITICAL REQUIREMENT: all characters MUST have ANIMAL faces — lion has lion muzzle/nose, rabbit has rabbit face, "
            "fox has fox snout, bear has bear muzzle — NEVER human faces on animal bodies, "
            "anthropomorphic bodies standing upright wearing colorful clothes, cinematic composition, "
            "modern animated movie art style rendered as 2D children's book illustration, "
            "warm inviting market atmosphere with colorful stalls and hanging banners, "
            "rich background detail with depth of field"
        ),
    },
    "bsl08": {
        "grade": 2, "semester": 1, "subject": "통합교과", "series": "마을",
        "unit": "", "unit_title": "마을에서 찾아라 (20-21p)", "sub_unit": "함께 골라요",
        "achievement_standard": "[2슬06-02]",
        "story_direction": (
            "귀여운 동물 친구들이 처음으로 혼자 마을 탐험을 떠난다. "
            "빵집, 꽃가게, 도서관, 우체국, 공원을 하나씩 방문하며 "
            "각 장소에서 일하는 사람들을 만나고, 마을 곳곳에 숨겨진 작은 보물(도토리, 편지, 꽃씨 등)을 찾아낸다. "
            "탐험이 끝날 무렵 '마을은 서로 도우며 살아가는 곳'이라는 것을 따뜻하게 깨닫는다. "
            "마을의 다양한 장소와 그곳에서 일하는 사람들(빵집 아저씨, 꽃집 이모, 사서 선생님, 우체부 아저씨)의 역할을 "
            "자연스럽게 익힐 수 있도록 대화에 녹여주세요."
        ),
        "world_setting": "korean_village",
        "world_desc": (
            "알록달록 우리 마을 — 갓 구운 빵 냄새 가득한 빵집, 색깔별로 꽃이 가득한 꽃가게, "
            "책이 가득한 도서관, 빨간 우편함이 있는 우체국, 미끄럼틀과 그네가 있는 공원, "
            "돌멩이 길과 따뜻한 햇살이 내리쬐는 아늑한 골목"
        ),
        "character_type": (
            "cute animal children (main: small curious fox cub and fluffy rabbit) "
            "exploring their cheerful neighborhood village, meeting kind animal shopkeepers"
        ),
        "art_style_en": (
            "Korean children's picture book illustration, bright gouache and cheerful watercolor village scenes, "
            "warm community atmosphere, colorful neighborhood shops with hand-painted signs, "
            "soft pencil outlines with vivid pigment fills, cozy and inviting street-level perspectives, "
            "inspired by Richard Scarry's Busytown meets modern Korean picture book warmth"
        ),
    },
    "bsl01": {
        "grade": 2, "semester": 1, "subject": "통합교과", "series": "바슬즐",
        "unit": "", "unit_title": "자연 4. 숲속을 걸어요", "sub_unit": "함께 골라요",
        "achievement_standard": "[2바01-03]",
        "story_direction": "숲속 동물들과 함께 걸으며 자연을 탐험하는 이야기",
        "world_setting": "forest", "world_desc": "알록달록 숲속 — 큰 나무들, 시냇물, 버섯집",
        "character_type": "cute animal children exploring the forest",
        "art_style_en": "Korean children's picture book, bright watercolor forest illustration",
    },
    "bsl02": {
        "grade": 2, "semester": 1, "subject": "통합교과", "series": "바슬즐",
        "unit": "", "unit_title": "봄 — 씨앗을 심어요", "sub_unit": "함께 골라요",
        "achievement_standard": "[2바01-01]",
        "story_direction": "씨앗을 심고 새싹이 자라는 이야기",
        "world_setting": "garden", "world_desc": "봄 텃밭 — 화분, 씨앗, 물뿌리개",
        "character_type": "cute animal children planting seeds",
        "art_style_en": "Korean children's picture book, bright spring watercolor illustration",
    },
    "bsl05": {
        "grade": 1, "semester": 1, "subject": "통합교과", "series": "사람들",
        "unit": "", "unit_title": "우리 가족", "sub_unit": "함께 골라요 — 우리 가족 (사람들 30-31p)",
        "achievement_standard": "[1바06-01]",
        "story_direction": (
            "토끼 가족이 숲속 아늑한 토굴에서 행복하게 살고 있다. "
            "어느 날 갑자기 큰 비가 내려 홍수가 나고, 토굴이 무너질 뻔한 위기에 처한다. "
            "토끼 아빠와 엄마가 당황하고 있을 때, 삼촌 토끼가 달려와 모래주머니를 쌓아주고, "
            "이모 토끼는 아기 토끼들을 안전한 곳으로 데려가 준다. "
            "할아버지 토끼는 경험을 살려 물길을 돌리고, 고모 토끼는 마른 풀과 먹을 것을 가져온다. "
            "사촌 토끼들은 함께 새 토굴을 파는 것을 도와준다. "
            "친척들이 각자의 방법으로 도와주어 위기를 극복하고, "
            "가족과 친척의 소중함, 서로 돕는 마음을 깨닫는 따뜻한 이야기. "
            "친척을 부르는 말(삼촌, 이모, 할아버지, 고모, 사촌)을 자연스럽게 익힐 수 있게 대화에 녹여주세요."
        ),
        "world_setting": "forest_burrow",
        "world_desc": (
            "초록 숲속 언덕 아래 아늑한 토끼 토굴 마을. "
            "나무뿌리가 천장이 되고 작은 창문에서 빛이 들어오는 아기자기한 토굴 집, "
            "맑은 시냇물, 야생화 들판, 큰 참나무, 비 오는 숲 풍경"
        ),
        "character_type": (
            "cute rabbit family in cozy underground burrow village, "
            "parent rabbits, uncle rabbit, aunt rabbit, grandpa rabbit, cousin rabbits"
        ),
        "art_style_en": (
            "Beatrix Potter meets modern Korean children's picture book style, "
            "soft watercolor with gentle ink outlines, warm earthy tones and fresh greens, "
            "cozy underground burrow interiors with warm lamplight, "
            "rainy forest atmosphere with dramatic clouds and puddles, "
            "heartwarming family illustration, detailed nature background"
        ),
    },
    "bsl03": {
        "grade": 1, "semester": 1, "subject": "통합교과", "series": "탐험",
        "unit": "", "unit_title": "용기를 내 볼까", "sub_unit": "함께 골라요 (탐험 34-35p)",
        "achievement_standard": "[1바03-02]",
        "story_direction": (
            "용감한 햄스터 하미가 스스로 발명한 작은 잠수함 '뽀글이'를 타고 처음으로 바닷속 탐험을 떠난다. "
            "처음엔 두렵고 망설이지만, 반짝이는 해파리, 수줍은 해마, 장난꾸러기 문어, "
            "우렁찬 고래 등 새 친구들을 하나씩 만나며 용기가 쌓인다. "
            "마침내 깊은 바닷속 보물 동굴에서 '용기란 두렵더라도 해보는 것'이라는 걸 깨닫는다."
        ),
        "world_setting": "underwater",
        "world_desc": (
            "햄스터 발명가의 귀여운 잠수함 '뽀글이' 내부 조종석, "
            "형형색색 산호초 숲, 빛나는 해파리 떼, 심해 보물 동굴, 반짝이는 바닷속 야경"
        ),
        "character_type": (
            "brave hamster girl pilot in a tiny round submarine, "
            "colorful sea creatures (jellyfish, seahorse, octopus, whale) as friends"
        ),
        "art_style_en": (
            "Studio Ghibli meets Korean picture book style underwater adventure illustration, "
            "vibrant ocean blues and teals with warm amber submarine interior lighting, "
            "glowing bioluminescent creatures, cute round submarine design with porthole windows, "
            "transparent water effects with sun rays filtering through, "
            "soft watercolor texture, dreamy and adventurous atmosphere"
        ),
    },
    "segye01": {
        "grade": 2, "semester": 1, "subject": "통합교과", "series": "세계",
        "unit": "", "unit_title": "세계로 가는 기차놀이 (20-21p)", "sub_unit": "함께 골라요",
        "achievement_standard": "[2슬08-01]",
        "story_direction": (
            "숲속에서만 살던 어린 표범 '반점이'가 어느 날 신비로운 '세계 기차'를 발견한다. "
            "기차에는 부엉이 차장이 있고, 세계 여러 나라를 돌아다닌다고 한다. "
            "반점이가 용기를 내어 기차에 올라타자, 기차는 빠르게 달려 여러 나라를 방문한다. "
            "첫 번째 정류장: 한국 - 경복궁 앞에서 한복 입은 토끼 친구를 만난다. "
            "두 번째 정류장: 일본 - 후지산 앞에서 기모노 입은 너구리 친구를 만난다. "
            "세 번째 정류장: 이집트 - 피라미드 앞에서 터번을 두른 낙타 친구를 만난다. "
            "네 번째 정류장: 프랑스 - 에펠탑 앞에서 베레모를 쓴 여우 친구를 만난다. "
            "다섯 번째 정류장: 미국 - 자유의 여신상 앞에서 카우보이 모자 쓴 곰 친구를 만난다. "
            "각 나라마다 대표 명소 이름과 그 나라의 짧은 인사말(안녕하세요, こんにちは, مرحبا, Bonjour, Hello)을 배운다. "
            "여행을 마친 반점이는 '세상에는 이렇게 다양하고 아름다운 나라들이 있구나!'를 깨닫고 "
            "새로운 친구들과 편지를 나누기로 약속하며 집으로 돌아온다. "
            "반드시 각 나라 슬라이드에 대표 명소 이름을 대화에 명확히 포함하세요. "
            "주토피아처럼 의인화된 동물들이 각 나라 문화복장을 입고 등장한다. "
            "어린이들이 세계 여러 나라와 그 나라의 대표 명소를 자연스럽게 익히도록 구성하세요."
        ),
        "world_setting": "world_train_adventure",
        "world_desc": (
            "마법의 세계 기차 '세계호' — 구름 위를 달리는 알록달록 증기 기차, "
            "한국의 경복궁 처마와 단청, 일본의 눈 덮인 후지산, "
            "이집트의 황금빛 사막과 피라미드, 프랑스의 에펠탑이 빛나는 파리 야경, "
            "미국의 자유의 여신상과 넓은 항구, 각 나라의 국기와 전통 건축물"
        ),
        "character_type": (
            "Zootopia-inspired anthropomorphic animals: a young spotted leopard cub ('반점이') as main character wearing a backpack, "
            "a wise owl train conductor wearing a uniform, "
            "and animal residents of each country wearing traditional cultural clothing. "
            "CRITICAL: all animals MUST have ANIMAL faces (leopard has spots and muzzle, owl has beak and round eyes, "
            "rabbit has long ears, tanuki has round face, camel has long neck, fox has pointed ears, bear has round ears) "
            "— NEVER human faces on animal bodies. "
            "Bodies standing upright wearing cultural clothes like Zootopia characters."
        ),
        "art_style_en": (
            "Zootopia-inspired vibrant anthropomorphic animal illustration, world travel adventure style, "
            "bright saturated colors with each country's distinct visual identity, "
            "detailed iconic landmark backgrounds (Gyeongbokgung Palace with colorful dancheong, snow-capped Mt. Fuji, "
            "Great Pyramids in golden desert, Eiffel Tower in Parisian evening, Statue of Liberty at harbor), "
            "CRITICAL REQUIREMENT: all characters MUST have ANIMAL faces — "
            "leopard has leopard spots on fur and feline muzzle, owl has large round eyes and beak, "
            "rabbit has tall ears and rabbit nose — NEVER human faces on animal bodies, "
            "anthropomorphic bodies wearing culturally authentic traditional clothes, "
            "cinematic wide composition showing landmark prominently in background, "
            "modern Disney-Pixar animated movie art style, warm exciting travel adventure atmosphere, "
            "rich background detail with depth of field, award-winning children's book illustration quality"
        ),
    },
    "school01": {
        "grade": 1, "semester": 1, "subject": "통합교과", "series": "학교",
        "unit": "", "unit_title": "함께 준비해요", "sub_unit": "12. 발표는 이렇게(42-43p)",
        "achievement_standard": "[1국01-04]",
        "story_direction": (
            "집현전 초등학교에 다니는 어린 너구리 '두루'는 발표 시간만 되면 목소리가 작아지고 몸이 굳어버리는 아이이다. "
            "반 친구인 활발한 다람쥐 '도토리'와 든든한 곰 '웅이'는 두루의 고민을 듣고 방과 후에 함께 발표 연습을 도와주기로 한다. "
            "친구들은 먼저 '바른 자세'를 연습한다. 허리를 펴고 청중을 바라보고 손을 가지런히 하기. "
            "다음엔 '목소리 크기'를 연습한다. 작은 목소리, 중간 목소리, 큰 목소리를 게임처럼 맞춰본다. "
            "연습 중 두루가 긴장해서 실수를 해도, 친구들은 격려하고 다시 해보자고 다독인다. "
            "연습 도중 두루가 화분에 걸려 넘어지는 사건이 발생해 웃음이 터지고, 오히려 긴장이 풀리는 계기가 된다. "
            "드디어 발표 날. 두루가 떨리는 마음을 꾹 참고 친구들 얼굴을 보며 또박또박 발표한다. "
            "발표가 끝나자 반 친구들이 모두 박수를 쳐준다. "
            "두루는 발표는 완벽하지 않아도 돼. 용기 내서 해보는 게 중요해. 라는 것을 깨닫는다. "
            "집현전이라는 전통 한옥 건물을 품은 특별한 초등학교가 배경. "
            "어린이들이 발표의 기본 자세(바른 자세, 알맞은 목소리 크기, 청중 바라보기)를 자연스럽게 익히도록 구성하세요."
        ),
        "world_setting": "jiphyeonjeon_school",
        "world_desc": (
            "집현전 초등학교 — 전통 한옥 기와지붕이 있는 아름다운 교정, "
            "넓고 밝은 교실, 전통 문양이 그려진 복도, 운동장 한쪽의 고즈넉한 소나무, "
            "발표 연습을 하는 다목적실, 친구들이 응원하는 따뜻한 교실"
        ),
        "character_type": (
            "Zootopia-inspired anthropomorphic animals in Korean school uniforms: "
            "a shy young raccoon ('두루') as main character with striped tail and round masked eyes wearing a blue school backpack, "
            "a cheerful squirrel girl ('도토리') with big fluffy tail and bright yellow bow, "
            "a kind sturdy bear boy ('웅이') with round soft ears and a gentle wide smile. "
            "CRITICAL: all animals MUST have ANIMAL faces — raccoon has distinctive black eye mask markings and pointed snout, "
            "squirrel has big bushy tail and small round ears, bear has round fuzzy ears and broad nose — "
            "NEVER human faces on animal bodies. "
            "Bodies standing upright wearing Korean elementary school casual uniforms."
        ),
        "art_style_en": (
            "Zootopia-inspired warm anthropomorphic animal illustration in Korean elementary school setting, "
            "traditional Korean hanok architecture (기와지붕, 단청) mixed with bright modern school classroom, "
            "soft pastel colors with warm honey-amber and forest green tones, "
            "detailed classroom backgrounds with traditional Korean decorative patterns on walls, "
            "cherry blossom trees visible through large windows, "
            "CRITICAL REQUIREMENT: all characters MUST have ANIMAL faces — "
            "raccoon has distinctive black eye mask markings (너구리 눈 테두리) and pointed snout, "
            "squirrel has large fluffy tail and tiny paws, bear has round ears and soft brown fur — "
            "NEVER human faces on animal bodies, "
            "expressive emotions showing nervousness then courage then joy, "
            "cozy warm school atmosphere, bright natural spring daylight, "
            "Korean children's picture book illustration quality"
        ),
    },
    "school02": {
        "grade": 1, "semester": 1, "subject": "통합교과", "series": "학교",
        "unit": "학교", "unit_title": "함께 배워요", "sub_unit": "1. 어깨동무 내 동무(68-69p)",
        "achievement_standard": "[1바01-03]",
        "story_direction": (
            "집현전 초등학교 운동장에서 작은 고슴도치 '솔이'는 가시 때문에 친구들이 어깨동무를 하기 싫어할까봐 항상 혼자 떨어져 있다. "
            "전래 동요 '어깨동무' 를 배우는 음악 시간에도 찌찌는 양 옆 친구 어깨에 팔을 얹지 못하고 우물쭈물한다. "
            "짝꿍 토끼 '솜솜'이 찌찌에게 다가와 직접 어깨를 내밀며 말한다. 가시가 조금 따가워도 괜찮아. 친구잖아. "
            "둘이 어깨동무를 하자 다른 친구들도 하나둘 합류해 긴 어깨동무 줄이 만들어진다. "
            "어깨동무하며 함께 노래를 부르고 운동장을 한 바퀴 도는 장면이 이 이야기의 클라이맥스. "
            "마지막에 찌찌는 친구란 나의 가시도 받아들여 주는 사람이라는 것을 깨닫는다. "
            "전래 동요 어깨동무 내 동무 노랫말을 동화 대사에 자연스럽게 녹여주세요. "
            "어린이들이 친구와 함께하는 즐거움과 친구를 있는 그대로 받아들이는 따뜻함을 자연스럽게 느끼도록 구성하세요."
        ),
        "world_setting": "jiphyeonjeon_school_playground",
        "world_desc": (
            "집현전 초등학교 — 봄볕이 따뜻한 운동장, 벚꽃 나무 아래 야외 음악 시간, "
            "알록달록 놀이 기구가 있는 운동장, 전통 한옥 처마가 보이는 교정, "
            "어깨동무 줄이 이어지는 운동장 트랙"
        ),
        "character_type": (
            "Zootopia-inspired anthropomorphic animals in Korean school uniforms: "
            "a small timid hedgehog ('솔이') as main character with soft spines and shy round eyes, "
            "a fluffy white rabbit girl ('솜솜') with long ears who is kind and warm-hearted, "
            "and various animal classmates (puppy, hamster, chick, squirrel) all in school uniforms. "
            "CRITICAL: all animals MUST have ANIMAL faces — hedgehog has small round snout and soft quills, "
            "rabbit has long floppy ears and a pink nose, "
            "all classmates have their species-specific features — NEVER human faces on animal bodies. "
            "Bodies upright wearing Korean elementary school casual uniforms, expressive and cute."
        ),
        "art_style_en": (
            "Zootopia-inspired warm anthropomorphic animal illustration in Korean elementary school outdoor setting, "
            "traditional Korean hanok architecture visible in background, cherry blossom trees in bloom, "
            "bright warm spring colors with soft pink and fresh green tones, "
            "CRITICAL REQUIREMENT: all characters MUST have ANIMAL faces — "
            "hedgehog has soft rounded spines (not sharp) and tiny round eyes showing shyness then joy, "
            "rabbit has long floppy ears and gentle expression, "
            "NEVER human faces on animal bodies, "
            "heartwarming shoulder-link scenes with joyful energetic composition, "
            "bright sunny outdoor school atmosphere, vibrant spring daylight, "
            "Korean children's picture book illustration quality"
        ),
    },
}

# ── 에피소드 목록 (2학년 1학기 국어) ──────────────────────
EPISODES = [
    {
        "ep": 1,
        "unit": "01",
        "unit_title": "만나서 반가워요!",
        "sub_unit": "1. 말차례를 지키며 대화하기",
        "achievement_standard": "[2국01-03]",
        "story_direction": "말차례 안 지켜서 친구가 속상 → 말차례 지키니 대화 즐거움",
        "world_setting": "korean_school",
        "world_desc": "한국 초등학교 2학년 교실과 운동장",
        "character_type": "Korean elementary school children (human)",
        "art_style_en": "Korean children's picture book illustration, colored pencil and gouache mixed media technique, CLEAN BRIGHT NATURAL COLORS, natural daylight, detailed Korean elementary school background",
    },
    {
        "ep": 2,
        "unit": "01",
        "unit_title": "만나서 반가워요!",
        "sub_unit": "2. 친구들에게 자신을 소개하기",
        "achievement_standard": "[2국01-04]",
        "story_direction": "수줍은 전학생이 자기소개 마법카드로 친구 사귀기",
        "world_setting": "korean_school",
        "world_desc": "한국 초등학교 2학년 교실과 복도",
        "character_type": "Korean elementary school children (human)",
        "art_style_en": "Korean children's picture book illustration, colored pencil and gouache mixed media technique, CLEAN BRIGHT NATURAL COLORS, natural daylight, detailed Korean elementary school background",
    },
    {
        "ep": 3,
        "unit": "02",
        "unit_title": "말의 재미가 솔솔",
        "sub_unit": "1. 말의 재미 느끼기",
        "achievement_standard": "[2국05-01]",
        "story_direction": "의성어·의태어들이 살아있는 소리 왕국에서, 작은 소리 요정 '소솔'이 침묵의 마녀에게 빼앗긴 소리들을 되찾는 모험. 퐁당퐁당, 반짝반짝, 어흥, 멍멍 등 소리말들이 캐릭터로 등장.",
        "world_setting": "fantasy_sound_kingdom",
        "world_desc": "소리로 가득 찬 마법의 왕국 — 음표 모양 나무, 악기 성, 소리 방울 꽃",
        "character_type": "small luminous sound fairies and magical creatures",
        "art_style_en": "Studio Ghibli inspired watercolor fairy tale illustration with glowing musical particles and magical sparkles, soft pastel rainbow colors, dreamy and whimsical atmosphere, detailed fantasy sound kingdom background with musical note trees and glowing orbs",
    },
    {
        "ep": 4,
        "unit": "02",
        "unit_title": "말의 재미가 솔솔",
        "sub_unit": "2. 책에 대한 생각이나 느낌 나누기",
        "achievement_standard": "[2국05-02]",
        "story_direction": "동물 마을 숲속 도서관에서 토끼 아이 '콩이'와 곰 아이 '뭉치'가 같은 책을 읽고 완전히 다르게 느끼는 이야기. 다르게 느껴도 괜찮다는 것을 깨달음.",
        "world_setting": "animal_village",
        "world_desc": "숲속 동물 마을 — 나무 도서관, 버섯 집, 꽃밭 광장",
        "character_type": "anthropomorphic animals (rabbit, bear children) dressed in cute clothes",
        "art_style_en": "Beatrix Potter style woodland animal illustration meets modern Korean picture book, soft watercolor with ink outlines, warm forest greens and browns, cozy and charming atmosphere, detailed animal village library background",
    },
    {
        "ep": 5,
        "unit": "03",
        "unit_title": "겪은 일을 나타내요",
        "sub_unit": "1. 꾸며 주는 말을 넣어 문장 쓰고 읽기",
        "achievement_standard": "[2국03-02]",
        "story_direction": "꾸며주는 말(형용사·부사)을 잃어버린 회색 우주 행성에서 꼬마 우주인 '루나'가 형용사와 부사를 모아 행성에 색깔과 감정을 되돌려주는 우주 모험.",
        "world_setting": "space",
        "world_desc": "알록달록 행성들이 있는 우주 — 우주선, 별빛 터널, 무지개 행성",
        "character_type": "cute child astronaut in colorful space suit, with alien helper friends",
        "art_style_en": "Retro space adventure picture book style, bold clean colors with neon accents against deep space navy, cute rounded spaceship designs, inspired by 1960s space age illustration meets modern children's book, glowing planets and star clusters in background",
    },
    {
        "ep": 6,
        "unit": "03",
        "unit_title": "겪은 일을 나타내요",
        "sub_unit": "2. 자신의 생각을 담은 일기 쓰기",
        "achievement_standard": "[2국03-04]",
        "story_direction": "조선시대 어린 선비 '도담'이 마법 일기장을 발견하고, 하루의 일을 솔직하게 기록하면 밤하늘에 별이 뜨는 신비로운 이야기.",
        "world_setting": "ancient_korea",
        "world_desc": "조선시대 마을 — 초가집, 서당, 대청마루, 별이 빛나는 밤하늘",
        "character_type": "Korean children in traditional Joseon-era hanbok clothing",
        "art_style_en": "Traditional Korean ink wash painting (수묵화) combined with delicate hanji paper texture and warm color illustration, inspired by classic Korean folk painting (민화) meets modern children's book, detailed Joseon-era architecture background, night sky with stars",
    },
    {
        "ep": 7,
        "unit": "04",
        "unit_title": "분위기를 살려 읽어요",
        "sub_unit": "1. 겹받침을 바르게 읽고 쓰기",
        "achievement_standard": "[2국04-02]",
        "story_direction": "괴물 나라에서 꼬마 괴물 '흥글'이 닭을 '닥'이라 잘못 읽자 닭 괴물이 화가 나서 괴물 나라가 혼란에 빠짐. 바른 발음을 배워 평화를 되찾는 이야기.",
        "world_setting": "monster_kingdom",
        "world_desc": "귀여운 괴물들의 왕국 — 울퉁불퉁 성, 버섯 마을, 알록달록 괴물 시장",
        "character_type": "cute friendly monsters of various shapes and colors",
        "art_style_en": "Monsters Inc. meets Korean picture book style, vibrant saturated colors, cute rounded monster designs, playful and energetic illustration style, detailed monster kingdom background with quirky architecture and funny signage",
    },
    {
        "ep": 8,
        "unit": "04",
        "unit_title": "분위기를 살려 읽어요",
        "sub_unit": "2. 작품을 분위기에 알맞게 읽기",
        "achievement_standard": "[2국05-01]",
        "story_direction": "그리스 신화 세계에서 목소리의 요정 에코(Echo)가 올림포스 연극 대회에서 같은 대사를 다양한 감정으로 읽어 신들을 감동시키는 이야기.",
        "world_setting": "greek_mythology",
        "world_desc": "그리스 신화 세계 — 올림포스 산, 대리석 신전, 황금빛 구름 무대",
        "character_type": "Greek mythology inspired child characters (nymphs, small gods, fauns)",
        "art_style_en": "Ancient Greek pottery painting meets modern children's book illustration, warm terracotta and gold tones with Mediterranean blue accents, classical architectural columns and laurel wreaths, mythological atmosphere with dramatic lighting and flowing robes",
    },
]


def build_prompt(ep_info: dict) -> str:
    """에피소드 정보를 바탕으로 Gemini에 보낼 전체 프롬프트를 구성합니다."""

    grade    = ep_info.get("grade", 2)
    subject  = ep_info.get("subject", "국어")
    series   = ep_info.get("series", "")
    unit     = ep_info.get("unit", "")
    unit_ref = f"{unit}단원" if unit else ep_info.get("unit_title", "")
    sub_text_label = f"{grade}학년 {subject} {series} {unit_ref}".strip()
    yt_title_prefix = f"{grade}학년 추천 {subject} {series} {unit_ref}".strip()

    prompt = f"""\
당신은 한국 초등학교 {grade}학년 아이들을 위한 동화 작가이자 그림책 아트디렉터입니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[기본 규칙]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 슬라이드 13~17장: 표지(cover) 1장 + 본문(story) 11~15장 + 끝(ending) 1장. 장면을 최대한 다이나믹하게 나눠서 많이 만드세요.
- {grade}학년 수준의 쉬운 어휘, 의성어와 의태어를 풍부하게 사용
- 주인공은 이 에피소드의 세계관에 맞는 캐릭터로 설계하세요 (인간 어린이, 동물, 요정, 로봇, 괴물 등 자유롭게). 세계관: {ep_info['world_setting']}
- 각 대사에 speaker 태그를 반드시 붙이세요: narrator, child_boy, child_girl, teacher
- 비율: 내레이터(narrator) 50~60%, 캐릭터 대화(child_boy, child_girl, teacher) 40~50%
- tts_segments는 동화 구연의 핵심입니다. 반드시 다음 규칙을 지켜주세요:
  - tts_segments의 voice 필드는 speaker 이름과 동일하게 적으세요 (narrator, child_boy, child_girl, teacher)
  - "speaker" 값은 캐릭터의 실제 성별에 맞게 배정: 남자아이 → "child_boy", 여자아이 → "child_girl", 어른 → "teacher", 나레이터 → "narrator"
  - characters 배열(meta.characters)의 gender 필드를 반드시 참고할 것. gender가 "boy"/"male"이면 child_boy, "girl"/"female"이면 child_girl
  - tts_segments의 emotion은 구체적인 연기 지시문으로 작성 (예: "놀라서 눈이 동그래진 목소리", "속삭이듯 조심스럽게")
  - 모든 story 슬라이드에 반드시 tts_segments 배열을 포함하세요. 이것을 절대 생략하지 마세요!
  - 각 슬라이드의 text에 등장인물의 직접 대화("")가 있으면 반드시 해당 캐릭터의 speaker로 분리하세요
  - 예시:
    text: '지아가 신나게 말했어요. "어제 우리 강아지가 재롱을 부렸어!" 우진이가 끼어들었어요. "나도 나도!"'
    → tts_segments:
      [{{"speaker":"narrator", "voice":"narrator", "text":"지아가 신나게 말했어요.", "emotion":"밝게 설명하는 톤"}},
       {{"speaker":"child_girl", "voice":"child_girl", "text":"어제 우리 강아지가 재롱을 부렸어!", "emotion":"신나서 들뜬 목소리"}},
       {{"speaker":"narrator", "voice":"narrator", "text":"우진이가 끼어들었어요.", "emotion":"약간 안타까운 톤"}},
       {{"speaker":"child_boy", "voice":"child_boy", "text":"나도 나도!", "emotion":"급하게 끼어드는 목소리"}}]
  - 절대로 전부 narrator로 넣지 마세요! 대화는 반드시 캐릭터 speaker로!
  - 선생님의 대화도 teacher speaker로 분리하세요
  - 각 슬라이드마다 최소 2개 이상의 tts_segment를 넣으세요 (나레이션 + 대화)
- JSON만 출력하세요. 설명이나 마크다운 코드블록 없이 순수 JSON만 출력하세요

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[A. 세계관 & 캐릭터 자유 설계]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
이 에피소드의 세계관: **{ep_info['world_setting']}** — {ep_info['world_desc']}
캐릭터 타입: {ep_info['character_type']}

이 세계관에 완전히 어울리는 고유한 캐릭터를 설계하세요. 캐릭터는 인간일 필요가 없습니다:
- korean_school → 인간 어린이
- fantasy_sound_kingdom → 소리 요정, 마법 생물
- animal_village → 의인화된 동물
- space → 우주인, 로봇, 외계인 어린이
- ancient_korea → 한복 입은 어린이
- monster_kingdom → 귀여운 괴물 아이들
- greek_mythology → 요정, 작은 신, 신화 속 아이

meta.characters 구조:
- main_1: name(세계관에 맞는 이름), gender("boy"/"girl"/"neutral"), species(존재 종류, 예: "요정", "토끼", "우주인", "괴물"), personality(성격), appearance_kr(한국어 외형), appearance_en(영어 외형 — species/size/color/costume/expression 포함, 예: "small luminous sound fairy, translucent glowing wings, electric blue flowing hair, silver robe decorated with musical notes, bare tiny feet, wide curious sparkling eyes")
- main_2: 동일 구조
- supporting: name, role(역할, 예: "현명한 나무 요정", "마법사 선생님", "올빼미 사서"), appearance_en

meta.world 구조 (반드시 포함):
- setting: 세계관 고유 이름 (예: "소리 왕국 '울림'", "숲속 동물 마을 '책숲'")
- art_style_en: {ep_info['art_style_en']}
- bg_elements_en: 이 세계의 배경 요소 5가지 영어 리스트 (구체적 소품)

meta.color_palette 구조:
- primary: 메인 색상 hex (예: "#4A90D9")
- secondary: 보조 색상 hex
- accent: 포인트 색상 hex
- mood: 전체 색감 분위기 설명 (한국어)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[B. 슬라이드별 구도(composition)와 색감 분위기(color_mood)]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
각 슬라이드에 composition과 color_mood 필드를 반드시 넣으세요.

composition은 아래 12가지 중 선택하되, 연속 두 장이 같은 구도가 되면 안 됩니다:
1. wide_establishing — 장소 전체가 보이는 원경
2. medium_two_shot — 두 인물 허리 위로
3. close_up_face — 얼굴 클로즈업
4. over_shoulder — 한 인물 뒤에서 상대를 봄
5. birds_eye — 위에서 내려다보는 구도
6. low_angle — 아래에서 올려다보는 구도
7. silhouette — 역광 실루엣
8. detail_shot — 손, 물건 부분 클로즈업
9. full_body_action — 전신 액션 포즈
10. group_scene — 여러 명 함께
11. window_frame — 창문/문틀 프레이밍
12. book_cover — 표지 전용 (slide 0에만 사용)

color_mood는 아래 중 선택:
- bright_cheerful: 밝고 즐거운 장면
- sad_lonely: 슬프거나 외로운 장면
- tense_worried: 긴장되거나 걱정되는 장면
- realization: 깨달음의 순간
- happy_ending: 해피엔딩
- cover: 표지 전용

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[C. image_prompt 작성 규칙 (매우 중요)]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
각 슬라이드의 image_prompt는 반드시 영어로, 아래 7가지 요소를 이 순서대로 포함해야 합니다:

1) 구도/카메라 앵글: composition 값에 맞는 영어 설명
   - wide_establishing → "Wide establishing shot showing the entire scene,"
   - medium_two_shot → "Medium two-shot from waist up,"
   - close_up_face → "Close-up on face filling the frame,"
   - over_shoulder → "Over-the-shoulder shot looking at the other character,"
   - birds_eye → "Bird's eye view looking straight down,"
   - low_angle → "Low angle shot looking up,"
   - silhouette → "Backlit silhouette composition,"
   - detail_shot → "Extreme close-up detail shot of hands/object,"
   - full_body_action → "Dynamic full body action pose,"
   - group_scene → "Group scene with multiple characters together,"
   - window_frame → "Scene framed through a window or doorway,"
   - book_cover → "Children's book cover composition, title space at top,"

2) 캐릭터 행동 묘사: 이 장면에서 캐릭터가 무엇을 하고 있는지 구체적으로

3) 캐릭터 외형 전체 붙여넣기: meta.characters에서 정의한 appearance_en 텍스트를 그대로 복사하여 포함. 등장하는 모든 캐릭터의 외형을 빠짐없이 넣으세요.

4) 세계관 배경 디테일: meta.world.bg_elements_en의 5가지 요소를 반드시 포함. 이 세계관({ep_info['world_setting']})에 어울리는 구체적 배경 소품 최소 5가지.

5) 조명/색감: color_mood에 따라 아래 중 해당하는 것을 넣으세요. 세계관에 따라 분위기를 조정하세요:
   - bright_cheerful: "vivid bright colors, cheerful lighting, energetic and lively atmosphere"
   - sad_lonely: "muted desaturated colors, dim lighting, lonely and quiet atmosphere, cool blue-gray tones"
   - tense_worried: "slightly desaturated, cool shadows, nervous energy, dimmer lighting"
   - realization: "warm golden light breaking through, contrast between light and shadow, magical moment"
   - happy_ending: "full spectrum of bright clean colors, maximum brightness and saturation, joyful and vibrant, celebratory atmosphere"
   - cover: "the most eye-catching and colorful illustration, dynamic composition, bright and inviting"

6) 스타일 접미사 (세계관 반응형): {ep_info['art_style_en']}, award-winning children's illustration quality

7) 금지 사항 접미사 (매 장면 고정): "absolutely no text, no speech bubbles, no split screen, no panels, single continuous composition, no readable text on any surface"

8) 색온도 접미사: korean_school 세계관은 "NEUTRAL to COOL color temperature, no warm/yellow cast". 그 외 세계관은 세계관 고유 색감을 살리되 탁하거나 칙칙하지 않게.

9) 인물 수 제한: 한 화면에 또렷한 인물 최대 3명. 배경 캐릭터는 "soft blurred silhouettes in the background, out of focus"로 처리.

10) 신체 표현: "character appendages shown only as part of full body pose, never extreme close-up of fingers/claws/paws"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[D. Shorts 전략 자동 선택]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- shorts_strategy를 반드시 포함하세요. 동화 내용을 분석해서 5가지 유형 중 가장 효과적인 것을 선택하세요:

  유형 1 "behavior_quiz": 문제 행동을 보여주고 "뭐가 잘못됐을까?" 퀴즈. 명확한 잘못된 행동이 있는 에피소드에 적합.
  유형 2 "cliffhanger": 갈등 최고조에서 끊고 "이 다음에 어떻게 됐을까?". 반전이 강한 에피소드에 적합.
  유형 3 "consequence": "OO하면 이렇게 됩니다" 역순 구조. 결과→원인. 인과관계가 뚜렷한 에피소드에 적합.
  유형 4 "before_after": 문제 장면과 해결 장면을 상하 비교. 변화가 극적인 에피소드에 적합.
  유형 5 "emotion_zoom": 캐릭터 감정 클로즈업 + 감성 한 문장. 감정선이 강한 에피소드에 적합.

  선택한 유형과 함께 구체적인 실행 계획(slides_to_use, hook_line, cutoff_slide, result_slide, cause_slides 등)을 적으세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[E. 썸네일 데이터]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- thumbnail 정보를 반드시 포함하세요:
  - text: 썸네일에 들어갈 짧은 텍스트 (3~5글자, 자극적이고 궁금증 유발). 예: "말 끊지 마!", "왜 울어?", "비밀 편지"
  - slide_number: 썸네일 배경으로 쓸 슬라이드 번호 (감정이 가장 강한 장면)
  - emotion: 해당 장면의 감정 (sad/angry/surprised/worried/happy)
  - sub_text: 작은 글씨 (예: "2학년 국어 01단원")

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[F. 퀴즈 슬라이드 연동]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- quiz_questions의 각 문제에 related_slide 필드를 추가하세요.
  해당 문제와 가장 관련 있는 슬라이드 번호(1~10)를 적어서,
  퀴즈 화면에서 해당 장면 이미지를 함께 보여줄 수 있게 하세요.
- quiz_questions는 3문항이며 유형을 배분하세요: 사실확인 1 + 추론 1 + 적용/정서 1.
  answer는 20자 이내의 완결된 1문장으로 쓰세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[F2. 활동지 데이터(activity_sheet v2) 생성]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
독후 활동지에 그대로 렌더링될 데이터입니다. 이야기를 이해한 당신이 직접 만들어야
조사·맞춤법·화자·라벨이 정확합니다. 아래 필드를 activity_sheet 안에 모두 채우세요.

[공통 원칙]
- 초등학교 1학년이 읽고 풀 수 있는 쉬운 어휘. 조사(은/는, 이/가, 을/를)와 맞춤법을 정확히.
- 모든 문장은 이야기 실제 내용에 근거해야 하며, 없는 사실을 지어내지 마세요.
- 힌트에는 정답(정답 낱말·정답 대사)을 절대 노출하지 마세요.

[ox_items] 3개 — {{"text": "이야기 속 사실 문장", "answer": true 또는 false}}
- O·X 비율은 2:1 또는 1:2 (전부 O이거나 전부 X는 금지).
- 거짓(false) 문항은 자연스럽고 비문 없는 문장을 직접 새로 쓰세요. 같은 인물 이름을
  한 문장에 두 번 넣지 마세요(예: "토토와 토토는"은 금지).

[sequence_items] 3개 — {{"label": "A", "text": "이야기 속 사건 1문장", "order": 정답순서(1~3)}}
- 이야기의 초반·중반·후반에서 각 1문장씩. label은 A·B·C, order는 실제 일어난 순서.

[speech_bubbles] 2~3개 — {{"speaker": "캐릭터 실명", "situation": "대사 직전 상황 1문장", "hint": "감정·주제 힌트"}}
- speaker는 반드시 등장인물의 실제 이름. situation은 그 대사를 하기 직전의 상황 서술.
- hint는 정답 대사를 노출하지 말고 감정이나 주제만 알려주세요.

[fill_blanks] 2개 — {{"sentence": "___ 빈칸 1~2개가 든 완성형 문장", "example": "보기 낱말", "answer": "정답"}}
- 완결된 문장 안에 ___ 로 1~2개의 빈칸. example은 아이에게 보여줄 보기 낱말, answer는 정답.

[draw] — {{"prompt": "이야기와 연계된 그리기 발문", "field1_label": "기입란1 라벨", "field2_label": "기입란2 라벨"}}
- field 라벨은 반드시 prompt 주제와 일치시키세요. (발문이 음식이면 "🍽 음식 이름",
  동물이면 "🐾 동물 이름", 초능력이면 "🏷 초능력 이름"처럼.)
- 예: {{"prompt":"내가 갖고 싶은 초능력을 그려보세요!","field1_label":"🏷 초능력 이름","field2_label":"💬 이 힘으로 하고 싶은 일"}}

[wordplay] — {{"anagram_words": ["핵심 낱말 4개"], "consonant_words": ["초성퀴즈 낱말 3개"]}}
- anagram_words: 3~4글자 핵심 낱말 4개(캐릭터 이름은 최대 1개까지만).
- consonant_words: 초성 퀴즈에 쓸 3~4글자 낱말 3개.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[G. 출력 JSON 구조]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{{"meta":{{"grade":{grade},"semester":{ep_info.get('semester',1)},"subject":"{subject}","series":"{series}","unit":"{unit}","unit_title":"{ep_info['unit_title']}","sub_unit":"{ep_info['sub_unit']}","story_title":"동화 제목","youtube_title":"{yt_title_prefix} | 동화 제목","characters":{{"main_1":{{"name":"주인공1 이름","gender":"boy","personality":"성격 한국어","appearance_kr":"한국어 외형 묘사","appearance_en":"English appearance description"}},"main_2":{{"name":"주인공2 이름","gender":"girl","personality":"성격 한국어","appearance_kr":"한국어 외형 묘사","appearance_en":"English appearance description"}},"supporting":{{"teacher":{{"name":"조력자 이름","appearance_en":"English appearance description"}}}}}},"color_palette":{{"primary":"#hex","secondary":"#hex","accent":"#hex","mood":"색감 분위기 한국어 설명"}}}},"slides":[{{"slide_number":0,"type":"cover","composition":"book_cover","color_mood":"cover","text":"제목","image_prompt":"(규칙 C의 7가지 요소를 모두 포함한 영어 프롬프트)","tts_segments":[]}},{{"slide_number":1,"type":"story","composition":"wide_establishing","color_mood":"bright_cheerful","text":"본문","image_prompt":"(규칙 C의 7가지 요소를 모두 포함한 영어 프롬프트)","tts_segments":[{{"speaker":"narrator","voice":"narrator","text":"내레이션","emotion":"감정 지시"}},{{"speaker":"child_boy","voice":"child_boy","text":"대사","emotion":"감정 지시"}}]}},{{"slide_number":2,"type":"story","composition":"(다른 구도)","color_mood":"(적절한 분위기)","text":"...","image_prompt":"...","tts_segments":[...]}},("... 이야기 전개에 맞춰 slide_number 3~N까지 본문 슬라이드를 6~13장 자유롭게 생성하세요. 총 8~15장. ..."),{{"slide_number":"(마지막 번호)","type":"ending","composition":"group_scene","color_mood":"happy_ending","text":"— 끝 —\\n마무리 메시지","image_prompt":"(규칙 C의 7가지 요소를 모두 포함한 영어 프롬프트)","tts_segments":[{{"speaker":"narrator","voice":"narrator","text":"마무리","emotion":"warm, gentle closing"}}]}}],"shorts_strategy":{{"type":"(behavior_quiz/cliffhanger/consequence/before_after/emotion_zoom 중 선택)","type_name":"유형 이름","reason":"이 유형을 선택한 이유","slides_to_use":[5,3,2],"title":"쇼츠 제목","hook_line":"훅 대사 한 문장","cutoff_slide":5,"result_slide":5,"cause_slides":[2,3]}},"thumbnail":{{"text":"3~5글자 자극적 텍스트","slide_number":5,"emotion":"(sad/angry/surprised/worried/happy)","sub_text":"{sub_text_label}"}},"activity_sheet":{{"quiz_questions":[{{"question":"사실확인 질문","answer":"20자 이내 답","related_slide":3}},{{"question":"추론 질문","answer":"20자 이내 답","related_slide":7}},{{"question":"적용/정서 질문","answer":"20자 이내 답","related_slide":10}}],"ox_items":[{{"text":"이야기 속 사실 문장","answer":true}},{{"text":"이야기 속 사실 문장","answer":true}},{{"text":"틀린 사실 문장(자연스러운 비문 없는 문장)","answer":false}}],"sequence_items":[{{"label":"A","text":"초반 사건 1문장","order":1}},{{"label":"B","text":"중반 사건 1문장","order":2}},{{"label":"C","text":"후반 사건 1문장","order":3}}],"speech_bubbles":[{{"speaker":"캐릭터 실명","situation":"대사 직전 상황 1문장","hint":"감정·주제 힌트(정답 대사 미노출)"}},{{"speaker":"캐릭터 실명","situation":"대사 직전 상황 1문장","hint":"감정·주제 힌트"}}],"fill_blanks":[{{"sentence":"___ 빈칸이 든 완성형 문장","example":"보기 낱말","answer":"정답"}},{{"sentence":"___ 빈칸이 든 완성형 문장","example":"보기 낱말","answer":"정답"}}],"draw":{{"prompt":"이야기 연계 그리기 발문","field1_label":"발문 주제에 맞는 라벨1","field2_label":"발문 주제에 맞는 라벨2"}},"wordplay":{{"anagram_words":["핵심낱말1","핵심낱말2","핵심낱말3","핵심낱말4"],"consonant_words":["낱말1","낱말2","낱말3"]}}}}}}

위 JSON 구조의 모든 "..." 부분을 실제 내용으로 채워서 완성된 JSON을 출력하세요.
모든 슬라이드에 대해 composition, color_mood, image_prompt를 완전하게 작성하세요.
image_prompt는 각각 최소 150단어 이상이어야 합니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[H. 단원 정보]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- {grade}학년 {ep_info.get('semester',1)}학기 {subject} {series} {ep_info['unit_title']}
- 중단원/주제: {ep_info['sub_unit']}
- 성취기준: {ep_info['achievement_standard']}
- 동화 방향: {ep_info['story_direction']}"""

    return prompt


def generate_story(ep_num: int = None, ep_info: dict = None) -> dict:
    """Claude Code CLI(claude -p)를 서브프로세스로 호출하여 스토리 JSON을 생성합니다.
    현재 Claude Code 세션 인증을 그대로 사용하므로 API 키 불필요.
    ep_num: EPISODES 리스트 번호 (1~8)
    ep_info: 커스텀 에피소드 딕셔너리 (BSL 등)
    """
    if ep_info is None:
        ep_info = None
        for ep in EPISODES:
            if ep["ep"] == ep_num:
                ep_info = ep
                break
        if ep_info is None:
            print(f"[ERROR] 에피소드 {ep_num}은(는) 존재하지 않습니다. (1~8)")
            sys.exit(1)

    series = ep_info.get("series", "")
    print(f"[INFO] 스토리 생성 시작")
    print(f"       {ep_info.get('grade',2)}학년 {ep_info.get('subject','국어')} {series}")
    print(f"       단원/주제: {ep_info['unit_title']}")
    print(f"       중단원: {ep_info['sub_unit']}")
    print(f"       성취기준: {ep_info['achievement_standard']}")
    print(f"       동화 방향: {ep_info['story_direction'][:80]}...")
    print()

    # 시스템 지시를 프롬프트 앞에 삽입 (claude -p는 별도 system 파라미터 없음)
    system_prefix = (
        "당신은 한국 초등학교 아이들을 위한 동화 작가이자 그림책 아트디렉터입니다.\n"
        "반드시 순수 JSON만 출력하세요. 마크다운 코드블록(```)이나 설명 텍스트를 절대 포함하지 마세요.\n\n"
    )
    full_prompt = system_prefix + build_prompt(ep_info)

    print("[INFO] Claude Code CLI (claude -p) 호출 중...")

    # 최대 3회 재시도
    story = None
    raw_text = ""
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["claude", "-p"],
                input=full_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=600,
                env=_CLAUDE_ENV,
            )
            if result.returncode != 0:
                err_msg = result.stderr.strip()[:300]
                raise RuntimeError(f"claude CLI 종료코드 {result.returncode}: {err_msg}")

            raw_text = result.stdout.strip()
            print(f"[INFO] Claude 응답 수신 완료 (시도 {attempt + 1}, {len(raw_text)} chars)")

            # JSON 마커 제거 (안전장치)
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3].strip()

            story = json.loads(raw_text)
            break
        except json.JSONDecodeError as e:
            print(f"[WARN] JSON 파싱 실패 (시도 {attempt + 1}): {e}")
            if attempt == 2:
                print("[ERROR] 3회 시도 모두 실패. 마지막 응답 저장 후 종료.")
                debug_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "output", f"ep{ep_num:02d}" if ep_num else "debug", "debug_response.txt"
                )
                os.makedirs(os.path.dirname(debug_path), exist_ok=True)
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(raw_text)
                print(f"  디버그 파일: {debug_path}")
                sys.exit(1)
        except Exception as e:
            print(f"[WARN] claude CLI 호출 실패 (시도 {attempt + 1}): {e}")
            if attempt == 2:
                sys.exit(1)

    # 슬라이드 수 검증
    num_slides = len(story.get("slides", []))
    if num_slides < 13 or num_slides > 17:
        print(f"[WARN] 슬라이드 수가 {num_slides}장입니다. (기대: 13~17장)")
    else:
        print(f"[OK] 슬라이드 {num_slides}장 확인")

    # tts_segments 누락 검증 & 자동 보정 (대사를 캐릭터별로 분리)
    import re
    missing_count = 0
    # 캐릭터 이름 → speaker 매핑 구축
    chars = story.get("meta", {}).get("characters", {})
    name_to_speaker = {}

    # characters 배열 구조 지원 (list of {name, gender, ...})
    char_gender = {}  # name.lower() → "child_boy" / "child_girl"
    characters_list = chars if isinstance(chars, list) else []
    if isinstance(characters_list, list):
        for ch in characters_list:
            ch_name = ch.get("name", "").strip()
            ch_gender = ch.get("gender", "")
            if ch_name:
                if ch_gender in ("female", "girl"):
                    char_gender[ch_name.lower()] = "child_girl"
                elif ch_gender in ("male", "boy"):
                    char_gender[ch_name.lower()] = "child_boy"

    # meta.characters dict 구조 처리 (main_1, main_2, supporting)
    main1_name = (chars.get("main_1") or {}).get("name", "")
    main2_name = (chars.get("main_2") or {}).get("name", "")
    main1_gender = (chars.get("main_1") or {}).get("gender", "boy")
    main2_gender = (chars.get("main_2") or {}).get("gender", "girl")
    if main1_name:
        spk = "child_boy" if main1_gender in ("boy", "male") else "child_girl"
        name_to_speaker[main1_name] = spk
        char_gender[main1_name.lower()] = spk
    if main2_name:
        spk = "child_girl" if main2_gender in ("girl", "female") else "child_boy"
        name_to_speaker[main2_name] = spk
        char_gender[main2_name.lower()] = spk
    _supporting = chars.get("supporting") or {}
    _teacher = _supporting.get("teacher") or {} if isinstance(_supporting, dict) else {}
    teacher_name = _teacher.get("name", "") if isinstance(_teacher, dict) else ""
    if teacher_name:
        name_to_speaker[teacher_name] = "teacher"
        char_gender[teacher_name.lower()] = "teacher"

    # supporting 내 다른 캐릭터도 처리
    supporting = chars.get("supporting", {})
    if isinstance(supporting, dict):
        for role_key, role_val in supporting.items():
            if isinstance(role_val, dict):
                s_name = role_val.get("name", "")
                s_gender = role_val.get("gender", "")
                if s_name and s_name not in name_to_speaker:
                    if s_gender in ("female", "girl"):
                        name_to_speaker[s_name] = "child_girl"
                        char_gender[s_name.lower()] = "child_girl"
                    elif s_gender in ("male", "boy"):
                        name_to_speaker[s_name] = "child_boy"
                        char_gender[s_name.lower()] = "child_boy"

    for slide in story.get("slides", []):
        slide_type = slide.get("type", "story")
        segs = slide.get("tts_segments", None)

        if slide_type == "cover":
            if not isinstance(segs, list):
                slide["tts_segments"] = []
            continue

        if not isinstance(segs, list) or len(segs) == 0:
            missing_count += 1
            text = slide.get("text", "")
            if not text:
                slide["tts_segments"] = []
                continue

            # 대사 패턴 분리:
            # 1) 큰따옴표: "대사" 또는 \u201c대사\u201d
            # 2) XML 태그: <child_boy>대사 또는 <narrator>대사
            # 먼저 <speaker>태그를 정규화
            tag_pattern = re.compile(r'<(narrator|child_boy|child_girl|teacher)>\s*')
            if tag_pattern.search(text):
                # 태그 기반 분리
                raw_parts = tag_pattern.split(text)
                segments = []
                current_speaker = "narrator"
                for rp in raw_parts:
                    rp = rp.strip()
                    if not rp:
                        continue
                    if rp in ("narrator", "child_boy", "child_girl", "teacher"):
                        current_speaker = rp
                    else:
                        segments.append({
                            "speaker": current_speaker, "voice": current_speaker,
                            "text": rp, "emotion": "expressive, in-character" if current_speaker != "narrator" else "warm, storytelling tone"
                        })
                        current_speaker = "narrator"
                slide["tts_segments"] = segments if segments else [
                    {"speaker": "narrator", "voice": "narrator",
                     "text": text, "emotion": "warm, storytelling tone"}
                ]
                continue

            parts = re.split(r'(["""\u201c][^"""\u201d]+["""\u201d])', text)
            segments = []
            dialogue_index = 0  # fallback: boy/girl 번갈아 배정 (캐릭터 특정 불가 시)
            # fallback 기준 성별: 등록된 캐릭터 중 첫 번째 boy/girl 우선 사용
            _fallback_speakers = [s for s in name_to_speaker.values() if s in ("child_boy", "child_girl")]
            _fallback_boy = next((s for s in _fallback_speakers if s == "child_boy"), "child_boy")
            _fallback_girl = next((s for s in _fallback_speakers if s == "child_girl"), "child_girl")

            for part in parts:
                part = part.strip()
                if not part:
                    continue

                if part.startswith(('"', '\u201c')) and part.endswith(('"', '\u201d')):
                    # 대사 부분 — 앞 나레이션에서 누가 말하는지 추측
                    dialogue_text = part.strip('""\u201c\u201d ')
                    speaker = None

                    # 1순위: 바로 앞 나레이션에서 캐릭터 이름 찾기 (name_to_speaker 활용)
                    if segments:
                        last_narr = segments[-1].get("text", "")
                        for name, spk in name_to_speaker.items():
                            if name in last_narr:
                                speaker = spk
                                break

                    # 2순위: char_gender에서 대화문 내 캐릭터 이름 직접 탐색
                    if not speaker:
                        for ch_name_lower, ch_spk in char_gender.items():
                            if ch_name_lower in dialogue_text.lower():
                                speaker = ch_spk
                                break

                    if not speaker:
                        # 3순위(최후 fallback): 스토리 캐릭터 성별 패턴 기반 번갈아 배정
                        # boy/girl 교대지만 실제 등록된 캐릭터 성별을 반영
                        speaker = _fallback_boy if dialogue_index % 2 == 0 else _fallback_girl
                        dialogue_index += 1

                    segments.append({
                        "speaker": speaker, "voice": speaker,
                        "text": dialogue_text, "emotion": "expressive, in-character"
                    })
                else:
                    # 나레이션 부분
                    segments.append({
                        "speaker": "narrator", "voice": "narrator",
                        "text": part, "emotion": "warm, storytelling tone"
                    })

            slide["tts_segments"] = segments if segments else [
                {"speaker": "narrator", "voice": "narrator",
                 "text": text, "emotion": "warm, storytelling tone"}
            ]

    if missing_count > 0:
        print(f"[FIX] tts_segments 누락 {missing_count}개 슬라이드 — 대사/나레이션 분리 보정 완료")

    return story


# ── 인도네시아어 동화 생성 ─────────────────────────────────

def build_prompt_id(theme: str = "") -> str:
    """인도네시아어 동화 스토리 프롬프트를 생성합니다."""
    theme_line = f"Tema/judul cerita: {theme}" if theme else "Pilih tema cerita yang menarik dan unik sendiri."
    return f"""Kamu adalah penulis dongeng anak-anak Indonesia yang kreatif dan berbakat.
Buat sebuah dongeng lengkap dalam Bahasa Indonesia untuk anak-anak usia 6-8 tahun (SD kelas 1-2).

{theme_line}

Semua teks cerita, narasi, dan dialog HARUS dalam Bahasa Indonesia yang baik, sederhana, dan ekspresif.
image_prompt HARUS dalam Bahasa Inggris (English).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ATURAN DASAR]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Jumlah slide: 13-17 slide (cover 1 + story 11-15 + ending 1). Buat sebanyak mungkin adegan dinamis.
- Bahasa sederhana, ekspresif, banyak onomatopeia (byur!, krak!, wuss!, dll)
- Pesan moral yang positif (keberanian, persahabatan, kejujuran, dll)
- speaker: narrator, child_boy, child_girl, teacher (gunakan minimal 3 jenis)
- Proporsi: narrator 50-60%, dialog karakter 40-50%
- Jangan gunakan karakter: ..., —, ―, ★, ♪ (gunakan titik dan koma saja)
- JSON murni saja, tanpa markdown atau penjelasan

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[KARAKTER & DUNIA]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Rancang dunia dan karakter yang segar dan orisinal:
- Nama karakter: nama Indonesia atau fantasi yang unik dan lucu
- Bisa hewan, manusia, makhluk fantasi, robot, peri, dll
- Kepribadian yang jelas
- appearance_en: deskripsi visual lengkap dalam bahasa Inggris (species, size, color, outfit, expression)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[KOMPOSISI PER SLIDE]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
composition (jangan 2 slide berturut-turut sama):
book_cover / wide_establishing / medium_two_shot / close_up_face / over_shoulder /
birds_eye / low_angle / silhouette / detail_shot / full_body_action / group_scene / window_frame

color_mood: bright_cheerful / sad_lonely / tense_worried / realization / happy_ending / cover

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ATURAN image_prompt]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
image_prompt HARUS bahasa Inggris, minimal 150 kata, mencakup:
1) Camera angle sesuai composition
2) Aksi karakter yang spesifik
3) Full appearance karakter (salin dari meta.characters.appearance_en)
4) Detail latar: minimal 5 elemen spesifik sesuai dunia cerita
5) Pencahayaan: bright_cheerful=vivid bright / sad_lonely=muted cool / tense_worried=cool shadows / realization=warm golden light / happy_ending=maximum brightness
6) Art style: bright watercolor Indonesian children's picture book illustration, warm tropical colors, joyful atmosphere, award-winning quality
7) "absolutely no text, no speech bubbles, no split screen, single continuous composition, no readable text on any surface"
8) "NEUTRAL to COOL color temperature, no yellow cast"
9) Maksimal 3 karakter jelas per frame

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[tts_segments]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- text: Bahasa Indonesia
- emotion: Bahasa Inggris, panduan akting suara (contoh: "excited, breathless", "whispering nervously", "warm storytelling tone")
- Pisahkan dialog dari narasi
- Minimal 2 segment per slide story

Contoh:
[
  {{"speaker":"narrator","voice":"narrator","text":"Hari itu, langit sangat cerah.","emotion":"warm, gentle storytelling tone"}},
  {{"speaker":"child_girl","voice":"child_girl","text":"Wah, indahnya hari ini!","emotion":"excited, full of wonder"}},
  {{"speaker":"narrator","voice":"narrator","text":"Sari melompat kegirangan sambil tertawa.","emotion":"cheerful, describing joyful action"}}
]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[FORMAT JSON OUTPUT]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{"meta":{{"language":"id","story_title":"Judul Dongeng","youtube_title":"Dongeng Anak | Judul Dongeng","characters":{{"main_1":{{"name":"NamaKarakter1","gender":"girl","species":"jenis","personality":"sifat karakter","appearance_kr":"","appearance_en":"full English visual description"}},"main_2":{{"name":"NamaKarakter2","gender":"boy","species":"jenis","personality":"sifat","appearance_kr":"","appearance_en":"full English visual description"}},"supporting":{{"helper":{{"name":"Nama","role":"peran","appearance_en":"English appearance"}}}}}},"world":{{"setting":"nama dunia","art_style_en":"bright watercolor Indonesian children's picture book, warm tropical colors, joyful atmosphere","bg_elements_en":["elemen1","elemen2","elemen3","elemen4","elemen5"]}},"color_palette":{{"primary":"#hex","secondary":"#hex","accent":"#hex","mood":"deskripsi suasana"}},"gemini_voices":{{"narrator":{{"voice_name":"Kore","speed":0.95}},"child_girl":{{"voice_name":"Puck","speed":1.0}},"child_boy":{{"voice_name":"Fenrir","speed":1.0}},"teacher":{{"voice_name":"Charon","speed":0.9}}}}}},"slides":[{{"slide_number":0,"type":"cover","composition":"book_cover","color_mood":"cover","text":"Judul Dongeng","image_prompt":"(English 150+ words)","tts_segments":[]}},{{"slide_number":1,"type":"story","composition":"wide_establishing","color_mood":"bright_cheerful","text":"Teks narasi Bahasa Indonesia...","image_prompt":"(English 150+ words)","tts_segments":[{{"speaker":"narrator","voice":"narrator","text":"Bahasa Indonesia narasi.","emotion":"warm storytelling"}},{{"speaker":"child_girl","voice":"child_girl","text":"Dialog Bahasa Indonesia.","emotion":"excited"}}]}},...LANJUTKAN SEMUA SLIDE...,{{"slide_number":"N","type":"ending","composition":"group_scene","color_mood":"happy_ending","text":"Penutup.","image_prompt":"(English)","tts_segments":[{{"speaker":"narrator","voice":"narrator","text":"Pesan moral dan penutup.","emotion":"warm, gentle closing"}}]}}],"shorts_strategy":{{"type":"cliffhanger","type_name":"Cliffhanger","reason":"alasan pemilihan","slides_to_use":[5,6,7],"title":"Judul Shorts","hook_line":"Kalimat pembuka yang bikin penasaran","cutoff_slide":6,"result_slide":8,"cause_slides":[3,4]}},"thumbnail":{{"text":"2-4 kata mengejutkan","slide_number":7,"emotion":"surprised","sub_text":"Dongeng Anak Indonesia"}},"activity_sheet":{{"quiz_questions":[{{"question":"Pertanyaan 1?","answer":"Jawaban 1","related_slide":3}},{{"question":"Pertanyaan 2?","answer":"Jawaban 2","related_slide":7}},{{"question":"Pertanyaan 3?","answer":"Jawaban 3","related_slide":10}}]}}}}

Isi SEMUA slide secara lengkap dari slide 0 sampai ending. Jangan disingkat!
Setiap image_prompt minimal 150 kata. Buat cerita yang seru dan berkesan!"""


def generate_story_id(theme: str = "") -> dict:
    """Claude Code CLI(claude -p)를 호출하여 인도네시아어 동화 JSON을 생성합니다."""
    print(f"[INFO] 인도네시아어 동화 생성 시작")
    if theme:
        print(f"       테마: {theme}")
    else:
        print(f"       테마: AI 자유 선택")
    print()

    system_prefix = (
        "You are a creative Indonesian children's story writer.\n"
        "Output ONLY pure JSON. No markdown code blocks, no explanations.\n\n"
    )
    full_prompt = system_prefix + build_prompt_id(theme)

    print("[INFO] Claude Code CLI (claude -p) 호출 중 (인도네시아어 모드)...")
    story = None
    raw_text = ""
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["claude", "-p"],
                input=full_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=600,
                env=_CLAUDE_ENV,
            )
            if result.returncode != 0:
                err_msg = result.stderr.strip()[:300]
                raise RuntimeError(f"claude CLI 종료코드 {result.returncode}: {err_msg}")

            raw_text = result.stdout.strip()
            print(f"[INFO] Claude 응답 수신 완료 (시도 {attempt + 1}, {len(raw_text)} chars)")

            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3].strip()

            story = json.loads(raw_text)
            break
        except json.JSONDecodeError as e:
            print(f"[WARN] JSON 파싱 실패 (시도 {attempt + 1}): {e}")
            if attempt == 2:
                print("[ERROR] 3회 시도 실패.")
                sys.exit(1)
        except Exception as e:
            print(f"[WARN] claude CLI 호출 실패 (시도 {attempt + 1}): {e}")
            if attempt == 2:
                sys.exit(1)

    # 언어 태그 보장
    story.setdefault("meta", {})["language"] = "id"

    # gemini_voices 미포함 시 기본값 추가
    if "gemini_voices" not in story.get("meta", {}):
        story["meta"]["gemini_voices"] = GEMINI_TTS_VOICES

    num_slides = len(story.get("slides", []))
    print(f"[OK] 슬라이드 {num_slides}장 생성")
    if num_slides < 13:
        print(f"[WARN] 슬라이드가 적습니다 ({num_slides}장, 권장 13~17)")

    return story


# ---------------------------------------------------------------------------
# 한국어 자유 주제 동화 생성
# ---------------------------------------------------------------------------
def build_prompt_ko_free(theme: str = "") -> str:
    """한국어 자유 주제 동화 프롬프트를 생성합니다."""
    theme_line = f"동화 주제/테마: {theme}" if theme else "창의적이고 독창적인 주제를 AI가 자유롭게 선택하세요."
    return f"""당신은 한국 초등학교 1~2학년 아이들을 위한 창의적인 동화 작가입니다.
아래 주제로 완성도 높은 한국어 동화를 JSON 형식으로 작성하세요.

{theme_line}

모든 스토리 텍스트·대사는 한국어로, image_prompt는 반드시 영어(English)로 작성하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[기본 규칙]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 슬라이드 13~17장: 표지(cover) 1장 + 본문(story) 11~15장 + 마무리(ending) 1장
- 1~2학년 수준의 쉬운 어휘, 의성어·의태어 풍부하게 사용
- 각 대사에 speaker 태그 필수: narrator, child_boy, child_girl, teacher
- 비율: narrator 50~60%, 캐릭터 대화 40~50%
- tts_segments 규칙:
  - voice 필드는 speaker와 동일하게 작성
  - 남자아이 → child_boy, 여자아이 → child_girl, 어른/교사 → teacher, 나레이터 → narrator
  - emotion은 구체적 연기 지시문 (예: "놀라서 눈이 동그래진 목소리")
  - 모든 story 슬라이드에 최소 2개 이상 tts_segment 포함
  - 대화("")는 반드시 캐릭터 speaker로 분리, narrator로만 채우지 말 것
  - ..., —, ―, ★, ♪ 등 특수문자 사용 금지 (마침표·쉼표만 사용)
- JSON만 출력 (마크다운 코드블록 없이 순수 JSON)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[캐릭터 & 세계관 자유 설계]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
주제에 완전히 어울리는 독창적 캐릭터를 설계하세요:
- main_1, main_2: name(한국어 또는 고유명), gender("boy"/"girl"), species(종류), personality, appearance_kr, appearance_en
- supporting: name, role, appearance_en
- appearance_en: species/size/color/outfit/expression 포함 영어 서술

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[슬라이드 구도 & 색감]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
composition (연속 두 장 동일 금지):
wide_establishing / medium_two_shot / close_up_face / over_shoulder /
birds_eye / low_angle / silhouette / detail_shot / full_body_action / group_scene / window_frame / book_cover

color_mood: bright_cheerful / sad_lonely / tense_worried / realization / happy_ending / cover

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[image_prompt 규칙]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
image_prompt는 반드시 영어, 최소 150단어:
1) composition에 맞는 카메라 앵글
2) 캐릭터의 구체적 행동
3) 캐릭터 외형 전체 (appearance_en에서 복사)
4) 배경 최소 5가지 구체 요소
5) 조명: bright_cheerful=vivid bright / tense_worried=cool shadows / happy_ending=maximum brightness / realization=warm golden light
6) Art style: bright watercolor Korean children's picture book illustration, clean vivid colors, joyful warm atmosphere, award-winning quality
7) "absolutely no text, no speech bubbles, no split screen, single continuous composition"
8) "NEUTRAL to COOL color temperature, no yellow cast"
9) 한 프레임에 명확한 캐릭터 최대 3명

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[JSON 출력 형식]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{"meta":{{"language":"ko","story_title":"동화 제목","youtube_title":"어린이 동화 | 동화 제목","characters":{{"main_1":{{"name":"이름1","gender":"girl","species":"종류","personality":"성격","appearance_kr":"한국어 외형","appearance_en":"English full appearance"}},"main_2":{{"name":"이름2","gender":"boy","species":"종류","personality":"성격","appearance_kr":"한국어 외형","appearance_en":"English full appearance"}},"supporting":{{"helper":{{"name":"이름","role":"역할","appearance_en":"English appearance"}}}}}},"world":{{"setting":"세계관 이름","art_style_en":"bright watercolor Korean children's picture book illustration, clean vivid colors, joyful warm atmosphere","bg_elements_en":["element1","element2","element3","element4","element5"]}},"color_palette":{{"primary":"#hex","secondary":"#hex","accent":"#hex","mood":"색감 분위기 한국어 설명"}}}},"slides":[{{"slide_number":0,"type":"cover","composition":"book_cover","color_mood":"cover","text":"동화 제목","image_prompt":"(English 150+ words)","tts_segments":[]}},{{"slide_number":1,"type":"story","composition":"wide_establishing","color_mood":"bright_cheerful","text":"나레이션 텍스트","image_prompt":"(English 150+ words)","tts_segments":[{{"speaker":"narrator","voice":"narrator","text":"나레이션 텍스트.","emotion":"따뜻하게 이야기하는 톤"}},{{"speaker":"child_girl","voice":"child_girl","text":"대사 텍스트!","emotion":"신나서 들뜬 목소리"}}]}},...모든 슬라이드 완성...,{{"slide_number":"N","type":"ending","composition":"group_scene","color_mood":"happy_ending","text":"마무리 텍스트","image_prompt":"(English)","tts_segments":[{{"speaker":"narrator","voice":"narrator","text":"마무리 나레이션.","emotion":"따뜻하고 포근한 마무리 톤"}}]}}],"shorts_strategy":{{"type":"cliffhanger","type_name":"클리프행어","reason":"선택 이유","slides_to_use":[5,6,7],"title":"Shorts 제목","hook_line":"첫 3초 후킹 대사","cutoff_slide":6,"result_slide":8,"cause_slides":[3,4]}},"thumbnail":{{"text":"2~4자 충격 문구","slide_number":7,"emotion":"surprised","sub_text":"어린이 동화"}},"activity_sheet":{{"quiz_questions":[{{"question":"퀴즈 1?","answer":"정답 1","related_slide":3}},{{"question":"퀴즈 2?","answer":"정답 2","related_slide":7}},{{"question":"퀴즈 3?","answer":"정답 3","related_slide":10}}]}}}}

모든 슬라이드를 slide 0부터 ending까지 빠짐없이 완성하세요. 생략 금지!
각 image_prompt는 최소 150단어로 작성하세요."""


def generate_story_ko_free(theme: str = "") -> dict:
    """Claude Code CLI(claude -p)를 호출하여 한국어 자유 주제 동화 JSON을 생성합니다."""
    print(f"[INFO] 한국어 자유 주제 동화 생성 시작")
    print(f"       테마: {theme if theme else 'AI 자유 선택'}")
    print()

    system_prefix = (
        "당신은 한국 초등학교 1~2학년 아이들을 위한 창의적인 동화 작가입니다.\n"
        "반드시 순수 JSON만 출력하세요. 마크다운 코드블록(```)이나 설명 텍스트를 절대 포함하지 마세요.\n\n"
    )
    full_prompt = system_prefix + build_prompt_ko_free(theme)

    print("[INFO] Claude Code CLI (claude -p) 호출 중 (한국어 자유 모드)...")
    story = None
    raw_text = ""
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["claude", "-p"],
                input=full_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=600,
                env=_CLAUDE_ENV,
            )
            if result.returncode != 0:
                err_msg = result.stderr.strip()[:300]
                raise RuntimeError(f"claude CLI 종료코드 {result.returncode}: {err_msg}")

            raw_text = result.stdout.strip()
            print(f"[INFO] Claude 응답 수신 완료 (시도 {attempt + 1}, {len(raw_text)} chars)")

            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3].strip()

            story = json.loads(raw_text)
            break
        except json.JSONDecodeError as e:
            print(f"[WARN] JSON 파싱 실패 (시도 {attempt + 1}): {e}")
            if attempt == 2:
                print("[ERROR] 3회 시도 실패.")
                sys.exit(1)
        except Exception as e:
            print(f"[WARN] claude CLI 호출 실패 (시도 {attempt + 1}): {e}")
            if attempt == 2:
                sys.exit(1)

    story.setdefault("meta", {})["language"] = "ko"
    num_slides = len(story.get("slides", []))
    print(f"[OK] 슬라이드 {num_slides}장 생성")
    if num_slides < 13:
        print(f"[WARN] 슬라이드가 적습니다 ({num_slides}장, 권장 13~17)")

    return story


def make_output_dirname(meta: dict) -> str:
    """story.json meta에서 출력 폴더명을 생성합니다.

    커리큘럼: 과목_단원_학년_차시_주제_책제목
    자유주제:  주제_책제목
    """
    def clean(s, max_len=20):
        """Windows 파일명 안전 처리: 특수문자·공백 제거"""
        if not s:
            return ""
        s = re.sub(r'[\\/:*?"<>|]', '', str(s))          # Windows 불가 문자
        s = re.sub(r'[\s\.\!\?\,\(\)\[\]·…—―~\-]', '', s)  # 공백·구두점
        return s[:max_len]

    subject    = clean(meta.get("subject", ""), 10)
    grade_num  = meta.get("grade")
    grade      = f"{grade_num}학년" if grade_num else ""
    unit       = clean(meta.get("unit", ""), 10)
    unit_title = clean(meta.get("unit_title", ""), 15)
    sub_unit_raw = meta.get("sub_unit", "")
    story_title  = clean(meta.get("story_title", "동화"), 20)

    # 차시 추출: "1. 말차례를 ..." → cha_si="1차시", 나머지 텍스트 분리
    m = re.match(r'^(\d+)\.\s*(.*)', sub_unit_raw)
    if m:
        cha_si       = f"{m.group(1)}차시"
        sub_unit_text = clean(m.group(2), 15)
    else:
        cha_si        = ""
        sub_unit_text = clean(sub_unit_raw, 15)

    # 단원 표현: 숫자면 "01단원", 아니면 그대로 (예: "봄", "사람들")
    if unit and re.match(r'^\d+$', unit):
        unit_part = f"{unit}단원"
    elif unit:
        unit_part = unit
    else:
        unit_part = unit_title  # unit 없으면 unit_title로 대체

    # 교육과정 vs 자유주제 판단
    is_curriculum = bool(subject and (unit or unit_title) and grade)

    if is_curriculum:
        # 과목_단원_학년_차시_주제_책제목
        parts = [p for p in [subject, unit_part, grade, cha_si, sub_unit_text, story_title] if p]
    else:
        # 자유주제: 주제_책제목
        topic = unit_title or sub_unit_text or "동화"
        parts = [p for p in [topic, story_title] if p]

    return "_".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Claude Code CLI로 동화 스토리 JSON 생성")
    parser.add_argument("--ep",  type=int, default=None, help="에피소드 번호 (1~8)")
    parser.add_argument("--dir", type=str, default=None,
                        help="출력 디렉토리 (BSL/Indonesian 시리즈용, 예: output/bsl03, output/id01)")
    parser.add_argument("--lang", type=str, default="ko",
                        help="언어 코드: ko (기본) 또는 id (인도네시아어)")
    parser.add_argument("--theme", type=str, default="",
                        help="[인도네시아어 전용] 동화 테마/제목 힌트 (생략 시 AI 자유 생성)")
    args = parser.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))

    # ── 언어 감지: --lang id 또는 --dir output/idXX ──────────
    lang = args.lang
    if args.dir and os.path.basename(args.dir.rstrip("/\\")).startswith("id"):
        lang = "id"

    if lang == "id":
        # 인도네시아어 모드
        if not args.dir:
            print("[ERROR] 인도네시아어 모드에서는 --dir 필요 (예: --dir output/id01)")
            sys.exit(1)
        out_dir = os.path.join(base, args.dir)
        story = generate_story_id(theme=args.theme)
    elif lang == "ko" and args.theme and args.dir:
        # 한국어 자유 주제 모드: 스토리 생성 후 폴더명 자동 결정 (주제_책제목)
        story = generate_story_ko_free(theme=args.theme)
        auto_name = make_output_dirname(story.get("meta", {}))
        out_dir = os.path.join(base, "output", auto_name)
        print(f"[INFO] 출력 폴더 자동 결정: output/{auto_name}")
    elif args.dir:
        # BSL 시리즈: 디렉토리 이름으로 BSL_EPISODES 조회
        dir_key = os.path.basename(args.dir.rstrip("/\\"))  # e.g. "bsl03"
        ep_info = BSL_EPISODES.get(dir_key)
        if ep_info is None:
            print(f"[ERROR] BSL_EPISODES에 '{dir_key}' 없음.")
            print(f"  등록된 키: {list(BSL_EPISODES.keys())}")
            print(f"  자유 주제로 생성하려면: --lang ko --theme '테마' --dir {args.dir}")
            sys.exit(1)
        story = generate_story(ep_info=ep_info)
        auto_name = make_output_dirname(story.get("meta", {}))
        out_dir = os.path.join(base, "output", auto_name)
        print(f"[INFO] 출력 폴더 자동 결정: output/{auto_name}")
    elif args.ep is not None:
        story = generate_story(ep_num=args.ep)
        auto_name = make_output_dirname(story.get("meta", {}))
        out_dir = os.path.join(base, "output", auto_name)
        print(f"[INFO] 출력 폴더 자동 결정: output/{auto_name}")
    else:
        # 기본값: ep01
        story = generate_story(ep_num=1)
        auto_name = make_output_dirname(story.get("meta", {}))
        out_dir = os.path.join(base, "output", auto_name)
        print(f"[INFO] 출력 폴더 자동 결정: output/{auto_name}")

    # ── 보이스 자동 선택 ────────────────────────────────────
    if lang == "id":
        # 인도네시아어: Gemini TTS 보이스 (이미 story.json에 포함됨)
        print("\n[INFO] 인도네시아어 모드 — Gemini TTS 보이스 사용")
        if "gemini_voices" not in story.get("meta", {}):
            story["meta"]["gemini_voices"] = GEMINI_TTS_VOICES
    else:
        # 한국어: 보이스 캐스팅은 03_generate_tts.py에서 Typecast 추천 API로 수행
        print("\n[INFO] 한국어 보이스는 TTS 단계에서 Typecast 맥락 캐스팅으로 자동 선택됩니다")

    # 출력 디렉터리 생성
    os.makedirs(out_dir, exist_ok=True)

    # JSON 저장
    out_path = os.path.join(out_dir, "story.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)

    print()
    print(f"[DONE] 스토리 저장 완료: {out_path}")
    print(f"       제목: {story.get('meta', {}).get('story_title', '(제목 없음)')}")
    print(f"       슬라이드: {len(story.get('slides', []))}장")
    print(f"       퀴즈: {len(story.get('activity_sheet', {}).get('quiz_questions', []))}문항")


if __name__ == "__main__":
    main()
