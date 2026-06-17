# SQL Q&A Demo

A chatbot that translates plain-English questions into SQL queries against a SQL Server database. Built with LangGraph for multi-step agent orchestration and FAISS for intelligent schema pruning.

---

## Features

- **Plain-English queries** — ask questions naturally; the agent writes and runs the SQL
- **Ambiguity clarification** — when a question is genuinely ambiguous, the agent asks for clarification before querying
- **SQL validation gate** — generated SQL is checked against schema and business rules before hitting the database
- **Smart repair on error** — if execution fails, the agent diagnoses the exact error and makes a targeted fix (up to 3 retries)
- **Excel / CSV report export** — say "give me an Excel report of..." to download a file
- **Follow-up questions** — the agent carries conversation context across turns ("what about last month?", "same but for agents")
- **Schema pruning** — FAISS vector index selects only the relevant tables from the schema, keeping prompts tight

---

## Architecture

```
User question
      │
      ▼
analyze_question ──► chat_response (greetings / capability questions)
      │
      ├──► clarify (ambiguous question → ask user)
      │
      └──► fetch_schema
                │
                ▼
          generate_sql
                │
                ▼
          validate_sql  ◄── semantic quality gate (enums, table choice, join keys)
                │
                ▼
          execute_sql ──► (error + retries left) ──► generate_sql
                │
                ├──► generate_report  (Excel / CSV)
                │
                └──► format_response
```

All agent state flows through `SQLAgentState` (TypedDict). Routing decisions are made by pure functions so the graph stays testable.

---

## Project Structure

```
├── app.py                  # Streamlit UI entry point
├── config.py               # All configuration (LLM, DB, schema index settings)
├── platform_context.md     # Business context: table purposes, enums, join patterns
├── requirements.txt
│
├── agent/
│   ├── state.py            # SQLAgentState TypedDict
│   ├── graph.py            # LangGraph graph + routing functions
│   └── nodes.py            # Node implementations
│
├── tools/
│   ├── schema_index.py     # FAISS index: build + retrieve relevant tables
│   ├── sql_tools.py        # SQL execution helpers
│   └── report_generator.py # Excel / CSV export
│
└── utils/
    └── prompts.py          # All LLM prompt templates + JSON extractor
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

> Requires Python 3.11+ and [ODBC Driver 17 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server).

### 2. Configure

Open `config.py` and fill in your values:

```python
# LLM — choose "openai" or "anthropic"
LLM_PROVIDER    = "openai"
OPENAI_API_KEY  = "sk-..."
OPENAI_MODEL    = "gpt-5.4"

# Database
DB_SERVER   = "your-server-ip"
DB_PORT     = 1433
DB_NAME     = "YourDatabase"
DB_USERNAME = "your_user"
DB_PASSWORD = "your_password"
```

### 3. Build the schema index

On first run, click **Rebuild index** in the sidebar — this introspects the database, builds embedding documents for every table (enriched with descriptions from `platform_context.md`), and saves a FAISS index to `schema_index/`.

Rebuild whenever:
- Tables are added or removed from the database
- `platform_context.md` is updated with new table descriptions or enum values

### 4. Run

```bash
streamlit run app.py
```

---

## Configuration Reference

| Key | Default | Description |
|-----|---------|-------------|
| `LLM_PROVIDER` | `"openai"` | `"openai"` or `"anthropic"` |
| `OPENAI_MODEL` | `"gpt-5.4"` | Model name passed to ChatOpenAI |
| `ANTHROPIC_MODEL` | `"claude-sonnet-4-6"` | Model name passed to ChatAnthropic |
| `MAX_RETRIES` | `3` | Max SQL repair attempts per question |
| `SCHEMA_MAX_TABLES` | `8` | Max tables injected into the SQL prompt |
| `SCHEMA_SCORE_THRESHOLD` | `0.25` | FAISS cosine similarity cutoff (0–1) |
| `EMBEDDING_PROVIDER` | `"huggingface"` | `"huggingface"` (local) or `"openai"` |

---

## Utilities

**Inspect the database schema:**

```bash
python test_schema.py            # list all tables
python test_schema.py 1 10       # print schema for tables 1–10
python test_schema.py --txt      # export full schema to schema_<DB>.txt
```

---

## Platform Context

`platform_context.md` is the single source of truth for business-specific knowledge:

- **Table purposes** — what each table stores and when to use it
- **Enum values** — `appStatus`, `appUserType`, `BetStatus` codes
- **Join patterns** — polymorphic FK rules (e.g. `tblDepositWithdrawCount.appUserType`)
- **P&L routing** — sports vs casino split via `appTPGameRefID`

Both the SQL generation prompt and the FAISS schema index are built from this file. Update it when the business adds new tables or enum values, then rebuild the schema index.
