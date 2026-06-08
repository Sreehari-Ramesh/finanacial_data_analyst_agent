"""Streamlit UI for the LangGraph SQL Q&A Agent."""
import sys
import io
import time
import threading
import queue as _queue
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

st.set_page_config(
    page_title="SQL Q&A Agent",
    page_icon="🗄️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* Background */
.stApp { background: #0d1117; }
.block-container { padding-top: 1.2rem !important; }

/* Sidebar */
[data-testid="stSidebar"] > div:first-child {
    background: #161b22;
    border-right: 1px solid #21262d;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label { color: #c9d1d9 !important; }

/* Chat input */
[data-testid="stChatInput"] textarea {
    background: #161b22 !important;
    border: 1px solid #30363d !important;
    color: #e6edf3 !important;
    border-radius: 10px !important;
}

/* Expanders */
[data-testid="stExpander"] {
    background: #161b22 !important;
    border: 1px solid #21262d !important;
    border-radius: 8px !important;
}
[data-testid="stExpander"] summary { color: #8b949e !important; }
[data-testid="stExpander"] summary:hover { color: #c9d1d9 !important; }

/* Code blocks */
.stCodeBlock pre { background: #1e1e2e !important; border-radius: 8px !important; }

/* Dataframe */
[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }

/* Status */
[data-testid="stStatus"] { border-radius: 10px !important; }

/* Divider */
hr { border-color: #21262d !important; }

/* Sidebar buttons */
.stButton > button {
    background: #161b22 !important;
    border: 1px solid #30363d !important;
    color: #8b949e !important;
    border-radius: 10px !important;
    padding: 8px 14px !important;
    font-size: 0.87rem !important;
    width: 100%;
    transition: all 0.15s;
}
.stButton > button:hover {
    background: #1f2d45 !important;
    border-color: #388bfd !important;
    color: #e6edf3 !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #0d1117; }
::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────

def _init():
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("_running", False)
    st.session_state.setdefault("_current_question", "")
    st.session_state.setdefault("_stop_event", None)
    st.session_state.setdefault("_result_queue", None)
    st.session_state.setdefault("_progress", {"step": ""})


# ── DB connection (cached across reruns) ──────────────────────────────────────

@st.cache_resource(show_spinner=False)
def _db_info() -> dict:
    from database.db_setup import test_connection
    return test_connection()


@st.cache_resource(show_spinner=False)
def _ensure_schema_index() -> str:
    try:
        from tools.schema_index import get_schema_index
        from config import get_db_engine
        index = get_schema_index()
        engine = get_db_engine()
        if index.needs_rebuild(engine):
            index.build(engine)
        else:
            index.load()
        import json
        meta = json.loads(index._meta_path().read_text())
        return f"indexed:{meta['count']}"
    except Exception as exc:
        return f"error:{exc}"


# ── Background agent worker ───────────────────────────────────────────────────

def _agent_worker(
    question: str,
    history: list,
    result_q: "_queue.Queue",
    stop_ev: threading.Event,
    progress: dict,
):
    """Runs agent nodes in a daemon thread. Stops cleanly on stop_ev."""
    from agent.nodes import (
        analyze_question, chat_response,
        fetch_schema, generate_sql,
        execute_sql, format_response, generate_report,
    )
    from config import MAX_RETRIES

    def stopped():
        return stop_ev.is_set()

    state: dict = {
        "user_question":        question,
        "conversation_history": history,
        "needs_db":             True,
        "question_analysis":    None,
        "relevant_tables":      None,
        "is_report_request":    False,
        "report_format":        "excel",
        "schema_info":          None,
        "sql_query":            None,
        "sql_explanation":      None,
        "query_results":        None,
        "column_names":         None,
        "row_count":            None,
        "response":             None,
        "report_path":          None,
        "error":                None,
        "retry_count":          0,
    }

    try:
        # progress["step"] = "🔍 Understanding your question…"
        if stopped(): result_q.put({"__stopped__": True}); return
        state.update(analyze_question(state))

        if not state.get("needs_db", True):
            # progress["step"] = "💬 Preparing answer…"
            if stopped(): result_q.put({"__stopped__": True}); return
            state.update(chat_response(state))
            result_q.put(state)
            return

        # progress["step"] = "📋 Reading database schema…"
        if stopped(): result_q.put({"__stopped__": True}); return
        state.update(fetch_schema(state))

        for attempt in range(MAX_RETRIES + 1):
            # progress["step"] = (
            #     "⚙️ Writing SQL query…"
            #     if attempt == 0
            #     else f"⚙️ Fixing SQL (attempt {attempt + 1})…"
            # )
            if stopped(): result_q.put({"__stopped__": True}); return
            state.update(generate_sql(state))

            progress["step"] = "⚡ Querying database…"
            if stopped(): result_q.put({"__stopped__": True}); return
            state.update(execute_sql(state))

            if not state.get("error"):
                break
            if state.get("retry_count", 0) >= MAX_RETRIES:
                break

        if state.get("is_report_request") and not state.get("error"):
            progress["step"] = "📊 Building report file…"
            if stopped(): result_q.put({"__stopped__": True}); return
            state.update(generate_report(state))

        progress["step"] = "💬 Preparing answer…"
        if stopped(): result_q.put({"__stopped__": True}); return
        state.update(format_response(state))

        result_q.put(state)

    except Exception as exc:
        result_q.put({"__error__": str(exc)})


def _build_history(n_turns: int = 3) -> list:
    msgs   = st.session_state.get("messages", [])
    recent = msgs[-(n_turns * 2):]
    return [
        {
            "role":      m["role"],
            "content":   m.get("content", ""),
            "sql_query": m.get("sql_query"),
        }
        for m in recent
    ]


def _start_agent(question: str):
    """Kick off the background agent thread for the given question."""
    stop_ev  = threading.Event()
    result_q = _queue.Queue()
    progress = {"step": "Starting…"}

    thread = threading.Thread(
        target=_agent_worker,
        args=(question, _build_history(), result_q, stop_ev, progress),
        daemon=True,
    )

    st.session_state._running         = True
    st.session_state._current_question = question
    st.session_state._stop_event      = stop_ev
    st.session_state._result_queue    = result_q
    st.session_state._progress        = progress

    thread.start()


# ── Result renderer ───────────────────────────────────────────────────────────

def render_result(msg: dict, key_prefix: str = ""):
    answer = msg.get("content") or msg.get("response") or ""
    st.markdown(answer if answer else "_No response generated._")

    row_count   = msg.get("row_count")
    sql         = msg.get("sql_query")
    results     = msg.get("query_results") or []
    col_names   = msg.get("column_names") or []
    report_path = msg.get("report_path")

    badges = []
    if row_count is not None:
        badges.append(f"🗃️ **{row_count}** row{'s' if row_count != 1 else ''}")
    if sql:
        badges.append("📝 SQL generated")
    if report_path:
        badges.append("📊 Report ready")
    if badges:
        st.caption("  ·  ".join(badges))

    if sql:
        with st.expander("View SQL"):
            st.code(sql, language="sql")

    if results and col_names:
        df = pd.DataFrame(results, columns=col_names)
        if not df.columns.is_unique:
            seen: dict = {}
            deduped = []
            for col in df.columns:
                if col in seen:
                    seen[col] += 1
                    deduped.append(f"{col}_{seen[col]}")
                else:
                    seen[col] = 0
                    deduped.append(col)
            df.columns = deduped
        with st.expander(f"View Data  ({row_count} rows)"):
            st.dataframe(df, use_container_width=True, hide_index=True)
            c1, c2, _ = st.columns([1, 1, 4])
            with c1:
                st.download_button(
                    "⬇ CSV",
                    data=df.to_csv(index=False).encode(),
                    file_name="results.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key=f"{key_prefix}_csv",
                )
            with c2:
                buf = io.BytesIO()
                df.to_excel(buf, index=False)
                st.download_button(
                    "⬇ Excel",
                    data=buf.getvalue(),
                    file_name="results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key=f"{key_prefix}_xlsx",
                )

    if report_path and Path(report_path).exists():
        with open(report_path, "rb") as f:
            st.download_button(
                "📥 Download Full Report",
                data=f.read(),
                file_name=Path(report_path).name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"{key_prefix}_report",
            )


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar(info: dict):
    with st.sidebar:
        st.markdown(
            "<h2 style='color:#58a6ff; margin-bottom:0;'>🗄️ SQL Q&A</h2>",
            unsafe_allow_html=True,
        )
        st.caption("Powered by LangChain · LangGraph")
        st.divider()

        if info.get("success"):
            st.markdown(
                f"🟢 **Connected**  \n"
                f"Server &nbsp; `{info.get('server','—')}`  \n"
                f"Database &nbsp; `{info.get('database','—')}`"
            )
        else:
            st.markdown("🔴 **Not Connected**")
            st.error(info.get("error", "Unknown error"), icon="⚠️")

        st.divider()

        tables = info.get("tables", [])
        st.caption(f"📦 {len(tables)} table{'s' if len(tables) != 1 else ''} available")

        idx_status = st.session_state.get("_idx_status", "")
        if idx_status.startswith("indexed:"):
            n = idx_status.split(":")[1]
            st.caption(f"🧠 Schema index · {n} tables embedded")
        elif idx_status.startswith("error:"):
            st.caption("⚠️ Schema index error")
        else:
            st.caption("⏳ Schema index loading…")

        if st.button("🔄 Rebuild index", use_container_width=True,
                     help="Force-rebuild the schema embedding index"):
            st.cache_resource.clear()
            st.session_state["_idx_status"] = ""
            st.rerun()

        st.divider()

        n = len([m for m in st.session_state.messages if m["role"] == "user"])
        st.caption(f"💬 {n} question{'s' if n != 1 else ''} this session")

        if st.button("🧹 Clear conversation", use_container_width=True):
            st.session_state.messages = []
            # Cancel any running query too
            if st.session_state.get("_stop_event"):
                st.session_state._stop_event.set()
            st.session_state._running = False
            st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    _init()
    info = _db_info()
    render_sidebar(info)

    st.markdown(
        "<h1 style='font-size:1.5rem; color:#e6edf3; margin-bottom:0.2rem;'>"
        "SQL Q&amp;A Agent</h1>",
        unsafe_allow_html=True,
    )

    if not info.get("success"):
        st.error(
            f"Cannot connect to SQL Server. Check your `.env` file.  \n"
            f"`{info.get('error','Unknown error')}`",
            icon="🔌",
        )
        st.stop()

    # Build / load schema index once
    if "_idx_status" not in st.session_state:
        with st.spinner("Building schema index…"):
            status = _ensure_schema_index()
        st.session_state["_idx_status"] = status
        if status.startswith("error:"):
            st.warning(f"Schema index could not be built: {status[6:]}", icon="⚠️")

    # ── Chat history ──────────────────────────────────────────────────────────
    for i, msg in enumerate(st.session_state.messages):
        if msg["role"] == "user":
            with st.chat_message("user", avatar="👤"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("assistant", avatar="🤖"):
                render_result(msg, key_prefix=f"h{i}")

    # ── Running state: show progress + stop button ────────────────────────────
    if st.session_state._running:
        q_text   = st.session_state._current_question
        result_q = st.session_state._result_queue
        progress = st.session_state._progress

        with st.chat_message("user", avatar="👤"):
            st.markdown(q_text)

        with st.chat_message("assistant", avatar="🤖"):
            step = progress.get("step", "Working…")
            left, right = st.columns([5, 1])
            with left:
                st.markdown(f"⏳ &nbsp; {step}")
            with right:
                if st.button("⏹ Stop", type="secondary", key="stop_btn",
                             use_container_width=True):
                    st.session_state._stop_event.set()
                    st.session_state._running = False
                    st.session_state.messages.append(
                        {"role": "user", "content": q_text}
                    )
                    st.session_state.messages.append(
                        {"role": "assistant", "content": "_Query stopped._"}
                    )
                    st.rerun()

        # Poll result queue (non-blocking)
        try:
            result = result_q.get_nowait()
            st.session_state._running = False

            if result.get("__stopped__"):
                st.session_state.messages.append(
                    {"role": "user", "content": q_text}
                )
                st.session_state.messages.append(
                    {"role": "assistant", "content": "_Query stopped._"}
                )
            elif result.get("__error__"):
                st.session_state.messages.append(
                    {"role": "user", "content": q_text}
                )
                st.session_state.messages.append(
                    {"role": "assistant",
                     "content": f"Something went wrong: {result['__error__']}"}
                )
            else:
                st.session_state.messages.append(
                    {"role": "user", "content": q_text}
                )
                st.session_state.messages.append({
                    "role":          "assistant",
                    "content":       result.get("response", ""),
                    "sql_query":     result.get("sql_query"),
                    "query_results": result.get("query_results"),
                    "column_names":  result.get("column_names"),
                    "row_count":     result.get("row_count"),
                    "report_path":   result.get("report_path"),
                })

            st.rerun()

        except _queue.Empty:
            # Still running — wait briefly then rerun to poll again
            time.sleep(0.3)
            st.rerun()

        return  # Don't render chat input while running

    # ── Idle state: accept new question ───────────────────────────────────────
    question = st.chat_input("Ask anything about your data…")
    if question:
        _start_agent(question)
        st.rerun()


if __name__ == "__main__":
    main()
