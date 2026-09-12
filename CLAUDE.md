# AI 동화책 자동 생성 파이프라인

## 프로젝트 개요
초등학교 2학년 대상 한국어 동화 영상을 자동 생성하는 파이프라인.
Gemini(스토리+이미지) + Supertone(TTS) + FFmpeg(영상) 사용.

## 핵심 규칙
- **스토리 생성**: `01_generate_story.py` → **Claude Code CLI** (`claude -p` 서브프로세스) 사용
  - API 키 불필요 — 현재 Claude Code 세션 인증 그대로 사용
  - Gemini/API 키 방식 사용 금지 (01_generate_story.py 한정)
  - 평가/재생성(`01a_evaluate_story.py`)도 Claude (Haiku 평가, Sonnet 재생성)
- TTS: 전 언어 → **Google Gemini TTS 메인** (`gemini-2.5-flash-preview-tts`, 품질 확인됨)
  - 한국어 기본 엔진 = gemini (`TTS_ENGINE_KO`로 변경 가능, `--engine typecast` 선택지 유지)
  - 화자별 보이스+페르소나: narrator=Kore/구연가, child_boy=Fenrir, child_girl=Puck,
    teacher=Charon, adult_female=Gacrux(엄마 역), adult_male=Alnilam — `GEMINI_VOICE_DEFAULTS`
  - 감정 지시는 반드시 **콜론 구문** ("다음 문장을 {지시}으로 읽어줘: {대사}") — 괄호 포맷은 지시문을 읽어버림
  - **Supertone API는 2026-08-31 서비스 종료로 사용 금지**
  - OpenAI TTS 사용 금지
  - 언어는 story.json의 `meta.language`로 자동 감지 (`ko` / `id` / 기타)
- 이미지 생성은 반드시 **Gemini 2.5 Flash Image** 사용 (`gemini-2.5-flash-image`, `GEMINI_IMAGE_MODEL`로 오버라이드 가능)
  - **캐릭터 일관성**: 캐릭터 시트(`characters/`)를 먼저 생성한 뒤, 슬라이드 이미지에 레퍼런스로 첨부 + STRICT 가드 (multicultural-board 패턴)
  - 비활성화: `--no-char-ref`
  - **기본: Batch API** (50% 할인, $0.039 → $0.0195/장, 비동기 처리)
  - `--realtime` 플래그로 즉시 생성 가능 (비용 2배)
  - OpenAI gpt-image-1 사용 금지 (품질 이유로 폐기)
  - API: `google-genai` 라이브러리, `GEMINI_API_KEY` 사용
  - **이미지 비율**: `image_config=ImageConfig(aspect_ratio="16:9", image_size="1K")` 반드시 설정
- 슬라이드 수는 8~15장 자동 결정 (고정 아님)
- timing.json이 단일 진실 소스 (Single Source of Truth)
- 이미지 색감: 누런 톤 금지, 깨끗하고 밝은 자연색
- 인물 수: 한 화면에 또렷한 인물 최대 3명
- TTS 텍스트: `…`, `—`, `―` 등 특수문자 금지 (마침표/쉼표만 사용)

## 퀴즈 섹션 규칙 (2026-08 개편)
- 문제·정답 본문도 narrator TTS로 낭독 (1학년 문해력 배려)
  - `activity_sheet.quiz_questions[i].question/answer` → `quiz_q{i}_body.wav` / `quiz_a{i}_body.wav`
  - 문제 슬라이드 오디오 = 안내 멘트(`quiz_q{i}.wav`) + 본문 낭독(`quiz_q{i}_body.wav`) concat
- 문제 후 카운트다운 5초 (880Hz 비프음). 침묵 대기 금지
- 정답 슬라이드 최소 3초 (본문 낭독 길이 우선)
- body wav가 없는 기존 편은 폴백(기존 안내 멘트만 + 무음 대기)으로 자동 처리

## --dir 인수 지원 스크립트
모든 스크립트에서 `--ep N` 대신 `--dir output/폴더명` 사용 가능 (아래 폴더 목록 참조):
- 02_generate_images.py ✓
- 03_generate_tts.py ✓
- 04_concat_audio.py ✓
- 05_generate_srt.py ✓
- 06_assemble_video.py ✓
- 07b_generate_quiz_slides.py ✓
- 10_generate_thumbnail.py ✓

## 공식 파이프라인 실행 순서 (v3 품질 점검 포함)

에피소드 N을 생성하려면 아래 순서대로 실행:

```bash
# FFmpeg PATH 설정 (Windows)
export PATH="/c/Users/권준구/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin:$PATH"

# 1. 스토리 생성 (Gemini)
python 01_generate_story.py --ep N

# 1a. ★ 스토리 품질 평가 (교육성·재미성·개연성 병렬 LLM) → story_eval.json
python 01a_evaluate_story.py --ep N --auto-improve   # 미달 시 자동 재생성

# 1b. ★ Shorts 구간 분석 (4기준 점수) + 이미지 생성 통합
#     --with-images: Shorts 구간 슬라이드 삭제 후 02_generate_images.py 자동 실행
#     → shorts_plan.json + 전체 이미지(16:9) + Shorts 구간 9:16 이미지 동시 생성
python 01b_analyze_shorts_plan.py --ep N --with-images

# 2a. ★ 이미지 품질 LLM 점검 (할루시네이션·비교육성·텍스트노출·캐릭터·화질)
python 02a_check_images.py --ep N --auto-regen       # 불합격 시 자동 재생성

# 3. TTS 생성 (Typecast/Gemini TTS 언어별 자동)
python 03_generate_tts.py --ep N

# 3a. ★ 나레이션 스크립트 LLM 점검 (화자혼입·언어·연령·흐름·특수문자)
python 03a_check_narration.py --ep N --auto-fix      # 자동 수정 가능 항목 즉시 수정

# 4. 오디오 합치기
python 04_concat_audio.py --ep N

# 5. SRT 자막 생성
python 05_generate_srt.py --ep N

# 6. 활동지 HTML
python 07_generate_worksheet.py --ep N
python 07a_check_worksheet.py --dir output/폴더   # ★ 활동지 QA (불합격 시 사람 검토)

# 7. 퀴즈 슬라이드 PNG (Jua 폰트)
python 07b_generate_quiz_slides.py --ep N

# 7c. ★ 애니 배경분리판 (핵심 6컷: 도입1+전개2+절정2+결말1)
#     TTS와 무관 → 07b·06 사이 언제든 병렬 실행 가능. anim/slide_XX.mp4 생성 시 06이 자동 삽입
python 11_animate_scenes.py --dir output/epNN --limit 6

# 8. Shorts 영상 (Mode A: 9:16 이미지 / Mode B: blur 합성)
python 09b_smart_shorts.py --ep N

# 9. 썸네일 A/B (Jua 폰트)
python 10_generate_thumbnail.py --ep N

# 10. 최종 영상 조립 (1920x1080, 퀴즈 포함)
python 06_assemble_video.py --ep N

# 11. ★ 그림책 PPTX 생성 (1분할: 풀블리드+오버레이, 폰트 임베드)
python 08_generate_book_pptx.py --dir output/epNN --mode 1
# 전 언어·전 콘텐츠 일괄 생성:
# python 08a_batch_book_pptx.py

# 12. ★ 파이프라인 품질 점검 (6영역 100점 채점 + 자동 수정 순환)
python pipeline_inspector.py --ep N --auto-fix --json output/epNN/qa_report.json

# 13. 유튜브 업로드/예약발행 (channel_registry.json 검증 게이트 통과해야 진행됨 — 아래 참고)
python publish_youtube.py --dir output/epNN --channel ko --schedule "..." --yes

# 14. ★★ 썸네일 C 배경분리 액션("사진 액션") — 반드시 13번 업로드 *이후*, 절대 생략 금지
#     10b_batch_thumb_bg.py는 publish_log.json(video_id)이 있는 폴더만 대상으로 잡기 때문에
#     반드시 업로드 이후에 실행해야 함(업로드 전에 돌리면 조용히 스킵되고 아무 오류도 안 남).
#     최근 2회 실제로 이 단계를 빼먹어 신규 에피소드에 thumbnail_c가 누락된 사고가 있었음 —
#     새 에피소드를 만들 때마다 13번 다음에 반드시 세트로 실행할 것.
python 10b_batch_thumb_bg.py --only <에피소드 폴더명 일부>
python 10_generate_thumbnail.py --dir output/epNN --style c
python _push_thumb_c_live.py output/epNN   # publish_log.json의 video_id에 썸네일C 라이브 반영
```

### 품질 점검 스크립트 요약
| 단계 | 스크립트 | 점검 내용 | 자동 수정 |
|------|---------|---------|--------|
| 1a ★ | 01a_evaluate_story.py | 교육성·재미성·개연성 (100점) — Claude Haiku 평가, Claude Sonnet 재생성 | 미달 시 스토리 재생성 |
| 1b ★ | 01b_analyze_shorts_plan.py | 4기준 Shorts 점수 (80점 기준) | --with-images 자동 연계 |
| 2a ★ | 02a_check_images.py | 할루시네이션·비교육성 (100점) | 불합격 이미지 재생성 |
| 3a ★ | 03a_check_narration.py | 화자혼입·언어·흐름 | 특수문자·voice 자동 수정 |
| QA ★ | pipeline_inspector.py | 6영역 종합 (100점) | 순환 자동 수정 |
| 14 ★★ | 10b_batch_thumb_bg.py + 10(--style c) + _push_thumb_c_live.py | 썸네일 C 배경분리("사진 액션") | 업로드 후 자동 적용 필수 — 빠뜨리면 조용히 스킵됨 |

## 업로드 채널 안전장치 (2026-09-12 사고 이후 필수)
- `token_id.json`이 실제로는 한국어 메인 채널로 인증되어 있어서, 인니 채널 업로드가 그대로 본채널에 공개된 사고 발생(에피소드 1개, 즉시 비공개 전환).
- 재발 방지: `publish_youtube.py`는 업로드 직전 `verify_channel()`로 실제 인증된 channel_id를 `channel_registry.json`과 대조하고, 등록 안 됐거나 불일치하면 업로드를 **강제 차단**한다.
- 새 채널(`--channel` 코드)을 처음 쓸 때는 반드시 `channel_registry.json`에 실측 channel_id를 등록한 뒤 사용할 것. 등록 없이 우회 금지.

## 에피소드별 재생성 가이드

### 스토리만 재생성
```bash
rm output/epNN/story.json
python 01_generate_story.py --ep N
```

### 이미지만 재생성 (스토리 유지)
```bash
rm -rf output/epNN/images
python 02_generate_images.py --ep N
```

### TTS만 재생성
```bash
rm -rf output/epNN/audio
python 03_generate_tts.py --ep N
python 04_concat_audio.py --ep N
python 05_generate_srt.py --ep N
```

### 영상만 재조립 (이미지/오디오 유지)
```bash
rm output/epNN/video.mp4
python 06_assemble_video.py --ep N
```

### 전체 재생성
```bash
rm -rf output/epNN
# 위 순서대로 전체 실행
```

## API 키
- .env 파일에 GEMINI_API_KEY, TYPECAST_API_KEY, ELEVENLABS_API_KEY 설정 (OPENAI_API_KEY는 보조)
- .env 파일은 절대 공유 금지

## 에피소드 목록 (2학년 1학기 국어)
| EP | 단원 | 중단원 |
|----|------|--------|
| 1 | 01. 만나서 반가워요! | 말차례를 지키며 대화하기 |
| 2 | 01. 만나서 반가워요! | 친구들에게 자신을 소개하기 |
| 3 | 02. 말의 재미가 솔솔 | 말의 재미 느끼기 |
| 4 | 02. 말의 재미가 솔솔 | 책에 대한 생각이나 느낌 나누기 |
| 5 | 03. 겪은 일을 나타내요 | 꾸며 주는 말을 넣어 문장 쓰고 읽기 |
| 6 | 03. 겪은 일을 나타내요 | 자신의 생각을 담은 일기 쓰기 |
| 7 | 04. 분위기를 살려 읽어요 | 겹받침을 바르게 읽고 쓰기 |
| 8 | 04. 분위기를 살려 읽어요 | 작품을 분위기에 알맞게 읽기 |

## 인도네시아어 동화 파이프라인

```bash
# 1. 스토리 생성 (인도네시아어 자유 동화)
python 01_generate_story.py --dir "output/인도네시아어_자유주제_빛새의비밀_하숲속빛새의비밀" --lang id
# 또는 새 테마 지정
python 01_generate_story.py --dir output/id02 --lang id --theme "petualangan kelinci di hutan"

# 1b. Shorts 구간 분석
python 01b_analyze_shorts_plan.py --dir "output/인도네시아어_자유주제_빛새의비밀_하숲속빛새의비밀"

# 2. 이미지 생성 (16:9 + 9:16 동시)
python 02_generate_images.py --dir "output/인도네시아어_자유주제_빛새의비밀_하숲속빛새의비밀"

# 3. TTS 생성 (자동으로 Gemini TTS 사용)
python 03_generate_tts.py --dir "output/인도네시아어_자유주제_빛새의비밀_하숲속빛새의비밀"

# 4~11. 이후 동일 (--dir에 해당 폴더명 사용)
```

### Gemini TTS 보이스 매핑 (인도네시아어)
| speaker | voice_name | 특성 |
|---------|-----------|------|
| narrator | Kore | 차분한 스토리텔링 |
| child_girl | Puck | 밝고 활기찬 |
| child_boy | Fenrir | 에너지 넘치는 남성 |
| teacher | Charon | 권위있는 어른 |

## 콘텐츠 목록 & 출력 폴더

### 통합교과 (바슬즐/사람들/탐험/마을)
| 학년 | 교과 | 단원/주제 | 동화 제목 | 출력 폴더 |
|------|------|-----------|----------|-----------|
| 2학년 | 자연 | 숲속을 걸어요 | 나리의 꿈속 자연 탐험 | `output/통합교과_자연_2학년_숲속을걸어요_나리의꿈속자연탐험` |
| 2학년 | 봄 | 씨앗을 심어요 | 솔이와 다람쥐의 씨앗 여행 | `output/통합교과_봄_2학년_씨앗을심어요_솔이와다람쥐의씨앗여행` |
| 1학년 | 탐험 | 용기를 내 볼까 | 뽀글이 잠수함의 용감한 탐험 | `output/통합교과_탐험_1학년_용기를내볼까_뽀글이잠수함의용감한탐험` |
| 1학년 | 사람들 | 함께하는 일 | 도토리 왕국의 특별한 생일 잔치 | `output/통합교과_사람들_1학년_함께하는일_도토리왕국의특별한생일잔치` |
| 1학년 | 사람들 | 우리 가족 | 풀잎 둥지 가족의 특별한 비 오는 날 | `output/통합교과_사람들_1학년_우리가족_풀잎둥지가족의특별한비오는날` |
| 2학년 | 마을 | 마을 장터 | 와글와글 장터의 새 친구 | `output/통합교과_마을_2학년_마을장터_와글와글장터의새친구` |
| 1학년 | 탐험 | 무엇을 입고 갈까 | 에코의 탐험복 찾기 | `output/통합교과_탐험_1학년_무엇을입고갈까_에코의탐험복찾기` |
| 2학년 | 마을 | 마을에서 찾아라 | 골목길 친구들의 보물 찾기 | `output/통합교과_마을_2학년_마을에서찾아라_골목길친구들의보물찾기` |
| 1학년 | 사람들 | 특별한 초대 | 아미와 부비의 특별한 초대 | `output/통합교과_사람들_1학년_특별한초대_아미와부비의특별한초대` |
| 1학년 | 학교 | 나란히 놀이 | 말랑이 왕국의 나란히 줄다리기! | `output/통합교과_학교_1학년_나란히놀이_말랑이왕국의나란히줄다리기` |
| 1학년 | 학교 | 발표는 이렇게(12차시) | 두루의 첫 발표 도전! | `output/통합교과_학교_1학년_12차시_발표는이렇게_두루의첫발표도전` |
| 1학년 | 학교 | 어깨동무 내 동무(1차시) | 솔이의 어깨동무 도전! | `output/통합교과_학교_1학년_1차시_어깨동무내동무_솔이의어깨동무도전` |

### 국어
| 학년 | 단원 | 주제 | 동화 제목 | 출력 폴더 |
|------|------|------|----------|-----------|
| 2학년 | 02단원 | 말의 재미 느끼기 | 소리 요정 소솔이의 반짝반짝 모험 | `output/국어_02단원_2학년_말의재미느끼기_소리요정소솔이의반짝반짝모험` |
| 2학년 | 04단원 | 분위기에 맞게 읽기 | 달라도 괜찮아! | `output/국어_04단원_2학년_분위기에맞게읽기_달라도괜찮아` |

### 자유주제
| 언어 | 주제 | 동화 제목 | 출력 폴더 |
|------|------|----------|-----------|
| 한국어 | 세계 기차 여행 | 반점이의 세계 기차 여행 | `output/자유주제_세계기차여행_반점이의세계기차여행` |
| 한국어 | 우주 탐험 | 몽실이와 코코의 신나는 우주 탐험 | `output/자유주제_우주탐험_몽실이와코코의신나는우주탐험` |
| 인도네시아어 | 빛새의 비밀 | 하숲속 빛새의 비밀 | `output/인도네시아어_자유주제_빛새의비밀_하숲속빛새의비밀` |

## 다국어 버전 현황
| 원본 폴더명 | 영어 | 포르투갈어 | 인도네시아어 | 스페인어 |
|------------|------|----------|------------|---------|
| 통합교과_봄_2학년_씨앗을심어요_* | _영어 ✓ | _포르투갈어 ✓ | _인도네시아어 ✓ | _스페인어 ✓ |
| 통합교과_탐험_1학년_용기를내볼까_* | _영어 ✓ | _포르투갈어 ✓ | _인도네시아어 ✓ | _스페인어 ✓ |
| 통합교과_사람들_1학년_함께하는일_* | _영어 ✓ | _포르투갈어 ✓ | _인도네시아어 ✓ | _스페인어 ✓ |
| 통합교과_탐험_1학년_무엇을입고갈까_* | _영어 ✓ | _포르투갈어 ✓ | _인도네시아어 ✓ | _스페인어 ✓ |
| 통합교과_사람들_1학년_특별한초대_* | _영어 ✓ | _포르투갈어 ✓ | _인도네시아어 ✓ | _스페인어 ✓ |
| 통합교과_마을_2학년_마을에서찾아라_* | _영어 ✓ | _포르투갈어 ✓ | _인도네시아어 ✓ | _스페인어 ✓ |
| 자유주제_우주탐험_* | _영어 ✓ | _포르투갈어 ✓ | _인도네시아어 ✓ | _스페인어 ✓ |

### 타국어 버전 생성 규칙
- 번역 스크립트: `translate_multilang.py --src "output/원본폴더명" --lang en` 또는 `--all`
- 이미지: 원본 bsl 폴더에서 자동 복사 (재생성 불필요)
- TTS: Gemini 2.5 Flash TTS (`03_generate_tts_gemini.py`) — 100 req/일 무료 한도
- TTS 폴백 1: ElevenLabs **eleven_v3** (`03_generate_tts_elevenlabs.py`) — 70+ 언어, 표현력 최상 (`ELEVEN_TTS_MODEL`로 v2 전환 가능)
- OpenAI TTS(`03_generate_tts_openai.py`)는 폐기 — 사용 금지
- story.json: `meta.language` 필드 필수 (ko/en/pt/id/es/ja)
- story.json TTS 세그먼트: `"voice"` 필드 사용 (Gemini/ElevenLabs 스크립트 기준)
  - 주의: `03_generate_tts.py`(Typecast/한국어)는 `"speaker"` 필드 사용

## 책 PPTX 생성 (전 언어 지원)

```bash
# 단일 에피소드 (1분할 / 2분할 / 둘 다)
python 08_generate_book_pptx.py --dir output/bsl02 --mode 1
python 08_generate_book_pptx.py --dir output/bsl02 --mode both

# 전 언어·전 콘텐츠 일괄 생성
python 08a_batch_book_pptx.py
python 08a_batch_book_pptx.py --skip-done   # 이미 생성된 것 건너뜀
```

| 모드 | 레이아웃 | 출력 파일 |
|------|---------|---------|
| 1분할 ★ | 풀블리드 이미지 + 하단 반투명 오버레이(높이 동적) + 텍스트 | `book_1분할.pptx` |
| 2분할 | 좌: 이미지 풀 하이트 / 우: 종이색 배경 + 텍스트 | `book_2분할.pptx` |

- 표지: 풀블리드 이미지 + 반투명 밴드 + **폭 꽉 채우는 자동 크기 제목** + 저자(햄찌쌤/Teacher Hami)
- 폰트 임베딩: **Noto Serif KR(제목) + Noto Sans KR(본문)** — 어느 컴에서나 동일 렌더링
- 오버레이 높이 동적 조절: 텍스트 양에 따라 2.8~6.0cm 자동 확장, 초과 시 뒤 세그먼트 제외
- 나레이터: 중앙 정렬 이탤릭 회청색 / 대사: 중앙 정렬 `"..."` 표시
- 언어 자동 감지: `meta.language` → 없으면 폴더명 suffix (`_en`, `_pt`, `_id`, `_es`) 감지
- 색상 팔레트: `meta.color_palette` dict 자동 적용 (없으면 기본 파란색)

## 출력 폴더 명명 규칙

`01_generate_story.py` 실행 시 story.json의 meta 필드로 폴더명을 자동 결정합니다.

| 구분 | 형식 | 예시 |
|------|------|------|
| 교육과정 | `과목_단원_학년_차시_주제_책제목` | `국어_01단원_2학년_1차시_말차례를지키며대화하기_준우야내말좀들어줘` |
| 교육과정(단원이 단어) | `과목_단원명_학년_주제_책제목` | `통합교과_봄_2학년_씨앗과식물_솔이와다람쥐의씨앗여행` |
| 자유주제 | `주제_책제목` | `세계기차여행_반점이의세계기차여행` |

- `--ep N` / `--dir output/bslXX` / `--lang ko --theme ... --dir ...` 모두 자동 적용
- 생성 후 `[INFO] 출력 폴더 자동 결정: output/XXX` 로 경로 출력됨
- 후속 스크립트는 `--dir output/XXX` 에 해당 폴더명을 사용

## 주요 산출물 (output/폴더명/)
- `story.json` — 스토리 데이터 (shorts_strategy, thumbnail 포함)
- `images/` — 슬라이드 PNG (1536x1024)
- `audio/` — TTS WAV + timing.json + 퀴즈/Shorts TTS
- `quiz/` — 퀴즈 슬라이드 PNG (1920x1080)
- `subtitles.srt` — SRT 자막
- `video.mp4` — 최종 본편 영상 (1920x1080)
- `shorts.mp4` — YouTube Shorts (1080x1920)
- `thumbnail_a.png`, `thumbnail_b.png` — 썸네일 A/B
- `worksheet.html` — 활동지

## 폰트
- 퀴즈/썸네일: Jua (주아) 폰트 사용
- assets/fonts/Jua-Regular.ttf (없으면 자동 다운로드)
- 자막/영상: Malgun Gothic (시스템 폰트)

## 업로드·운영 정책 (2026-08 확정)
- 공개 주기: 주 1~2편, publish_youtube --schedule 로 예약 공개. 대량 동시 공개 금지
- 타이밍: 해당 단원 진도 1~2주 전 공개 (2학기 하루·상상 = 9~11월)
- Shorts: 본편 요약형 제작 중단. --shorts는 명시 요청 시에만.
  (신규 쇼츠는 15~20초 자체 완결 '그림 수수께끼' 포맷 확정 후 재개 — 별도 기획)
- 성공 지표: 구독자·조회수 아님. "단원 재생목록의 교실 재생"(트래픽 소스: 외부/직접 유입)
  분기 1회 _channel_audit.py로 점검
- 유통: 신규 단원 완성 시 인디스쿨 게시(단원 재생목록 + 통합 Drive 폴더 링크)가 공개 절차의 마지막 단계
