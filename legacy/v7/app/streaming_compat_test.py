"""Minimal streaming + st.expander() compatibility test.

Run: streamlit run app/streaming_compat_test.py

PURPOSE
-------
Verify that st.write_stream() can be called inside or outside st.expander()
without rendering conflicts (known Streamlit issue with tabs/expanders).

RESULTS
-------
Result A (stream inside expander): some Streamlit versions raise
  StreamlitAPIException or render a blank container. If this happens, use Result B.
Result B (stream outside expander): baseline — always works.

Once you observe the behavior, update TODOS.md and proceed with either:
  - Plan A: stream_narrative_insight goes inside the expander (if A works)
  - Plan B: stream_narrative_insight rendered outside/above any expander (safe path)
"""

import time

import streamlit as st

st.title("Streaming + expander() compat test")
st.caption("Tests whether st.write_stream() works inside st.expander().")


def _fake_stream(text: str, delay: float = 0.04):
    """Yield words one by one to simulate LLM streaming."""
    for word in text.split():
        yield word + " "
        time.sleep(delay)


SAMPLE = (
    "This novel traces the quiet fracturing of trust between two sisters "
    "over one long summer. The prose is spare, the pacing deliberate, and "
    "the emotional weight arrives sideways — in what characters don't say."
)

st.divider()
st.subheader("Test A — stream INSIDE st.expander()")
st.caption("If this renders correctly, the plan's stream-in-expander approach is safe.")

with st.expander("🧬 BOOK DNA (inside expander)", expanded=True):
    try:
        st.write_stream(_fake_stream(SAMPLE))
        st.success("✅ Test A passed — write_stream works inside expander")
    except Exception as e:
        st.error(f"❌ Test A FAILED: {type(e).__name__}: {e}")
        st.warning("Use Plan B: render streaming card OUTSIDE expander.")

st.divider()
st.subheader("Test B — stream OUTSIDE st.expander() (baseline)")
st.caption("This should always work regardless of Streamlit version.")

st.write_stream(_fake_stream(SAMPLE, delay=0.03))
st.success("✅ Test B passed (baseline)")

st.divider()
st.subheader("Test C — stream inside st.tabs()")
st.caption("Quick Insight uses tabs — verify streaming works in that context too.")

tabs = st.tabs(["Quick Insight", "Detail"])
with tabs[0]:
    try:
        st.write_stream(_fake_stream(SAMPLE, delay=0.02))
        st.success("✅ Test C passed — write_stream works inside st.tabs()")
    except Exception as e:
        st.error(f"❌ Test C FAILED: {type(e).__name__}: {e}")

st.divider()
st.caption(
    "After observing results, update TODOS.md item #2 and remove this file "
    "from the project (it is in .gitignore)."
)
