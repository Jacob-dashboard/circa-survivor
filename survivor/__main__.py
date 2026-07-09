"""Entry point that works BOTH ways:

  * `python -m survivor [subcommand]` — normal CLI (package context exists).
  * Run as a bare script — e.g. Streamlit Cloud configured with
    "survivor/__main__.py" as the main file path. Relative imports are
    impossible in that mode, so instead of crashing we bootstrap the project
    root onto sys.path and boot the Streamlit UI.
"""
if __package__:
    from .cli import main

    if __name__ == "__main__":
        main()
else:
    import os
    import sys

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    import survivor.ui  # noqa: F401  (import side effect runs the Streamlit app)
