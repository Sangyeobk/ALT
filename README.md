# ALT — Agentic Literature Tracker

A literature-survey plugin for Claude Code and Codex (one repository, installs in both). Give it a **topic, an approach and a period**; it searches the scholarly databases, scores and selects papers, and writes:

| File | What it is |
|---|---|
| `00_summary.md` | Summary of the survey |
| `01_background.pptx` | Background slides on the topic |
| `02_literature_map.png` | Literature map (candidates by axis, selected papers highlighted) |
| `03_report.docx` | Survey report (Word) |
| `04_presentation.pptx` | Survey presentation |
| `05_references.xlsx` | Scored reference list (all candidates, with reasons) |
| `06_context.md` | Condensed context for coding / follow-up work |
| `figures/` | Literature map, selection flow, technology tree, paper-count charts |

Output text is Korean. Other output languages are not supported yet: the fixed text the code adds (section titles, table headers, method notes, Excel column names, figure labels) is Korean only. Code comments and the AI instructions (`SKILL.md`, guides) are in Korean.

## How it works
1. **Define the topic** — The executing AI proposes a precise scope (included/excluded, research question, map axis) and asks you to confirm.
2. **Search** — OpenAlex, plus citation tracking from seed papers. Crossref and DOAJ are used for bibliographic, retraction and venue checks.
3. **Score** — relevance is judged from title/abstract by the executing AI or its role agents; citations and venue are combined with fixed weights (`alt/config.yaml`). New surveys use another AI for independent cross-checks under the shared procedure.
4. **Select** — core papers, review papers, classic papers that many candidates cite, institution/class-society documents, notable adjacent papers.
5. **Read** — open-access PDFs are downloaded where allowed; within the approved scope, full texts are summarised page by page so the report can cite numbers and figures.
6. **Write** — summary, report, slides, reference list; every citation is checked against the reference list (`check_citations.py`), and only papers confirmed by the APIs are cited.

Large AI steps (scoring, full-text reading, writing) show an estimate first. Existing approval carries across stages and tools; only work outside that scope needs a new decision. An explicitly skipped verification remains skipped for that run, with no automatic retry or claim that it passed. New surveys retain the default independent verification procedure.

Switching between Claude Code and Codex resumes the same survey folder and reuses
its confirmed inputs and results. It does not automatically repeat the search or
scoring. A separately requested end-to-end test is kept apart from the confirmed survey.

The policy source for both tools is [`alt/agent_guide.md`](alt/agent_guide.md).
[`AGENTS.md`](AGENTS.md) and the optional private `CLAUDE.md` point to it;
[`skills/run/SKILL.md`](skills/run/SKILL.md) defines the shared steps.
Private project logs are preserved separately and are not required in a public installation.

## Install

You need **Windows** and **[Python 3.12](https://www.python.org/downloads/windows/)** (tick *Add python.exe to PATH* when installing — if Python is missing, ALT shows this link and can install it for you).

| | Claude (desktop app) | Codex |
|---|---|---|
| Install | Settings → **Plugins** → **+ Add** → **Add from repository** → `Sangyeobk/ALT` → install **alt** | In a terminal:<br>`codex plugin marketplace add Sangyeobk/ALT`<br>`codex plugin add alt@alt-marketplace` |
| Start | Open a session in the folder where results should go, type `/alt:run` | Open Codex in that folder, type `$alt:run` |

That's all — ALT sets up its own Python packages on the first run and asks for anything else it needs.

<details>
<summary>Other ways to install, and manual setup</summary>

- **Claude Code from a terminal** (needs [Git](https://git-scm.com/download/win)): `claude plugin marketplace add Sangyeobk/ALT` then `claude plugin install alt@alt-marketplace`. The terminal and the desktop app share settings, so it also appears in the desktop app. Inside a terminal `claude` session the same works as `/plugin marketplace add …` / `/plugin install …` (in the desktop app `/plugin` only opens the Plugins settings).
- **Development checkout**: `claude --plugin-dir .` from this folder.
- **Python packages by hand** (normally automatic, `alt/setup_env.py`), in PowerShell from the plugin folder — keep the environment outside synced folders such as OneDrive:
  ```powershell
  python -m venv "$env:USERPROFILE/.venvs/alt"
  & "$env:USERPROFILE/.venvs/alt/Scripts/python.exe" -m pip install -r requirements.txt
  ```
- Network access to api.openalex.org, api.crossref.org and api.unpaywall.org is required. Independent verification uses the *other* AI (Codex checks Claude's results and vice versa) if it is installed and logged in; otherwise ALT records that verification was skipped.
- Results go into `outputs/` of the folder you opened; the plugin's own files stay in its installation.
- Personal settings (your e-mail for Crossref/Unpaywall, an optional free [OpenAlex key](https://openalex.org/settings/api)) are kept in `~/.alt/settings.yaml`, never in this repository. ALT asks for the e-mail on first run and for the key only if the shared search limit is hit.

</details>

## Use
**Open the session in the folder where results should be saved** (results go to `outputs/` there). If the session was opened in your home folder, a drive root, or a folder never used for ALT, `/alt:run` stops first and asks whether to use the current folder (`run_status.py --init-workspace`) or reopen in another one. Type:
```
/alt:run
```
The executing AI asks for the topic, approach and period — no manual needed. After that it runs to the end and stops only three times: to confirm the topic wording and search queries, to approve the estimated usage once, and to check the interim selection (step ⑥). PDFs to download by hand and sub-survey suggestions come in the final report. You can also give them on one line:
```
/alt:run Wave loads on offshore structures, data-driven, 2025-2027
```

With Codex, install the plugin as above and type `$alt:run` (or, without installing, open a checkout, read `AGENTS.md` and request the survey in conversation). The role agents `alt:alt-*` are Claude Code registrations; Codex runs the same role guides directly. Follow the shared adapter instructions for script paths, role guides, verifier selection and usage reporting. Use the same survey folder and file contracts.

There are three functions, chosen in conversation:

| Function | What it does |
|---|---|
| 1. New project | New topic → search → scoring and selection → outputs |
| 2. Project update | Searches the same topic again, adds papers published since, re-selects. Newly selected papers are marked NEW, dropped ones "excluded (previously selected)"; the previous results are kept in `run_YYYYMMDD/` |
| 3. Feedback on outputs | No new search — revises direction or quality of the outputs, or makes a new kind of output from the papers already found (including PDFs you add) |

Each survey lives in its own folder under `outputs/`. An unfinished survey resumes where it stopped.

### Presentation template (optional)
Without a template file, slides use a plain 16:9 layout — nothing to set up. To use your own template, put the `.pptx` in your working folder's `templates/`, then in `alt/config.yaml` **copy an existing entry under `output.pptx_templates`** (e.g. `"01"`; every key — `colors`, `content_box`, `slides` … — is required) under a new `<id>`, change `file` (path) and `slides` (which slides are cover / closing / section / body), and set `output.pptx_template` to that `<id>`. Delete the copied `catalog` line unless you also write a slide-type list for your template (a missing list is skipped); with a list, the talk and background decks are rewritten to fit the template's slide types. Template files are not distributed (licence) and are not tracked by git.

## Utilities

Preview result counts without collecting candidates:

```text
python alt/search_papers.py --count-only --years 2025-2027 --query "wave loads offshore structures machine learning" --out outputs/query_counts.json
```

Replace a library PDF edition while preserving the old PDF and notes:

```text
python alt/library.py --replace-pdf publisher.pdf --run outputs/your_survey --key Author2026
```

Existing survey copies stay unchanged. Notes for the new edition need to be prepared again.

Build a local plugin archive from the explicit public file list:

```text
python alt/package_plugin.py --out outputs/alt-plugin.zip
```

## Tests

```powershell
& "$env:USERPROFILE/.venvs/alt/Scripts/python.exe" -m pytest -q tests
```

Run from the plugin folder. Tests that need a presentation template are skipped when `templates/` has none.

## Layout
| Path | Contents |
|---|---|
| `alt/agent_guide.md` | Shared development and execution policy, including tool adapters |
| `skills/run/SKILL.md` | The procedure followed by all executing AIs |
| `agents/` | Shared scoring, reading and writing roles with Claude plugin registration headers |
| `alt/` | Python scripts, `config.yaml` (weights, thresholds, field names), guides and rubrics |
| `tests/` | pytest tests |

## Licence
- This project: MIT License, see `LICENSE`.
