"""Streamlit login form and session helpers."""
import streamlit as st
from auth.users import verify_password


def show_login() -> bool:
    """Render login form. Returns True when the session is authenticated."""
    if st.session_state.get("authenticated"):
        return True

    # Centre the form with columns
    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        st.markdown(
            "<h2 style='text-align:center; color:#3d3530; margin-bottom:1.5rem;'>"
            "🗄️ SQL Q&A Agent</h2>",
            unsafe_allow_html=True,
        )
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)

        if submitted:
            if not username or not password:
                st.error("Please enter both username and password.")
                return False
            user = verify_password(username, password)
            if user:
                st.session_state["authenticated"] = True
                st.session_state["current_user"]  = {
                    "id":       user["id"],
                    "username": user["username"],
                    "role":     user["role"],
                    "agent_id": user["agent_id"],
                }
                st.rerun()
            else:
                st.error("Invalid username or password.")

    return False


def logout() -> None:
    """Clear auth session state and rerun."""
    for key in ("authenticated", "current_user", "messages",
                "_running", "_current_question", "_stop_event",
                "_result_queue", "_progress", "_idx_status"):
        st.session_state.pop(key, None)
    st.rerun()
