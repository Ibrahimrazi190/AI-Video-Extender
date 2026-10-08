import app
import json

jid = 'd54e40da80484c26aefeffb5a039763f'
job = app.get_job(jid)
if not job:
    print("Job not found!")
    exit(1)

print(f"=== JOB {jid} CLIPS 13 TO 19 AUDIT ===")
for i in range(12, 19):

    c = job.clips[i]
    ms = c.movie_script or {}
    mode = ms.get('delivery_mode')
    loc = ms.get('location_id')
    speech = ms.get('speech', [])
    shot = ms.get('shot', '')
    actions = [f"{a.get('character')}: {a.get('action')}" for a in ms.get('action_steps', [])]
    speech_str = ' | '.join(f"{s.get('speaker')}: \"{s.get('line')}\"" for s in speech)
    print(f"Clip {i+1:02d} [{mode}] in {loc} (status: {c.status})")
    print(f"  Shot: {shot}")
    print(f"  Audio: {speech_str}")
    print(f"  Actions: {'; '.join(actions)}")
    print()
