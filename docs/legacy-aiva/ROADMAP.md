# Aiva Product Roadmap

## Strategy

Build the highest-value integrations in-house to establish quality, trust, and product patterns. Once the core ecosystem is proven, open the plugin platform so third parties can extend the long tail.

The internal plugin architecture (`ToolDef + register()`) is already the right abstraction for this -- the SDK is essentially the internal pattern, documented and published.

---

# Phase 1 -- Foundation (Months 1-2)

## Web Search

A core expected capability for any modern assistant experience. Users will naturally assume the chat interface can search and reason over current information.

- Integrate a search API (Brave, Tavily, or Perplexity)
- Agent can answer questions about current events, look up addresses, research topics
- Combines naturally with other tools:
  - "Search for the CEO of Acme Corp and draft an intro email"
  - "Find recent news about Nvidia and summarize it"

## Google Workspace Depth

Aiva is already on Google OAuth -- fill the gaps before adding new platforms.

### Gmail

- Reply in-thread (not just `In-Reply-To` header)
- Label, archive, delete, mark read/unread
- Create draft
- Complex query syntax passthrough

### Google Calendar

- Delete event
- Recurring event support
- Free/busy lookup ("when am I free next week?")

### Google Drive

- List files, read file content (Docs, Sheets, plain text)
- Create / upload document

### Google Contacts

- Sync with Google People API (in addition to the internal `Contact` model)

## Microsoft Ecosystem

A large portion of consumers use Outlook and OneDrive. The OAuth plugin pattern is identical.

- Outlook / Office 365 Mail -- same tool surface as Gmail
- Microsoft Calendar -- same tool surface as Google Calendar
- OneDrive -- list and read files

## Apple Ecosystem

A critical ecosystem for the long-term Aiva experience, especially with plans to leverage Apple foundational models and deeper iOS/macOS integration.

### Apple Apps & System Integrations

- Apple Calendar integration
- Apple Mail integration
- Apple Reminders integration
- Apple Contacts integration
- Siri shortcut execution support
- Deep-link support between Aiva and Apple apps

### Siri & Shortcuts

- Trigger Aiva workflows through Siri
- Run saved workflows through Apple Shortcuts
- Voice-triggered assistant actions
- Context-aware handoff between Siri and Aiva

## Voice Interface

Natural daily-use interaction pattern and tightly connected to Apple ecosystem functionality.

- Whisper-based voice transcription on the client
- TTS response playback
- Hands-free interactions
- Driving-mode quick actions
- Siri-compatible workflow execution
- Voice-first morning briefings

---

# Phase 2 -- Intelligence Layer (Months 3-5)

## Scheduled / Recurring Runs

Implemented in v1 for saved workflow execution. Delivery channels remain future work.

- `ScheduledRun` model with cron expression, timezone, saved workflow FK, enabled state, and next-run tracking
- `ScheduledRunExecution` model stores queued/running/success/failed/skipped execution history and final results
- Celery Beat dispatches due schedules every minute; Celery workers execute workflows through the orchestrator
- Redis is the local/dev Celery broker
- Platform endpoints live under `/scheduled-runs/`
- Workflows containing confirmation-required tools can be scheduled and will execute automatically when due
- Push or email delivery of results is not implemented yet

Examples:

- "Summarize my unread emails every morning"
- "Run my daily briefing at 7am"
- "Generate a weekly spending summary every Friday"

## Saved Workflows / Shortcuts

Power-user stickiness feature.

- User names and saves a prompt as a workflow:
  - "Morning briefing" -> stored multi-step plan
- Optional schedule attachment
- Triggerable via chat:
  - "Run my morning briefing"
- Triggerable through Siri and Apple Shortcuts

## Proactive Monitoring & Alerts

One of the largest long-term differentiation opportunities.

Implementation approach still evolving, but direction is clear.

- `WatchRule` model: condition + action + cadence
- Background workers evaluate conditions and fire push/email notifications
- AI-written summaries and recommendations

Examples:

- "Alert me when I get an email about the Henderson deal"
- "Remind me if I haven't replied to Sarah in 3 days"
- "Notify me if my calendar changes tomorrow morning"

## Persistent Memory / User Profile

The difference between a useful daily assistant and a one-off tool.

- `UserMemory` model: key-value facts the agent reads at planning time
- User can define:
  - preferences
  - relationships
  - writing style
  - recurring contacts
- Agent automatically learns frequent contacts, preferred times, and patterns over time
- Memory viewer and editor in the UI
- Planning system prompt injects relevant memories:
  - "User prefers morning meetings"
  - "Assistant is Sarah"

---

# Phase 3 -- Ecosystem Expansion (Months 6-9)

## Task & Project Management

| Integration | Actions |
|---|---|
| Todoist | List, create, complete, move tasks |
| Linear | List issues, create, update status |
| Notion | Read page, create page, update database row |

## Finance & Spending

High consumer value, very few competitors here.

### Plaid (read-only)

- Categorize recent transactions
- Monthly spending summaries
- Budget insights

### Stripe

- List invoices
- Check balances
- Revenue summaries for freelancers/creators

### Splitwise

- Check balances
- Log expenses
- Shared expense summaries

Examples:

- "How much did I spend on restaurants last month?"
- "Summarize my subscriptions this month"
- "Who still owes me money from Whistler?"

## Content & Media

### RSS / Newsletter Digest

- Summarize feeds on a schedule
- Personalized daily digests

### YouTube

- Summarize video transcripts from URLs
- Extract key ideas and action items

---

# Phase 4 -- Platform & Ecosystem (Months 9-18)

## Plugin Marketplace / Third-Party SDK

Once internal plugins establish quality standards and patterns, open the platform.

### SDK & Developer Platform

- Publish the `ToolDef` plugin spec as a documented SDK
- Developer portal:
  - register tools
  - set scopes
  - manage OAuth credentials
- Review and approval flow
- Sandboxed execution environment

### Marketplace

- Users can install and share plugins
- Revenue-sharing model for paid plugins
- Third parties build the long tail:
  - Salesforce
  - HubSpot
  - Spotify
  - Banking apps
  - Niche productivity tools

---

# Lower Priority / Long-Term Research

These features remain interesting long-term opportunities but are deprioritized due to complexity and planning overhead.

## Multi-Agent Architecture

- Specialist sub-agents:
  - Email Agent
  - Calendar Agent
  - Finance Agent
- Top-level orchestrator routes sub-tasks to the right specialist

## Agentic / Autonomous Mode

- Confidence-based autonomous execution
- Adjustable user trust levels
- Full audit logs and approval system

## Shared Agents for Families & Small Teams

- Shared projects and integrations
- Collaborative assistant workflows
- Permission systems

## On-Device / Privacy Mode

- Local LLM execution (Ollama, MLX on Apple Silicon)
- Sensitive data never leaves device
- Premium "Private Mode" tier

---

# Priority Matrix

| Feature | Consumer Value | Competitive Gap | Effort | Phase |
|---|---|---|---|---|
| Web search | Very High | Low | Low | 1 |
| Apple ecosystem + Siri | Very High | Medium | Medium | 1 |
| Voice interface | High | Medium | Medium | 1 |
| Gmail depth (reply, label, draft) | Very High | Low | Low | 1 |
| Google Drive read/write | High | Medium | Low | 1 |
| Outlook / Microsoft | High | Low | Medium | 1 |
| Scheduled runs | Very High | Medium | Low | 2 |
| Saved workflows | High | Medium | Low | 2 |
| Proactive monitoring | Very High | High | Medium | 2 |
| Persistent memory | Very High | High | Medium | 2 |
| Todoist / Notion | Medium | Low | Low | 3 |
| Finance (Plaid / Stripe / Splitwise) | High | High | High | 3 |
| Content & media plugins | Medium | Medium | Low | 3 |
| Plugin marketplace / SDK | Very High (long-term) | High | Very High | 4 |
| Multi-agent architecture | Medium | Medium | High | Long-term |
| Autonomous mode | Medium | Medium | High | Long-term |
| Shared agents | Medium | Low | High | Long-term |
| On-device mode | Medium | High | Very High | Long-term |

---

# What Makes Aiva Defensible

## 1. Plan Transparency

Every destructive or meaningful action shows a plain-English "I will..." summary with a conversational modify loop before executing.

Copilot and Gemini often act immediately. Zapier requires a visual editor. Aiva's confirm-before-execute flow creates trust while still feeling conversational and fluid.

## 2. Cross-Service Compound Actions

The `plan -> [step1, step2, step3] -> processing_llm` architecture naturally composes tools across services from a single natural-language request.

Example:

> "Find emails from John about the proposal, check if we have a meeting this week, and draft a follow-up email."

This becomes a coordinated multi-step plan across multiple plugins and services from one prompt.

That orchestration layer becomes increasingly difficult to replicate as Aiva gains:
- memory
- workflows
- monitoring
- plugin ecosystem depth
- user personalization

The roadmap compounds these advantages over time, evolving Aiva from a reactive assistant into a contextually aware operating layer for digital life.
