from typing import TypedDict, Optional


class SQLAgentState(TypedDict):
    # Input
    user_question: str

    # Phase 1: question understanding
    question_analysis: Optional[dict]   # intent, type, entities, etc.
    relevant_tables:   Optional[list]   # tables the LLM thinks are needed
    is_report_request: bool
    report_format:     Optional[str]    # "excel" | "csv"
    needs_db:          bool             # False → answer conversationally, skip DB pipeline

    # Phase 2: schema
    schema_info: Optional[str]

    # Phase 3: SQL generation
    sql_query:      Optional[str]
    sql_explanation: Optional[str]

    # Phase 4: execution
    query_results: Optional[list]   # list of row dicts
    column_names:  Optional[list]
    row_count:     Optional[int]

    # Phase 5: output
    response:    Optional[str]
    report_path: Optional[str]

    # Error handling / retry
    error:       Optional[str]
    retry_count: int

    # Ambiguity detection (set during analyze_question)
    is_ambiguous:          bool
    clarification_question: Optional[str]

    # Conversation memory (injected from outside; not mutated by the graph)
    # Each entry: {"role": "user"|"assistant", "content": str, "sql_query": str|None}
    conversation_history: list
