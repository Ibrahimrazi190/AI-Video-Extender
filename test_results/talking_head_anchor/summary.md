# Talking Head anchor test (Formula B)

Source job: `f2008f3548944596b32ba59fcc3faaf6` (topic: A woman tells her breakup story while talking to us directly seeing the camera). 5 s clips, 480p.
Folders are relative to `test_results/talking_head_anchor/`.

| Folder | What it is | Status |
|---|---|---|
| `master_clip1/` | the first clip of the earlier run: the source of the fixed audio and last-frame references | copied for review |
| `chained_previous_run/` | clips 2 and 3 of the earlier run, each chained from the previous clip's video + audio + last frame (the formula being compared against) | copied for review |
| `formula_b/clip2/` | Clip 2 with Formula B: previous clip's video (the master) + first clip's audio + first clip's last frame. | ok |
| `formula_b/clip3/` | Clip 3 with Formula B: previous clip's video (this run's clip 2) + the SAME first-clip audio and last frame. | ok |

Total credits consumed (successful generations): 48

What to compare, clip by clip, against `chained_previous_run/`:
- Face: does clip 3 still look like the same woman as `master_clip1/video.mp4`?
- Audio: is the voice steady, and does clip 3 still sound clean at its ending?
- Seams: is the cut from the master into clip 2, and from clip 2 into clip 3, as smooth as in the chained run?
- Colour: any saturation/colour shift at the cuts?

Notes: `audio.mp3` and `last_frame.jpg` in `master_clip1/` are review copies converted from the WAV/PNG files that were re-extracted and used as references. `api_response` in each `meta.json` is what `generate_clip` returns (task id, video URL, credits).
