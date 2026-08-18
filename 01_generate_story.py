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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[G. 출력 JSON 구조]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{{"meta":{{"grade":{grade},"semester":{ep_info.get('semester',1)},"subject":"{subject}","series":"{series}","unit":"{unit}","unit_title":"{ep_info['unit_title']}","sub_unit":"{ep_info['sub_unit']}","story_title":"동화 제목","youtube_title":"{yt_title_prefix} | 동화 제목","characters":{{"main_1":{{"name":"주인공1 이름","gender":"boy","personality":"성격 한국어","appearance_kr":"한국어 외형 묘사","appearance_en":"English appearance description"}},"main_2":{{"name":"주인공2 이름","gender":"girl","personality":"성격 한국어","appearance_kr":"한국어 외형 묘사","appearance_en":"English appearance description"}},"supporting":{{"teacher":{{"name":"조력자 이름","appearance_en":"English appearance description"}}}}}},"color_palette":{{"primary":"#hex","secondary":"#hex","accent":"#hex","mood":"색감 분위기 한국어 설명"}}}},"slides":[{{"slide_number":0,"type":"cover","composition":"book_cover","color_mood":"cover","text":"제목","image_prompt":"(규칙 C의 7가지 요소를 모두 포함한 영어 프롬프트)","tts_segments":[]}},{{"slide_number":1,"type":"story","composition":"wide_establishing","color_mood":"bright_cheerful","text":"본문","image_prompt":"(규칙 C의 7가지 요소를 모두 포함한 영어 프롬프트)","tts_segments":[{{"speaker":"narrator","voice":"narrator","text":"내레이션","emotion":"감정 지시"}},{{"speaker":"child_boy","voice":"child_boy","text":"대사","emotion":"감정 지시"}}]}},{{"slide_number":2,"type":"story","composition":"(다른 구도)","color_mood":"(적절한 분위기)","text":"...","image_prompt":"...","tts_segments":[...]}},("... 이야기 전개에 맞춰 slide_number 3~N까지 본문 슬라이드를 6~13장 자유롭게 생성하세요. 총 8~15장. ..."),{{"slide_number":"(마지막 번호)","type":"ending","composition":"group_scene","color_mood":"happy_ending","text":"— 끝 —\\n마무리 메시지","image_prompt":"(규칙 C의 7가지 요소를 모두 포함한 영어 프롬프트)","tts_segments":[{{"speaker":"narrator","voice":"narrator","text":"마무리","emotion":"warm, gentle closing"}}]}}],"shorts_strategy":{{"type":"(behavior_quiz/cliffhanger/consequence/before_after/emotion_zoom 중 선택)","type_name":"유형 이름","reason":"이 유형을 선택한 이유","slides_to_use":[5,3,2],"title":"쇼츠 제목","hook_line":"훅 대사 한 문장","cutoff_slide":5,"result_slide":5,"cause_slides":[2,3]}},"thumbnail":{{"text":"3~5글자 자극적 텍스트","slide_number":5,"emotion":"(sad/angry/surprised/worried/happy)","sub_text":"{sub_text_label}"}},"activity_sheet":{{"quiz_questions":[{{"question":"질문1","answer":"답1","related_slide":3}},{{"question":"질문2","answer":"답2","related_slide":7}},{{"question":"질문3","answer":"답3","related_slide":10}}]}}}}

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
