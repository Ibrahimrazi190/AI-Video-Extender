# Fixed-references test

Source job: `90de45a2833348f2a2ec53c09812a64b` (topic: The reason I hate my husband, a girl tells while looking at the camera). 5 s clips, 480p.
Folders are relative to `test_results/fixed_refs/`.

References for every generated clip: video = the MASTER (first) clip, audio = the master's audio with its tail trimmed, image = the master's last frame. Nothing chains through another generated clip.
Audio trim: the audio already ends in silence, so the last word finished cleanly: keeping all speech (cut at 4.74 s, kept 4.74 s of 5.09 s).

| Folder / file | What it is | Status |
|---|---|---|
| `master/` | the first clip (video), its audio before and after trimming (mp3), and its last frame | prepared |
| `previous_run_chained/` | the earlier chained clips 2 to 5 (clips 4 and 5 were bad), for comparison | copied |
| `full_video_NEW_fixed_refs.mp4` | master + the new clips 2 to 5, stitched: watch this straight through | see below |
| `full_video_OLD_chained.mp4` | master + the old chained clips 2 to 5, stitched: the version that degraded | see below |
| `clip2/` | Clip 2 regenerated with all three references fixed to the master (line: "Then he started turning my dreams into jokes at dinner."). | ok |
| `clip3/` | Clip 3 regenerated with all three references fixed to the master (line: "I laughed along until I barely recognized my own voice."). | ok |
| `clip4/` | Clip 4 regenerated with all three references fixed to the master (line: "So when people ask why I hate him, that's why."). | ok |
| `clip5/` | Clip 5 regenerated with all three references fixed to the master (line: "He made me smaller, and I finally chose to leave."). | ok |

Total credits consumed (successful generations): 96

Rough per-clip measurements (edge energy = a sharpness proxy, higher = sharper; trust your eyes over the number):

| Clip | video kbps | edge energy |
|---|---|---|
| clip 1 (master) | 2192 | 24.29 |
| NEW clip 2 | 2274 | 25.22 |
| NEW clip 3 | 2150 | 25.28 |
| NEW clip 4 | 2163 | 24.96 |
| NEW clip 5 | 2123 | 25.01 |
| OLD clip 2 | 1987 | 25.31 |
| OLD clip 3 | 1927 | 26.31 |
| OLD clip 4 | 1912 | 27.16 |
| OLD clip 5 | 1988 | 28.28 |

What to check:
- Video: watch both stitched videos. In the OLD one quality falls off by clips 4 and 5. Does the NEW one stay as clean from clip 2 through clip 5?
- Audio: listen to the last second of every NEW clip. Is the "oment" (from "disappointment") gone, and is each clip's own last word clear?
- Seams and start pose: the video reference is now the master, not the previous clip, so look for odd jumps at the cuts (the trade-off), and for repeated movements.
