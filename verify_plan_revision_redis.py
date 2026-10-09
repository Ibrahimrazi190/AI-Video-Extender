"""Plan revision against a REAL Redis: real job saves, the real versions key, the real endpoints. Only the model calls are faked.

Run it against a THROWAWAY Redis, never the stack's own (it calls flushdb):

    docker network create locknet
    docker run -d --name lockredis --network locknet redis:7-alpine
    docker run --rm --network locknet -e PYTHONPATH=/work -e OPENAI_API_KEY= -e KIE_API_KEY= \
        -e REDIS_URL=redis://lockredis:6379/0 -v "<project>:/work" -w /work ai-video-extender python verify_plan_revision_redis.py
    docker rm -f lockredis; docker network rm locknet

It makes no OpenAI or kie.ai call.
"""
import copy
import json

import app
import hybrid_narrated_drama as hnd
from fastapi.testclient import TestClient

ok = fail = 0


def check(label, cond):
    global ok, fail
    ok += bool(cond)
    fail += (not cond)
    print(("  PASS  " if cond else "  FAIL  ") + label, flush=True)


app.redis_client.flushdb()
bible = {"pov_protagonist": "Ethan Blackwood",
         "characters": [{"name": "Ethan Blackwood"}, {"name": "Lily Chen"}], "locations": [{"id": "stall"}], "props": []}
beats = [{"clip_number": n, "delivery_mode": "dialogue", "location_id": "stall", "present_characters": ["Ethan Blackwood", "Lily Chen"],
          "speaker_or_actor": "Ethan Blackwood", "summary": f"summary {n}", "speech_budget": 7,
          "audio_lines": [{"speaker": "Ethan Blackwood", "line": f"line {n} one two three four"}]} for n in range(1, 13)]
req = app.ClipRequest(topic="a premise", duration=60, mode="narrated_drama")
job = app.Job(request=req, resolution=req.resolution, mode="narrated_drama", status="plan_ready", movie_bible=bible, beats=beats,
              plan_report={"problems": ["[REVIEW] kept"]})
app.save_job(job)
jid = job.id

# the model is faked; everything else is real: the endpoints, the Job model, the Redis store, the lock
hnd.propose_plan_revision = lambda note, rules, b, acts, bb, premise="": {
    "items": [{"text": "Lily never recognises Jack", "kind": "rule", "in_scope": True, "why_out_of_scope": "", "replaces_rule_ids": []}],
    "rules_new": ["Lily never recognises Jack"], "replaces": [], "blocked": None, "clips": [{"clip": 3, "reason": "r", "change": "c"}]}
hnd.apply_plan_revision = lambda sel, instr, rules, b, bb, d, a: {
    "beats": [dict(x, summary="REVISED") if x["clip_number"] in sel else x for x in b],
    "changed": [{"clip": n, "before": {"summary": "s", "lines": []}, "after": {"summary": "REVISED", "lines": []}} for n in sel],
    "unresolved": [], "notes": []}
hnd.verify_plan_revision = lambda rules, b, acts=None: []
hnd.plan_delivery_report = lambda plan: {"problems": [], "stats": {}}
app.propose_plan_revision_task.delay = lambda j: app.propose_plan_revision_task.run(j)          # the real task body, with its real lock
app.apply_plan_revision_task.delay = lambda j, chosen: app.apply_plan_revision_task.run(j, chosen)

c = TestClient(app.app)
r = c.post(f"/jobs/{jid}/revise-plan", json={"note": "Lily must not recognise him"})
j = app.get_job(jid)
check("the proposal is stored in Redis through the real task, with its lock released afterwards",
      r.status_code == 202 and j.revision["status"] == "proposed" and not app.job_is_running(jid))
r = c.post(f"/jobs/{jid}/revise-plan/add-clips", json={"clips": [9, 5]})
j = app.get_job(jid)
check("clips added by hand are stored with the proposal in Redis, ticked and sorted",
      r.status_code == 200 and [x["clip"] for x in j.revision["clips"]] == [3, 5, 9] and j.revision["clips"][1].get("manual") is True and j.revision["clips"][1]["selected"])
check("a clip the plan does not have is refused", c.post(f"/jobs/{jid}/revise-plan/add-clips", json={"clips": [40]}).status_code == 400)
r = c.post(f"/jobs/{jid}/revise-plan/apply", json={"clips": [3]})
j = app.get_job(jid)
check("applying changes only the ticked clip, saves the rule, and records the result",
      r.status_code == 202 and j.beats[2]["summary"] == "REVISED" and j.beats[3]["summary"] == "summary 4"
      and j.plan_rules and j.plan_rules[0]["text"] == "Lily never recognises Jack" and j.revision["status"] == "applied")
raw = app.redis_client.get(f"jobplanv:{jid}")
check("the earlier version is stored beside the job, in its own Redis key", raw and len(json.loads(raw)) == 1 and json.loads(raw)[0]["beats"][2]["summary"] == "summary 3")
body = c.get(f"/jobs/{jid}").json()
check("the job the dashboard polls carries the count but NOT the saved plans", body["plan_versions_count"] == 1 and "plan_versions" not in body and "jobplanv" not in json.dumps(body))
check("the polled job is small however many versions there are", len(json.dumps(body)) < 60000)
c.post(f"/jobs/{jid}/revise-plan/cancel")
r = c.post(f"/jobs/{jid}/undo-plan-revision")
j = app.get_job(jid)
check("undo restores the plan from Redis, and removes the key when none are left",
      r.status_code == 200 and j.beats[2]["summary"] == "summary 3" and j.plan_rules is None and j.plan_versions_count == 0 and app.redis_client.get(f"jobplanv:{jid}") is None)
# the lock: a revision cannot be started, or cleared, while another task holds the job
with app.job_lock(jid):
    check("a held job refuses to have a stuck revision cleared", c.post(f"/jobs/{jid}/revise-plan/cancel").status_code == 409)
    app.update_job(jid, revision={"status": "proposing", "note": "n"})
    app.propose_plan_revision_task.run(jid)            # a second task for the same job: stops at once
    check("a second revision task for a held job changes nothing", app.get_job(jid).revision["status"] == "proposing")
app.update_job(jid, revision=None)
# versions are capped at 5 in Redis
for k in range(8):
    app.update_job(jid, revision={"status": "proposed", "note": f"n{k}", "items": [], "rules_new": [], "replaces": [], "blocked": None,
                                  "clips": [{"clip": 2, "reason": "r", "change": "c"}]})
    c.post(f"/jobs/{jid}/revise-plan/apply", json={"clips": [2]})
check("only the last 5 versions are kept in Redis", len(json.loads(app.redis_client.get(f"jobplanv:{jid}"))) == 5 and app.get_job(jid).plan_versions_count == 5)
# a re-plan drops the versions; deleting the job drops them too
app.update_job(jid, revision=None)
c.post(f"/jobs/{jid}/replan")
check("a re-plan removes the saved versions", app.redis_client.get(f"jobplanv:{jid}") is None and app.get_job(jid).plan_versions_count == 0)
app.update_job(jid, status="plan_ready")
app.redis_client.set(f"jobplanv:{jid}", json.dumps([{"beats": []}]))
c.delete(f"/jobs/{jid}")
check("deleting a job deletes its saved versions too", app.redis_client.get(f"jobplanv:{jid}") is None and app.get_job(jid) is None)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
