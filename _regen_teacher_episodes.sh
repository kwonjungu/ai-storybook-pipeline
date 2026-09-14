#!/bin/bash
set -e
export PATH="/c/Users/권준구/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin:$PATH"
EPS=(
  "통합교과_세상을바꿀초능력이생긴다면38_1학년_함께골라요_삐요와토토별똥별초능력"
  "통합교과_하늘의하루2223p_1학년_함께골라요_삐요와토토하늘의색을세어봐요"
  "통합교과_물건이악기가된다면3637p_1학년_함께골라요_통통이와두리의둥둥팅팅음악회"
  "통합교과_하루세번3637p_1학년_함께골라요_까까와냠냠의골고루하루"
  "통합교과_하루의리듬4041p_1학년_함께골라요_통통이와짤랑이의하루리듬"
  "통합교과_하루저금통3031p_1학년_함께골라요_삐요와토토의반짝반짝하루저금통"
)
for ep in "${EPS[@]}"; do
  echo "===================== $ep ====================="
  python 03_generate_tts.py --dir "output/$ep"
  python 04_concat_audio.py --dir "output/$ep"
  python 05_generate_srt.py --dir "output/$ep"
  python 06_assemble_video.py --dir "output/$ep"
  echo "----- $ep 완료 -----"
done
echo "ALL_DONE"
