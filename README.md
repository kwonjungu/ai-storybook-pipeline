# AI 동화책 자동 생성 파이프라인

초등학교 저학년 대상 **AI 동화 영상**을 자동으로 생성하는 파이프라인입니다.

스토리 생성 → 이미지 생성 → TTS 음성 → 영상 조립까지 한 번에 처리합니다.

## 파이프라인 흐름

```
story.json → 이미지(PNG) → TTS(WAV) → 자막(SRT) → 영상(MP4)
                                                    ├── Shorts(9:16)
                                                    ├── 썸네일
                                                    ├── 활동지(HTML)
                                                    └── 그림책(PPTX)
```

| 단계 | 스크립트 | 엔진 | 비용 |
|------|---------|------|------|
| 스토리 생성 | `01_generate_story.py` | Claude Code CLI | 무료 |
| 스토리 평가 | `01a_evaluate_story.py` | Claude API | 소량 |
| Shorts 분석 | `01b_analyze_shorts_plan.py` | Claude API | 소량 |
| **이미지 생성** | `02_generate_images.py` | **Gemini 2.5 Flash (Batch)** | **$0.0195/장** |
| 이미지 점검 | `02a_check_images.py` | Gemini Vision | 소량 |
| TTS (한국어) | `03_generate_tts.py` | Supertone API | 소량 |
| TTS (다국어) | `03_generate_tts_gemini.py` | Gemini TTS | 무료 |
| 오디오 합치기 | `04_concat_audio.py` | FFmpeg | 무료 |
| 자막 생성 | `05_generate_srt.py` | timing.json 기반 | 무료 |
| 영상 조립 | `06_assemble_video.py` | FFmpeg | 무료 |
| 활동지 | `07_generate_worksheet.py` | HTML 생성 | 무료 |
| 퀴즈 슬라이드 | `07b_generate_quiz_slides.py` | Pillow | 무료 |
| 그림책 PPTX | `08_generate_book_pptx.py` | python-pptx | 무료 |
| Shorts 영상 | `09b_smart_shorts.py` | FFmpeg | 무료 |
| 썸네일 | `10_generate_thumbnail.py` | Pillow | 무료 |

## 설치

### 1. Python 패키지

```bash
pip install google-genai python-dotenv python-pptx Pillow requests
```

### 2. FFmpeg

```bash
# Windows
winget install ffmpeg

# macOS
brew install ffmpeg

# Linux
sudo apt install ffmpeg
```

### 3. 폰트 (자동 다운로드 또는 수동 설치)

`assets/fonts/` 폴더에 아래 폰트를 넣으세요 (없으면 일부 스크립트가 자동 다운로드):

- [Jua (주아)](https://fonts.google.com/specimen/Jua) — 퀴즈/썸네일용
- [Noto Sans KR](https://fonts.google.com/noto/specimen/Noto+Sans+KR) — 그림책 본문
- [Noto Serif KR](https://fonts.google.com/noto/specimen/Noto+Serif+KR) — 그림책 제목

### 4. API 키 설정

```bash
cp env.example .env
```

`.env` 파일을 열고 실제 API 키를 입력하세요:

| 키 | 용도 | 발급처 |
|----|------|--------|
| `GEMINI_API_KEY` | 이미지 생성 + TTS | [Google AI Studio](https://aistudio.google.com) |
| `OPENAI_API_KEY` | STT 등 보조 용도 | [OpenAI Platform](https://platform.openai.com/api-keys) |
| `SUPERTONE_API_KEY` | 한국어 TTS | [Supertone](https://supertone.ai) |
| `ELEVENLABS_API_KEY` | 다국어 TTS 폴백 | [ElevenLabs](https://elevenlabs.io) |

> **주의**: `.env` 파일은 `.gitignore`에 포함되어 GitHub에 올라가지 않습니다.

## 사용법

### 에피소드 생성 (전체 파이프라인)

```bash
# 1. 스토리 생성
python 01_generate_story.py --ep 1

# 2. 스토리 평가 & 자동 개선
python 01a_evaluate_story.py --ep 1 --auto-improve

# 3. 이미지 생성 (기본: 배치 모드, 50% 할인)
python 02_generate_images.py --ep 1
# 급할 때: python 02_generate_images.py --ep 1 --realtime

# 4. TTS → 오디오 합치기 → 자막
python 03_generate_tts.py --ep 1
python 04_concat_audio.py --ep 1
python 05_generate_srt.py --ep 1

# 5. 최종 영상 조립
python 06_assemble_video.py --ep 1
```

### 디렉터리 지정 모드

```bash
python 02_generate_images.py --dir output/통합교과_봄_2학년_씨앗을심어요_솔이와다람쥐의씨앗여행
```

### 다국어 버전

```bash
# 번역
python translate_multilang.py --src "output/원본폴더" --lang en  # 영어
python translate_multilang.py --src "output/원본폴더" --all      # 전 언어

# 다국어 TTS
python 03_generate_tts_gemini.py --dir "output/폴더_영어"
```

## 출력물

| 파일 | 설명 |
|------|------|
| `story.json` | 스토리 데이터 |
| `images/*.png` | 슬라이드 이미지 (1536x1024) |
| `audio/*.wav` | TTS 음성 파일 |
| `video.mp4` | 최종 영상 (1920x1080) |
| `shorts.mp4` | YouTube Shorts (1080x1920) |
| `thumbnail_a/b.png` | 썸네일 A/B 버전 |
| `worksheet.html` | 독후 활동지 |
| `book_1분할.pptx` | 그림책 PPTX |

## 1편 예상 비용

| 항목 | 비용 |
|------|------|
| 스토리 (Claude) | ₩0 |
| 이미지 12장 (Gemini Batch) | ~₩350 |
| TTS 6분 (Supertone) | ~₩200 |
| FFmpeg + 조립 | ₩0 |
| **합계** | **~₩550** |

## 라이선스

이 프로젝트는 교육 목적으로 제작되었습니다.
