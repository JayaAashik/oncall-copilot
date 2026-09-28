"""On-Call Copilot dashboard (v3.1).  Run:  python -m streamlit run app/dashboard.py"""
from datetime import datetime

import pandas as pd
import streamlit as st

from app import projects as prj
from app.agent import OnCallCopilot
from app.seed_data import PAST_INCIDENTS, seed, seed_global

st.set_page_config(page_title="On-Call Copilot", page_icon="🚨", layout="wide")

st.markdown(
    """
<style>
header[data-testid="stHeader"] {display:none;} #MainMenu, footer {visibility:hidden;}
html, body, [class*="css"] {font-family: "Segoe UI", system-ui, -apple-system, sans-serif;}
.block-container {padding-top: 1rem; max-width: 1180px;}
.hero {background: linear-gradient(120deg,#0078D4 0%,#004E8C 100%); padding: 1.1rem 1.5rem; border-radius: 14px; color:#fff; margin-bottom:.9rem;}
.hero h1 {margin:0; font-size:1.6rem; color:#fff; font-weight:700;}
.hero p {margin:.25rem 0 0 0; opacity:.92; font-size:.95rem;}
.strip {display:grid; grid-template-columns: repeat(3, 1fr); gap:.8rem; margin:0 0 .8rem 0;}
.stat {border:1px solid rgba(128,128,128,.25); border-radius:12px; padding:.6rem 1rem; background: rgba(128,128,128,.05);}
.stat .k {font-size:.7rem; text-transform:uppercase; letter-spacing:.07em; opacity:.65;}
.stat .v {font-size:1.02rem; font-weight:700; margin-top:.1rem;}
.steps {display:flex; gap:.5rem; flex-wrap:wrap; margin:0 0 1rem 0;}
.step {padding:.28rem .85rem; border-radius:999px; font-size:.82rem; border:1px solid rgba(128,128,128,.35);}
.step.done {background:#E3F6E8; color:#107C10; border-color:#B7E4C1; font-weight:600;}
.banner {border-radius:12px; padding:.85rem 1.1rem; margin-bottom:.7rem; font-size:.98rem; line-height:1.4;}
.banner.memory {background:#E3F6E8; color:#0B5A0B;} .banner.shared {background:#EDE7F6; color:#3F2A82;}
.banner.new {background:#FFF0DD; color:#8A3B00;} .banner.info {background:#E5F1FB; color:#004E8C;}
.badge {display:inline-block; padding:.2rem .7rem; border-radius:999px; font-weight:700; font-size:.8rem; margin-right:.35rem;}
.sev-P1 {background:#FDE7E9; color:#A80000;} .sev-P2 {background:#FFF0DD; color:#B34700;}
.sev-P3 {background:#FFF9D6; color:#7A6400;} .sev-P4 {background:#E3F6E8; color:#107C10;}
.conf-High {background:#E3F6E8; color:#107C10;} .conf-Medium {background:#FFF9D6; color:#7A6400;}
.conf-Low {background:#FDE7E9; color:#A80000;} .cat {background:#E5F1FB; color:#004E8C;} .proj {background:#EDE7F6; color:#4A148C;}
.card {border:1px solid rgba(128,128,128,.3); border-left:5px solid #0078D4; border-radius:10px; padding:.7rem 1rem; margin:.45rem 0; background: rgba(0,120,212,.05);}
.card.memory {border-left-color:#107C10; background: rgba(16,124,16,.06);}
.card.shared {border-left-color:#6B4FBB; background: rgba(107,79,187,.07);}
.small {font-size:.85rem; opacity:.78;}
.sec {font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; opacity:.6; margin:.2rem 0 .3rem 0; font-weight:700;}
</style>
""",
    unsafe_allow_html=True,
)

SAMPLES = {
    "🔁 Recurring pattern (SQL connection pool)": (
        "ALERT [prod] service=search-api severity=P1\n"
        "502 Bad Gateway rate: 210/min (baseline: 1/min)\n"
        "Logs: 'Timeout expired. The timeout period elapsed prior to obtaining a connection from the pool' (Azure SQL)\n"
        "Started: 90 seconds ago, during a scheduled reindex job."
    ),
    "📨 Service Bus dead-letter growth": (
        "ALERT [prod] service=shipment-processor severity=P2\n"
        "Azure Service Bus queue 'shipments': dead-letter count 12 -> 940 in 20 minutes\n"
        "Consumer logs: JsonException while deserializing message; deploy of producer finished 14:10 UTC."
    ),
    "🔐 TLS certificate errors": (
        "ALERT [prod] service=partner-gateway severity=P1\n"
        "Azure Front Door: clients failing TLS handshake, 'certificate has expired'. Started 07:52 UTC."
    ),
    "🐛 Code bug (stack trace)": (
        "ALERT [prod] service=billing-api severity=P2\n"
        "System.InvalidOperationException: Timeout expired obtaining a connection from the pool\n"
        "   at BillingRepository.GetInvoice(Int32 id) in BillingRepository.cs:line 41\n"
        "Code: var conn = new SqlConnection(cs); conn.Open(); var r = conn.Query(sql); return r; // no Dispose"
    ),
    "🆕 Brand-new problem (no history)": (
        "ALERT [prod] service=ml-inference severity=P2\n"
        "GPU node pool: pods crash-looping with 'CUDA out of memory' every ~10 minutes after model v4 rollout.\n"
        "Request latency p95 up 6x."
    ),
    "❓ Vague alert (agent should ask questions)": "Customers are saying the site feels slow since this morning.",
}

for key, default in {
    "projects": prj.load(), "alert_text": list(SAMPLES.values())[0], "result": None, "result_alert": "",
    "history": [], "fb_done": False, "retained": False, "postmortem": None, "status": None,
    "qa": [], "lesson": None, "shared": False, "seeded_map": {}, "global_loaded": None, "agent_trace": [],
}.items():
    st.session_state.setdefault(key, default)


@st.cache_resource(show_spinner="Connecting to Hindsight and Groq...")
def get_copilot():
    return OnCallCopilot()


try:
    copilot = get_copilot()
except Exception as exc:
    st.error(f"Could not start the agent: {exc}")
    st.info("Check that GROQ_API_KEY, HINDSIGHT_API_KEY and HINDSIGHT_BASE_URL are set in this terminal.")
    st.stop()


def reset_result():
    st.session_state.update(result=None, fb_done=False, retained=False, postmortem=None, status=None,
                            lesson=None, shared=False)
    for k in ("lesson_edit", "resolution", "extra_details"):
        st.session_state.pop(k, None)


def load_sample():
    st.session_state.alert_text = SAMPLES[st.session_state.sample_choice]


def create_project():
    name = st.session_state.get("new_project", "").strip()
    if name and name.lower() not in [p["name"].lower() for p in st.session_state.projects]:
        st.session_state.projects.append({"name": name, "use_shared": True, "contribute": True})
        prj.save(st.session_state.projects)
        st.session_state.project_name = name
        reset_result()
    st.session_state.new_project = ""


names = [p["name"] for p in st.session_state.projects]
if st.session_state.get("project_name") not in names:
    st.session_state.project_name = names[0]
proj = next(p for p in st.session_state.projects if p["name"] == st.session_state.project_name)
slug = prj.slugify(proj["name"])
bank = copilot.bank_for(slug)

if bank not in st.session_state.seeded_map:
    st.session_state.seeded_map[bank] = copilot.has_memory(bank)
if st.session_state.global_loaded is None:
    st.session_state.global_loaded = copilot.has_memory(copilot.global_bank)
has_mem = st.session_state.seeded_map[bank]


def run_diagnosis(alert):
    with st.spinner("🤖 Agent is deciding which tools to call..."):
        try:
            res = copilot.run_autonomous_agent(alert, bank_id=bank, use_shared=proj["use_shared"])
        except Exception as exc:
            st.error(f"Diagnosis failed: {exc}")
            return
    reset_result()
    st.session_state.result, st.session_state.result_alert = res, alert
    st.session_state.agent_trace = res.get("agent_trace", [])
    st.session_state.history.append({
        "Time": datetime.now().strftime("%H:%M:%S"), "Project": proj["name"],
        "Alert": alert.strip().splitlines()[0][:50], "Severity": res["severity"], "Confidence": res["confidence"],
        "Project memories": res["project_found"], "Shared lessons": res["shared_found"],
        "Outcome": "Needs info" if res["needs_more_info"] else (
            "Recognised" if res["matched_past_incidents"] else "New pattern"),
        "Retained": "No",
    })


def change_project_from_top():
    st.session_state.project_name = st.session_state.top_project_name
    reset_result()


def load_shared_lessons_action():
    bar = st.progress(0, text="Starting shared lessons...")
    try:
        copilot.ensure_bank(copilot.global_bank, "Shared lessons")
        seed_global(copilot.hindsight, copilot.global_bank, on_progress=lambda i, n, t: bar.progress(i / n, text=f"Retaining {i}/{n}"))
        st.session_state.global_loaded = True
        st.success("Shared lessons loaded successfully.")
    except Exception as exc:
        st.error(f"Failed to load shared lessons: {exc}")

def load_project_history_action():
    bar = st.progress(0, text="Starting project history...")
    try:
        copilot.ensure_bank(bank, proj["name"])
        seed(copilot.hindsight, bank, on_progress=lambda i, n, t: bar.progress(i / n, text=f"Retaining {i}/{n}: {t}"))
        st.session_state.seeded_map[bank] = True
        st.success(f"Project history loaded for {proj['name']}.")
    except Exception as exc:
        st.error(f"Failed to load project history: {exc}")

def retain_current_fix_action():
    res = st.session_state.get("result")
    fix = st.session_state.get("resolution", "").strip()
    if not res:
        st.warning("Diagnose an alert first.")
        return
    if not fix:
        st.warning("Enter the actual resolution first.")
        return
    try:
        with st.spinner("Retaining the fix to this project's private Hindsight memory..."):
            copilot.resolve_and_retain(st.session_state.result_alert, fix, res, bank_id=bank)
        st.session_state.retained = True
        st.session_state.seeded_map[bank] = True
        if st.session_state.history:
            st.session_state.history[-1]["Retained"] = "Yes"
        st.success("Fix retained privately in Hindsight.")
    except Exception as exc:
        st.error(f"Could not retain the fix: {exc}")


# ---------------- sidebar (kept short on purpose) ----------------
with st.sidebar:
    st.markdown("### 📁 Project")
    st.caption("Choose the active project from the main selector above.")
    st.caption(f"🔒 Private bank: `{bank}`")

    with st.expander("🔒 Sharing settings"):
        use_shared = st.checkbox("Use shared lessons (anonymized)", value=proj["use_shared"], key=f"us_{slug}")
        contribute = st.checkbox("Offer to share lessons after a fix (I review first)", value=proj["contribute"], key=f"co_{slug}")
        if (use_shared, contribute) != (proj["use_shared"], proj["contribute"]):
            proj["use_shared"], proj["contribute"] = use_shared, contribute
            prj.save(st.session_state.projects)

    with st.expander("🌱 Demo data (load once)", expanded=not (has_mem and st.session_state.global_loaded)):
        st.caption("Shared lessons = generic tips from other teams. Project history = this project's own past incidents.")
        if st.button("🌐 Load shared lessons", disabled=bool(st.session_state.global_loaded), width="stretch"):
            load_shared_lessons_action()
        if st.button("🌱 Load project history", disabled=has_mem, width="stretch"):
            load_project_history_action()

    with st.expander("➕ New project"):
        st.text_input("Project name", key="new_project")
        st.button("Create project", on_click=create_project)

    if copilot.last_error:
        st.warning(copilot.last_error)

# ---------------- header + status ----------------
st.markdown(
    """<div class="hero"><h1>🚨 On-Call Copilot</h1>
<p>An incident-response agent that remembers every fix, keeps each project's data private, and shares only anonymized lessons. Powered by Hindsight.</p></div>""",
    unsafe_allow_html=True,
)

# These are real Streamlit controls. The previous version used HTML <span> elements for the four steps,
# so they looked like buttons but could not actually be clicked.
project_col, memory_col, shared_col = st.columns([1.3, 1, 1])
with project_col:
    st.selectbox("📁 Active project", names, index=names.index(st.session_state.project_name), key="top_project_name", on_change=change_project_from_top)
with memory_col:
    st.metric("🔒 Private memory", "Has history" if has_mem else "Cold start")
with shared_col:
    st.metric("🌐 Shared lessons", "Loaded" if st.session_state.global_loaded else "Empty")

st.markdown("### Demo controls")
c1, c2, c3, c4 = st.columns(4)
with c1:
    if st.button("① 🌐 Shared lessons", width="stretch", disabled=bool(st.session_state.global_loaded)):
        load_shared_lessons_action()
with c2:
    if st.button("② 🌱 Project history", width="stretch", disabled=has_mem):
        load_project_history_action()
with c3:
    if st.button("③ 🔍 Diagnose", type="primary", width="stretch"):
        alert_now = st.session_state.get("alert_text", "").strip()
        if alert_now:
            run_diagnosis(alert_now)
        else:
            st.warning("Choose or enter an alert first.")
with c4:
    if st.button("④ 🧠 Retain fix", width="stretch", disabled=bool(st.session_state.retained)):
        retain_current_fix_action()

st.divider()

tab_console, tab_ask, tab_privacy, tab_insights, tab_how = st.tabs(
    ["🚨 Incident console", "💬 Ask the memory", "🔒 Privacy & isolation", "📊 Insights", "⚙️ How it works"]
)

# ---------------- console ----------------
with tab_console:
    left, right = st.columns([1, 1.55], gap="large")

    with left:
        with st.container(border=True):
            st.markdown('<div class="sec">Incoming alert</div>', unsafe_allow_html=True)
            st.selectbox("Sample scenario", list(SAMPLES.keys()), key="sample_choice", on_change=load_sample)
            alert = st.text_area("Alert, error log or stack trace", key="alert_text", height=230)
            if st.button("🔍 Diagnose incident", type="primary", width="stretch"):
                if alert.strip():
                    run_diagnosis(alert)
                else:
                    st.warning("Paste an alert first.")
            st.caption("Reads only THIS project's private memory, plus anonymized shared lessons if enabled.")

    with right:
        res = st.session_state.result
        if not res:
            st.info("Choose a sample scenario on the left, then click **Diagnose incident**.")
        else:
            mine = [m for m in res["matched_past_incidents"] if m.get("source") != "shared_lesson"]
            shared = [m for m in res["matched_past_incidents"] if m.get("source") == "shared_lesson"]

            # ---------------- autonomous agent activity ----------------
            with st.container(border=True):
                st.markdown('<div class="sec">🤖 Agent activity · autonomous tool calling</div>', unsafe_allow_html=True)
                trace = res.get("agent_trace", [])
                if not trace:
                    st.info("No tool trace was returned. The deterministic fallback may have been used.")
                else:
                    for i, item in enumerate(trace, 1):
                        tool = item.get("tool", "unknown")
                        status = item.get("status", "")
                        preview = item.get("result_preview", "")
                        icon = "✅" if status == "completed" else ("⚠️" if status in ("error", "fallback") else "🔄")
                        st.markdown(f"**{icon} {i}. `{tool}`** — {status}")
                        if preview:
                            st.caption(str(preview))
                    st.caption(f"Agent mode: `{res.get('agent_mode', 'unknown')}` · Tool calls: {res.get('tool_calls', 0)}")

            with st.container(border=True):
                if mine:
                    st.markdown(f'<div class="banner memory">🧠 <b>Memory hit in this project.</b> Hindsight recalled {res["project_found"]} facts and the agent matched {len(mine)} of your own past incident(s).</div>', unsafe_allow_html=True)
                elif shared:
                    st.markdown('<div class="banner shared">🌐 <b>New for this project, seen elsewhere.</b> No history here, but an anonymized shared lesson applies.</div>', unsafe_allow_html=True)
                elif res["needs_more_info"]:
                    st.markdown('<div class="banner info">❓ <b>Not enough detail yet.</b> Answer the questions below to get a precise diagnosis.</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="banner new">🆕 <b>New to the team.</b> Nothing relevant in memory, so this is a best-effort answer. Retain the fix to teach the agent.</div>', unsafe_allow_html=True)

                st.markdown(
                    f'<span class="badge sev-{res["severity"]}">Severity {res["severity"]}</span>'
                    f'<span class="badge conf-{res["confidence"]}">Confidence: {res["confidence"]}</span>'
                    f'<span class="badge cat">{res["category"]}</span>', unsafe_allow_html=True)
                if res["confidence_reason"]:
                    st.caption(res["confidence_reason"])
                st.markdown(f"**What is happening.** {res['summary']}")
                if res["likely_root_cause"]:
                    st.markdown(f"**Likely root cause.** {res['likely_root_cause']}")
                for m in mine:
                    meta = " · ".join(x for x in [m.get("date"), m.get("runbook"), f"Owner: {m['owner']}" if m.get("owner") else None] if x)
                    st.markdown(f'<div class="card memory">🔒 <b>{m.get("title", "Past incident")}</b> <span class="small">(this project)</span><br><span class="small">{meta}</span><br>Fix that worked: {m.get("what_fixed_it", "")}</div>', unsafe_allow_html=True)
                for m in shared:
                    st.markdown(f'<div class="card shared">🌐 <b>{m.get("title", "Shared lesson")}</b> <span class="small">(anonymized, from other projects)</span><br>{m.get("what_fixed_it", "")}</div>', unsafe_allow_html=True)
                if res["past_resolution_time"]:
                    st.markdown(f"⏱️ **Last time this took:** {res['past_resolution_time']}")

                if res["needs_more_info"] and res["clarifying_questions"]:
                    st.markdown("**Questions to narrow it down**")
                    for q in res["clarifying_questions"]:
                        st.markdown(f"- {q}")
                    extra = st.text_area("Your answers / extra details", key="extra_details", height=90)
                    if st.button("🔄 Re-diagnose with these details"):
                        run_diagnosis(st.session_state.result_alert + "\n\nADDITIONAL DETAILS FROM ENGINEER:\n" + extra)
                        st.rerun()

            with st.container(border=True):
                st.markdown('<div class="sec">Recommended actions</div>', unsafe_allow_html=True)
                for i, a in enumerate(res["immediate_actions"], 1):
                    st.markdown(f"**{i}.** {a}")
                if res.get("code_suggestion"):
                    st.markdown("**Suggested code / config fix**")
                    st.code(str(res["code_suggestion"]))
                if res["long_term_fixes"]:
                    with st.expander("Long-term fixes"):
                        for a in res["long_term_fixes"]:
                            st.markdown(f"- {a}")
                with st.expander(f"Memory used ({res['project_found']} project facts, {res['shared_found']} shared lessons)"):
                    st.text(res["memory_text"])

            with st.container(border=True):
                st.markdown('<div class="sec">Close the loop: this is how the agent learns</div>', unsafe_allow_html=True)
                c1, c2, c3 = st.columns([1, 1, 2])
                if not st.session_state.fb_done:
                    if c1.button("👍 Helpful"):
                        copilot.record_feedback(st.session_state.result_alert, res, True, bank_id=bank)
                        st.session_state.fb_done = True
                        st.rerun()
                    if c2.button("👎 Not helpful"):
                        copilot.record_feedback(st.session_state.result_alert, res, False, bank_id=bank)
                        st.session_state.fb_done = True
                        st.rerun()
                    c3.caption("Rate the advice so the agent learns what works.")
                else:
                    st.success("Feedback saved to this project's memory.")

                fix = st.text_input("How was it actually resolved?", key="resolution")
                if st.button("✅ Resolve and retain to memory", disabled=st.session_state.retained):
                    if fix.strip():
                        with st.spinner("Retaining to this project's private memory..."):
                            copilot.resolve_and_retain(st.session_state.result_alert, fix, res, bank_id=bank)
                        st.session_state.retained = True
                        st.session_state.seeded_map[bank] = True
                        if st.session_state.history:
                            st.session_state.history[-1]["Retained"] = "Yes"
                        st.rerun()
                    else:
                        st.error("Write the resolution first.")

                if st.session_state.retained:
                    st.success("Retained privately. The next similar incident in THIS project will recall this fix.")
                    if proj["contribute"]:
                        if st.session_state.lesson is None:
                            with st.spinner("Preparing an anonymized lesson for review..."):
                                st.session_state.lesson = copilot.sanitize_lesson(
                                    st.session_state.result_alert, st.session_state.get("resolution", ""), proj["name"])
                        les = st.session_state.lesson
                        st.markdown(f'<div class="card shared">🌐 <b>Optional: share what you learned, anonymized.</b><br><span class="small">{les["redactions"]} identifying item(s) were removed automatically. Nothing is shared until you approve.</span></div>', unsafe_allow_html=True)
                        edited = st.text_area("Review the lesson (delete anything sensitive)", value=les["lesson"], key="lesson_edit", height=130)
                        if not st.session_state.shared:
                            if st.button("🌐 Share this lesson"):
                                copilot.share_lesson(edited, proj["name"], st.session_state.result_alert)
                                st.session_state.shared = True
                                st.session_state.global_loaded = True
                                st.rerun()
                        else:
                            st.success("Shared. Other projects benefit without seeing anything about yours.")
                    else:
                        st.info("🔒 Sharing is off for this project. Everything stays private.")

                b1, b2 = st.columns(2)
                if b1.button("📣 Draft Teams update"):
                    with st.spinner("Writing..."):
                        st.session_state.status = copilot.status_update(st.session_state.result_alert, res)
                if b2.button("📝 Draft post-mortem", disabled=not st.session_state.retained):
                    with st.spinner("Writing..."):
                        st.session_state.postmortem = copilot.postmortem(st.session_state.result_alert, st.session_state.get("resolution", ""), res)
                if st.session_state.status:
                    st.code(st.session_state.status, language=None)
                if st.session_state.postmortem:
                    with st.expander("Post-mortem draft", expanded=True):
                        st.markdown(st.session_state.postmortem)
                        st.download_button("Download .md", st.session_state.postmortem, file_name="postmortem.md")

# ---------------- ask memory ----------------
with tab_ask:
    st.subheader(f"Ask the memory of: {proj['name']}")
    st.caption("Powered by Hindsight reflect. It reasons over THIS project's private memory only.")
    quick = ["Which services fail most often and why?", "What recurring root causes should we fix permanently?",
             "Which past fixes were fastest and what made them fast?", "Who has handled the most database incidents?"]
    cols = st.columns(2)
    picked = None
    for i, q in enumerate(quick):
        if cols[i % 2].button(q, key=f"quick{i}", width="stretch"):
            picked = q
    typed = st.text_input("Or ask your own question", key="qa_input")
    if st.button("Ask", type="primary") and typed.strip():
        picked = typed.strip()
    if picked:
        with st.spinner("Reflecting over memory..."):
            try:
                st.session_state.qa.insert(0, (proj["name"], picked, copilot.ask_memory(picked, bank_id=bank)))
            except Exception as exc:
                st.error(f"Could not answer: {exc}")
    for pname, q, out in st.session_state.qa:
        with st.container(border=True):
            st.markdown(f"**Q: {q}**  \n<span class='small'>{pname} · via {out['method']}</span>", unsafe_allow_html=True)
            st.markdown(out["answer"])

# ---------------- privacy ----------------
with tab_privacy:
    st.subheader("Data isolation, proven live")
    st.markdown(
        "Every project has its **own Hindsight memory bank**. The agent never queries another project's bank, so data from an old "
        "project cannot appear in a new one. Only **anonymized lessons a human approved** reach the shared library."
    )
    st.graphviz_chart(
        """digraph G { rankdir=LR; node [shape=box, style="rounded,filled", fontname="Helvetica"];
        A [label="Project A\\nprivate bank", fillcolor="#DFF6DD"]; B [label="Project B\\nprivate bank", fillcolor="#DFF6DD"];
        S [label="Anonymizer\\n+ human review", fillcolor="#FFF9D6"]; L [label="Shared lessons\\n(no names, no IDs)", fillcolor="#EDE7F6"];
        A -> S [label=" fix"]; B -> S; S -> L; L -> A [style=dashed, label=" general tips"]; L -> B [style=dashed];
        A -> B [label=" BLOCKED", color=red, fontcolor=red, style=dotted, dir=none]; }"""
    )
    with st.container(border=True):
        st.markdown("**Try it.** Type a name or service from another project (for example `Priya` or `checkout-api`) and check whether this project can reach it.")
        term = st.text_input("Search term", value="Priya", key="probe_term")
        if st.button("🔎 Run isolation check"):
            with st.spinner("Searching..."):
                own = copilot.probe(bank, term)
                shared_hits = copilot.probe(copilot.global_bank, term)
            c1, c2 = st.columns(2)
            c1.metric(f"Hits in {proj['name']} private memory", len(own))
            c2.metric("Hits in shared lessons library", len(shared_hits))
            if not own and not shared_hits:
                st.success(f"No trace of '{term}' is reachable from this project. Isolation holds.")
            elif own:
                st.info("This term exists in THIS project's own history (expected, it is your own data).")
            if shared_hits:
                st.error("Found in the shared library. Review and remove this lesson.")
                for h in shared_hits:
                    st.text(h)

# ---------------- insights ----------------
with tab_insights:
    st.subheader("Session insights")
    hist = st.session_state.history
    recognised = sum(1 for h in hist if h["Outcome"] == "Recognised")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Incidents diagnosed", len(hist))
    m2.metric("Recognised from project memory", recognised)
    m3.metric("Fixes retained", sum(1 for h in hist if h["Retained"] == "Yes"))
    m4.metric("Memory-hit rate", f"{round(100 * recognised / len(hist))}%" if hist else "n/a")
    if hist:
        st.dataframe(pd.DataFrame(hist), width="stretch", hide_index=True)
    else:
        st.info("Diagnose a few incidents and they will show up here.")

# ---------------- how it works ----------------
with tab_how:
    st.subheader("How Hindsight memory powers the agent")
    st.markdown(
        """
1. **Recall.** Each alert searches this project's private Hindsight bank (and, if enabled, the anonymized shared library).
2. **Reason.** The LLM answers using only what was recalled. No match means it says so instead of inventing history.
3. **Retain.** Resolutions and 👍/👎 feedback are written back to the project's private bank.
4. **Share safely.** A fix can become a generic lesson, auto-redacted, and only shared after a human approves it.
5. **Reflect.** Teams can ask questions across their whole project memory.
        """
    )
    st.caption(f"Demo history size: {len(PAST_INCIDENTS)} synthetic incidents.")