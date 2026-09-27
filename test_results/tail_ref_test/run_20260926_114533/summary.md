# Tail-reference test

Topic: A young woman tells here story of why she left her husband while looking into the camera
Run folder: `test_results/tail_ref_test/run_20260926_114533/`
Settings: 5 clips x 5 s, 480p, bytedance/seedance-2-mini, mode talking_head.

The one change from the pipeline: each clip's video reference is the last 2 s of the previous clip (muted, plus one frame so it can't round under kie.ai's 2 s minimum), not the whole previous clip. Audio reference = clip 1's audio and image reference = clip 1's last frame, fixed for the whole run, as in the pipeline. Prompts are the pipeline's own.

| Clip | Line | Credits | Video kbps | Edge energy | Status |
|---|---|---|---|---|---|
| 1 | I kept telling myself love meant staying, even when I disappeared. | 19.0 | 1932 | 23.49 | ok |
| 2 | Then one night, he apologized before I'd even said anything. | 16.8 | 1956 | 24.94 | ok |
| 3 | I realized my silence had become part of our marriage. | 16.8 | 2044 | 25.95 | ok |
| 4 | So I packed one suitcase, called my sister, and chose breathing. | 16.8 | 2127 | 26.66 | ok |
| 5 | Leaving wasn't sudden; it was the first honest promise to myself. | 16.8 | 2059 | 27.18 | ok |

Total credits consumed: 86.2
`full_video.mp4`: joined without re-encoding

Edge energy is mean Sobel edge strength, a rough sharpness/artifact proxy. The same measure on the earlier 5-clip run (test_results/fixed_refs, a different topic): master 19.55; the whole previous clip as reference 20.65, 21.63, 22.47, 23.25 (quality fell off); the master as reference 20.51, 20.56, 20.46, 20.52 (flat). The level depends on the picture, so look at the trend from clip 2 to clip 5, and trust your eyes over it.

What to check:
- Watch `full_video.mp4` straight through. Do clips 4 and 5 look as clean as clip 2? (With the whole previous clip as the reference, clips 4 and 5 were very bad.)
- The seams: with only 2 s of motion to continue from, do the cuts still look smooth?
- `clipN/tail_sent_to_next_clip.mp4` is exactly what kie.ai received as the next clip's video reference.
