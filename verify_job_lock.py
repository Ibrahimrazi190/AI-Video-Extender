"""One running task per job: checks against a REAL Redis (the offline suite has none, and the lock is Lua plus key expiry).

Run it against a THROWAWAY Redis, never the stack's own (it calls flushdb):

    docker network create locknet
    docker run -d --name lockredis --network locknet redis:7-alpine
    docker run --rm --network locknet -e PYTHONPATH=/work -e OPENAI_API_KEY= -e KIE_API_KEY= \
        -e REDIS_URL=redis://lockredis:6379/0 -v "<project>:/work" -w /work ai-video-extender python verify_job_lock.py
    docker rm -f lockredis; docker network rm locknet

It makes no OpenAI or kie.ai call. It takes about 20 seconds because it waits for real lock expiry.
"""
import time, threading
import app
from fastapi.testclient import TestClient

app.JOB_LOCK_TTL = 3          # short, so expiry and renewal can be watched in seconds
ok = fail = 0
def check(label, cond):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("  PASS  " if cond else "  FAIL  ") + label, flush=True)

r = app.redis_client
r.flushdb()

# a. exclusion
with app.job_lock("j1"):
    check("a held job reports as running", app.job_is_running("j1"))
    try:
        with app.job_lock("j1"):
            second = True
    except app.JobBusy:
        second = False
    check("a second task cannot take a held job", second is False)
    check("a different job is unaffected", not app.job_is_running("j2"))
check("the lock is released when the block ends", not app.job_is_running("j1"))

# b. released even when the work fails
try:
    with app.job_lock("j1"):
        raise RuntimeError("boom")
except RuntimeError:
    pass
check("and when the work raises", not app.job_is_running("j1"))

# c. it only ever frees its own lock
with app.job_lock("j3"):
    r.set(app._lock_key("j3"), "someone-elses-token", ex=60)
check("a task never releases a lock that is no longer its own", r.get(app._lock_key("j3")) == "someone-elses-token")
r.delete(app._lock_key("j3"))

# d. renewal keeps a long task's lock alive well past the TTL
with app.job_lock("j4"):
    time.sleep(app.JOB_LOCK_TTL * 2.4)     # 7+ s on a 3 s lock
    check("a task that runs longer than the TTL still holds the job", app.job_is_running("j4"))
    check("and its TTL was renewed, not just left over", r.ttl(app._lock_key("j4")) > 0)
check("renewal stops with the task", not app.job_is_running("j4"))

# e. a crashed worker: nobody renews, so the lock runs out by itself
r.set(app._lock_key("j5"), "dead-worker", nx=True, ex=app.JOB_LOCK_TTL)
check("a crashed worker's lock still blocks right after the crash", app.job_is_running("j5"))
time.sleep(app.JOB_LOCK_TTL + 1)
check("and frees the job by itself within JOB_LOCK_TTL seconds", not app.job_is_running("j5"))

# f. the task: a second copy changes nothing; the first runs exactly once
calls = []
def fake_traced(job_id, **kw):
    calls.append(job_id)
    time.sleep(0.3)
app._execute_movie_job_traced = fake_traced
with app.job_lock("j6"):
    app.execute_movie_job.run("j6")
check("a second queued task for a running job does nothing at all", calls == [])
app.execute_movie_job.run("j6")
check("with nothing running it runs once", calls == ["j6"])
check("and releases the job afterwards", not app.job_is_running("j6"))
results = []
threads = [threading.Thread(target=lambda: app.execute_movie_job.run("j7")) for _ in range(4)]
calls.clear()
for t in threads: t.start()
for t in threads: t.join()
check("four copies started at the same instant: exactly one does the work", calls == ["j7"])

# g. the endpoint, through the real app
req = app.ClipRequest(topic="t", duration=15, clip_duration=5, mode="narrated_drama")
job = app.Job(request=req, resolution=req.resolution, mode=req.mode, status="failed",
              movie_bible={"pov_protagonist": "A"}, beats=[{"clip_number": 1}])
app.save_job(job)
c = TestClient(app.app)
with app.job_lock(job.id):
    resp = c.post(f"/jobs/{job.id}/resume")
    check("Resume on a running job is refused with 409", resp.status_code == 409)
    check("and says why", "still running" in resp.json()["detail"])
    check("and leaves the job exactly as it was", app.get_job(job.id).status == "failed")
resp = c.post(f"/jobs/{job.id}/resume")
check("Resume on a job nobody is running is accepted", resp.status_code == 202 and app.get_job(job.id).status == "generating")
# a job left 'generating' by a dead worker can still be resumed (its lock ran out)
app.update_job(job.id, status="generating")
resp = c.post(f"/jobs/{job.id}/resume")
check("a job left 'generating' by a dead worker can be resumed", resp.status_code == 202)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
