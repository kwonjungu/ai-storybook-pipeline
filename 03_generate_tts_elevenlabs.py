#!/usr/bin/env python3
"""
03_generate_tts_elevenlabs.py — ElevenLabs TTS 음성 생성 (다국어)
모델: eleven_v3 (기본, 70+ 언어·표현력 최상) / eleven_multilingual_v2 (환경변수로 전환)
  ELEVEN_TTS_MODEL=eleven_multilingual_v2 python 03_generate_tts_elevenlabs.py ...
사용법:
  python 03_generate_tts_elevenlabs.py --dir output/bsl02_id
  python 03_generate_tts_elevenlabs.py --dir output/bsl02_es
"""
import argparse, io, json, os, sys, time, wave
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import requests
from dotenv import load_dotenv
load_dotenv()

ELEVEN_API_KEY = os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVEN_API_KEY")
if not ELEVEN_API_KEY:
    print("[ERROR] ELEVENLABS_API_KEY가 .env에 없습니다."); sys.exit(1)

ELEVEN_MODEL    = os.getenv("ELEVEN_TTS_MODEL", "eleven_v3")
ELEVEN_BASE_URL = "https://api.elevenlabs.io/v1"
# eleven_v3는 voice_settings의 세밀 stability(0.45 등)·speed를 지원하지 않음
#   → v3 계열이면 voice_settings 생략(서버 기본값), v2 계열이면 기존 설정 유지
ELEVEN_IS_V3    = ELEVEN_MODEL.startswith("eleven_v3") or ELEVEN_MODEL.startswith("eleven_ttv_v3")
SILENCE_SAME    = 0.2
SILENCE_CHANGE  = 0.5
SILENCE_SLIDE   = 1.0
COVER_DUR       = 3.0

DEFAULT_ELEVEN_VOICES = {
    "narrator":        {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel",  "stability": 0.5,  "similarity_boost": 0.75},
    "main_1":          {"voice_id": "MF3mGyEYCl7XYWbV9V6O", "name": "Elli",    "stability": 0.5,  "similarity_boost": 0.75},
    "main_2":          {"voice_id": "ErXwobaYiN019PkySvjV",  "name": "Antoni",  "stability": 0.5,  "similarity_boost": 0.75},
    "wise_tree":       {"voice_id": "VR6AewLTigWG4xSOukaG",  "name": "Arnold",  "stability": 0.6,  "similarity_boost": 0.80},
    "child_girl":      {"voice_id": "MF3mGyEYCl7XYWbV9V6O",  "name": "Elli",   "stability": 0.5,  "similarity_boost": 0.75},
    "child_boy":       {"voice_id": "ErXwobaYiN019PkySvjV",   "name": "Antoni", "stability": 0.5,  "similarity_boost": 0.75},
    "teacher":         {"voice_id": "VR6AewLTigWG4xSOukaG",   "name": "Arnold", "stability": 0.6,  "similarity_boost": 0.80},
    "supporting":      {"voice_id": "EXAVITQu4vr4xnSDxMaL",  "name": "Bella",  "stability": 0.5,  "similarity_boost": 0.75},
    "woodland_spirit": {"voice_id": "EXAVITQu4vr4xnSDxMaL",  "name": "Bella",  "stability": 0.55, "similarity_boost": 0.80},
    "dream_goblin":    {"voice_id": "yoZ06aMxZJJ28mfd3POQ",   "name": "Sam",    "stability": 0.45, "similarity_boost": 0.70},
}
QUIZ_TTS = {
    "id": {"quiz_intro":"Saatnya kuis!","quiz_q1":"Pertanyaan pertama!","quiz_q2":"Pertanyaan kedua!","quiz_q3":"Pertanyaan ketiga!","quiz_a1":"Benar sekali!","quiz_a2":"Benar sekali!","quiz_a3":"Benar sekali!"},
    "es": {"quiz_intro":"Es hora del quiz!","quiz_q1":"Pregunta uno!","quiz_q2":"Pregunta dos!","quiz_q3":"Pregunta tres!","quiz_a1":"Correcto!","quiz_a2":"Correcto!","quiz_a3":"Correcto!"},
    "en": {"quiz_intro":"Quiz time!","quiz_q1":"Question one!","quiz_q2":"Question two!","quiz_q3":"Question three!","quiz_a1":"Correct!","quiz_a2":"Correct!","quiz_a3":"Correct!"},
    "pt": {"quiz_intro":"Hora do quiz!","quiz_q1":"Pergunta um!","quiz_q2":"Pergunta dois!","quiz_q3":"Pergunta tres!","quiz_a1":"Correto!","quiz_a2":"Correto!","quiz_a3":"Correto!"},
}

LANG_SPEED = {"ko": 1.0, "en": 1.0, "id": 0.92, "es": 1.0, "pt": 0.93, "ja": 0.95}

def eleven_tts(voice_id, text, stability=0.5, similarity=0.75, speed=1.0, retries=3):
    url = f"{ELEVEN_BASE_URL}/text-to-speech/{voice_id}"
    headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    payload = {"text": text, "model_id": ELEVEN_MODEL}
    if not ELEVEN_IS_V3:
        voice_settings = {"stability": stability, "similarity_boost": similarity}
        if speed != 1.0:
            voice_settings["speed"] = speed
        payload["voice_settings"] = voice_settings
    for i in range(retries):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 200: return r.content
            if r.status_code == 429: time.sleep(2**i); continue
            print(f"    [ERR] {r.status_code}: {r.text[:80]}"); return None
        except Exception as e:
            if i < retries-1: time.sleep(2**i)
            else: print(f"    [ERR] {e}"); return None
    return None

def mp3_to_wav(mp3_bytes):
    try:
        from pydub import AudioSegment
        seg = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        seg = seg.set_frame_rate(44100).set_channels(1).set_sample_width(2)
        buf = io.BytesIO()
        seg.export(buf, format="wav")
        return buf.getvalue()
    except ImportError:
        pass
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
        tf.write(mp3_bytes)
        mp3_p = tf.name
    wav_p = mp3_p.replace(".mp3", ".wav")
    try:
        subprocess.run(["ffmpeg","-y","-i",mp3_p,"-ar","44100","-ac","1","-acodec","pcm_s16le",wav_p], capture_output=True, check=True)
        return open(wav_p,"rb").read()
    finally:
        for p in [mp3_p, wav_p]:
            try: os.unlink(p)
            except: pass

def save_wav(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

def wav_dur(path):
    try:
        with wave.open(str(path),"rb") as w:
            f = w.getnframes()
            r = w.getframerate()
            nc = w.getnchannels()
            sw = w.getsampwidth()
            if r == 0: return 0.0
            if f > 2**30:
                f = (path.stat().st_size - 44) // (nc * sw)
            return f / r
    except:
        return 0.0

def concat_wavs(paths, out):
    with wave.open(str(paths[0]),"rb") as w:
        nc, sw, fr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        data = [w.readframes(w.getnframes())]
    for p in paths[1:]:
        with wave.open(str(p),"rb") as w:
            data.append(w.readframes(w.getnframes()))
    all_data = b"".join(data)
    with wave.open(str(out),"wb") as w:
        w.setnchannels(nc)
        w.setsampwidth(sw)
        w.setframerate(fr)
        w.setnframes(len(all_data) // (nc * sw))
        w.writeframesraw(all_data)

def main():
    p = argparse.ArgumentParser(description="ElevenLabs TTS 생성 (eleven_multilingual_v2)")
    p.add_argument("--ep", type=int)
    p.add_argument("--dir", type=str)
    a = p.parse_args()
    if a.dir:
        ep_dir = Path(a.dir)
    elif a.ep is not None:
        ep_dir = Path(f"output/ep{a.ep:02d}")
    else:
        p.print_help(); sys.exit(1)
    if not ep_dir.is_absolute():
        ep_dir = Path(__file__).parent / ep_dir

    story = json.load(open(ep_dir / "story.json", encoding="utf-8"))
    slides = story.get("slides", [])
    meta   = story.get("meta", {})
    lang   = meta.get("language", "en")
    title  = meta.get("story_title", ep_dir.name)
    audio_dir = ep_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    ev    = meta.get("elevenlabs_voices", {})
    vmap  = {**DEFAULT_ELEVEN_VOICES, **ev}
    speed = LANG_SPEED.get(lang, 1.0)

    print(f"\n{'='*60}")
    print(f"  [ElevenLabs TTS] {title}  언어={lang}")
    used = set(seg.get("voice", seg.get("speaker", "narrator")) for sl in slides for seg in sl.get("tts_segments", []))
    for sp in sorted(used):
        vi = vmap.get(sp, vmap["narrator"])
        print(f"    {sp:15} -> {vi['name']:10} ({vi['voice_id']})")
    print(f"{'='*60}")

    seg_map = {}
    for sl in slides:
        n    = sl.get("slide_number", 0)
        segs = sl.get("tts_segments", [])
        if not segs or sl.get("type", "") in ("quiz_question", "quiz_answer"):
            continue
        print(f"  [슬라이드 {n:02d}] {len(segs)}개...")
        entries = []
        for i, seg in enumerate(segs):
            sp   = seg.get("voice", seg.get("speaker", "narrator"))
            text = seg.get("text", "").strip()
            path = audio_dir / f"slide_{n:02d}_seg_{i:02d}.wav"
            entries.append((i, seg, path))
            if path.exists():
                print(f"    seg{i:02d}[{sp}] 이미 존재")
                continue
            if not text:
                continue
            vi  = vmap.get(sp, vmap["narrator"])
            spd = vi.get("speed", speed)
            mp3 = eleven_tts(vi["voice_id"], text, vi.get("stability", 0.5), vi.get("similarity_boost", 0.75), spd)
            if mp3:
                save_wav(mp3_to_wav(mp3), path)
                print(f"    seg{i:02d}[{sp}] voice={vi['name']} 완료")
            else:
                print(f"    seg{i:02d}[{sp}] 실패")
        seg_map[n] = entries
        existing = [p for _, _, p in entries if p.exists()]
        if existing:
            concat_wavs(existing, audio_dir / f"slide_{n:02d}.wav")
            print(f"    -> slide_{n:02d}.wav 합침")

    # 퀴즈 TTS
    print("\n  [퀴즈 TTS]")
    qt  = story.get("quiz_tts", QUIZ_TTS.get(lang, QUIZ_TTS["en"]))
    nvi = vmap.get("narrator", DEFAULT_ELEVEN_VOICES["narrator"])
    for key in ["quiz_intro","quiz_q1","quiz_q2","quiz_q3","quiz_a1","quiz_a2","quiz_a3"]:
        wp = audio_dir / f"{key}.wav"
        if wp.exists():
            print(f"    {key}.wav 이미 존재")
            continue
        mp3 = eleven_tts(nvi["voice_id"], qt.get(key, key), nvi.get("stability", 0.5), nvi.get("similarity_boost", 0.75), speed)
        if mp3:
            save_wav(mp3_to_wav(mp3), wp)
            print(f"    {key}.wav 완료")
        else:
            print(f"    {key}.wav 실패")

    # timing.json
    print("\n  timing.json 생성...")
    t_segs, t_slides, cur = [], [], 0.0
    # slide_number → type 매핑 (09b_smart_shorts.py의 "type" 필드 필요)
    slide_type_map = {sl.get("slide_number", 0): sl.get("type", "story") for sl in slides}
    slide_nums = sorted(set(s.get("slide_number", 0) for s in slides if s.get("type", "") not in ("quiz_question", "quiz_answer")))
    tot_segs = 0
    for n in slide_nums:
        ss = cur
        stype = slide_type_map.get(n, "story")
        if n == 0:
            cur += COVER_DUR
            t_slides.append({"slide": 0, "type": "cover", "start": round(ss, 3), "end": round(cur, 3), "duration": round(COVER_DUR, 3)})
            continue
        cur += SILENCE_SLIDE
        ss = cur
        prev_sp = None
        for i, seg, path in seg_map.get(n, []):
            if not path.exists():
                continue
            sp  = seg.get("voice", seg.get("speaker", "narrator"))
            dur = wav_dur(path)
            if prev_sp is not None:
                cur += SILENCE_SAME if sp == prev_sp else SILENCE_CHANGE
            t_segs.append({"file": f"slide_{n:02d}_seg_{i:02d}.wav", "slide": n, "index": i, "speaker": sp, "text": seg.get("text", ""), "duration": round(dur, 3), "start": round(cur, 3), "end": round(cur + dur, 3)})
            cur += dur
            prev_sp = sp
            tot_segs += 1
        t_slides.append({"slide": n, "type": stype, "start": round(ss, 3), "end": round(cur, 3), "duration": round(cur - ss, 3)})

    timing = {"slides": t_slides, "segments": t_segs, "total_duration": round(cur, 3), "total_segments": tot_segs}
    (audio_dir / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> timing.json 완료 ({tot_segs}개 세그먼트, 총 {cur:.1f}초)")
    print(f"\n  [DONE]")
    print(f"    python 04_concat_audio.py --dir {ep_dir}")
    print(f"    python 05_generate_srt.py --dir {ep_dir}")

if __name__ == "__main__":
    main()
