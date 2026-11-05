"""Streamlit UI for AgentOps Platform: triage, approvals, copilot (streamed), audit.

Run:  uv run streamlit run ui/app.py      (API on http://localhost:8000)

LEARNING NOTES
- The UI is a thin client: it holds a token and calls the API. Every permission check happens
  server-side, so the UI hiding a button is convenience, never security. Try calling /audit as an
  officer with curl: still 403.
- "Sign in" uses dev tokens (pick a fictional user) or Keycloak's password grant when
  KEYCLOAK_URL is set. Password grant is fine for a local demo and wrong for production
  (use the authorization-code flow with PKCE).
- The copilot tab reads the Server-Sent Events stream and renders deltas as they arrive, so you can
  *see* time-to-first-token.
"""

from __future__ import annotations

import json
import os

import httpx
import streamlit as st

API = os.getenv("AGENTOPS_API", "http://localhost:8000")
KEYCLOAK = os.getenv("KEYCLOAK_URL")  # e.g. http://localhost:8080/realms/wattle
USERS = {
    "officer-1": ["officer"],
    "fraud-1": ["officer", "fraud_specialist"],
    "hardship-1": ["officer", "hardship_specialist"],
    "manager-1": ["manager"],
    "compliance-1": ["viewer", "compliance"],
}

st.set_page_config(page_title="AgentOps · Wattle Bank (fictional)", layout="wide")
st.sidebar.title("Wattle Bank (fictional)")
user = st.sidebar.selectbox("Sign in as", list(USERS))


@st.cache_data(ttl=600)
def token_for(u: str) -> str:
    if KEYCLOAK:
        r = httpx.post(f"{KEYCLOAK}/protocol/openid-connect/token",
                       data={"grant_type": "password", "client_id": "agentops-api", "username": u, "password": "password"})  # fmt: skip
        r.raise_for_status()
        return str(r.json()["access_token"])
    from agentops.auth import dev_token

    return dev_token(u, USERS[u])


H = {"Authorization": f"Bearer {token_for(user)}"}
st.sidebar.caption(f"roles: {', '.join(USERS[user])}")
tab_triage, tab_approvals, tab_copilot, tab_audit = st.tabs(["Triage", "My approvals", "Copilot", "Audit"])

with tab_triage:
    msg = st.text_area("Customer message", "My card was stolen at the airport, call me on 0411 821 692")
    cust = st.text_input("Customer id (optional)", "")
    if st.button("Triage"):
        r = httpx.post(f"{API}/triage", json={"message": msg, "customer_id": cust or None}, headers=H, timeout=60)
        st.write(f"HTTP {r.status_code}")
        st.json(r.json())

with tab_approvals:
    r = httpx.get(f"{API}/approvals/mine", headers=H)
    items = r.json() if r.status_code == 200 else []
    if not items:
        st.info("Nothing waiting for you.")
    for a in items:
        with st.expander(f"#{a['id']} {a['action']} ({a['domain']}) due {a['sla_due']}"):
            case = httpx.get(f"{API}/cases/{a['case_id']}", headers=H).json()
            st.write(case.get("summary"))
            reason = st.text_input("Reason", key=f"reason-{a['id']}")
            c1, c2 = st.columns(2)
            for col, approve, label in ((c1, True, "Approve"), (c2, False, "Reject")):
                if col.button(label, key=f"{label}-{a['id']}"):
                    d = httpx.post(
                        f"{API}/approvals/{a['id']}/decision", json={"approve": approve, "reason": reason}, headers=H
                    )
                    st.write(f"HTTP {d.status_code}", d.json())

with tab_copilot:
    q = st.text_input("Ask about policy", "What hardship arrangement options can we offer?")
    if st.button("Ask"):
        out, box = "", st.empty()
        with httpx.stream("POST", f"{API}/copilot/stream", json={"question": q, "session_id": f"ui-{user}"},
                          headers=H, timeout=60) as r:  # fmt: skip
            event = None
            for line in r.iter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: ") and event == "delta":
                    out += line[6:]
                    box.markdown(out)
                elif line.startswith("data: ") and event == "done":
                    done = json.loads(line[6:])
                    st.caption(
                        f"sources: {done['sources']} · referred to: {done['referred_to']} · ttft {done['ttft_ms']} ms"
                    )

with tab_audit:
    r = httpx.get(f"{API}/audit", headers=H)
    if r.status_code == 403:
        st.warning("Audit is for managers and compliance (server returned 403).")
    else:
        st.dataframe(r.json(), use_container_width=True)
