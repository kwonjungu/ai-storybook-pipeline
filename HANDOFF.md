# 인수인계 — 동화 시리즈 (2026-09-13 갱신)

작업 폴더: `C:\Users\권준구\Desktop\AIarea\동화만들기 프로젝트-20260403T101321Z-1-001\동화만들기 프로젝트`
GitHub: kwonjungu/ai-storybook-pipeline

## 채널 현황

| 코드 | 채널 | channel_id | 상태 |
|------|------|-----------|------|
| ko | 햄찌와 떠나는 동화 여행 | UCoLLxrXQFYUaJvIzKTSGw8w | 운영 중 (공개 41편+) |
| en | HAMZZI (@HAMZZI-g4m) | UC_JAT6vjJoDtwJ5eRqjdJdQ | 2026-09-13 운영 시작 |
| id | **미개설** | - | 채널 개설 + `_auth_setup_channel.py id --register` 필요 |

### 사람이 해야 하는 일 (스크립트로 대체 불가)
1. **인니 채널 개설 + 인증** — 유튜브에서 브랜드 채널 생성 후
   `python _auth_setup_channel.py id` → 표시된 채널 확인 → `--register` 로 등록.
   등록 전에는 `verify_channel()`이 업로드를 막는다(2026-09-12 오업로드 사고 방지).
2. **HAMZZI 전화 인증** — https://www.youtube.com/verify
   신규 채널은 인증 전까지 맞춤 썸네일이 403. 인증 후 `python _push_thumb_en.py` 한 번이면
   이미 올라간 영어 영상 전체에 썸네일이 소급 적용된다.

## 2026-09-12 밤 ~ 09-13 진행

### 한국어 (예약 발행)
| 예약일 | 제목 | video_id |
|--------|------|----------|
| 9/15 | 나르미의 커다란 선물 상자 | 9yEoPaDgvFQ |
| 9/16 | 수도꼭지를 잠그면 | CILn9n-CTXM |
| 9/17 | 삐요와 토토의 소중한 약속 | 5JmmFt3ML7I |
| 9/18 | 콩콩이와 방울이의 약속 놀이 | _7K8iGJ1Eb4 |
| 9/19 | 반짝이와 꺼꺼의 반짝반짝 절약 마을 | b-0v3pIUxm8 |
| 9/20 | 파도와 조개, 바다를 부탁해 | (09-13 재개분) |

- 9/21~9/24 4편(알알이와미세 / 나무를위한약속 / 햇살이와그늘이 / 냠냠이와우물우물이)은
  `_pipeline_queue.txt` 에 대기. `_start_ko_queue_after_en.sh` 가 영어 배치 종료를 감지하면
  자동으로 디스패처를 띄운다(Typecast 직렬 규칙 때문에 동시 실행 금지).

### 영어 (HAMZZI)
- `run_en_batch.py` — 상상 단원 10편. 1편 즉시 공개, 나머지 화·목 09:00 예약.
- 1호: https://youtu.be/80AMXhx--Pw (Piyo and Toto's Amazing Egg Hunt)
- TTS는 Typecast ssfm-v30 `language=eng` — 한국어판과 같은 캐릭터 보이스. 실측 품질 양호.
- **이름 표기 주의**: `translate_multilang` 이 번역 전에 라틴 표기로 치환한다.
  삐요=Piyo / 토토=Toto 고정(FIXED_NAME_ROMAN), 설명형 조연은 의미 번역(까치 어미=Mother Magpie).
  이 경로를 안 타면 "Ppiyo"가 나오고 TTS가 "Peep-Peep-O"라고 읽는다.

### 인도네시아어
- 채널이 없어 업로드 불가 → `run_id_sangsang_batch.py --no-upload` 로 **제작만** 선행 중.
- 채널 등록 후 `--no-upload` 빼고 재실행하면 제작분부터 이어서 업로드된다.
- TTS는 Gemini(무료 100req/일, 편당 70~80req) → 하루 1편이 사실상 한계.

### teacher 보이스 재캐스팅 (재업로드 대기)
`_audit_voice_gender.py` 로 'teacher' 화자가 전부 Hyunseung(젊은 남성)인 걸 발견.
'부엉 할머니', '포근 아줌마' 배역까지 남성 목소리였음 → 6편 재캐스팅 + 영상 재조립 완료(로컬).

| 에피소드 | 배역 | 새 보이스 | 구버전 |
|---------|------|----------|--------|
| 별똥별 초능력 | 부엉 할아버지 | Ilho | rlz7ktbysXY |
| 하늘의 하루 | 올빼미 할아버지 부엉 | Ilho | mtr9rR2Er9c |
| 둥둥팅팅 음악회 | 포포 아저씨 | Hakchul | ZLLDQbOsDS0 |
| 하루 세 번 | 포근 아줌마 | Seohyeon | vHyeAcXF-Us |
| 하루의 리듬 | 다온 선생님 | Hakchul | frQijSmd9eY |
| 하루 저금통 | 부엉 할머니 | Emma | N_TNZkz88eA |

```bash
python _reupload_revoiced.py --dry-run   # 재생목록·구버전 확인만
python _reupload_revoiced.py             # 업로드 -> 재생목록 교체 -> 구버전 private -> publish_log 갱신
```
- 유튜브 일일 업로드 쿼터(기본 10,000 units, 업로드 1건 = 1,600)에 걸리면 자동 중단되고,
  다음 날 재실행 시 남은 편부터 이어진다.

## 운영 스크립트 정리
| 스크립트 | 용도 |
|---------|------|
| `_run_full_pipeline.sh` | 스토리 있는 폴더를 예약발행까지 전체 처리 |
| `_resume_pipeline.sh` | **중단된 편 재개 전용** (썸네일→조립→업로드만. 01a/01b/03을 다시 안 태움) |
| `_pipeline_dispatcher.sh` | `_pipeline_queue.txt` 를 한 편씩 직렬 처리 |
| `_start_ko_queue_after_en.sh` | 영어 배치 종료를 기다렸다 한국어 큐 시작 |
| `run_en_batch.py` / `run_id_*_batch.py` | 언어별 배치 (`--limit`, `--no-upload`) |
| `_auth_setup_channel.py` | 새 언어 채널 인증 + 레지스트리 등록 |
| `_push_thumb_en.py` | 영어 채널 썸네일 소급 적용(전화 인증 후) |
| `_reupload_revoiced.py` | 재캐스팅본 재업로드 + 재생목록 교체 + 구버전 비공개 |

## 변함없는 주의점
- **중단된 편을 `_run_full_pipeline.sh`로 재개하지 말 것** — 01a가 스토리를 재생성하고 01b가
  이미지를 다시 사고 03이 TTS를 다시 태운다. 재개는 `_resume_pipeline.sh`.
- TTS(03)는 직렬. 한국어·영어 모두 Typecast를 쓰므로 두 배치를 동시에 돌리지 말 것.
- 썸네일 C는 반드시 **업로드 이후**(publish_log.json의 video_id가 있어야 10b가 대상으로 인식).
- detached 실행은 `python -u`, 네트워크 루프엔 재시도.
- 유튜브 영상은 파일 교체 불가 → 새 업로드 + 구버전 private + 재생목록 교체.
