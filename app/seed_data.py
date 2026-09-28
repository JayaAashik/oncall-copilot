"""Realistic (synthetic) incident history for an Azure-based engineering team."""

PAST_INCIDENTS = [
    {"title": "Azure SQL connection pool exhaustion (checkout-api)", "content": (
        "INCIDENT [2026-01-14 03:12 UTC] Service: checkout-api (Azure App Service). "
        "Symptom: 502s spiking; logs show 'Timeout expired. The timeout period elapsed prior to obtaining a connection from the pool' against Azure SQL. "
        "Root cause: pool max size 20 too small for flash-sale burst; connections not released because of a missing try/finally in the payment retry loop. "
        "Fix: raised Max Pool Size to 100, set connection timeout to 5s, wrapped the retry loop in try/finally so connections always release. "
        "Resolution time: 47 minutes. Runbook: RB-SQL-003. Owner: Priya.")},
    {"title": "Redis cache stampede (product-catalog)", "content": (
        "INCIDENT [2026-02-02 14:05 UTC] Service: product-catalog (AKS) using Azure Cache for Redis. "
        "Symptom: p99 latency jumped from 80ms to 4200ms, Redis CPU at 100%. "
        "Root cause: the cache key of the top-selling SKU expired at the same moment on all 40 pods, causing a thundering herd of identical database queries. "
        "Fix: added jittered TTL (base + random 0-30s) and request coalescing (singleflight). "
        "Resolution time: 33 minutes. Runbook: RB-CACHE-011. Owner: Arjun.")},
    {"title": "Memory leak in notification-worker", "content": (
        "INCIDENT [2026-02-20 09:40 UTC] Service: notification-worker (AKS). "
        "Symptom: pods OOMKilled roughly every 6 hours, memory graph climbs linearly. "
        "Root cause: an event listener was registered per message instead of once at startup, so listeners were never garbage collected. "
        "Fix: moved listener registration outside the message loop and added a memory alert at 80% of the pod limit. "
        "Resolution time: 90 minutes. Runbook: RB-WORKER-004. Owner: Sara.")},
    {"title": "AKS node NotReady - disk pressure", "content": (
        "INCIDENT [2026-02-28 21:30 UTC] Service: AKS cluster prod-aks-01. "
        "Symptom: nodes flipping to NotReady, pods Evicted with reason DiskPressure. "
        "Root cause: unrotated container logs from a chatty debug-level service filled the node OS disk. "
        "Fix: cordoned and drained affected nodes, set log level to Warning, enabled log rotation, moved node pool to larger OS disks. "
        "Resolution time: 55 minutes. Runbook: RB-AKS-007. Owner: Kiran.")},
    {"title": "Azure Service Bus dead-letter queue growth", "content": (
        "INCIDENT [2026-03-05 16:20 UTC] Service: invoice-processor consuming Azure Service Bus queue 'invoices'. "
        "Symptom: dead-letter queue grew from 5 to 1,800 messages; consumer logged deserialization exceptions. "
        "Root cause: producer deployed a new message schema (renamed field) without versioning; the old consumer treated messages as poison. "
        "Fix: deployed a tolerant consumer, replayed dead-lettered messages, added schema version field and contract tests in CI. "
        "Resolution time: 65 minutes. Runbook: RB-SB-002. Owner: Meera.")},
    {"title": "Key Vault certificate expiry - TLS failures", "content": (
        "INCIDENT [2026-03-09 07:50 UTC] Service: public API behind Azure Front Door. "
        "Symptom: clients report TLS handshake failures, 'certificate has expired'. "
        "Root cause: certificate in Azure Key Vault was not auto-renewed because the renewal contact email was a former employee. "
        "Fix: renewed and rotated the certificate in Key Vault, updated the Front Door binding, fixed the contact, added expiry alerts at 30, 14 and 7 days. "
        "Resolution time: 28 minutes. Runbook: RB-CERT-001. Owner: Rahul.")},
    {"title": "Cosmos DB 429 throttling (RU exhaustion)", "content": (
        "INCIDENT [2026-03-11 12:15 UTC] Service: cart-service using Azure Cosmos DB. "
        "Symptom: HTTP 429 'Request rate is large', cart latency up, Azure Functions retrying. "
        "Root cause: a hot partition key (tenantId) during a promotion consumed the provisioned RU/s. "
        "Fix: raised autoscale max RU from 4000 to 10000, added retry with exponential backoff, and planned a synthetic partition key (tenantId + hash). "
        "Resolution time: 40 minutes. Runbook: RB-COSMOS-005. Owner: Ananya.")},
    {"title": "Bad release - missing environment variable", "content": (
        "INCIDENT [2026-03-18 18:05 UTC] Service: orders-api after release 2026.03.18. "
        "Symptom: sudden 500 errors right after deployment, logs show 'PAYMENT_GATEWAY_URL is not set'. "
        "Root cause: a new required config value existed in staging but was never added to production app settings. "
        "Fix: rolled back with an App Service slot swap, added the setting, added a config validation gate to the release pipeline. "
        "Resolution time: 15 minutes. Runbook: RB-DEPLOY-009. Owner: Vikram.")},
    {"title": "Front Door 502 - WAF blocking health probe", "content": (
        "INCIDENT [2026-03-24 10:40 UTC] Service: web-frontend behind Azure Front Door with WAF. "
        "Symptom: intermittent 502s, origin marked unhealthy although the app was fine. "
        "Root cause: a newly enabled WAF managed rule blocked the Front Door health probe requests. "
        "Fix: added a WAF exclusion for the probe path, verified origin health, added a WAF change review step. "
        "Resolution time: 70 minutes. Runbook: RB-NET-006. Owner: Divya.")},
    {"title": "Azure SQL pool exhaustion recurrence (order-history)", "content": (
        "INCIDENT [2026-04-02 22:18 UTC] Service: checkout-api, order-history endpoint. "
        "Symptom: 502s again with the same 'timeout ... obtaining a connection from the pool' error as RB-SQL-003. "
        "Root cause: the same missing try/finally pattern was copy-pasted into a new module before the original fix reached it. "
        "Fix: applied RB-SQL-003 pattern, added a connection pool metrics dashboard and a lint rule that enforces the pattern repo-wide. "
        "Resolution time: 12 minutes (fast because of the earlier runbook). Runbook: RB-SQL-003. Owner: Priya.")},
    {"title": "Event Hubs consumer lag", "content": (
        "INCIDENT [2026-04-09 05:25 UTC] Service: analytics-ingest consuming Azure Event Hubs. "
        "Symptom: consumer lag grew to 2 million events, dashboards hours behind. "
        "Root cause: only 4 consumer instances for 16 partitions and a slow checkpoint write to Blob Storage after every event. "
        "Fix: scaled consumers to match partitions and checkpointed every 500 events. "
        "Resolution time: 50 minutes. Runbook: RB-EH-003. Owner: Karthik.")},
    {"title": "Blob Storage throttling 503 ServerBusy", "content": (
        "INCIDENT [2026-04-15 13:10 UTC] Service: report-generator writing to Azure Blob Storage. "
        "Symptom: 503 ServerBusy and timeouts during month-end report burst. "
        "Root cause: thousands of small blobs written under one sequential prefix hit partition throughput limits. "
        "Fix: added exponential backoff, spread blob names across hashed prefixes, batched small writes. "
        "Resolution time: 35 minutes. Runbook: RB-STG-004. Owner: Sneha.")},
]


def seed(client, bank_id, on_progress=None):
    """Push synthetic history into Hindsight so recall has something to find."""
    total = len(PAST_INCIDENTS)
    for i, incident in enumerate(PAST_INCIDENTS, 1):
        client.retain(bank_id=bank_id, content=incident["content"])
        print(f"[seeded] {incident['title']}")
        if on_progress:
            on_progress(i, total, incident["title"])


# Anonymized lessons: what a global playbook looks like AFTER teams approve sharing.
# No project, service, person or runbook names, only reusable engineering knowledge.
GLOBAL_LESSONS = [
    "GENERAL LESSON [Database]: Pattern: 502 errors with 'timeout expired obtaining a connection from the pool' on Azure SQL during traffic bursts. "
    "Cause: pool max size too small and connections not released because retry code paths lack try/finally. "
    "Fix: raise max pool size, set a short connection timeout, wrap every connection use in try/finally or a using block. "
    "Prevention: add pool-usage metrics and a lint rule so the pattern is enforced across all modules.",
    "GENERAL LESSON [Cache]: Pattern: sudden latency spike and Redis CPU saturation when a hot key expires on many pods at once (cache stampede). "
    "Fix: add jittered TTLs and request coalescing (single-flight). Prevention: never give hot keys identical fixed TTLs.",
    "GENERAL LESSON [Compute/Kubernetes]: Pattern: worker pods OOMKilled on a regular schedule with steadily climbing memory. "
    "Cause: an event listener or callback registered per message instead of once. Fix: register once at startup. "
    "Prevention: alert at 80% of the memory limit and add a static-analysis rule.",
    "GENERAL LESSON [Compute/Kubernetes]: Pattern: Kubernetes nodes NotReady and pods evicted with DiskPressure. "
    "Cause: unrotated container logs from a verbose service filled the node disk. Fix: cordon and drain, lower log level, enable log rotation, use larger OS disks.",
    "GENERAL LESSON [Messaging]: Pattern: Azure Service Bus dead-letter queue grows quickly right after a deployment with deserialization errors. "
    "Cause: producer changed the message schema without versioning. Fix: make the consumer tolerant, replay dead-lettered messages. "
    "Prevention: add a schema version field and consumer-driven contract tests in CI.",
    "GENERAL LESSON [Security/Certificates]: Pattern: clients suddenly fail TLS handshakes with 'certificate has expired'. "
    "Cause: auto-renewal failed because the renewal contact was an inactive mailbox. Fix: rotate the certificate in Key Vault and rebind it. "
    "Prevention: alerts at 30, 14 and 7 days before expiry and a shared team mailbox as contact.",
    "GENERAL LESSON [Database]: Pattern: Cosmos DB returns HTTP 429 during a traffic promotion. "
    "Cause: hot partition key consuming provisioned throughput. Fix: raise autoscale max RU, retry with exponential backoff. "
    "Prevention: use a higher-cardinality or synthetic partition key.",
    "GENERAL LESSON [Deployment/Config]: Pattern: 500 errors immediately after a release with 'setting is not set' in logs. "
    "Cause: a new required config value existed in staging but not in production. Fix: roll back via deployment slot swap, add the setting. "
    "Prevention: config validation gate in the release pipeline.",
]


def seed_playbook(client, bank_id, on_progress=None):
    total = len(GLOBAL_LESSONS)
    for i, text in enumerate(GLOBAL_LESSONS, 1):
        client.retain(bank_id=bank_id, content=text)
        if on_progress:
            on_progress(i, total, f"lesson {i}")


# ---------------------------------------------------------------------------
# Shared lessons library: what the anonymizer produces. No project, service,
# people, runbook or date information; only technology + pattern + fix.
# ---------------------------------------------------------------------------
GLOBAL_LESSONS = [
    "GENERAL LESSON: Azure SQL or Postgres connection-pool exhaustion (errors such as 'timeout expired obtaining a connection from the pool' or 'too many clients') usually comes from a pool sized too small for a traffic burst combined with connections that are not released on error paths. Raise the pool size carefully, set a short acquire timeout, and make sure every connection is released in a finally or using block. It tends to recur because the unsafe pattern gets copy-pasted into new modules, so enforce it with a lint rule and alert on pool utilisation.",
    "GENERAL LESSON: A Redis cache stampede shows up as a sudden latency spike with cache CPU at 100% when a hot key expires everywhere at once and every request hits the database. Add random jitter to TTLs and coalesce identical in-flight requests (singleflight) so only one request rebuilds the value.",
    "GENERAL LESSON: Pods in Kubernetes that are OOMKilled on a regular schedule with a steadily climbing memory graph often leak event listeners or handlers registered per message instead of once at startup. Register listeners once outside the processing loop, alert at about 80% of the memory limit, and add static analysis for listener leaks.",
    "GENERAL LESSON: Kubernetes nodes flipping to NotReady with pods evicted for DiskPressure are commonly caused by unrotated container logs from a chatty debug-level workload. Cordon and drain the node, lower the log level, enable log rotation, and consider larger OS disks for the node pool.",
    "GENERAL LESSON: A growing Azure Service Bus dead-letter queue right after a deployment usually means the producer changed the message schema without versioning, so the consumer treats messages as poison. Deploy a tolerant consumer, replay the dead-lettered messages, and add a schema version field plus contract tests in CI.",
    "GENERAL LESSON: Sudden TLS handshake failures with 'certificate has expired' on an edge service such as Azure Front Door usually mean an auto-renewal silently failed, often because the renewal contact is stale. Rotate the certificate in Key Vault, update the binding, fix the contact, and alert on expiry at 30, 14 and 7 days.",
    "GENERAL LESSON: HTTP 429 'Request rate is large' from Azure Cosmos DB during a traffic spike points to exhausted RU/s, frequently caused by a hot partition key. Raise autoscale RU as a short-term fix, add retry with exponential backoff, and redesign the partition key (for example add a hash suffix) for the long term.",
    "GENERAL LESSON: A burst of 500 errors immediately after a release, with logs saying a required setting is missing, means the configuration exists in staging but not in production. Roll back quickly (for example with an App Service slot swap), add the setting, and add a configuration validation gate to the release pipeline.",
]


def seed_global(client, global_bank, on_progress=None):
    total = len(GLOBAL_LESSONS)
    for i, lesson in enumerate(GLOBAL_LESSONS, 1):
        client.retain(bank_id=global_bank, content=lesson)
        if on_progress:
            on_progress(i, total, f"lesson {i}")


def leak_scan(text, terms):
    """Return the private terms that appear in `text` (case-insensitive)."""
    low = text.lower()
    return [t for t in terms if t.lower() in low]


PRIVATE_TERMS = [
    "Priya", "Arjun", "Sara", "Kiran", "Meera", "Rahul", "Ananya", "Vikram", "Divya", "Karthik", "Sneha",
    "checkout-api", "product-catalog", "notification-worker", "invoice-processor", "cart-service",
    "orders-api", "web-frontend", "analytics-ingest", "report-generator", "prod-aks-01",
    "RB-", "2026-",
]