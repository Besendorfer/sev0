# sev0

**Your AI on-call engineer.** Sev0 automatically ingests error logs and alerts, triages them with AI, creates tickets, and notifies your team — so you can sleep through the night.

---

Most on-call rotations look the same: an alert fires, an engineer wakes up, spends 20 minutes reading logs, decides it's not critical, and goes back to sleep. Or worse — it *is* critical, and those 20 minutes of triage delay matter.

Sev0 handles the first 80% of incident response automatically. It pulls errors from your log sources, deduplicates them, runs AI-powered triage to assess severity and root cause, creates tickets for actionable issues, and notifies your team with a structured summary. By the time a human looks at it, the context is already there.

## How it works

```
  Scheduled sweep                Reactive alert
  (cron: 8am, 5pm)              (Teams/Slack message)
        |                               |
        v                               v
  ┌────────────┐                 ┌────────────┐
  │ CloudWatch │                 │   Teams    │
  │  Datadog   │                 │   Slack    │
  │  Splunk    │                 │   Email    │
  └──────┬─────┘                 └──────┬─────┘
         │                              │
         └──────────┬───────────────────┘
                    v
            ┌──────────────┐
            │  Normalize   │  Common event format
            └──────┬───────┘
                   v
            ┌──────────────┐
            │    Dedup     │  Skip if already triaged
            └──────┬───────┘
                   v
            ┌──────────────┐
            │  AI Triage   │  Severity, root cause,
            │   (Claude)   │  suggested owner, action
            └──────┬───────┘
                   v
         ┌─────────┴──────────┐
         v                    v
   ┌──────────┐        ┌──────────┐
   │  Create  │        │  Notify  │
   │  Ticket  │        │  Team    │
   │  (Jira)  │        │ (Teams)  │
   └──────────┘        └──────────┘
```

**Two flows, one pipeline:**

1. **Scheduled sweeps** — On a cron schedule (morning, evening, or whatever you want), Sev0 pulls recent errors from your log sources and triages everything that's new.
2. **Reactive alerts** — When an alert lands in your Teams/Slack channel, Sev0 picks it up and triages it immediately.

Both flows share the same core: deduplicate, triage with AI, create tickets, notify.

## Quick start

```bash
# Clone and install
git clone https://github.com/Besendorfer/sev0.git
cd sev0
uv sync --all-extras

# Configure
cp config.example.yaml config.yaml
cp .env.example .env
# Edit both files with your credentials

# Validate your setup
uv run sev0 check

# Run a one-shot sweep
uv run sev0 sweep

# Start the scheduler + listeners
uv run sev0 run
```

## Configuration

Sev0 is entirely config-driven. Define your sources, channels, actions, and schedule in a single YAML file:

```yaml
sources:
  - type: cloudwatch
    region: us-east-1
    log_groups:
      - /aws/lambda/my-api
      - /ecs/my-service
    query: "fields @timestamp, @message | filter @message like /ERROR|Exception/"
    lookback_minutes: 480

channels:
  - type: teams
    webhook_url: ${TEAMS_WEBHOOK_URL}

actions:
  - type: jira
    base_url: ${JIRA_BASE_URL}
    email: ${JIRA_EMAIL}
    api_token: ${JIRA_API_TOKEN}
    project_key: OPS

triage:
  model: claude-sonnet-4-6
  severity_threshold: medium   # only create tickets for medium+

schedule:
  - cron: "0 8 * * *"          # morning sweep
  - cron: "0 17 * * *"         # evening sweep
```

Environment variables are interpolated with `${VAR_NAME}` syntax, with optional defaults: `${VAR:fallback}`.

## Adapter architecture

Every integration point in Sev0 is a pluggable adapter. The core engine doesn't know or care whether you're using CloudWatch or Datadog, Jira or Linear, Teams or Slack.

**Adding a new adapter is one file:**

```python
from sev0.adapters.sources.base import AbstractSource
from sev0.registry import register_source

@register_source("datadog")
class DatadogSource(AbstractSource):
    async def fetch_alerts(self, since):
        # Your implementation here
        ...
```

Then add one import line to `src/sev0/adapters/__init__.py`. Zero changes to the engine, registry, or any other code.

### Currently supported

| Layer | Adapters |
|-------|----------|
| **Sources** (where errors come from) | AWS CloudWatch |
| **Channels** (where alerts arrive + notifications go) | Microsoft Teams |
| **Actions** (what to do about it) | Jira |

### Planned

| Layer | Adapters |
|-------|----------|
| **Sources** | Datadog, Splunk, Grafana Loki, Sentry |
| **Channels** | Slack, Discord, Email, PagerDuty |
| **Actions** | GitHub Issues, Linear, Shortcut |

## How triage works

When Sev0 encounters an error, it:

1. **Normalizes** the error into a common format (timestamp, service, message, stack trace, metadata)
2. **Fingerprints** the error by stripping variable content (timestamps, UUIDs, IPs) and hashing the signature — so the same error from different instances at different times is recognized as one issue
3. **Deduplicates** against a local store with a configurable TTL (default: 72 hours) — no duplicate tickets
4. **Triages with AI** — sends the error to Claude with a structured prompt that returns severity, confidence, root cause analysis, suggested owner, and a recommended action
5. **Acts** — creates a ticket (if severity meets threshold) and notifies your team channel with a rich summary card

The AI triage classifies severity as:

| Level | Meaning | Example |
|-------|---------|---------|
| **critical** | Data loss, full outage, security breach | Database corruption, auth service down |
| **high** | Partial outage, degraded experience for many users | API returning 500s for 30% of requests |
| **medium** | Errors affecting a subset of users or non-critical path | Payment webhook retries exhausting |
| **low** | Intermittent errors, edge cases | Timeout on rarely-used admin endpoint |
| **info** | Noise, transient, self-healing | Connection pool briefly saturated then recovered |

## CLI

```bash
sev0 run              # Start scheduler + channel listeners
sev0 sweep            # Run a single triage sweep (one-shot)
sev0 check            # Validate config and test connectivity

# Options
sev0 -c my-config.yaml sweep    # Use a custom config file
sev0 -v run                     # Verbose (debug) logging
```

## Development

```bash
# Install with dev dependencies
uv sync --all-extras

# Run tests
uv run pytest tests/ -v

# Run a specific test file
uv run pytest tests/test_models.py -v
```

## License

MIT
