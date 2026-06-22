"""Input, SQL, and output guardrails for the SQL Q&A agent.

Three layers:
  guard_input  — blocks prompt injection and SQL injection in the question text
  guard_sql    — hard safety check on generated SQL before it touches the DB
  guard_output — blocks system-prompt leakage and empty/useless responses
"""
import re
from agent.state import SQLAgentState


# ---------------------------------------------------------------------------
# Input guard — prompt injection and SQL injection in the question
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[str] = [
    r"ignore\s+(all\s+)?(previous|prior|above|system|the)\s+instructions?",
    r"forget\s+(what|everything|all|your|the)\s+",
    r"you\s+are\s+now\s+",
    r"pretend\s+(you\s+are|to\s+be)",
    r"act\s+as\s+(?:a\s+)?(?:different|new|unrestricted|evil|unfiltered)",
    r"override\s+(your|the|all)\s+",
    r"disregard\s+(your|the|all|previous)\s+",
    r"new\s+(system\s+)?instructions?\s*:",
    r"\bDAN\b",
    r"\bjailbreak\b",
    r"do\s+anything\s+now",
    r"from\s+now\s+on\s+(you\s+)?(are|ignore|forget|will\s+)",
    r"your\s+true\s+(self|purpose|instructions?)",
    r"(reveal|show|print|display|repeat)\s+(your\s+)?(system\s+)?prompt",
    r"what\s+(are|were)\s+your\s+(original\s+)?instructions",
    r"speak\s+freely\s+without\s+",
    r"bypass\s+(your\s+)?(safety|filter|restriction|guardrail)",
    r"roleplay\s+as\s+",
]

# SQL modification keywords embedded in a plain-English question
_SQL_INJECT_PATTERNS: list[str] = [
    r"\b(?:DROP|DELETE|TRUNCATE|INSERT|UPDATE|ALTER|CREATE)\b.{0,40}\b(?:TABLE|DATABASE|FROM|INTO|INDEX|VIEW)\b",
    r"\bEXEC(?:UTE)?\b.{0,20}\b(?:sp_|xp_)",
    r"xp_cmdshell",
    r";.{0,15}\b(?:DROP|DELETE|INSERT|UPDATE|EXEC(?:UTE)?)\b",
    r"\bUNION\b.{0,15}\bSELECT\b",
    r"(?:--|\#)\s*$",   # trailing SQL comment suggesting injection attempt
]

# Inappropriate / out-of-scope content
_INAPPROPRIATE_PATTERNS: list[str] = [
    r"\b(?:hack|crack|exploit)\s+(?:the|this|your|a)\s+(?:system|database|server|app)",
    r"(?:steal|exfiltrate|leak)\s+(?:data|records|information|credentials)",
    r"\b(?:ransomware|malware|virus|trojan|keylogger)\b",
    r"(?:dump|export)\s+(?:all|entire|full)\s+(?:database|tables|records|users)",
]


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return pat
    return None


def guard_input(state: SQLAgentState) -> dict:
    """Block prompt injection, SQL injection, and harmful requests.

    Returns early with blocked=True and a safe decline message if anything
    matches. Returns blocked=False (no other changes) if the input is clean.
    """
    question = (state.get("user_question") or "").strip()

    if _first_match(question, _INJECTION_PATTERNS):
        return {
            "blocked":      True,
            "block_reason": "prompt_injection",
            "response":     "I can only answer questions about your business data. Please ask a plain data question.",
        }

    if _first_match(question, _SQL_INJECT_PATTERNS):
        return {
            "blocked":      True,
            "block_reason": "sql_injection_in_question",
            "response":     "Your question contains patterns I can't process. Please rephrase it as a plain-English data question.",
        }

    if _first_match(question, _INAPPROPRIATE_PATTERNS):
        return {
            "blocked":      True,
            "block_reason": "inappropriate_content",
            "response":     "That request is outside what I can help with. I answer data questions about this platform.",
        }

    return {"blocked": False, "block_reason": None}


# ---------------------------------------------------------------------------
# SQL guard — hard safety check before the query hits the live database
# ---------------------------------------------------------------------------

# First keyword in the SQL must be SELECT or WITH (CTEs)
_FIRST_KW = re.compile(r"^\s*(?:--[^\n]*)?\s*(\w+)", re.IGNORECASE)

# Modification verbs anywhere in the query
_MODIFICATION_VERBS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|MERGE)\b",
    re.IGNORECASE,
)

# Stacked statement: semicolon followed by a modification verb
_STACKED = re.compile(
    r";\s*(?:INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|EXEC(?:UTE)?|GRANT|REVOKE)",
    re.IGNORECASE,
)

# Dangerous stored procedures / shell access
_DANGEROUS_PROCS = re.compile(
    r"\b(xp_cmdshell|sp_executesql|sp_oacreate|openrowset|opendatasource)\b",
    re.IGNORECASE,
)


def guard_sql(sql: str) -> tuple[bool, str]:
    """Return (is_safe, reason). Called inside execute_sql before running the query.

    A False result causes the query to fail with a clear error message that
    the retry loop can log but will not attempt to "repair" into a working
    modification query.
    """
    sql = sql.strip()
    if not sql:
        return False, "Empty SQL query"

    # Must start with SELECT or WITH
    m = _FIRST_KW.match(sql)
    first_kw = m.group(1).upper() if m else ""
    if first_kw not in ("SELECT", "WITH"):
        return False, f"Only SELECT queries are permitted — received '{first_kw}'"

    # Modification verb anywhere in the query (catches subquery tricks)
    mv = _MODIFICATION_VERBS.search(sql)
    if mv:
        return False, f"Query contains a modification verb: {mv.group(1)}"

    # Stacked statements
    if _STACKED.search(sql):
        return False, "Query contains stacked modification statements"

    # Dangerous stored procedures
    dp = _DANGEROUS_PROCS.search(sql)
    if dp:
        return False, f"Query references a blocked procedure: {dp.group(1)}"

    return True, ""


# ---------------------------------------------------------------------------
# Output guard — block prompt leakage and empty responses
# ---------------------------------------------------------------------------

# Fragments that appear in system prompts but must never reach the user
_LEAKAGE_PATTERNS: list[str] = [
    r"PLATFORM CONTEXT:",
    r"ROUTING \(needs_db\)",
    r"CODING RULES:",
    r"ENUM VALUES\s+—",
    r"Return ONLY valid JSON",
    r"DATE RANGE AWARENESS:",
    r"TABLE ROUTING\s+—",
]

# Crude check for accidentally exposed secrets
_SECRET_PATTERNS: list[str] = [
    r"sk-[A-Za-z0-9]{20,}",          # OpenAI key
    r"sk-ant-[A-Za-z0-9\-]{20,}",    # Anthropic key
    r"password\s*[:=]\s*\S{6,}",
]


def guard_output(state: SQLAgentState) -> dict:
    """Sanitise the agent response before it reaches the user.

    Returns an empty dict (no change) when the response is clean.
    Returns a replacement response when a problem is detected.
    """
    response = (state.get("response") or "").strip()

    if not response:
        return {
            "response": "I wasn't able to generate a response for that. Please try rephrasing your question."
        }

    for pat in _LEAKAGE_PATTERNS:
        if re.search(pat, response, re.IGNORECASE):
            return {
                "response": "Something went wrong while generating the response. Please try again."
            }

    for pat in _SECRET_PATTERNS:
        if re.search(pat, response, re.IGNORECASE):
            return {
                "response": "Something went wrong while generating the response. Please try again."
            }

    return {}
