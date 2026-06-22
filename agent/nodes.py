"""LangGraph node functions — each transforms a slice of SQLAgentState."""
from datetime import date as _date
from tabulate import tabulate
from langchain_core.messages import SystemMessage, HumanMessage

from config import get_llm
from agent.state import SQLAgentState
from database.schema import get_schema, get_all_table_names, get_table_descriptions
from tools.sql_tools import execute_query
from tools.report_generator import generate_excel_report, generate_csv_report
from utils.prompts import (
    QUESTION_ANALYSIS_SYSTEM,
    QUESTION_ANALYSIS_HUMAN,
    SQL_GENERATION_SYSTEM,
    SQL_GENERATION_HUMAN,
    REPAIR_SQL_SYSTEM,
    REPAIR_SQL_HUMAN,
    VALIDATE_SQL_SYSTEM,
    VALIDATE_SQL_HUMAN,
    RESPONSE_FORMATTING_SYSTEM,
    RESPONSE_FORMATTING_HUMAN,
    REPORT_TITLE_HUMAN,
    CHAT_SYSTEM,
    CHAT_HUMAN,
    extract_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _llm_json(system: str, human: str) -> dict:
    """Call the LLM and return parsed JSON."""
    llm = get_llm(temperature=0)
    messages = [SystemMessage(content=system), HumanMessage(content=human)]
    response = llm.invoke(messages)
    return extract_json(response.content)


def _llm_text(system: str, human: str) -> str:
    """Call the LLM and return plain text."""
    llm = get_llm(temperature=0.3)
    messages = [SystemMessage(content=system), HumanMessage(content=human)]
    response = llm.invoke(messages)
    return response.content.strip()


def _rows_to_table(rows: list, columns: list, max_rows: int = 25) -> str:
    if not rows:
        return "(no rows returned)"
    display = rows[:max_rows]
    table   = [[(v if (v := row.get(c)) is not None else "") for c in columns] for row in display]
    result  = tabulate(table, headers=columns, tablefmt="grid", maxcolwidths=30)
    if len(rows) > max_rows:
        result += f"\n... and {len(rows) - max_rows} more rows"
    return result


# ---------------------------------------------------------------------------
# Node 1 — Understand the question
# ---------------------------------------------------------------------------

def _format_history(history: list) -> str:
    """Format conversation history into a prompt block the LLM can parse."""
    if not history:
        return ""
    lines = ["Conversation so far (use this to resolve follow-up references):"]
    for msg in history:
        role = "User" if msg.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {msg.get('content', '')}")
        if msg.get("role") == "assistant" and msg.get("sql_query"):
            lines.append(f"  SQL used: {msg['sql_query']}")
    lines.append("")   # blank line before next section
    return "\n".join(lines) + "\n"


def analyze_question(state: SQLAgentState) -> dict:
    """Classify the question and extract intent, metrics, filters, etc."""
    history       = state.get("conversation_history") or []
    history_block = _format_history(history[-6:])   # last 3 turns (6 messages)

    human = QUESTION_ANALYSIS_HUMAN.format(
        history_block=history_block,
        table_descriptions=get_table_descriptions(),
        question=state["user_question"],
    )
    try:
        analysis = _llm_json(QUESTION_ANALYSIS_SYSTEM, human)
    except Exception:
        analysis = {
            "needs_db":              True,
            "is_ambiguous":          False,
            "clarification_question": None,
            "question_type":         "aggregation",
            "intent":                state["user_question"],
            "relevant_tables":       get_all_table_names(),
            "metrics":               [],
            "filters":               [],
            "groupby":               [],
            "time_period":           None,
            "sort_order":            None,
            "limit":                 None,
            "is_report_request":     False,
            "report_format":         None,
        }

    return {
        "question_analysis":     analysis,
        "needs_db":              bool(analysis.get("needs_db", True)),
        "is_ambiguous":          bool(analysis.get("is_ambiguous", False)),
        "clarification_question": analysis.get("clarification_question"),
        "relevant_tables":       analysis.get("relevant_tables") or get_all_table_names(),
        "is_report_request":     bool(analysis.get("is_report_request", False)),
        "report_format":         analysis.get("report_format") or "excel",
        "error":                 None,
        "retry_count":           0,
    }
 

# ---------------------------------------------------------------------------
# Node 1b — Conversational reply (no DB needed)
# ---------------------------------------------------------------------------

def chat_response(state: SQLAgentState) -> dict:
    """Return a natural conversational reply without touching the database."""
    history       = state.get("conversation_history") or []
    history_block = _format_history(history[-6:])

    tables = ", ".join(get_all_table_names()) or "none loaded yet"

    human = CHAT_HUMAN.format(
        history_block=history_block,
        tables=tables,
        question=state["user_question"],
    )
    try:
        response = _llm_text(CHAT_SYSTEM, human)
    except Exception:
        response = "Sorry, I ran into an issue. Could you rephrase that?"

    return {"response": response}


# ---------------------------------------------------------------------------
# Node 1c — Clarification request (question is ambiguous)
# ---------------------------------------------------------------------------

def clarify(state: SQLAgentState) -> dict:
    """Return the clarification question to the user instead of querying the DB."""
    q = (
        state.get("clarification_question")
        or "Could you clarify your question? It could mean a few different things."
    )
    return {"response": q}


# ---------------------------------------------------------------------------
# Node 2 — Retrieve pruned schema via vector index
# ---------------------------------------------------------------------------

def fetch_schema(state: SQLAgentState) -> dict:
    """Select only the tables most relevant to the question using FAISS retrieval.

    Steps:
      1. Ensure the schema index is built (metadata → embeddings → FAISS).
      2. Embed (question + intent + metrics) as the retrieval query.
      3. Cosine-search → top-k table names, merged with LLM hint tables.
      4. Fetch CREATE TABLE + sample rows for those tables only.
    """
    from tools.schema_index import get_schema_index
    from config import get_db_engine

    analysis    = state.get("question_analysis") or {}
    hint_tables = state.get("relevant_tables") or []

    # Build a rich retrieval query from everything the LLM extracted
    retrieval_query = " ".join(filter(None, [
        state["user_question"],
        analysis.get("intent", ""),
        " ".join(analysis.get("metrics", []) or []),
        " ".join(analysis.get("filters", []) or []),
    ]))

    index = get_schema_index()
    index.ensure_ready(get_db_engine())

    retrieved_tables = index.retrieve(
        query=retrieval_query,
        question_type=analysis.get("question_type", "aggregation"),
        hint_tables=hint_tables,
    )

    schema = get_schema(table_names=retrieved_tables)

    return {
        "schema_info":     schema,
        "relevant_tables": retrieved_tables,
    }


# ---------------------------------------------------------------------------
# Node 2b — Probe actual date ranges in the DB for relevant tables
# ---------------------------------------------------------------------------

_DATE_TYPE_TOKENS = {"DATE", "DATETIME", "DATETIME2", "SMALLDATETIME", "TIMESTAMP"}


def fetch_date_context(state: SQLAgentState) -> dict:
    """For each relevant table, run MIN/MAX on its primary date column.

    The result is a concise text block passed to the SQL generator so it knows
    whether the user's relative date expression ("last month", "last week") maps
    to data that actually exists in the DB — and can shift to the most recent
    available period if not.
    """
    from config import get_db_engine
    from sqlalchemy import inspect as sa_inspect, text as sa_text

    tables = state.get("relevant_tables") or []
    if not tables:
        return {"date_context": ""}

    try:
        engine    = get_db_engine()
        inspector = sa_inspect(engine)
        lines: list[str] = []

        for tbl in tables:
            try:
                cols = inspector.get_columns(tbl)
            except Exception:
                continue

            date_col: str | None = None
            for col in cols:
                type_name = type(col["type"]).__name__.upper()
                col_upper = col["name"].upper()
                if any(tok in type_name for tok in _DATE_TYPE_TOKENS) or "DATE" in col_upper:
                    date_col = col["name"]
                    break

            if not date_col:
                continue

            try:
                with engine.connect() as conn:
                    row = conn.execute(
                        sa_text(f"SELECT MIN([{date_col}]), MAX([{date_col}]) FROM [{tbl}]")
                    ).fetchone()
                if row and row[0] is not None:
                    min_d = str(row[0])[:10]
                    max_d = str(row[1])[:10]
                    lines.append(f"  {tbl:<42} {date_col}: {min_d} → {max_d}")
            except Exception:
                continue

        if not lines:
            return {"date_context": ""}

        ctx = "Available data date ranges (from DB):\n" + "\n".join(lines)
        # print(ctx)  # log for debugging
        return {"date_context": ctx}

    except Exception:
        return {"date_context": ""}


# ---------------------------------------------------------------------------
# Node 3 — Generate SQL
# ---------------------------------------------------------------------------

def generate_sql(state: SQLAgentState) -> dict:
    """Translate the natural-language question into a SQL query."""
    analysis  = state.get("question_analysis") or {}
    retry     = state.get("retry_count", 0)
    schema    = state.get("schema_info", "")
    question  = state["user_question"]

    if retry > 0 and state.get("error") and state.get("sql_query"):
        # Targeted repair: show the model exactly what broke and ask for a minimal fix
        human = REPAIR_SQL_HUMAN.format(
            schema=schema,
            question=question,
            failed_sql=state["sql_query"],
            error=state["error"],
        )
        try:
            result = _llm_json(REPAIR_SQL_SYSTEM, human)
        except Exception as exc:
            return {"error": f"SQL repair failed: {exc}"}
    else:
        # Fresh generation from question analysis
        human = SQL_GENERATION_HUMAN.format(
            schema=schema,
            question=question,
            question_type=analysis.get("question_type", "aggregation"),
            intent=analysis.get("intent", ""),
            metrics=", ".join(analysis.get("metrics") or []) or "none specified",
            filters=", ".join(analysis.get("filters") or []) or "none specified",
            groupby=", ".join(analysis.get("groupby") or []) or "none specified",
            time_period=analysis.get("time_period") or "none",
            sort_order=analysis.get("sort_order") or "none",
            limit=str(analysis.get("limit")) if analysis.get("limit") else "none",
            today_date=_date.today().isoformat(),
            date_context=state.get("date_context") or "",
            retry_context="",
        )
        try:
            result = _llm_json(SQL_GENERATION_SYSTEM, human)
        except Exception as exc:
            return {"error": f"SQL generation failed: {exc}"}

    sql  = result.get("sql", "").strip()
    expl = result.get("explanation", "")

    if not sql:
        return {"error": "LLM returned an empty SQL query."}

    return {
        "sql_query":       sql,
        "sql_explanation": expl,
        "error":           None,
    }


# ---------------------------------------------------------------------------
# Node 3b — Validate / self-correct the generated SQL before execution
# ---------------------------------------------------------------------------

def validate_sql(state: SQLAgentState) -> dict:
    """Review the generated SQL for semantic correctness before hitting the DB.

    Checks enum values, table choice, join keys, and filter alignment with the
    user intent. If the reviewer finds an issue it returns a corrected SQL;
    otherwise the state is unchanged (empty dict → no-op update).
    """
    sql = state.get("sql_query", "")
    if not sql:
        return {}

    analysis = state.get("question_analysis") or {}
    human = VALIDATE_SQL_HUMAN.format(
        question=state["user_question"],
        intent=analysis.get("intent", state["user_question"]),
        schema=state.get("schema_info", ""),
        sql=sql,
    )

    try:
        result   = _llm_json(VALIDATE_SQL_SYSTEM, human)
        final_sql = result.get("sql", "").strip()
        issues    = result.get("issues") or []

        if final_sql and final_sql != sql:
            note = f"[Validator corrections: {'; '.join(issues)}]" if issues else ""
            return {
                "sql_query":       final_sql,
                "sql_explanation": (state.get("sql_explanation") or "") + ("\n" + note if note else ""),
            }
    except Exception:
        pass  # validation failed — proceed with the original SQL unchanged

    return {}


# ---------------------------------------------------------------------------
# Node 4 — Execute SQL
# ---------------------------------------------------------------------------

def execute_sql(state: SQLAgentState) -> dict:
    """Run the generated SQL query against the database."""
    sql = state.get("sql_query", "")
    if not sql:
        return {"error": "No SQL query to execute."}

    # from agent.guards import guard_sql
    # is_safe, reason = guard_sql(sql)
    # if not is_safe:
    #     return {
    #         "error":       f"Query blocked by safety check: {reason}",
    #         "retry_count": state.get("retry_count", 0) + 1,
    #     }

    result = execute_query(sql)

    if result["success"]:
        return {
            "query_results": result["rows"],
            "column_names":  result["columns"],
            "row_count":     result["row_count"],
            "error":         None,
        }
    else:
        return {
            "query_results": [],
            "column_names":  [],
            "row_count":     0,
            "error":         result["error"],
            "retry_count":   state.get("retry_count", 0) + 1,
        }


# ---------------------------------------------------------------------------
# Node 5 — Generate report file (optional)
# ---------------------------------------------------------------------------

def generate_report(state: SQLAgentState) -> dict:
    """Create an Excel or CSV file from the query results."""
    rows    = state.get("query_results") or []
    columns = state.get("column_names") or []
    question = state["user_question"]
    fmt      = (state.get("report_format") or "excel").lower()

    # Ask LLM for a polished report title
    try:
        title = _llm_text("", REPORT_TITLE_HUMAN.format(question=question))
    except Exception:
        title = f"Report: {question[:60]}"

    try:
        if fmt == "csv":
            data, fname = generate_csv_report(rows, columns, question)
        else:
            data, fname = generate_excel_report(
                rows, columns, question,
                title=title,
                sql_query=state.get("sql_query", ""),
            )
        return {"report_bytes": data, "report_filename": fname}
    except Exception as exc:
        return {"report_bytes": None, "report_filename": None, "error": f"Report generation failed: {exc}"}


# ---------------------------------------------------------------------------
# Node 6 — Format final natural-language response
# ---------------------------------------------------------------------------

def format_response(state: SQLAgentState) -> dict:
    """Turn the raw query results into a natural-language answer."""
    rows     = state.get("query_results") or []
    columns  = state.get("column_names") or []
    question = state["user_question"]
    analysis = state.get("question_analysis") or {}

    # Validation: empty result with no error — return directly, skip LLM call
    if not rows and not state.get("error"):
        return {
            "response": (
                "No results found. The query ran successfully but returned no data — "
                "the filters may be too specific, or data may not exist for the requested period."
            )
        }

    # Build the results table string for the prompt
    results_table = _rows_to_table(rows, columns)

    report_note = ""
    if state.get("report_filename"):
        report_note = f"Report ready to download: {state['report_filename']}"

    # Handle execution error case
    if state.get("error") and not rows:
        response = (
            f"I encountered an error while trying to answer your question: "
            f"{state['error']}\n\n"
            "Please try rephrasing your question, or check that the database has relevant data."
        )
        return {"response": response}

    human = RESPONSE_FORMATTING_HUMAN.format(
        question=question,
        question_type=analysis.get("question_type", "query"),
        sql_query=state.get("sql_query", ""),
        row_count=state.get("row_count", 0),
        results_table=results_table,
        report_note=report_note,
    )

    try:
        response = _llm_text(RESPONSE_FORMATTING_SYSTEM, human)
    except Exception:
        # Fallback: return raw table
        response = (
            f"Query returned {state.get('row_count', 0)} rows.\n\n"
            f"{results_table}"
        )

    return {"response": response}
