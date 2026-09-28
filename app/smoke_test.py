"""
Real-service smoke test: checks Groq + Hindsight + the agent end to end in about a minute.

Run (with your keys set in the same terminal):
    python -m app.smoke_test

It creates a few throwaway banks named smoke-<number>. Your demo banks are not touched.
"""
import os
import sys
import time

os.environ["BANK_ID"] = f"smoke-{int(time.time())}"  # must be set BEFORE importing the agent

missing = [k for k in ("GROQ_API_KEY", "HINDSIGHT_API_KEY", "HINDSIGHT_BASE_URL") if not os.environ.get(k)]
if missing:
    print("Missing environment variables:", ", ".join(missing))
    print("Set them in this terminal first, then run again.")
    sys.exit(1)

from app.agent import OnCallCopilot  # noqa: E402

results = []


def run(name, fn):
    t0 = time.time()
    try:
        out = fn()
        status, note = out if isinstance(out, tuple) else ("PASS", out or "")
    except Exception as exc:  # show the real reason
        status, note = "FAIL", f"{type(exc).__name__}: {str(exc)[:200]}"
    results.append((name, status, note))
    print(f"[{status}] {name}  {note}  ({time.time() - t0:.1f}s)", flush=True)


state = {}


def start():
    state["c"] = OnCallCopilot()
    c = state["c"]
    state["A"], state["B"] = c.bank_for("project-a"), c.bank_for("project-b")
    return f"prefix={c.prefix}"


def groq_ping():
    reply = state["c"]._chat("Reply with exactly one word.", "Say: pong")
    return ("PASS", reply.strip()[:30]) if "pong" in reply.lower() else ("WARN", f"unexpected reply: {reply[:40]}")


def create_bank():
    c = state["c"]
    c.ensure_bank(state["A"])
    if state["A"] not in c._ready:
        raise RuntimeError(c.last_error or "bank not created")
    return state["A"]


def retain():
    state["c"]._retain(
        state["A"],
        "INCIDENT RESOLVED: service smoke-svc failed with error XYZ-CANARY-42 after a deploy. "
        "RESOLUTION: restarted the worker and rolled back the config change.",
    )
    return "stored 1 incident"


def recall():
    c = state["c"]
    for _ in range(10):  # allow a little indexing time
        found = c._recall(state["A"], "smoke-svc failure after deploy")
        if found:
            return f"{len(found)} fact(s) recalled"
        time.sleep(4)
    return "WARN", "nothing recalled after 40s (indexing may be slow; retry the test)"


def isolation():
    c = state["c"]
    c.ensure_bank(state["B"])
    leaked = c._recall(state["B"], "smoke-svc failure after deploy")
    hits = c.probe(state["B"], "CANARY")
    if leaked or hits:
        raise RuntimeError(f"project B can see project A data ({len(leaked)} facts)")
    return "project B sees 0 facts from project A"


def empty_diagnosis():
    d = state["c"].handle_incident("Customers say the site feels slow since this morning.", bank_id=state["B"], use_shared=False)
    if d["memories_found"] != 0:
        return "WARN", f"expected 0 memories, got {d['memories_found']}"
    if "did not return structured" in d.get("confidence_reason", ""):
        return "WARN", "LLM did not return valid JSON (agent used its fallback)"
    return f"needs_more_info={d['needs_more_info']}, severity={d['severity']}"


def memory_hit():
    d = state["c"].handle_incident("service smoke-svc failing with XYZ-CANARY-42 after deploy", bank_id=state["A"], use_shared=False)
    if d["project_found"] == 0:
        return "WARN", "nothing recalled (indexing delay?)"
    if not d["matched_past_incidents"]:
        return "WARN", f"{d['project_found']} facts recalled but the LLM did not cite a match"
    return f"recalled {d['project_found']} facts, matched {len(d['matched_past_incidents'])} incident(s)"


def sanitize():
    r = state["c"].sanitize_lesson("ALERT service=smoke-svc", "restarted smoke-svc worker", "Smoke Project")
    if "smoke-svc" in r["lesson"].lower():
        raise RuntimeError("service name leaked into the shared lesson")
    return f"{r['redactions']} item(s) redacted"


def reflect():
    out = state["c"].ask_memory("What failed in this project and how was it fixed?", bank_id=state["A"])
    if out["method"] == "Hindsight reflect":
        return "reflect works"
    return "WARN", f"reflect failed, fallback used: {out['method']}"


print(f"Running smoke test (bank prefix {os.environ['BANK_ID']})...\n")
run("1. Start agent (Hindsight + Groq clients)", start)
if results[-1][1] == "FAIL":
    sys.exit(1)
run("2. Groq LLM answers", groq_ping)
run("3. Hindsight creates a bank", create_bank)
run("4. Hindsight retain (save memory)", retain)
run("5. Hindsight recall (find memory)", recall)
run("6. Project isolation (B cannot see A)", isolation)
run("7. Diagnose with empty memory", empty_diagnosis)
run("8. Diagnose with memory hit", memory_hit)
run("9. Anonymizer strips names", sanitize)
run("10. Hindsight reflect (Ask the memory)", reflect)

fails = [r for r in results if r[1] == "FAIL"]
warns = [r for r in results if r[1] == "WARN"]
print("\n" + "=" * 60)
if not fails and not warns:
    print("ALL GOOD: safe to run the dashboard and record the demo.")
elif not fails:
    print(f"MOSTLY GOOD: {len(warns)} warning(s). The app works; read the WARN lines above.")
else:
    print(f"{len(fails)} FAILED. Copy the [FAIL] lines above (NOT your keys) and send them to me.")
if state.get("c") and state["c"].last_error:
    print("Last bank error:", state["c"].last_error)