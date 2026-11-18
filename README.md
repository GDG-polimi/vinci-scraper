# vinci-scraper

Crawler that collects public Politecnico di Milano information for students (fees and DSU,
scholarships, calls and deadlines, student services, opportunities, regulations) and keeps it
versioned over time. Its output feeds the retrieval index of the **VINCI** assistant.

> Status: early development. See the [issues](https://github.com/GDG-polimi/vinci-scraper/issues)
> and milestones for what is planned and what is in progress.

## How it works

```
sitemap.xml + listing pages ──► fetch (polite, per-host limits) ──► extract main text + attachments
                                                                            │
          SQLite (documents, versions, attachments, fetch_log) ◄── hash & compare
                                                                            │
                                   raw HTML/PDF snapshots ──► published dataset ──► RAG index
```

1. **Discover.** Seed URLs from each host's sitemap, filtered by the allowed path prefixes. Items
   missing from the sitemap (news, calls, notices) are found by crawling listing pages.
2. **Fetch.** Async HTTP with an identifiable User-Agent. Respects `robots.txt` and stays within
   per-host rate limits. Uses Playwright only for hosts that need JavaScript.
3. **Extract.** Main content (via `trafilatura`, with a per-host CSS selector as fallback), plus
   text from linked PDFs and Office files.
4. **Version.** The normalized text is hashed. Unchanged pages only update `last_seen`. Changed
   pages get a new version. Vanished pages are archived, never deleted, so past calls stay
   searchable.

### Scope

| Tier | What | When |
| --- | --- | --- |
| 1 | DSU, fees, scholarships · calls, notices, deadlines · student services · opportunities · documents and regulations | now |
| 2 | school and department sites, academic calendar, FAQs, office contacts, alumni, admissions | later |
| 3 | research, staff, PhD, corporate, press, anything behind login, personal profiles | skipped |

Allowed hosts and path prefixes live in the host config, not in code.

## Getting started

Requirements: [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs the
right Python for you) and git.

```bash
git clone https://github.com/GDG-polimi/vinci-scraper.git
cd vinci-scraper
uv sync                 # creates .venv and installs all dependencies
uv run vinci --help     # the CLI
uv run pytest           # run the tests
```

Lint and format before you push:

```bash
uv run ruff check .
uv run ruff format .
```

## Project layout

```
src/vinci_scraper/   the package; `vinci` CLI entry point in cli.py
tests/               pytest tests (no network access)
.github/workflows/   CI (lint + tests on every PR) and project-board automation
```

## Workflow: issues, branches, pull requests

We work with **one issue → one branch → one pull request**. Nobody pushes to `main` directly.

In short: **assign yourself → branch → commit → PR with `Closes #N` → review → merge.**

### 1. Pick an issue

1. Open the project board and pick a card in **Todo**. Work milestone by milestone
   (`S0 Setup` → `S1 Fetch` → `S2 Discovery` → ...). Issues labelled `facoltativo` are optional
   and can wait.
2. **Assign the issue to yourself before you start working on it**, before you even create the
   branch. This is a rule, not a suggestion: it's how the team knows who is doing what and avoids
   two people working on the same issue. Don't pick up an issue someone else is assigned to; ask
   them in a comment first. Assigning moves the card to **In Progress** automatically (the
   `Project status` workflow). It only moves forward, so adding a second assignee later never
   pushes the card back.
3. If the issue is unclear or too large, ask in a comment on the issue *before* writing code.
   If you find new work along the way, open a new issue instead of growing your PR.

### 2. Create a branch

Always branch from an up-to-date `main`:

```bash
git switch main
git pull
git switch -c feat/scr-05-async-fetcher
```

Branch names: `<type>/<issue-key>-<short-description>`, lowercase, words joined with `-`.

| Type | Use for | Example |
| --- | --- | --- |
| `feat/` | new functionality | `feat/scr-09-sitemap-seed` |
| `fix/` | bug fixes | `fix/scr-11-chash-not-stripped` |
| `docs/` | documentation only | `docs/readme-setup` |
| `chore/` | tooling, CI, dependencies | `chore/bump-httpx` |
| `test/` | tests or fixtures only | `test/scr-19-golden-set` |

The issue key (`scr-05`) is the `SCR-xx` code in the issue title, not the GitHub `#number`.

### 3. Commit

- Small, focused commits. Imperative subject line, ideally under 72 characters:
  `Add per-host rate limiter`, not `added stuff`.
- Put the issue key at the start when it helps: `SCR-05: retry on 429 using Retry-After`.
- Before you push, run the same checks CI runs:
  `uv run ruff check . && uv run ruff format . && uv run pytest`.

### 4. Open a pull request

```bash
git push -u origin feat/scr-05-async-fetcher
gh pr create --fill   # or open it from the GitHub UI
```

- Target `main`, unless your work depends on another open PR (see *Stacked PRs* below).
- Write **`Closes #<number>`** in the description, using the GitHub issue number (for example
  `Closes #5` for SCR-05). When the PR is merged, GitHub closes the issue and the card moves to
  **Done**.
- Fill in the template: what changed and how a reviewer can test it.
- Open a **draft PR** early if you want feedback before the work is finished.

### 5. Review and merge

- At least **one approval** from another team member is needed before merging.
- CI (lint, format check, tests) must be green.
- Address review comments with new commits; don't force-push over a review in progress.
- Whoever opened the PR merges it after approval, then deletes the branch.

### Stacked PRs

When issue B needs code from issue A, and A's PR isn't merged yet:

1. Branch B from A's branch instead of `main`.
2. Open B's PR with A's branch as the **base**, and write "Depends on #<A's PR>" in the description.
3. Merge A first. GitHub retargets B to `main` when A's branch is deleted. If it shows conflicts,
   rebase B onto `main` (`git rebase --onto main <A's branch>`) and force-push B.

### Code conventions

- Python 3.12+, managed with uv. Add dependencies with `uv add <pkg>` (or `uv add --dev <pkg>`),
  and commit the updated `uv.lock`.
- Code, comments, commits and docs are in English.
- Every new module comes with tests in `tests/`. Tests must not hit the network: use fixtures.
- Never commit crawl output (`data/`, `*.sqlite`), credentials or `.env` files.

## Crawling etiquette

The crawler identifies itself and limits its own speed so it never burdens Polimi's servers.
Keep it that way: don't raise the rate limits, don't remove the User-Agent contact, and don't
crawl hosts marked as pending permission.

## License

[Apache 2.0](LICENSE)
