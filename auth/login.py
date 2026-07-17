"""Streamlit login / registration form and session helpers."""
import streamlit as st
from auth.users import verify_password, create_user


def show_login() -> bool:
    """Render login / register page. Returns True when the session is authenticated."""
    if st.session_state.get("authenticated"):
        return True

    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        st.markdown(
            "<h2 style='text-align:center; color:#3d3530; margin-bottom:1.2rem;'>"
            "🗄️ SQL Q&A Agent</h2>",
            unsafe_allow_html=True,
        )

        sign_in_tab, register_tab = st.tabs(["Sign In", "Create Account"])

        # ── Sign In ───────────────────────────────────────────────────────────
        with sign_in_tab:
            with st.form("login_form", clear_on_submit=False):
                username  = st.text_input("Username", placeholder="Enter your username")
                password  = st.text_input("Password", type="password",
                                          placeholder="Enter your password")
                submitted = st.form_submit_button("Sign in", use_container_width=True)

            if submitted:
                if not username or not password:
                    st.error("Please enter both username and password.")
                else:
                    user = verify_password(username, password)
                    if user:
                        _set_session(user)
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")

        # ── Create Account ────────────────────────────────────────────────────
        with register_tab:
            with st.form("register_form", clear_on_submit=True):
                new_username = st.text_input("Username", placeholder="Choose a username",
                                             key="reg_username")
                new_password = st.text_input("Password", type="password",
                                             placeholder="Min 6 characters",
                                             key="reg_password")
                confirm_pwd  = st.text_input("Confirm Password", type="password",
                                             placeholder="Repeat your password",
                                             key="reg_confirm")
                register_btn = st.form_submit_button("Create Account",
                                                     use_container_width=True)

            if register_btn:
                error = _validate_registration(new_username, new_password, confirm_pwd)
                if error:
                    st.error(error)
                else:
                    ok, msg = create_user(new_username, new_password)
                    if ok:
                        st.success("Account created! Go to Sign In to continue.")
                    else:
                        st.error(msg)

    return False


def _validate_registration(username: str, password: str, confirm: str) -> str | None:
    if not username or len(username.strip()) < 3:
        return "Username must be at least 3 characters."
    if not password or len(password) < 6:
        return "Password must be at least 6 characters."
    if password != confirm:
        return "Passwords do not match."
    return None


def _set_session(user: dict) -> None:
    st.session_state["authenticated"]  = True
    st.session_state["current_user"]   = {
        "id":       user["id"],
        "username": user["username"],
        "role":     user["role"],
    }
    st.session_state["_sessions_loaded"] = False


def logout() -> None:
    """Clear auth session state and rerun."""
    for key in ("authenticated", "current_user", "messages",
                "sessions", "_sessions_loaded", "current_session_id",
                "_running", "_current_question", "_stop_event",
                "_result_queue", "_progress", "_idx_status"):
        st.session_state.pop(key, None)
    st.rerun()
