# Typecast API Code Samples

## Python (Using SDK) - Recommended

```bash
pip install typecast-python
```

### Preset Mode (ssfm-v30)
```python
from typecast import Typecast
from typecast.models import TTSRequest, PresetPrompt, Output

# Initialize client
client = Typecast(api_key="YOUR_API_KEY")

# TTS request with ssfm-v30 Preset Mode
response = client.text_to_speech(TTSRequest(
    text="Hello! This is Typecast API.",
    model="ssfm-v30",
    voice_id="tc_672c5f5ce59fac2a48faeaee",
    prompt=PresetPrompt(
        emotion_type="preset",
        emotion_preset="happy",
        emotion_intensity=1.5
    ),
    output=Output(audio_format="mp3")
))

# Save audio
with open('output.mp3', 'wb') as f:
    f.write(response.audio_data)

print("Audio file saved successfully!")
```

### Smart Mode (ssfm-v30)
```python
from typecast import Typecast
from typecast.models import TTSRequest, SmartPrompt

client = Typecast(api_key="YOUR_API_KEY")

# Let AI infer emotion from context
response = client.text_to_speech(TTSRequest(
    text="Everything is going to be okay.",
    model="ssfm-v30",
    voice_id="tc_672c5f5ce59fac2a48faeaee",
    prompt=SmartPrompt(
        emotion_type="smart",
        previous_text="I just got the best news!",
        next_text="I can't wait to celebrate!"
    )
))

with open('output_smart.wav', 'wb') as f:
    f.write(response.audio_data)
```

---

## Python (Direct API)

### Preset Mode
```python
import requests
import os

api_key = os.environ.get("TYPECAST_API_KEY", "YOUR_API_KEY")

url = "https://api.typecast.ai/v1/text-to-speech"
headers = {
    "X-API-KEY": api_key,
    "Content-Type": "application/json"
}
payload = {
    "text": "Hello! This is Typecast API.",
    "model": "ssfm-v30",
    "voice_id": "tc_672c5f5ce59fac2a48faeaee",
    "prompt": {
        "emotion_type": "preset",
        "emotion_preset": "happy",
        "emotion_intensity": 1.5
    },
    "output": {
        "audio_format": "mp3"
    }
}

response = requests.post(url, headers=headers, json=payload)

if response.status_code == 200:
    with open('output.mp3', 'wb') as f:
        f.write(response.content)
    print("Audio saved successfully!")
else:
    print(f"Error: {response.status_code} - {response.text}")
```

### Smart Mode
```python
payload = {
    "text": "Everything is going to be okay.",
    "model": "ssfm-v30",
    "voice_id": "tc_672c5f5ce59fac2a48faeaee",
    "prompt": {
        "emotion_type": "smart",
        "previous_text": "I just got the best news!",
        "next_text": "I can't wait to celebrate!"
    }
}

response = requests.post(url, headers=headers, json=payload)
```

---

## JavaScript/TypeScript (Using SDK) - Recommended

```bash
npm install @neosapience/typecast-js
```

### Preset Mode
```javascript
import { TypecastClient } from "@neosapience/typecast-js";
import fs from "fs";

const client = new TypecastClient({ apiKey: "YOUR_API_KEY" });

// Preset Mode
const audio = await client.textToSpeech({
  text: "Hello! This is Typecast API.",
  model: "ssfm-v30",
  voice_id: "tc_672c5f5ce59fac2a48faeaee",
  prompt: {
    emotion_type: "preset",
    emotion_preset: "happy",
    emotion_intensity: 1.5,
  },
});

await fs.promises.writeFile("output.wav", Buffer.from(audio.audioData));
console.log("Audio saved successfully!");
```

### Smart Mode
```javascript
// Smart Mode
const smartAudio = await client.textToSpeech({
  text: "Everything is going to be okay.",
  model: "ssfm-v30",
  voice_id: "tc_672c5f5ce59fac2a48faeaee",
  prompt: {
    emotion_type: "smart",
    previous_text: "I just got the best news!",
    next_text: "I can't wait to celebrate!",
  },
});
```

---

## JavaScript (Direct API with fetch)

```javascript
const apiKey = process.env.TYPECAST_API_KEY || "YOUR_API_KEY";

const response = await fetch("https://api.typecast.ai/v1/text-to-speech", {
  method: "POST",
  headers: {
    "X-API-KEY": apiKey,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    text: "Hello! This is Typecast API.",
    model: "ssfm-v30",
    voice_id: "tc_672c5f5ce59fac2a48faeaee",
    prompt: {
      emotion_type: "preset",
      emotion_preset: "happy",
      emotion_intensity: 1.5,
    },
  }),
});

if (response.ok) {
  const arrayBuffer = await response.arrayBuffer();
  const fs = await import("fs");
  fs.writeFileSync("output.wav", Buffer.from(arrayBuffer));
  console.log("Audio saved successfully!");
} else {
  console.error(`Error: ${response.status}`);
}
```

---

## Quick Voice Cloning (Direct API)

```python
import requests

api_key = "YOUR_API_KEY"

with open("sample.wav", "rb") as audio_file:
    clone_response = requests.post(
        "https://api.typecast.ai/v1/voices/clone",
        headers={"X-API-KEY": api_key},
        data={"name": "My Cloned Voice", "model": "ssfm-v30"},
        files={"file": ("sample.wav", audio_file, "audio/wav")},
    )
clone_response.raise_for_status()

cloned_voice = clone_response.json()
voice_id = cloned_voice.get("voice_id") or cloned_voice.get("result", {}).get("voice_id")
if not voice_id:
    raise ValueError(f"voice_id not found in clone response: {cloned_voice}")

speech_response = requests.post(
    "https://api.typecast.ai/v1/text-to-speech",
    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
    json={
        "text": "Hello from my cloned voice.",
        "model": "ssfm-v30",
        "voice_id": voice_id,
    },
)
speech_response.raise_for_status()

with open("cloned_voice_output.wav", "wb") as f:
    f.write(speech_response.content)

if not voice_id.startswith("uc_"):
    raise ValueError(f"Refusing to delete non-cloned voice ID: {voice_id}")

requests.delete(
    f"https://api.typecast.ai/v1/voices/{voice_id}",
    headers={"X-API-KEY": api_key},
).raise_for_status()
```

```bash
curl -X POST "https://api.typecast.ai/v1/voices/clone" \
     -H "X-API-KEY: YOUR_API_KEY" \
     -F "name=My Cloned Voice" \
     -F "model=ssfm-v30" \
     -F "file=@sample.wav;type=audio/wav"

curl -X DELETE "https://api.typecast.ai/v1/voices/uc_YOUR_CLONED_VOICE_ID" \
     -H "X-API-KEY: YOUR_API_KEY"
```

Quick cloning accepts WAV or MP3 samples up to 25 MB. Delete only cloned voice IDs that start with `uc_`.

---

## cURL

### Preset Mode
```bash
curl -X POST "https://api.typecast.ai/v1/text-to-speech" \
     -H "X-API-KEY: YOUR_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
         "model": "ssfm-v30",
         "text": "Hello there!",
         "voice_id": "tc_672c5f5ce59fac2a48faeaee",
         "prompt": {
             "emotion_type": "preset",
             "emotion_preset": "happy"
         }
     }' > output.wav
```

### Smart Mode
```bash
curl -X POST "https://api.typecast.ai/v1/text-to-speech" \
     -H "X-API-KEY: YOUR_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
         "model": "ssfm-v30",
         "text": "Everything is going to be okay.",
         "voice_id": "tc_672c5f5ce59fac2a48faeaee",
         "prompt": {
             "emotion_type": "smart",
             "previous_text": "I just got the best news!"
         }
     }' > output_smart.wav
```

---

## List Available Voices (V2 API)

```bash
# List all ssfm-v30 voices
curl -X GET "https://api.typecast.ai/v2/voices?model=ssfm-v30" \
     -H "X-API-KEY: YOUR_API_KEY"

# Filter by gender and age
curl -X GET "https://api.typecast.ai/v2/voices?model=ssfm-v30&gender=female&age=young_adult" \
     -H "X-API-KEY: YOUR_API_KEY"
```

---

## AWS Lambda Example

```python
import json
import urllib.request
import os

def lambda_handler(event, context):
    api_key = os.environ['TYPECAST_API_KEY']

    url = "https://api.typecast.ai/v1/text-to-speech"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "text": event.get("text", "Hello from Lambda!"),
        "model": "ssfm-v30",
        "voice_id": "tc_672c5f5ce59fac2a48faeaee",
        "prompt": {
            "emotion_type": "preset",
            "emotion_preset": event.get("emotion", "normal")
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST'
    )

    with urllib.request.urlopen(req) as response:
        audio_data = response.read()
        # Save to S3 or return as base64
        return {
            'statusCode': 200,
            'body': 'Audio generated successfully'
        }
```

---

## Environment Variable Setup

### Linux/macOS
```bash
export TYPECAST_API_KEY="your_api_key_here"
```

### Windows (PowerShell)
```powershell
$env:TYPECAST_API_KEY="your_api_key_here"
```

### .env file (with python-dotenv)
```
TYPECAST_API_KEY=your_api_key_here
```

```python
from dotenv import load_dotenv
import os

load_dotenv()
api_key = os.environ.get("TYPECAST_API_KEY")
```

---

## Advanced: Emotion Control Examples

### ssfm-v30 Emotion Presets
```python
# Available presets: normal, happy, sad, angry, whisper, toneup, tonedown
prompt = {
    "emotion_type": "preset",
    "emotion_preset": "whisper",  # New in ssfm-v30
    "emotion_intensity": 1.5
}
```

### Happy with High Intensity
```python
prompt = {
    "emotion_type": "preset",
    "emotion_preset": "happy",
    "emotion_intensity": 2.0  # Maximum intensity
}
```

### Subtle Sadness
```python
prompt = {
    "emotion_type": "preset",
    "emotion_preset": "sad",
    "emotion_intensity": 0.5  # Subtle expression
}
```

### Adjusting Speed and Pitch
```python
output = {
    "audio_format": "mp3",
    "audio_tempo": 1.2,  # 20% faster
    "audio_pitch": 2,    # Slightly higher pitch
    "volume": 120        # 20% louder
}
```

---

## Use Cases

### E-learning Content
```python
# Clear, professional narration
payload = {
    "text": "Welcome to Chapter 1. Today we will learn about...",
    "model": "ssfm-v30",
    "voice_id": "tc_672c5f5ce59fac2a48faeaee",
    "prompt": {
        "emotion_type": "preset",
        "emotion_preset": "normal"
    },
    "output": {"audio_tempo": 0.9}  # Slightly slower for clarity
}
```

### YouTube/Shorts Narration
```python
# Energetic, engaging tone
payload = {
    "text": "You won't believe what happened next!",
    "model": "ssfm-v30",
    "voice_id": "tc_672c5f5ce59fac2a48faeaee",
    "prompt": {
        "emotion_type": "preset",
        "emotion_preset": "happy",
        "emotion_intensity": 1.5
    }
}
```

### Audiobook Production with Smart Mode
```python
# Let AI choose emotion based on context
payload = {
    "text": "The old man sat quietly by the window, watching the rain fall...",
    "model": "ssfm-v30",
    "voice_id": "tc_672c5f5ce59fac2a48faeaee",
    "prompt": {
        "emotion_type": "smart",
        "previous_text": "He had received the letter that morning.",
        "next_text": "His thoughts drifted to the past."
    }
}
```
