# Claude Code Tests

## Python Environment

A dedicated virtual environment is set up at `.venv/` for all data analysis, plotting, and scientific computing tasks. Always use this environment.

**Activate / run scripts:**
```bash
# Run a script
.venv/bin/python3 script.py

# Interactive shell
.venv/bin/ipython

# Jupyter Lab
.venv/bin/jupyter lab
```

### Installed packages

| Package | Version | Purpose |
|---|---|---|
| numpy | 2.0.2 | Arrays, linear algebra, numerical ops |
| pandas | 2.3.3 | DataFrames, tabular data, CSV/Excel I/O |
| matplotlib | 3.9.4 | Static plots and figures |
| seaborn | 0.13.2 | Statistical visualization (built on matplotlib) |
| altair | 6.0.0 | Declarative charts (Vega-Lite backend) |
| plotly | 6.7.0 | Interactive charts |
| scipy | 1.13.1 | Scientific computing, stats, signal processing |
| scikit-learn | 1.6.1 | Machine learning |
| statsmodels | 0.14.6 | Statistical models and tests |
| openpyxl / xlrd | — | Excel file support for pandas |
| vega_datasets | 0.9.0 | Sample datasets for Altair examples |
| jupyter / ipython | — | Interactive notebooks and REPL |

### Guidance for analysis tasks

- **Tabular data / wrangling** → pandas
- **Numerical computation** → numpy / scipy
- **Quick static plots** → matplotlib or seaborn
- **Grammar-of-graphics / Vega charts** → altair
- **Interactive / dashboards** → plotly
- **Statistics / hypothesis tests** → scipy.stats or statsmodels
- **ML pipelines** → scikit-learn

Always import from the venv; do not use the system `/usr/bin/python3`.

## Spatial Biology Tool (Aliquot)

A web tool for adding spatial biology data to Aliquot biospecimen records.

**Run locally:**
```bash
cd "/Users/areeb.mallick/Downloads/Claude Code Tests"
.venv/bin/pip install flask gunicorn -q
.venv/bin/python app.py
# Opens at http://localhost:8080
```

**Open the tool:**
```bash
open http://localhost:8080
```

When the user says anything like "open the spatial biology tool", "launch aliquot tool", or "open the biospecimen editor", run the two commands above (start the server then open the browser).

**What it does:**
- Search biospecimens by name in Aliquot
- Enter `transcripts_per_cell` values (averages multiple inputs automatically)
- Enter `experiment_id` values (stored as a list)
- Saves to `additionalProperties.userNotes` + `description` via PUT
- Records who made the update (decoded from CF_Authorization JWT)

**Deploy to Railway (share with team):**
```bash
cd "/Users/areeb.mallick/Downloads/Claude Code Tests"
git push origin main   # Railway auto-deploys from GitHub
```
Once deployed, the public URL is the shareable link for the team.

**GitHub repo:** https://github.com/am-ai319/Aliquot-Biospecimen-Search

**Auto-sync rule:** After every code change to this tool (app.py, index.html, or any related file), always:
1. Update README.md if the change affects features, APIs, or usage
2. Commit all changed files with a clear message
3. Push to `origin main`

Do this automatically at the end of every session where code was modified — do not wait for the user to ask.
