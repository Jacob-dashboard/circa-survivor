"""
Streamlit Community Cloud entry point.

IMPORTANT: this must RE-EXECUTE the UI script on every Streamlit rerun.
A plain `import survivor.ui` only runs the module once (Python caches
imports), so the first page load rendered and every rerun after that —
any click, any new session — drew a blank page. runpy executes the file
fresh each run, exactly like `streamlit run survivor/ui.py` does.
"""
import os
import runpy

_UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "survivor", "ui.py")
runpy.run_path(_UI, run_name="__main__")
