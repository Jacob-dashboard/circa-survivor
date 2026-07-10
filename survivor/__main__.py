"""Entry point that works BOTH ways:

  * `python -m survivor [subcommand]` — normal CLI (package context exists).
  * Run as a bare script — e.g. Streamlit Cloud configured with
    "survivor/__main__.py" as the main file path.

In the Streamlit case the UI script must be RE-EXECUTED on every rerun.
A plain `import survivor.ui` renders only the first run (Python caches
imports) and every rerun after that draws a blank page. runpy executes
the file fresh each run, matching `streamlit run survivor/ui.py`.
"""
if __package__:
    from .cli import main

    if __name__ == "__main__":
        main()
else:
    import os
    import runpy

    _UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.py")
    runpy.run_path(_UI, run_name="__main__")
