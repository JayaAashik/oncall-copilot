# On-Call Copilot 🧠🚨

> An autonomous AI incident-response copilot that investigates production alerts, uses persistent memory to learn from previous incidents, and recalls proven resolutions for future incidents.

## Overview

On-Call Copilot is an AI-powered incident-response system designed to assist engineers during production incidents.

Traditional incident-response systems can detect alerts and provide static information, but they do not continuously learn from how engineers actually resolve incidents.

On-Call Copilot addresses this by combining:

- Autonomous AI tool calling
- Production alert analysis
- Project-specific memory
- Shared engineering lessons
- Persistent incident memory using Hindsight
- Engineer feedback
- Historical incident recall

The system can investigate an alert, inspect relevant information, retrieve previous lessons, ask an engineer for missing context, generate a diagnosis, and retain the resolved incident so that the knowledge can be reused later.

---

## Problem

During production incidents, engineers often need to:

1. Understand the incoming alert.
2. Inspect logs and symptoms.
3. Search previous incidents.
4. Remember how similar incidents were resolved.
5. Consult other engineers.
6. Apply the fix.
7. Document what happened.

A major challenge is that valuable incident knowledge is often lost after the incident is resolved.

The same failure may happen again, requiring engineers to repeat the same investigation.

On-Call Copilot turns previous incident resolutions into reusable operational memory.

---

## Solution

On-Call Copilot introduces an autonomous AI agent between the production alert and the engineer.

The agent can decide which tools and memories are useful for the current incident.

### High-Level Flow

```text
Production Alert
       │
       ▼
┌───────────────────────┐
│   Autonomous Agent    │
│      Groq LLM         │
└───────────┬───────────┘
            │
            ▼
      Tool Selection
            │
    ┌───────┼────────┐
    │       │        │
    ▼       ▼        ▼
 Inspect   Recall   Ask Engineer
 Alert     Memory    Question
    │       │        │
    └───────┼────────┘
            ▼
       Diagnosis
            │
            ▼
     Recommended Fix
            │
            ▼
     Engineer Resolution
            │
            ▼
     Hindsight Memory
            │
            ▼
   Future Incident Recall
