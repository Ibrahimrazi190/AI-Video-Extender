# Test S results

5 s clips, 480p. Folders are relative to `test_results/test_s/`.

| Folder | Variant | Status | What it tests |
|---|---|---|---|
| `clip1/` | - | ok | Base clip: the woman visible, no references. Source of the audio and last frame used by every variant. |
| `variant1/clip2/` | 1 | ok | Talking Head formula: previous clip's video + audio + last frame (clip 1's). |
| `variant2/clip2/` | 2 | ok | Video + audio only, no image (clip 1's). |
| `variant3/clip2/` | 3 | ok | Video + audio + clip 1's last frame as the fixed character image, plus the 'looks exactly like @Image1' sentence. |
| `variant1/clip3/` | 1 | ok | Chains from variant 1's clip 2 (video + audio + last frame): scene change with the character returning. |
| `variant2/clip3/` | 2 | ok | Chains from variant 2's clip 2 (video + audio only): scene change with the character returning. |
| `variant3/clip3/` | 3 | ok | Video from variant 3's clip 2, but audio and image fixed to clip 1's (voice anchor + character image). |

Total credits consumed (successful generations): 163

Notes:
- `audio.mp3` and `last_frame.jpg` are review copies converted from the WAV/PNG files that were uploaded to kie.ai and used as references. Each `meta.json` has the exact URLs sent.
- `api_response` in `meta.json` is what `generate_clip` returns (task id, video URL, credits), not the full raw kie.ai reply.
- Failed or skipped steps have the reason in their `meta.json`.
