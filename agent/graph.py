"""Build and compile the LangGraph SQL agent."""
from langgraph.graph import StateGraph, START, END

from agent.state import SQLAgentState
from agent.nodes import (
    analyze_question,
    chat_response,
    clarify,
    fetch_schema,
    generate_sql,
    validate_sql,
    execute_sql,
    generate_report,
    format_response,
)
from config import MAX_RETRIES


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_after_execution(state: SQLAgentState) -> str:
    """After execute_sql:
      - Error + retries remaining  → re-generate SQL
      - Success + report requested → generate report file
      - Success + plain query      → format response
    """
    if state.get("error") and state.get("retry_count", 0) < MAX_RETRIES:
        return "generate_sql"

    if state.get("is_report_request") and not state.get("error"):
        return "generate_report"

    return "format_response"


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def route_after_analysis(state: SQLAgentState) -> str:
    """Route based on needs_db and is_ambiguous flags set during analysis."""
    if not state.get("needs_db", True):
        return "chat_response"
    if state.get("is_ambiguous", False):
        return "clarify"
    return "fetch_schema"


def build_graph():
    """Compile and return the runnable LangGraph agent."""
    g = StateGraph(SQLAgentState)

    # Register nodes
    g.add_node("analyze_question", analyze_question)
    g.add_node("chat_response",    chat_response)
    g.add_node("clarify",          clarify)
    g.add_node("fetch_schema",     fetch_schema)
    g.add_node("generate_sql",     generate_sql)
    g.add_node("validate_sql",     validate_sql)
    g.add_node("execute_sql",      execute_sql)
    g.add_node("generate_report",  generate_report)
    g.add_node("format_response",  format_response)

    # After analysis: chat shortcut or full DB pipeline
    g.add_edge(START, "analyze_question")
    g.add_conditional_edges(
        "analyze_question",
        route_after_analysis,
        {
            "chat_response": "chat_response",
            "clarify":       "clarify",
            "fetch_schema":  "fetch_schema",
        },
    )
    g.add_edge("chat_response", END)
    g.add_edge("clarify",       END)
    g.add_edge("fetch_schema",   "generate_sql")
    g.add_edge("generate_sql",   "validate_sql")
    g.add_edge("validate_sql",   "execute_sql")

    # Conditional routing after execution
    g.add_conditional_edges(
        "execute_sql",
        route_after_execution,
        {
            "generate_sql":    "generate_sql",
            "generate_report": "generate_report",
            "format_response": "format_response",
        },
    )

    # Report always flows into the response formatter
    g.add_edge("generate_report", "format_response")
    g.add_edge("format_response", END)

    return g.compile()


# Singleton — compiled once on import
agent_graph = build_graph()


def run_agent(question: str, conversation_history: list | None = None) -> dict:
    """Run the full agent pipeline for a user question.

    Args:
        question:             The current user question.
        conversation_history: Recent turns from the session — each entry is
                              {"role": "user"|"assistant", "content": str,
                               "sql_query": str|None}.
                              The agent uses this to resolve follow-up references
                              ("same", "it", "what about last month?", etc.).

    Returns the final state dict (response, sql_query, row_count, report_path, …).
    """
    initial_state: SQLAgentState = {
        "user_question":         question,
        "conversation_history":  conversation_history or [],
        "question_analysis":     None,
        "relevant_tables":       None,
        "is_report_request":     False,
        "report_format":         "excel",
        "needs_db":              True,
        "is_ambiguous":          False,
        "clarification_question": None,
        "schema_info":           None,
        "sql_query":             None,
        "sql_explanation":       None,
        "query_results":         None,
        "column_names":          None,
        "row_count":             None,
        "response":              None,
        "report_path":           None,
        "error":                 None,
        "retry_count":           0,
    }
    final_state = agent_graph.invoke(initial_state)
    return final_state
