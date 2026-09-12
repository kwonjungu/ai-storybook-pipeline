# 인수인계 — 통합교과 동화 시리즈 (2026-08-22 하루단원 완료)

작업 폴더: `C:\Users\권준구\Desktop\AIarea\동화만들기 프로젝트-20260403T101321Z-1-001\동화만들기 프로젝트`
GitHub: kwonjungu/ai-storybook-pipeline / 유튜브 채널: 햄찌와 떠나는 동화 여행 (token_ko.json)

## 완료 현황 — 하루단원 11주제 + 상상 초능력 전편 업로드 완료 ✅
주인공을 삐요·토토(간판)와 신규 콤비로 **교차**해 식상함 방지. 전편 **애니 배경분리판**.

| 코드 | 제목 | 주인공 | 단원 | YouTube |
|------|------|--------|------|---------|
| bsl17 | 하늘의 하루 | 삐요·토토 | 하루 | mtr9rR2Er9c |
| bsl18 | 달팽이의 하루 | 신규 느리·바지런 | 하루 | 8xoTRqv0dyc |
| bsl19 | 초능력 슈퍼히어로 | 삐요·토토 | 상상 | rlz7ktbysXY |
| bsl20 | 건강한 하루 | 신규 팔팔이·뒹굴 | 하루 | DaaedWAELw4 |
| bsl21 | 마음의 하루 | 신규 무지·포근 | 하루 | 6jCQTnIc3yE |
| bsl22 | 하루 저금통 | 삐요·토토 | 하루 | N_TNZkz88eA |
| bsl23 | 하루의 시작 | 신규 부엉·꼬꼬 | 하루 | F6E_61IUxTY |
| bsl24 | 모두의 하루 | 삐요·토토 | 하루 | mBeU965_sa0 |
| bsl25 | 하루 세 번 | 신규 까까·냠냠 | 하루 | vHyeAcXF-Us |
| bsl26 | 해야 해야 나오너라 (그림자밟기) | 삐요·토토 | 하루 | iiCGBDdLj4E |
| bsl27 | 하루의 리듬 | 신규 통통·짤랑 | 하루 | frQijSmd9eY |

- **하루단원 재생목록**: PLbfFBJVMkIK0 (10편) / **상상단원**: PLD7saDT0aReU (초능력 포함 10편)
- 전편 활동지·PPT Drive 링크 정상(하늘·달팽이는 `fix_drive_links.py`로 사후 보정 완료)

## 이번 세션 파이프라인 개선 (전부 코드 반영)
1. **애니 배경분리 (11_animate_scenes.py)**: 기존 inpaint는 캐릭터 자리에 흔적이 남음 → `bg_regenerate_clean()`으로 '캐릭터만 제거한 동일 배경'을 Gemini가 재생성(흔적 없음). 실패 시 inpaint 폴백. 핵심 4컷 자동 선정.
2. **QA 시트대조 (02a_check_images.py)**: `characters/main_1,2.png`를 Vision에 함께 첨부해 슬라이드 캐릭터가 시트 대비 '색·무늬·형태 확 달라짐'인지 대조(`build_character_gate(has_sheets)`). **실제 오류 포착 성공**(저금통 병아리중복, 모두의하루 삐요누락). 단 **오탐 여전 → 불합격분은 사람이 이미지 육안 최종판단** 필수.
3. **조연 시트화 (02_generate_images.py)**: supporting에 appearance_en 있으면 `supporting_*.png` 시트 자동 생성. `_refs_for_slide()`가 image_prompt+slide 나레이션까지 어절 매칭하도록 개선(한글 조연명도 첨부됨).
4. **활동지 로직 (07_generate_worksheet.py)** 다수 수정:
   - OX 거짓문항 이름교체 후 **조사 교정**(`_fix_josa`: 포근가→포근이)
   - **말풍선 화자 매핑** 버그 수정(`child_boy=main_1` 고정 가정 → `_speaker_name_map`이 대사 속 상대 이름으로 화자 추론)
   - 그리기 폴백 문구/조사, **매칭 종중복 제외**(부엉·엄마부엉이 둘다 올빼미 → 성격/제외), 정답란 25→38자, 별명 trait 첫절+조사어절 제거

## 파이프라인 표준 순서 (에피소드당)
```
01_generate_story --dir output/bslNN → 01a_evaluate(--auto-improve)
→ [Opus검증: 슬라이드연속·speaker표준·species/appearance_en·퀴즈정답·특수문자·열린질문]
→ 삐요토토는 기존편 characters/main_1,2.png 복사 / 신규는 02가 새 시트 생성
→ 01b_analyze_shorts_plan → 02_generate_images(배치) → 02a_check_images(사람 최종판단)
→ 11_animate_scenes(핵심4컷, 배경분리) ★
→ 03_generate_tts(직렬큐) → 04 → 05 → 07 → 07b → 09b → 10 → 06_assemble_video → 08 --mode 1
→ [Fable에이전트 활동지 PDF 점검] → publish_youtube --yes → 재생목록 추가
```
- **Shorts 업로드 중단(2026-08 정책, CLAUDE.md 우선)**: `--shorts`는 명시 요청 시에만. bsl26·bsl27은 본편만 업로드함
- **애니(11)·조립(06)은 TTS와 무관 → TTS 순서 기다리는 동안 애니 미리 병렬 생성하면 후반부 단축**

## 핵심 설정·주의점
- **TTS**: `TTS_ENGINE_KO=typecast`. 표준 캐스팅=내레이터 Mrs.Claus·삐요/child_boy Oliver·토토/child_girl Miu·성인남 Tim·성인여 Bono·teacher Hyunseung. **직렬 큐**(편별 03 동시 금지)
- **이미지 모델**: `GEMINI_IMAGE_MODEL=gemini-2.5-flash-image` (프로 3.1 금지). 배치 $0.0195/장. 배치 SUCCEEDED여도 1~2장 저장 누락 가능 → 누락분만 `--realtime` 재생성(존재분 skip)
- **이미지 생성 에이전트가 배치 폴링 중 rest**해도 python 폴링 프로세스는 살아 저장 진행. `tasklist | grep python`·`client.batches.list()`로 확인
- **업로드**: 신규는 `--no-drive` 빼고 실행(Drive 활동지·PPT + 설명란 링크 자동). 재업로드는 새 업로드+`videos().update`로 구버전 private. `--no-drive`로 올린 건 `fix_drive_links.py --dir`로 사후 보정
- **비용 정책**: Claude토큰·Opus에이전트 자유 / 유료 API(이미지·TTS)만 절약
- **detached 실행**: `python -u`, 네트워크 루프 SSL순단 잦음 → 재시도 필수

## 남은 후속(선택)
- 하루/상상 단원 다국어(en/pt/id/es) 확장 (translate_multilang.py, 이미지 재사용)
- 삐요토토 기존편 병아리 손/도구 오류 점검(쓰기 장면)
