"""
Streamlit Community Cloud entry point.

Streamlit Cloud looks for `streamlit_app.py` at the repo root by default.
Importing the UI module executes it (it's a top-level Streamlit script), so
this one line boots the whole app with no relative-import issues.
"""
import survivor.ui  # noqa: F401  (import side effect runs the app)
