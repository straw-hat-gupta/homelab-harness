# Workflow Creator — Frontend Design Brief

This document describes the workflow creator UI for Aiva. It is intended as a spec brief for building the feature. All backend endpoints referenced here are live and documented in `docs/ENDPOINTS.md`.

---

## Overview

The workflow creator lets users build, save, and run multi-step automation workflows without writing code. Each workflow is a sequence of tool calls (steps) where the output of one step can be fed into the next.

Workflows are **user-global** — not scoped to a project. A workflow can optionally be **tagged** to a project, which injects that project's `system_prompt` into the run as a `$project_system_prompt` variable available to any step.

---

## Backend API surface

| Method | Path | Used for |
|---|---|---|
| `GET` | `/agent/workflows/tools/` | Load all available tool schemas for the step picker |
| `GET` | `/agent/workflows/` | List the user's saved workflows |
| `POST` | `/agent/workflows/` | Save a new workflow |
| `GET` | `/agent/workflows/<id>/` | Load a workflow for editing |
| `PUT` | `/agent/workflows/<id>/` | Update an existing workflow |
| `DELETE` | `/agent/workflows/<id>/` | Delete a workflow |
| `POST` | `/agent/workflows/<id>/run/` | Run a saved workflow |
| `GET` | `/projects/` | Populate the optional project tag picker |

### Plan JSON shape (what gets saved as `plan`)

```json
{
  "steps": [
    {
      "id": "s1",
      "tool": "weather.get_current_weather",
      "params": { "city": "Tokyo" },
      "output_var": "weather_result"
    },
    {
      "id": "s2",
      "tool": "processing_llm",
      "params": {
        "instruction": "Summarise this weather: $weather_result"
      },
      "output_var": "final"
    }
  ],
  "final_output_var": "final",
  "summary": "Get Tokyo weather and summarise it"
}
```

**Variable references:** any param value prefixed with `$` is resolved at run time from a prior step's `output_var`. The UI should make this easy to insert.

---

## Pages / screens

### 1. Workflow list

**Route:** `/workflows`

- Header: "My Workflows" + "New Workflow" button (primary CTA)
- Grid or list of workflow cards, each showing:
  - Name
  - Description (truncated to 2 lines)
  - Tagged project name (if any), shown as a chip
  - Step count badge
  - `updated_at` timestamp
  - Actions: Run ▶, Edit ✎, Delete ✕
- Empty state: illustration + "Create your first workflow" button
- Running a workflow from the list opens a result modal (see §4)

---

### 2. Workflow creator / editor

**Route:** `/workflows/new` and `/workflows/<id>/edit`

This is the main builder view. It has three zones:

```
┌──────────────────────────────────────────────────────────────┐
│  ← Back   [Workflow name (editable inline)     ]  [Save] [Run▶]│
├──────────────────────┬───────────────────────────────────────┤
│                      │                                       │
│   STEP LIST          │   STEP EDITOR (right panel)           │
│   (left panel)       │                                       │
│                      │                                       │
│  ┌────────────────┐  │  Tool: [weather.get_current_weather ▾]│
│  │ Step 1         │  │                                       │
│  │ weather.get_   │  │  Parameters                           │
│  │ current_weather│  │  ┌─────────────────────────────────┐  │
│  └────────────────┘  │  │ city   [Tokyo              ] [↗]│  │
│         ↕ drag       │  └─────────────────────────────────┘  │
│  ┌────────────────┐  │                                       │
│  │ Step 2         │  │  Output variable name                 │
│  │ processing_llm │  │  [weather_result              ]       │
│  └────────────────┘  │                                       │
│                      │  ─────────────────────────────────── │
│  [+ Add Step]        │  Available from previous steps:       │
│                      │  $weather_result  (step 1 output)     │
└──────────────────────┴───────────────────────────────────────┘
│  Description: [optional                                    ] │
│  Project tag: [None ▾]   Final output: [final ▾]            │
└──────────────────────────────────────────────────────────────┘
```

#### Left panel — step list

- Ordered list of step cards (drag-to-reorder via drag handle)
- Each card shows: step number, tool name (short label), output var name
- Clicking a card selects it and opens it in the right panel
- Selected card is highlighted
- "✕" on hover to delete the step (with confirmation if it's referenced by later steps)
- "+ Add Step" button at the bottom opens the tool picker overlay

#### Right panel — step editor

Shown when a step is selected. Contains:

**Tool picker (dropdown/search)**
- Populated from `GET /agent/workflows/tools/`
- Searchable by tool name or description
- Grouped by category: Gmail, Calendar, Drive, Weather, Web, Memory, Processing
- Shows tool description as subtext

**Parameter form**
- Rendered from the selected tool's `params` schema
- Each param is a row: label + input + optional "insert variable" button (↗)
- Input types:
  - `string` → text input (single line) or textarea if the field name suggests long content (`instruction`, `body`, `content`, `prompt`)
  - `number` / `integer` → number input
  - `boolean` → toggle switch
  - `array` → comma-separated text input (parsed on save)
- "Insert variable" button (↗) opens a small dropdown of `$output_var` references from all preceding steps — clicking one appends it to the field value

**Output variable name**
- Editable text field, auto-populated as `step<N>_out`
- Validated: must be unique, alphanumeric + underscores only
- Shows a warning if another step references the old name before renaming

**Available variables panel**
- Read-only list of `$var_name → step N (tool name)` for all preceding steps
- Clicking copies `$var_name` to clipboard

#### Bottom bar

- **Description** — optional free-text for the workflow
- **Project tag** — dropdown populated from `GET /projects/`. Selecting a project makes `$project_system_prompt` available in all steps. Shows project name + "system prompt will be injected" hint when selected.
- **Final output** — dropdown of all `output_var` names across all steps. Defaults to the last step's output var.

---

### 3. Tool picker overlay

Opened by "+ Add Step". Full-screen overlay or large modal.

```
┌────────────────────────────────────────────────┐
│  🔍 [Search tools...                         ] │
├──────────────────┬─────────────────────────────┤
│  All             │                             │
│  Gmail       (14)│  weather.get_current_weather│
│  Calendar     (5)│  Get current weather for    │
│  Drive        (3)│  a city.                    │
│  Weather      (3)│                             │
│  Web          (1)│  Params: city               │
│  Memory       (2)│                             │
│  Processing   (1)│         [Add this step]     │
└──────────────────┴─────────────────────────────┘
```

- Left: category filter tabs with counts
- Right: tool detail (name, description, param list preview)
- "Add this step" adds the tool as a new step and closes the overlay
- Tools that `require_confirmation` show a ⚠️ badge ("will ask for approval before running")

---

### 4. Run result modal

Triggered by the Run button (saves first if unsaved, then calls `POST /agent/workflows/<id>/run/`).

```
┌──────────────────────────────────────┐
│  Running "Daily weather brief"  ⟳   │
│                                      │
│  ✓ Step 1 — weather.get_current_...  │
│  ✓ Step 2 — processing_llm           │
│                                      │
│  Result                              │
│  ┌────────────────────────────────┐  │
│  │ Today in Tokyo: 22°C, partly   │  │
│  │ cloudy with a light breeze...  │  │
│  └────────────────────────────────┘  │
│                      [Close] [Copy]  │
└──────────────────────────────────────┘
```

- Steps tick off as they complete (poll or optimistic — the sync endpoint returns only when done)
- Final result shown in a scrollable text area
- Copy button copies result to clipboard
- If a step requires confirmation, pause and show a "Confirm / Cancel" prompt inline before continuing

---

## State model

```ts
interface WorkflowStep {
  id: string;           // "s1", "s2", ...
  tool: string;         // tool name from registry
  params: Record<string, string | number | boolean>;
  output_var: string;
}

interface WorkflowDraft {
  id?: number;          // undefined = unsaved
  name: string;
  description: string;
  project_id?: number;
  steps: WorkflowStep[];
  final_output_var: string;
  summary: string;      // auto-generated from step list on save
}
```

Auto-generate `summary` on save: `"${steps.map(s => s.tool).join(' → ')}"`.

Auto-generate step `id` as `s${index + 1}` and resequence on reorder/delete.

---

## Validation (client-side, before save/run)

- `name` must be non-empty
- At least one step
- Every step must have a `tool` selected
- All required params (non-optional in schema) must be non-empty
- `output_var` names must be unique across all steps
- `final_output_var` must reference an existing step's `output_var`
- Variable references (`$foo`) in params must resolve to a prior step's `output_var` (warn, don't block)

---

## Key UX decisions

1. **Save before run** — clicking Run on an unsaved workflow auto-saves first, then runs. Never run a stale draft.
2. **Optimistic output_var naming** — default to `step1_out`, `step2_out`, etc. Users rename only when they want readable variable names in params.
3. **No branching / conditions in V1** — steps are strictly linear. Conditionals are a V2 concern.
4. **$variable insertion is additive** — clicking a variable from the panel appends it to the current cursor position in the field; it doesn't replace the field value.
5. **Unsaved changes warning** — navigating away from an unsaved draft shows a "You have unsaved changes" browser prompt.
