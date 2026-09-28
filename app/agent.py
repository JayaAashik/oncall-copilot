"""
On-Call Copilot - agent brain (v3: project-isolated memory + anonymized shared lessons).

Memory design (all on Hindsight):
  * One PRIVATE memory bank per project      -> full detail (services, owners, runbooks). Never read by other projects.
  * One SHARED LESSONS bank                  -> only anonymized, generic lessons that a human approved.
A new project starts with an empty private bank, but can still benefit from the shared lessons.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from groq import Groq
from hindsight_client import Hindsight

BANK_ID = os.environ.get("BANK_ID", "oncall-copilot")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

DIAGNOSE_SYSTEM = """You are On-Call Copilot, an incident-response agent for software teams (Azure-heavy stack).
You get:
- NEW ALERT
- PROJECT MEMORY: private facts from THIS project only (past incidents, fixes, engineer feedback).
- SHARED LESSONS: anonymized general lessons contributed by other projects. They did NOT happen in this project.

Return ONLY one JSON object (no markdown fences, no extra text) with exactly these keys:
{
  "needs_more_info": true/false,
  "clarifying_questions": ["..."],
  "severity": "P1" | "P2" | "P3" | "P4",
  "category": "Database" | "Cache" | "Compute/Kubernetes" | "Messaging" | "Networking" | "Security/Certificates" | "Deployment/Config" | "Storage" | "Application" | "Unknown",
  "confidence": "High" | "Medium" | "Low",
  "confidence_reason": "one short sentence",
  "is_new_pattern": true/false,
  "summary": "1-2 sentence plain description of what is happening",
  "likely_root_cause": "one or two sentences",
  "matched_past_incidents": [
    {"source": "this_project" | "shared_lesson", "title": "...", "date": "... or null", "runbook": "... or null", "owner": "... or null", "what_fixed_it": "..."}
  ],
  "past_resolution_time": "e.g. 47 minutes, or null",
  "immediate_actions": ["3-6 short imperative steps in order"],
  "long_term_fixes": ["1-4 items"],
  "code_suggestion": "a short code or config snippet ONLY if the alert contains code or a stack trace and a concrete fix is clear, otherwise null"
}

Rules:
1. Only PROJECT MEMORY may provide date, runbook, owner or resolution time. For source "shared_lesson" set date, runbook and owner to null and word it as "seen in other projects", never as something that happened here.
2. Never guess or reveal details of any other project. Use only what is given.
3. If only SHARED LESSONS match: is_new_pattern=true for this project and confidence at most "Medium".
4. If PROJECT MEMORY has feedback that a past recommendation was NOT helpful, do not repeat it; suggest an alternative.
5. If nothing is related: is_new_pattern=true, confidence "Low" or "Medium", say plainly it is new, and give best-effort steps from general engineering knowledge.
6. If the alert is too vague to act on (no service, symptom, error or metric): needs_more_info=true, give 3 specific clarifying_questions, and still give 2-3 safe first checks in immediate_actions. Otherwise clarifying_questions must be [].
7. Be concise and engineer-to-engineer. Output JSON only."""

SANITIZE_SYSTEM = """You turn a resolved incident into a GENERAL, reusable engineering lesson that is safe to share with other teams.
Remove ALL identifying information: company, project and team names, service/host/cluster names, people's names, emails, URLs, IPs, IDs, runbook or ticket numbers, dates, and exact metrics that could identify the system.
Keep: the technology involved (for example Azure SQL, Redis, Kubernetes), the generic symptom pattern, the root-cause pattern, the fix, and how to prevent recurrence.
Write 3-5 sentences. Start with 'GENERAL LESSON:'. Output only the lesson text."""

TEXT_SYSTEM = "You are a senior SRE writing clear, concise incident communication. Use plain professional English."

DEFAULTS = {
    "needs_more_info": False, "clarifying_questions": [], "severity": "P3", "category": "Unknown",
    "confidence": "Low", "confidence_reason": "", "is_new_pattern": True, "summary": "",
    "likely_root_cause": "", "matched_past_incidents": [], "past_resolution_time": None,
    "immediate_actions": [], "long_term_fixes": [], "code_suggestion": None,
}

# ---------- anonymisation (defence in depth; a human still reviews before sharing) ----------
_PATTERNS = [
    (r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>"),
    (r"https?://\S+", "<url>"),
    (r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "<ip>"),
    (r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b", "<id>"),
    (r"\b(?:gsk|hsk|sk|pk|ghp)_[A-Za-z0-9_]{8,}\b", "<secret>"),
    (r"\bRB-[A-Z]+-\d+\b", "<runbook>"),
    (r"\b[A-Z]{2,10}-\d{2,6}\b", "<ticket>"),
    (r"(?<!\w)@\w+", "<person>"),
    (r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)*-(?:api|service|worker|processor|gateway|catalog|ingest|generator|frontend|backend|app|db|cluster)\b", "<service>"),
]


def redact(text, extra_terms=()):
    """Return (clean_text, number_of_redactions)."""
    count = 0
    for pattern, repl in _PATTERNS:
        text, n = re.subn(pattern, repl, text)
        count += n
    for term in {t.strip() for t in extra_terms if t and len(t.strip()) >= 3}:
        text, n = re.subn(re.escape(term), "<name>", text, flags=re.IGNORECASE)
        count += n
    return text, count


def _service_names(alert_text):
    return re.findall(r"service=([\w.\-]+)", alert_text or "")


def _is_missing(exc):
    """True if an exception means 'bank not found' (HTTP 404)."""
    return getattr(exc, "status", None) == 404 or "404" in str(exc) or "not found" in str(exc).lower()


class _ThreadedClient:
    """Runs every Hindsight call on ONE dedicated thread.

    The Hindsight client keeps an async HTTP session bound to an event loop. Streamlit runs each
    page refresh on a different thread, which can break that session. One worker thread = one loop.
    """

    def __init__(self, client):
        self._client = client
        self._pool = ThreadPoolExecutor(max_workers=1)

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr
        return lambda *a, **k: self._pool.submit(attr, *a, **k).result()


class OnCallCopilot:
    def __init__(self):
        self.prefix = BANK_ID
        self.bank_id = BANK_ID  # default bank (used by the CLI demo)
        self.global_bank = os.environ.get("GLOBAL_BANK", f"{self.prefix}-shared-lessons")
        self.hindsight = _ThreadedClient(Hindsight(
            base_url=os.environ.get("HINDSIGHT_BASE_URL", "http://localhost:8888"),
            api_key=os.environ.get("HINDSIGHT_API_KEY"),
        ))
        self.last_error = ""
        self.groq = Groq(api_key=os.environ["GROQ_API_KEY"])
        self._ready = set()

    # ---------- banks ----------
    def bank_for(self, project_slug):
        return f"{self.prefix}-{project_slug}"

    def ensure_bank(self, bank_id, name=None, force=False):
        if bank_id in self._ready and not force:
            return
        try:
            self.hindsight.create_bank(bank_id=bank_id, name=name or bank_id)
            self._ready.add(bank_id)
            self.last_error = ""
        except Exception as exc:  # keep the reason visible instead of hiding it
            self.last_error = f"create_bank({bank_id}) failed: {str(exc)[:200]}"

    def _retain(self, bank_id, content):
        self.ensure_bank(bank_id)
        try:
            return self.hindsight.retain(bank_id=bank_id, content=content)
        except Exception as exc:
            if not _is_missing(exc):
                raise
            self.ensure_bank(bank_id, force=True)  # bank vanished or was never created: create and retry once
            return self.hindsight.retain(bank_id=bank_id, content=content)

    # ---------- helpers ----------
    def _chat(self, system, user, json_mode=False):
        kwargs = dict(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        if json_mode:
            try:
                r = self.groq.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
                return r.choices[0].message.content
            except Exception:
                pass
        r = self.groq.chat.completions.create(**kwargs)
        return r.choices[0].message.content

    @staticmethod
    def _parse_json(raw):
        if not raw:
            return None
        text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e > s:
            try:
                return json.loads(text[s : e + 1])
            except Exception:
                return None
        return None

    def _recall(self, bank_id, query):
        self.ensure_bank(bank_id)
        try:
            res = self.hindsight.recall(bank_id=bank_id, query=query)
        except Exception as exc:
            if not _is_missing(exc):
                raise
            self.ensure_bank(bank_id, force=True)
            try:
                res = self.hindsight.recall(bank_id=bank_id, query=query)
            except Exception as exc2:
                if _is_missing(exc2):
                    return []  # bank has no memory yet: treat as empty instead of crashing
                raise
        items = getattr(res, "results", []) or []
        return [m.text for m in items if getattr(m, "text", None)]

    def has_memory(self, bank_id=None):
        try:
            return len(self._recall(bank_id or self.bank_id, "incident outage error resolution lesson")) > 0
        except Exception:
            return False

    def probe(self, bank_id, term):
        """Isolation test: which memories in this bank mention `term`?"""
        try:
            return [m for m in self._recall(bank_id, term) if term.lower() in m.lower()]
        except Exception:
            return []

    # ---------- autonomous tool-calling agent ----------
    def _inspect_alert(self, alert_text):
        """Deterministic tool: extract useful facts from the incoming alert."""
        text = alert_text or ""
        service = None
        severity = None
        m = re.search(r"\bservice=([\w.\-]+)", text, re.I)
        if m:
            service = m.group(1)
        m = re.search(r"\bseverity=(P[1-4])\b", text, re.I)
        if m:
            severity = m.group(1).upper()
        status_codes = re.findall(r"\b(?:HTTP\s*)?(\d{3})\b", text)
        errors = []
        for pattern in [
            r"Timeout expired[^\n]*",
            r"certificate[^\n]*expired[^\n]*",
            r"CUDA out of memory[^\n]*",
            r"JsonException[^\n]*",
            r"connection pool[^\n]*",
            r"dead-letter[^\n]*",
            r"crash-looping[^\n]*",
        ]:
            errors.extend(re.findall(pattern, text, re.I))
        return {
            "service": service,
            "severity": severity,
            "status_codes": sorted(set(status_codes)),
            "error_signals": list(dict.fromkeys(errors))[:8],
            "has_stack_trace": bool(re.search(r"Traceback| at [A-Za-z_].*\(.*\)|Exception", text, re.I)),
            "alert_length": len(text),
        }

    AGENT_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "inspect_alert",
                "description": "Parse the incoming incident alert into structured facts before diagnosing it.",
                "parameters": {
                    "type": "object",
                    "properties": {"alert_text": {"type": "string"}},
                    "required": ["alert_text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "recall_project_memory",
                "description": "Search THIS project's private Hindsight memory for similar incidents, fixes, owners and feedback.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "recall_shared_lessons",
                "description": "Search the anonymized shared Hindsight lessons. Never treat these as incidents from the current project.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ask_engineer_question",
                "description": "Use when the alert is too vague to diagnose safely. Returns the clarification question to show the engineer.",
                "parameters": {
                    "type": "object",
                    "properties": {"question": {"type": "string"}},
                    "required": ["question"],
                },
            },
        },
    ]

    def _run_agent_tool(self, name, arguments, bank, use_shared):
        if name == "inspect_alert":
            return self._inspect_alert(arguments.get("alert_text", ""))
        if name == "recall_project_memory":
            query = arguments.get("query", "")[:2000]
            return {"scope": "this_project_only", "facts": self._recall(bank, query)}
        if name == "recall_shared_lessons":
            if not use_shared:
                return {"scope": "shared_lessons_disabled", "facts": []}
            query = arguments.get("query", "")[:2000]
            return {"scope": "anonymized_shared_lessons_only", "facts": self._recall(self.global_bank, query)}
        if name == "ask_engineer_question":
            q = (arguments.get("question") or "What additional information is available about the incident?").strip()
            return {"question": q, "requires_human_input": True}
        return {"error": f"Unknown tool: {name}"}

    def run_autonomous_agent(self, alert_text, bank_id=None, use_shared=True, max_steps=6):
        """Run an LLM-controlled tool loop. The model chooses which tool to call next."""
        bank = bank_id or self.bank_id
        trace = []
        tool_results = []
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an autonomous incident-response agent. You MUST use tools before giving a final diagnosis. "
                    "Choose the minimum useful tools; do not call every tool automatically. After each tool result, decide "
                    "whether another tool is needed. Project memory is private. Shared lessons are anonymized and are not "
                    "incidents from this project. Never invent owners, dates or fixes. If the alert is too vague, use "
                    "ask_engineer_question and then return the normal JSON diagnosis with needs_more_info=true. "
                    "When you have enough evidence, stop calling tools and return ONLY the JSON schema required by the "
                    "diagnosis format."
                ),
            },
            {"role": "user", "content": f"NEW ALERT:\n{alert_text}"},
        ]

        for step in range(max_steps):
            try:
                response = self.groq.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=messages,
                    tools=self.AGENT_TOOLS,
                    tool_choice="auto",
                    temperature=0,
                )
            except Exception as exc:
                # Keep the existing deterministic workflow as a safe fallback if function calling fails.
                trace.append({"tool": "agent_error", "status": "fallback", "detail": str(exc)[:180]})
                d = self.handle_incident(alert_text, bank_id=bank, use_shared=use_shared)
                d["agent_trace"] = trace
                d["tool_calls"] = len([x for x in trace if x.get("status") == "completed"])
                d["agent_mode"] = "fallback_after_tool_error"
                return d

            msg = response.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []
            if not calls:
                raw = msg.content or ""
                d = self._parse_json(raw)
                if not isinstance(d, dict):
                    # One final structured retry without tools.
                    raw = self._chat(
                        DIAGNOSE_SYSTEM,
                        f"NEW ALERT:\n{alert_text}\n\nTOOL RESULTS:\n{json.dumps(tool_results, ensure_ascii=False)}\n\nReturn the JSON object now.",
                        json_mode=True,
                    )
                    d = self._parse_json(raw)
                if not isinstance(d, dict):
                    d = {"summary": (raw or "").strip(), "confidence_reason": "Model did not return structured output."}
                break

            # Tell the model which tool calls it made, then feed every result back.
            # The assistant tool-call message must appear once before its tool results.
            assistant_tool_calls = []
            for call in calls:
                assistant_tool_calls.append({
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments or "{}"},
                })
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": assistant_tool_calls,
            })

            for call in calls:
                fn = call.function
                name = fn.name
                try:
                    args = json.loads(fn.arguments or "{}")
                except Exception:
                    args = {}
                trace.append({"tool": name, "status": "running", "step": step + 1})
                try:
                    result = self._run_agent_tool(name, args, bank, use_shared)
                    trace[-1].update({"status": "completed", "result_preview": self._tool_preview(result)})
                except Exception as exc:
                    result = {"error": str(exc)[:300]}
                    trace[-1].update({"status": "error", "result_preview": str(exc)[:180]})
                tool_results.append({"tool": name, "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

        else:
            # Safety valve: never loop forever.
            raw = self._chat(
                DIAGNOSE_SYSTEM,
                f"NEW ALERT:\n{alert_text}\n\nTOOL RESULTS:\n{json.dumps(tool_results, ensure_ascii=False)}\n\nReturn the JSON object now.",
                json_mode=True,
            )
            d = self._parse_json(raw) or {}

        for k, v in DEFAULTS.items():
            d.setdefault(k, v)
        if d["confidence"] not in ("High", "Medium", "Low"):
            d["confidence"] = "Low"
        if d["severity"] not in ("P1", "P2", "P3", "P4"):
            d["severity"] = "P3"

        # Derive displayed memory counts from the actual tool results, not from a second hidden recall.
        project_mem = []
        shared_mem = []
        for item in tool_results:
            if item["tool"] == "recall_project_memory":
                project_mem.extend(item["result"].get("facts", []))
            elif item["tool"] == "recall_shared_lessons":
                shared_mem.extend(item["result"].get("facts", []))
        project_mem = list(dict.fromkeys(project_mem))
        shared_mem = list(dict.fromkeys(shared_mem))
        pm = "\n".join(f"- {m}" for m in project_mem) or "(not queried)"
        sm = "\n".join(f"- {m}" for m in shared_mem) or "(not queried)"
        d.update(
            alert=alert_text,
            project_memories=project_mem,
            shared_memories=shared_mem,
            project_found=len(project_mem),
            shared_found=len(shared_mem),
            memories_found=len(project_mem) + len(shared_mem),
            memory_text=f"PROJECT:\n{pm}\n\nSHARED LESSONS:\n{sm}",
            agent_trace=trace,
            tool_calls=len([x for x in trace if x.get("status") == "completed"]),
            agent_mode="autonomous_tool_calling",
        )
        d["diagnosis"] = self._as_text(d)
        return d

    @staticmethod
    def _tool_preview(result):
        if isinstance(result, dict) and "facts" in result:
            return f"{len(result.get('facts', []))} memory fact(s)"
        if isinstance(result, dict) and "question" in result:
            return result["question"][:120]
        return json.dumps(result, ensure_ascii=False, default=str)[:160]

    # ---------- 1. diagnose ----------
    def handle_incident(self, alert_text, bank_id=None, use_shared=True):
        bank = bank_id or self.bank_id
        project_mem = self._recall(bank, alert_text)
        shared_mem = self._recall(self.global_bank, alert_text) if use_shared else []
        pm = "\n".join(f"- {m}" for m in project_mem) or "(none)"
        sm = "\n".join(f"- {m}" for m in shared_mem) or "(none)"
        raw = self._chat(
            DIAGNOSE_SYSTEM,
            f"NEW ALERT:\n{alert_text}\n\nPROJECT MEMORY:\n{pm}\n\nSHARED LESSONS:\n{sm}\n\nReturn the JSON object now.",
            json_mode=True,
        )
        d = self._parse_json(raw)
        if not isinstance(d, dict):
            d = {"summary": (raw or "").strip(), "confidence_reason": "Model did not return structured output."}
        for k, v in DEFAULTS.items():
            d.setdefault(k, v)
        if d["confidence"] not in ("High", "Medium", "Low"):
            d["confidence"] = "Low"
        if d["severity"] not in ("P1", "P2", "P3", "P4"):
            d["severity"] = "P3"
        d.update(
            alert=alert_text, project_memories=project_mem, shared_memories=shared_mem,
            project_found=len(project_mem), shared_found=len(shared_mem),
            memories_found=len(project_mem) + len(shared_mem),
            memory_text=f"PROJECT:\n{pm}\n\nSHARED LESSONS:\n{sm}",
        )
        d["diagnosis"] = self._as_text(d)
        return d

    @staticmethod
    def _as_text(d):
        lines = [d.get("summary", "")]
        if d.get("likely_root_cause"):
            lines.append(f"Likely root cause: {d['likely_root_cause']}")
        lines += [f"{i}. {a}" for i, a in enumerate(d.get("immediate_actions", []), 1)]
        return "\n".join(x for x in lines if x)

    # ---------- 2. learn (private) ----------
    def resolve_and_retain(self, alert_text, resolution_summary, diagnosis=None, bank_id=None):
        bank = bank_id or self.bank_id
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        record = f"INCIDENT RESOLVED [{when}]\nALERT: {alert_text}\nRESOLUTION: {resolution_summary}"
        if diagnosis and diagnosis.get("summary"):
            record += f"\nAGENT'S EARLIER ASSESSMENT: {diagnosis['summary']}"
        self._retain(bank, record)

    def record_feedback(self, alert_text, diagnosis, helpful, note="", bank_id=None):
        bank = bank_id or self.bank_id
        verdict = "HELPFUL and worked" if helpful else "NOT helpful"
        steps = "; ".join(diagnosis.get("immediate_actions", [])[:4])
        record = (f"ENGINEER FEEDBACK: For this alert: {alert_text[:300]}\n"
                  f"The recommendation ({steps}) was rated {verdict}. {note}").strip()
        self._retain(bank, record)

    # ---------- 3. learn (shared, anonymized, human-approved) ----------
    def sanitize_lesson(self, alert_text, resolution, project_name=""):
        raw = self._chat(SANITIZE_SYSTEM, f"ALERT:\n{alert_text}\n\nRESOLUTION:\n{resolution}")
        terms = [project_name] + _service_names(alert_text)
        clean, n = redact((raw or "").strip(), terms)
        return {"lesson": clean, "redactions": n}

    def share_lesson(self, lesson_text, project_name="", alert_text=""):
        terms = [project_name] + _service_names(alert_text)
        clean, _ = redact(lesson_text, terms)  # always redact again after the human edit
        self._retain(self.global_bank, clean)
        return clean

    # ---------- 4. ask the memory (private bank only) ----------
    def ask_memory(self, question, bank_id=None):
        bank = bank_id or self.bank_id
        self.ensure_bank(bank)
        try:
            res = self.hindsight.reflect(bank_id=bank, query=question)
            return {"answer": getattr(res, "text", None) or str(res), "method": "Hindsight reflect"}
        except Exception:
            ctx = "\n".join(f"- {m}" for m in self._recall(bank, question)) or "(no memory)"
            text = self._chat(TEXT_SYSTEM, f"Answer using ONLY this project memory. If it is not covered, say so.\n\nMEMORY:\n{ctx}\n\nQUESTION: {question}")
            return {"answer": text, "method": "Hindsight recall + LLM"}

    # ---------- 5. communication ----------
    def postmortem(self, alert_text, resolution, diagnosis=None):
        return self._chat(
            TEXT_SYSTEM,
            "Write a blameless post-mortem in Markdown with sections: Summary, Impact, Root Cause, Resolution, "
            "What Went Well, Action Items. Use only the facts given; do not invent numbers.\n\n"
            f"ALERT:\n{alert_text}\n\nRESOLUTION:\n{resolution}\n\nAGENT ASSESSMENT:\n{(diagnosis or {}).get('summary', '')}",
        )

    def status_update(self, alert_text, diagnosis):
        return self._chat(
            TEXT_SYSTEM,
            "Write a short Microsoft Teams status update (max 6 lines): what is happening, severity, current action, "
            "next update time placeholder [TIME].\n\n"
            f"ALERT:\n{alert_text}\n\nASSESSMENT:\n{diagnosis.get('summary', '')}\nSeverity: {diagnosis.get('severity')}\n"
            f"Actions: {'; '.join(diagnosis.get('immediate_actions', [])[:3])}",
        )