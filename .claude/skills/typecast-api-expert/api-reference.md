# Typecast API Reference

## Base URL
```
https://api.typecast.ai
```

## Authentication
```
Header: X-API-KEY: YOUR_API_KEY
```

---

## Available Models

| Model | Description | Emotion Control |
|-------|-------------|-----------------|
| ssfm-v21 | Stable production model | Preset only (normal, happy, sad, angry) |
| ssfm-v30 | Latest model with advanced features | Preset (7 emotions) + Smart (context-aware) |

### ssfm-v30 Features
- **7 Emotion Presets**: normal, happy, sad, angry, whisper, toneup, tonedown
- **Smart Mode**: AI automatically infers emotion from context
- **Context Awareness**: Use previous_text and next_text for better emotion inference
- **37 Languages**: Extended language support

---

## Endpoints

### 1. Text-to-Speech (Voice Generation)
```
POST /v1/text-to-speech
```

**Required Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `voice_id` | string | Voice ID (e.g., "tc_672c5f5ce59fac2a48faeaee") |
| `text` | string | Text to convert (max 2,000 characters) |
| `model` | string | "ssfm-v21" or "ssfm-v30" (recommended) |

**Optional Parameters (Common):**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `language` | string | Auto-detect | Language code (ISO 639-3, e.g., "eng", "kor") |
| `output.volume` | integer | 100 | 0 ~ 200 |
| `output.audio_pitch` | integer | 0 | -12 ~ +12 (semitones) |
| `output.audio_tempo` | number | 1.0 | 0.5 ~ 2.0 |
| `output.audio_format` | string | "wav" | "wav" or "mp3" |
| `seed` | integer | - | Seed value for reproducible results |

**Prompt Parameters for ssfm-v21:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt.emotion_preset` | string | "normal" | "normal", "happy", "sad", "angry" |
| `prompt.emotion_intensity` | number | 1.0 | 0.0 ~ 2.0 |

**Prompt Parameters for ssfm-v30 (Preset Mode):**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt.emotion_type` | string | "preset" | Must be "preset" |
| `prompt.emotion_preset` | string | "normal" | normal, happy, sad, angry, whisper, toneup, tonedown |
| `prompt.emotion_intensity` | number | 1.0 | 0.0 ~ 2.0 |

**Prompt Parameters for ssfm-v30 (Smart Mode):**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt.emotion_type` | string | "smart" | Must be "smart" |
| `prompt.previous_text` | string | null | Previous context text for emotion inference |
| `prompt.next_text` | string | null | Next context text for emotion inference |

**Request Example (ssfm-v30 Preset Mode):**
```json
{
  "text": "Hello! This is Typecast API.",
  "model": "ssfm-v30",
  "voice_id": "tc_672c5f5ce59fac2a48faeaee",
  "prompt": {
    "emotion_type": "preset",
    "emotion_preset": "happy",
    "emotion_intensity": 1.5
  },
  "output": {
    "audio_format": "mp3",
    "volume": 100
  }
}
```

**Request Example (ssfm-v30 Smart Mode):**
```json
{
  "text": "Everything is going to be okay.",
  "model": "ssfm-v30",
  "voice_id": "tc_672c5f5ce59fac2a48faeaee",
  "prompt": {
    "emotion_type": "smart",
    "previous_text": "I just got the best news!",
    "next_text": "I can't wait to celebrate!"
  }
}
```

**Response:** Binary audio data (wav or mp3)

---

### 2. List Voices (V2 API - Recommended)
```
GET /v2/voices
GET /v2/voices?model=ssfm-v30
GET /v2/voices?model=ssfm-v30&gender=female&age=young_adult
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | string | Filter by model: "ssfm-v21" or "ssfm-v30" |
| `gender` | string | Filter by gender: "male" or "female" |
| `age` | string | Filter by age: "child", "teen", "young_adult", "middle_aged", "senior" |
| `use_cases` | string | Filter by use case |

---

### 3. List Voices (V1 API - Legacy)
```
GET /v1/voices
GET /v1/voices?model=ssfm-v21
```

---

### 4. Get Specific Voice
```
GET /v1/voices/{voice_id}
```

Returns detailed information about a specific voice.

---

### 5. Quick Voice Cloning
```text
POST /v1/voices/clone
DELETE /v1/voices/{voice_id}
```

Quick Voice Cloning creates a custom cloned voice from a WAV or MP3 audio sample.
Use the returned cloned voice ID with TTS endpoints, then delete it when no longer needed.

#### Clone Voice

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Display name for the cloned voice. Must be 1-30 characters. |
| `model` | string | Yes | Voice cloning model. Use `ssfm-v30` by default. |
| `file` | binary | Yes | WAV or MP3 audio sample. Maximum size is 25 MB. |

**Response:** JSON containing the cloned voice ID, usually in `voice_id`.

#### Delete Cloned Voice

```http
DELETE /v1/voices/{voice_id}
```

- Only delete cloned custom voice IDs that start with `uc_`.
- Do not pass built-in Typecast voice IDs that start with `tc_`.

---

## API Characteristics

- **Synchronous**: The API returns audio data directly in the response
- **No SSML Support**: Currently SSML is not supported (use speed/volume parameters instead)
- **No Pronunciation Dictionary**: Currently not supported

---

## Supported Languages (37 languages)

| Language | Code | Language | Code | Language | Code |
|----------|------|----------|------|----------|------|
| English | eng | Japanese | jpn | Ukrainian | ukr |
| Korean | kor | Greek | ell | Indonesian | ind |
| Spanish | spa | Tamil | tam | Danish | dan |
| German | deu | Tagalog | tgl | Swedish | swe |
| French | fra | Finnish | fin | Malay | msa |
| Italian | ita | Chinese | zho | Czech | ces |
| Polish | pol | Slovak | slk | Portuguese | por |
| Dutch | nld | Arabic | ara | Bulgarian | bul |
| Russian | rus | Croatian | hrv | Romanian | ron |
| Bengali | ben | Hindi | hin | Hungarian | hun |
| Hokkien | nan | Norwegian | nor | Punjabi | pan |
| Thai | tha | Turkish | tur | Vietnamese | vie |
| Cantonese | yue | | | | |

**Primary Languages**: Korean (kor), English (eng), Japanese (jpn), Spanish (spa)

---

## Rate Limits by Plan

| Plan | Concurrent Requests |
|------|---------------------|
| Free | 2 |
| Lite | 5 |
| Plus | 15 |

---

## Competitor Comparison

| Feature | Typecast | ElevenLabs | AWS Polly | Google TTS |
|---------|----------|------------|-----------|------------|
| Emotional Expression | Best | Good | Average | Fair |
| Character Voices | 500+ unique characters | Clone-focused | Basic voices | Basic voices |
| Korean Quality | Native level | Average | Average | Fair |
| Price Competitiveness | Excellent | Average | Good | Good |

---

## AWS Marketplace Integration

Typecast SSFM is also available on AWS Marketplace for enterprises prioritizing security.

**Benefits:**
- Data Privacy: Input text data is not collected by Typecast
- Security: Processed within AWS infrastructure
- Easy Billing: Integrated into AWS invoices
- Compliance: Suitable for internal security policies

**Getting Started:**
1. Visit: https://aws.amazon.com/marketplace/seller-profile?id=seller-rauqp3qawr25s
2. Click "Continue to Subscribe"
3. Review and agree to terms
4. Access through AWS API Gateway

**References:**
- AWS Marketplace Model Package: https://github.com/neosapience/aws-marketplace-ssfm/blob/main/ssfm-Model.ipynb
- Official Docs: https://typecast.ai/docs/bestpractice/aws-marketplace
