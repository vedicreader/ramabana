# Claude instructions

Before you write code, check kosha. Invoke the `kosha` skill, and `litesearch` for semantic index queries, before Grep or Read. The answer is usually already in this repo or an installed package. For Python that needs state across calls, use `clikernel`, not repeated `uv run python`. kosha and clikernel live outside the venv.

Coding practices live in the code. Read the `coding_patterns` skill (`nbs/09_coding_patterns.ipynb`) before writing, reviewing, or refactoring.

The notebooks in `nbs/` are the source. Every file in `ramabana/` is generated and says so; so are `README.md`, `ramabana/__init__.py`, `ramabana/_modidx.py`, and `nbs/llms.txt`. Edit the notebook, then `nbdev-export`. Never hand-edit a generated file, and never parse an `.ipynb` as JSON: use `NotebookEdit` or `fastcore.nbio`.
