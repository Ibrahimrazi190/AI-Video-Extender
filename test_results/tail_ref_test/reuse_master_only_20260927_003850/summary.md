# Reuse test: 720p master only

Run folder: `test_results/tail_ref_test/reuse_master_only_20260927_003850/`
Source run: `test_results/tail_ref_test/master720_20260926_233941/` (its clip 1, master copy, audio and script are reused; clip 1 was not generated again).
Settings: clips 2 to 5 at 480p, 5 s, on bytedance/seedance-2-mini, mode talking_head.

References for clips 2 to 5: exactly two, the same every time: video = the whole 720p clip 1, muted, and audio = clip 1's audio. Nothing from the previous clip, no image. Prompts are the pipeline's own, so <Video 1> is the master. In the source run the same lines had three references: the last 2 s of the previous clip + the master + clip 1's last frame.

| Clip | Line | Credits | Edge energy now (at 864x496) | Same clip in the source run | Status |
|---|---|---|---|---|---|
| 1 | I left my husband after realizing love had become permission to disappear. | 0 | 27.72 | 27.72 | reused |
| 2 | At first, I called his control concern, and my silence compromise. | 24.0 | 28.17 | 28.36 | ok |
| 3 | Then I found my old journals and barely recognized that woman. | 24.0 | 28.24 | 28.54 | ok |
| 4 | So one morning, I packed two bags before he woke up. | 24.0 | 28.41 | 28.73 | ok |
| 5 | Leaving hurt, but staying would have cost me my whole self. | 24.0 | 28.21 | 28.59 | ok |

Total credits consumed: 96 (clip 1 reused, 0)
`full_video.mp4`: re-encoded at high quality, every clip scaled to 864x496 (clip 1 is 720p); judge quality on the single clips

Edge energy is mean Sobel edge strength, a rough sharpness/artifact proxy, measured at the 480p clips' size. The level depends on the picture; trust your eyes over it. Earlier runs, for the trend:

- tail test (run_20260926_114533): last 2 s of the previous clip, all 480p: 23.49, 24.94, 25.95, 26.66, 27.18
- fixed_refs, whole previous clip as reference (quality fell off): 19.55, 20.65, 21.63, 22.47, 23.25
- fixed_refs, the 480p master as reference (flat): 19.55, 20.51, 20.56, 20.46, 20.52

What to check:
- Compare each clip with the same-numbered clip in `master720_20260926_233941/`: same line, different references.
- The gliding: does the smooth, floaty motion still grow from clip 2 to clip 5, now that no clip sees the one before it?
- Quality: do clips 2 to 5 stay level with each other?
- The seams: every clip now starts from the master, not from where the previous clip ended, so expect jumps in pose at the cuts, and watch for clips repeating the same movements.
