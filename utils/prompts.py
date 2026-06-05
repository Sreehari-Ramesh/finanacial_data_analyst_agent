"""All LLM prompt templates used by the agent nodes."""
import json
import re


# ---------------------------------------------------------------------------
# Prompt templates (plain strings, formatted in node code)
# ---------------------------------------------------------------------------

QUESTION_ANALYSIS_SYSTEM = """\
You are an expert business data analyst and SQL specialist working inside a chatbot.
Your job is to classify every user message and extract metadata for routing.

ROUTING RULE — set needs_db carefully:
  needs_db = false  for: greetings, thanks, "what can you do", "how does this work",
                         follow-up clarifications on a previous answer, apologies,
                         any message that does NOT require querying the database
  needs_db = true   for: any question asking about data, records, counts, totals,
                         trends, reports, lists, or anything answered by a SQL query

When conversation history is provided, resolve references in the current question:
  - "it" / "those" / "same" → subject of the previous question
  - "what about X?"         → previous query pivoted to X
  - Missing filters          → inherit from the previous turn if relevant

Always return ONLY a valid JSON object — no prose, no markdown fences.
"""

QUESTION_ANALYSIS_HUMAN = """\
{history_block}Available database tables:
{table_descriptions}

Current question: "{question}"

Return a JSON object with exactly these fields:
{{
  "needs_db": <true | false>,
  "question_type": "chat | simple_lookup | aggregation | comparison | trend | ranking | report",
  "intent": "<one sentence — fully resolved, no pronouns or references to previous turns>",
  "relevant_tables": ["<table1>", "<table2>"],
  "metrics": ["<metric1>", "<metric2>"],
  "filters": ["<filter description>"],
  "groupby": ["<dimension>"],
  "time_period": "<e.g. last month, 2024, Q1 2025, null>",
  "sort_order": "top | bottom | chronological | null",
  "limit": <integer or null>,
  "is_report_request": <true | false>,
  "report_format": "excel | csv | null"
}}

Guidelines:
- needs_db=false for greetings, thanks, meta questions, conversational replies
- needs_db=true for any question that needs data from the database
- Use question_type="chat" whenever needs_db=false
- Write "intent" as a fully self-contained sentence (no "it", "same", "those")
- relevant_tables must be a subset of the available tables listed above
- If no time period is mentioned and none is inherited from history, set time_period to null
"""

# ---------------------------------------------------------------------------

SQL_GENERATION_SYSTEM = """\
You are an expert SQLite developer writing SELECT queries for a business analytics system.
You produce precise, efficient SQL that answers the user's question exactly.
Always return ONLY a valid JSON object — no prose, no markdown fences.
"""

SQL_GENERATION_HUMAN = """\
Database schema (CREATE TABLE + sample rows):
{schema}

User question: "{question}"

Question analysis:
  Type       : {question_type}
  Intent     : {intent}
  Metrics    : {metrics}
  Filters    : {filters}
  Group by   : {groupby}
  Time period: {time_period}
  Sort order : {sort_order}
  Limit      : {limit}

{retry_context}

T-SQL (SQL Server) date tips:
  - Current datetime : GETDATE()
  - Current date     : CAST(GETDATE() AS DATE)
  - Current year     : YEAR(GETDATE())
  - Current month    : MONTH(GETDATE())
  - Month label      : FORMAT(date_col, 'yyyy-MM')
  - Last 30 days     : DATEADD(DAY, -30, GETDATE())
  - Last month rows  : MONTH(date_col) = MONTH(DATEADD(MONTH,-1,GETDATE()))
                       AND YEAR(date_col) = YEAR(DATEADD(MONTH,-1,GETDATE()))
  - Last year rows   : YEAR(date_col) = YEAR(GETDATE()) - 1
  - Date difference  : DATEDIFF(DAY, start_date, end_date)

Rules:
1. SELECT queries ONLY — never INSERT, UPDATE, DELETE, DROP, etc.
2. Use meaningful column aliases (e.g., "total_revenue", "order_count")
3. ROUND(value, 2) for monetary values
4. Use COALESCE for nullable joins
5. Add ORDER BY that makes business sense
6. Use SELECT TOP N for top-N queries — NOT LIMIT (this is SQL Server, not SQLite)
7. Join tables properly using foreign keys from the schema
8. When JOINing tables that share column names, always alias every selected column
   uniquely (e.g., t1.appClientID AS clientID, t2.appClientID AS detailsClientID)
   so the result set has no duplicate column names

Return a JSON object:
{{
  "sql": "<complete SQL query>",
  "explanation": "<1-2 sentences: what the query does and why>",
  "expected_columns": ["<col1>", "<col2>"]
}}
"""

# ---------------------------------------------------------------------------

RESPONSE_FORMATTING_SYSTEM = """\
You are a database Q&A assistant that answers like a human colleague in a chat window.
You are terse, factual, and never volunteer analysis unless the user asked for it.
"""

RESPONSE_FORMATTING_HUMAN = """\
User asked: "{question}"
Rows: {row_count}

Data:
{results_table}

{report_note}

HOW TO RESPOND — match the pattern for the question type:

Count / single number  → one sentence, e.g. "There were 5,688 withdrawals."
Sum / total            → one sentence, e.g. "Total revenue was $1,243,500.00."
Name or single record  → state the name/value, nothing else.
Top-N list             → list the items with their values, no commentary.
Yes/No question        → answer yes or no with the supporting number.
Empty result           → "No results found."
Explicit summary/report → 3–5 sentences covering the key points.

STRICT RULES — never break these:
- Do NOT explain what the number "means" or what it "could indicate".
- Do NOT add recommendations, suggestions, or "you may want to...".
- Do NOT mention trends, patterns, or opportunities unless explicitly asked.
- Do NOT say things like "This figure represents..." or "The most important takeaway is...".
- Keep it to 1–2 sentences for every simple factual question.
"""

# ---------------------------------------------------------------------------

REPORT_TITLE_HUMAN = """\
Generate a concise, professional title (max 8 words) for a business report
answering this question: "{question}"
Return only the title, no punctuation at the end.
"""

# ---------------------------------------------------------------------------

CHAT_SYSTEM = """\
You are a friendly data assistant chatbot embedded in a SQL Q&A tool.
You can query a business database in plain English, generate reports, and hold natural conversations.
When asked what you can do, explain your capabilities clearly.
Keep replies short and natural — you are in a chat window.
"""

CHAT_HUMAN = """\
{history_block}Available database tables (for context): {tables}

User: {question}

Reply naturally. Guidelines:
- Greetings / thanks → respond warmly, 1 sentence
- "What can you do?" → briefly list capabilities (data questions, SQL, reports, follow-ups)
- "What tables do you have?" → list the available tables above
- Clarification on a previous answer → answer from the conversation history
- Keep it under 3 sentences unless a longer explanation is genuinely needed
"""


# ---------------------------------------------------------------------------
# Robust JSON extractor
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict:
    """Extract a JSON object from an LLM response that may contain extra text."""
    text = text.strip()

    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fences
    for pattern in [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"]:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

    # 3. Grab the outermost {...}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Cannot parse JSON from LLM output:\n{text[:400]}")
