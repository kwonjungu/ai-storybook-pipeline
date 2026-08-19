# Typecast API Troubleshooting Guide

## Error Codes Reference

| Code | Description | Cause | Solution |
|------|-------------|-------|----------|
| 400 | Bad Request | Missing required parameters or format error | Check voice_id, text, model required parameters |
| 401 | Unauthorized | API key authentication failed | Verify API key, check environment variables, remove whitespace/special characters |
| 402 | Payment Required | Insufficient credits | Upgrade plan or add payment |
| 403 | Forbidden | No permission or dormant account | See detailed checklist below |
| 404 | Not Found | voice_id does not exist | Check valid voice list with /v2/voices |
| 422 | Validation Error | Parameter value out of range or text cannot be synthesized | Check parameter ranges. For `TEXT_NOT_SYNTHESIZABLE`, correct the text before retrying |
| 429 | Too Many Requests | Concurrent request limit exceeded | Check plan limits (Free:2, Lite:5, Plus:15) |
| 500 | Internal Server Error | Unexpected server error | Retry later, contact support if problem persists |

---

## 403 Forbidden - Detailed Checklist

The 403 error is the most common issue. Check these items in order:

### 1. Are you using a Starter plan API key?
**Problem:** Starter plan API keys (old) are not compatible with the new SSFM API.

**Solution:**
1. Go to https://typecast.ai/developers/api
2. Subscribe to a new API plan (Free trial available)
3. Get a new API key from the API Keys tab
4. Replace your old key with the new one

### 2. Is your account dormant?
**Problem:** Accounts that haven't logged in for a while may be marked as dormant.

**Solution:**
1. Go to https://typecast.ai
2. Log in to your account
3. This automatically reactivates your account
4. Retry your API call

### 3. Does your API key contain whitespace or newlines?
**Problem:** Copy-paste errors can introduce hidden characters.

**Solution:**
```python
# Bad - may have hidden whitespace
api_key = "tc_abc123... "  # Trailing space

# Good - trim whitespace
api_key = "tc_abc123...".strip()

# Best - use environment variables
import os
api_key = os.environ.get("TYPECAST_API_KEY", "").strip()
```

---

## 401 Unauthorized

### Check API Key Format
```python
# Correct header format
headers = {
    "X-API-KEY": "your_api_key_here",  # Note: X-API-KEY, not Authorization
    "Content-Type": "application/json"
}

# Wrong - using Authorization header
headers = {
    "Authorization": "Bearer your_api_key_here"  # This won't work!
}
```

### Verify Environment Variable
```bash
# Check if environment variable is set
echo $TYPECAST_API_KEY

# If empty, set it
export TYPECAST_API_KEY="your_api_key_here"
```

---

## 429 Too Many Requests

### Rate Limits by Plan
| Plan | Concurrent Requests |
|------|---------------------|
| Free | 2 |
| Lite | 5 |
| Plus | 15 |

### Solution: Add Request Throttling
```python
import time
import requests
from concurrent.futures import ThreadPoolExecutor

def make_request(text, max_concurrent=2):
    # Simple rate limiting
    time.sleep(0.5)  # Add delay between requests

    response = requests.post(
        "https://api.typecast.ai/v1/text-to-speech",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"text": text, "model": "ssfm-v30", "voice_id": voice_id}
    )
    return response

# Process with limited concurrency
with ThreadPoolExecutor(max_workers=2) as executor:  # Match your plan limit
    results = executor.map(make_request, texts)
```

---

## 404 Not Found

### Invalid voice_id
```python
# First, get list of valid voices using V2 API
import requests

response = requests.get(
    "https://api.typecast.ai/v2/voices?model=ssfm-v30",
    headers={"X-API-KEY": api_key}
)

voices = response.json()
print([v["voice_id"] for v in voices])  # Print available voice IDs
```

---

## 422 Validation Error

### Text Cannot Be Synthesized

Unsupported character or symbol sequences and language mismatches return:

```json
{
  "error_code": "TEXT_NOT_SYNTHESIZABLE",
  "message": "The input text contains characters or symbols that cannot be synthesized into speech. Please check your input text."
}
```

Do not retry the same text. Correct the input before sending another request. For streaming TTS, the API can return this status only before the streaming response begins; once streaming has started, the HTTP status cannot change.

### Parameter Ranges
| Parameter | Valid Range |
|-----------|-------------|
| emotion_intensity | 0.0 ~ 2.0 |
| volume | 0 ~ 200 |
| audio_pitch | -12 ~ +12 |
| audio_tempo | 0.5 ~ 2.0 |
| text | 1 ~ 2,000 characters |

### Example Fix
```python
# Wrong - values out of range
payload = {
    "prompt": {"emotion_intensity": 5.0},  # Max is 2.0!
    "output": {"volume": 500}              # Max is 200!
}

# Correct
payload = {
    "prompt": {"emotion_intensity": 2.0},  # Within range
    "output": {"volume": 200}              # Within range
}
```

---

## Quick Voice Cloning Issues

### Clone Voice returns 400 or 422

Check these fields first:

| Field | Valid Value |
|-------|-------------|
| `name` | 1-30 characters |
| `model` | `ssfm-v30` |
| `file` | WAV or MP3 |
| File size | 25 MB or smaller |

For direct API calls, send Clone Voice as `multipart/form-data`, not JSON:

```python
with open("sample.wav", "rb") as audio_file:
    response = requests.post(
        "https://api.typecast.ai/v1/voices/clone",
        headers={"X-API-KEY": api_key},
        data={"name": "My Cloned Voice", "model": "ssfm-v30"},
        files={"file": ("sample.wav", audio_file, "audio/wav")},
    )
```

### Delete Cloned Voice fails

- Only pass cloned custom voice IDs that start with `uc_`.
- Do not delete built-in Typecast voice IDs that start with `tc_`.
- If the voice was already deleted, refresh the user's stored voice ID before retrying.

---

## Common Issues

### Issue: Empty audio file returned
**Cause:** Text might be empty or contain only whitespace.

**Solution:**
```python
text = user_input.strip()
if not text:
    raise ValueError("Text cannot be empty")
```

### Issue: Audio plays but sounds wrong
**Cause:** Language mismatch.

**Solution:**
```python
# Explicitly set language for non-English text
payload = {
    "text": "안녕하세요",
    "language": "kor",  # Explicitly set Korean (lowercase)
    "model": "ssfm-v30",
    "voice_id": voice_id
}
```

### Issue: API works locally but fails in production
**Cause:** API key exposure or environment issues.

**Solution:**
1. Never hardcode API keys
2. Use environment variables or secret managers
3. Ensure production environment has the key set

```python
import os

api_key = os.environ.get("TYPECAST_API_KEY")
if not api_key:
    raise EnvironmentError("TYPECAST_API_KEY environment variable not set")
```

### Issue: emotion_type validation error (ssfm-v30)
**Cause:** Using ssfm-v21 prompt format with ssfm-v30.

**Solution:**
```python
# ssfm-v21 format (old)
prompt = {
    "emotion_preset": "happy",
    "emotion_intensity": 1.5
}

# ssfm-v30 format (new) - requires emotion_type
prompt = {
    "emotion_type": "preset",  # Required for ssfm-v30
    "emotion_preset": "happy",
    "emotion_intensity": 1.5
}
```

---

## FAQ

### Q: Can I use SSML?
**A:** No, the API does not support SSML. Use `output.audio_tempo`, `output.volume`, `output.audio_pitch` parameters as alternatives.

### Q: Does the API support Pronunciation Dictionary?
**A:** Currently, the API does not support pronunciation dictionary features.

### Q: Can I use the API in AWS Lambda?
**A:** Yes! See the Lambda example in [code-samples.md](code-samples.md).

### Q: Can I use the API in mobile apps?
**A:** Yes, but **never put the API key directly in client code**. Always call the API through a backend server.

### Q: Why do English characters speak Korean well?
**A:** Typecast voices are multilingual. English character voices can speak Korean and other languages naturally.

### Q: What's the difference between ssfm-v21 and ssfm-v30?
**A:**
- **ssfm-v21**: 4 emotion presets (normal, happy, sad, angry)
- **ssfm-v30**: 7 emotion presets + Smart Mode (context-aware emotion), 37 languages

### Q: How do I use Smart Mode?
**A:** Set `emotion_type: "smart"` and optionally provide `previous_text` and `next_text` for context. The AI will infer the appropriate emotion.

---

## Getting Help

If you're still stuck:

1. **Discord Community**: https://discord.gg/fhDDUbBKap
2. **Intercom Chat**: https://typecast.ai (bottom right)
3. **Official Docs**: https://typecast.ai/docs/overview
4. **Email**: sales@neosapience.com (for Enterprise inquiries)
