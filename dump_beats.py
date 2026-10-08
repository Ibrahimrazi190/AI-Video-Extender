import app
import json

jid = '8b7f939314de4ba896867b6c972d0afe'
job = app.get_job(jid)
if not job:
    print("Job not found!")
    exit(1)

print(f"=== JOB {jid} (mode={job.mode}, status={job.status}) ===")
print("Scene Bible Characters:")
for c in job.movie_bible.get('characters', []):
    print(f"  {c['name']} ({c['role'] if 'role' in c else ''}): hair={c.get('appearance', {}).get('hair_color')}, voice={c.get('voice')}")

print("\nScene Bible Locations:")
for l in job.movie_bible.get('locations', []):
    print(f"  {l['id']}: {l['description'][:80]}...")

print("\n--- BEATS 1 to 7 ---")
for idx, b in enumerate(job.beats[:7], 1):
    mode = b.get('delivery_mode')
    loc = b.get('location_id')
    chars = ", ".join(b.get('present_characters', [])) or "nobody"
    lines = " | ".join(f"{t.get('speaker')}: \"{t.get('line')}\"" for t in b.get('audio_lines', []))
    summary = b.get('summary', '')
    reveals = b.get('reveals', [])
    rev_str = f" [Reveals: {reveals}]" if reveals else ""
    print(f"Clip {idx:02d} [{mode}] in {loc} ({chars})")
    print(f"  Action/Summary: {summary}")
    if lines:
        print(f"  Audio: {lines}")
    if rev_str:
        print(f" {rev_str}")
    print()


