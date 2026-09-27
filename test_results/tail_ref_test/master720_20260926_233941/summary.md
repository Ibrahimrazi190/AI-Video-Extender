# 720p-master + tail test

Topic: A young woman talking to the camera tells why she left her husband
Run folder: `test_results/tail_ref_test/master720_20260926_233941/`
Settings: 5 clips x 5 s on bytedance/seedance-2-mini, mode talking_head. Clip 1 at 720p (the master), clips 2 to 5 at 480p.

References for clips 2 to 5: two videos, (1) the last 2 s of the previous clip, muted (plus one frame so it can't round under kie.ai's 2 s minimum), and (2) the whole 720p clip 1, muted, the same file every time. Audio = clip 1's audio and image = clip 1's last frame, fixed, as in the pipeline. Prompts are the pipeline's own, so <Video 1> is the tail; the master is the second, untagged video. `clip1/master_reference_muted.mp4` and `clipN/tail_sent_to_next_clip.mp4` are exactly what kie.ai received.

| Clip | Resolution | Line | Credits | Video kbps | Edge energy (at 864x496) | Status |
|---|---|---|---|---|---|---|
| 1 | 720p | I left my husband after realizing love had become permission to disappear. | 41.0 | 3430 | 27.72 | ok |
| 2 | 480p | At first, I called his control concern, and my silence compromise. | 28.8 | 1722 | 28.36 | ok |
| 3 | 480p | Then I found my old journals and barely recognized that woman. | 28.8 | 1711 | 28.54 | ok |
| 4 | 480p | So one morning, I packed two bags before he woke up. | 28.8 | 1703 | 28.73 | ok |
| 5 | 480p | Leaving hurt, but staying would have cost me my whole self. | 28.8 | 1672 | 28.59 | ok |

Total credits consumed: 156.2
`full_video.mp4`: re-encoded at high quality, every clip scaled to 864x496 (clip 1 is 720p); judge quality on the single clips

Edge energy is mean Sobel edge strength, a rough sharpness/artifact proxy. Every clip is measured at the 480p clips' size, so clip 1 (720p) is scaled down first. The level depends on the picture, so compare the trend from clip 2 to clip 5 with the earlier runs, and trust your eyes over it:

- tail test (run_20260926_114533): last 2 s of the previous clip, all 480p: 23.49, 24.94, 25.95, 26.66, 27.18
- fixed_refs, whole previous clip as reference (quality fell off): 19.55, 20.65, 21.63, 22.47, 23.25
- fixed_refs, the 480p master as reference (flat): 19.55, 20.51, 20.56, 20.46, 20.52

What to check:
- Watch `full_video.mp4` straight through. Do clips 2 to 5 stay equally clean, or does the drift from the last tail test (visible from clip 2 on) still build up?
- The step from clip 1 to clip 2 (720p to 480p) is expected; what matters is whether clips 2 to 5 hold level.
- The seams: with the tail plus the master, do the cuts still look smooth?
