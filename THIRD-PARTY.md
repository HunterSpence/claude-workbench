# Third-party software

This kit ships only its own code, plus one skill adapted from an MIT project
(`skills/ponytail`, notice in its `LICENSE.txt`) and one adapted from an Apache-2.0 project
(`skills/ctx-agent-history-search`, licence and change notice in its `LICENSE.txt`). Everything
below is **referenced, not included**: install it from its source, at a version you choose, after
your organisation's approval. Licences were checked when this release was built, with
`gh api repos/<owner>/<repo> --jq .license.spdx_id` or the package metadata; re-check before you
install, because licences and owners change. Scan any third-party skill with the `skill-scan` skill
before first use.

## Claude Code plugins and skills
| What | Source | Licence | Install |
|---|---|---|---|
| security-guidance, hookify, frontend-design, claude-code-setup | `anthropics/claude-plugins-official` (one folder per plugin) | Apache-2.0 (each plugin's LICENSE) | `/plugin marketplace add anthropics/claude-plugins-official` then `/plugin install <name>@claude-plugins-official`. `--upstream-plugins` enables security-guidance and frontend-design (and adamsreview below); the others are registered but off |
| superpowers | `obra/superpowers` (also listed in the official marketplace) | MIT | `/plugin install superpowers@claude-plugins-official` |
| adamsreview (multi-agent PR review) | `adamjgmiller/adamsreview` | MIT | `/plugin marketplace add adamjgmiller/adamsreview` then `/plugin install adamsreview@adamsreview` |
| ponytail (upstream plugin; this kit carries an adapted skill) | `DietrichGebert/ponytail` | MIT | `/plugin marketplace add DietrichGebert/ponytail` then `/plugin install ponytail@ponytail` |
| humanizer (de-AI prose rewriting) | `blader/humanizer` | MIT | `tools/fetch-upstream` (pinned v3.1.0), or `/plugin marketplace add blader/humanizer` then `/plugin install humanizer@humanizer` |
| Playwright CLI and its skill | npm `@playwright/cli` (`microsoft/playwright-cli`) | Apache-2.0 | setup installs pin 0.1.22 with `npm install -g --ignore-scripts` into a user-writable prefix, sets Edge headless as the default, then runs `playwright-cli install --skills` from that pinned version; `--with update-latest` moves it to the newest. Fallback when npm is blocked: the pinned skill in `tools/fetch-upstream/upstream.optional.lock.json` |
| web-interface-guidelines (UI review rules read from disk by `ui-build`) | `vercel-labs/web-interface-guidelines` | MIT | `tools/fetch-upstream` default set, one pinned commit |
| diagram-render (offline renderer behind the `diagram` skill) | `garrytan/gstack`, `lib/diagram-render` only | MIT; its embedded fonts are SIL OFL 1.1 | `tools/fetch-upstream` default set, one pinned commit; the rest of gstack is not fetched |
| grilling (stress-test a plan in rounds of questions) | `mattpocock/skills` (`skills/productivity/grilling`) | MIT | `/plugin marketplace add mattpocock/skills` then `/plugin install mattpocock-skills@mattpocock` |
| evals skills (build product-specific AI evals) | `ai-evals-course/evals-skills` | Apache-2.0 | registered, off, by `--upstream-plugins-optional`; enable with `/plugin` |
| Trail of Bits security skills | `trailofbits/skills` | **CC-BY-SA-4.0 (share-alike)** | `/plugin marketplace add trailofbits/skills` then `/plugin install <skill>@trailofbits`. Share-alike: anything you derive from these skills and distribute must carry the same licence and attribution. Use them as installed; do not copy their text into your own skills or repositories |
| **document-skills** (docx, pptx, xlsx, pdf) | `anthropics/skills` | **Proprietary, source-available**: their LICENSE.txt forbids copying them outside Anthropic's services, derivative works and redistribution | `/plugin marketplace add anthropics/skills` then `/plugin install document-skills@anthropic-agent-skills`, only after legal or IT has read the licence. Never copy these files into a repository. This kit's office-pptx, office-xlsx and office-render skills are independent and use only the open-source libraries below |

## Not recommended on a managed laptop
These are permissively licensed and popular, but each does something worth knowing before you add it on a managed
laptop. They are kept out of the default
`tools/fetch-upstream` set and listed only in `tools/fetch-upstream/upstream.optional.lock.json`.

| What | Source | Licence | Why not by default |
|---|---|---|---|
| gstack skills (design-review, qa, diagram, investigate, ...) | `garrytan/gstack` | MIT (its NOTICE.md lists Apache-2.0-derived files) | every skill starts with a preamble that runs gstack helper scripts and writes usage logs under `~/.gstack` (remote telemetry is opt-in); the full `./setup` installs Bun, builds binaries and downloads a browser. This kit's `investigate` skill is a separate, original text |
| impeccable (frontend design; critique, polish, layout shortcuts) | `pbakaus/impeccable` | Apache-2.0 | its launcher downloads and caches an engine binary on first run, and its hooks can trigger that download outside model-tool approval |

## Microsoft 365 options (no install from this kit)
The Claude for Excel, PowerPoint and Word add-ins work inside Office if your tenant administrator
deploys or allows them; Microsoft 365 Copilot's agents may also use Anthropic models where your
organisation enabled that. Ask IT; neither needs anything from this repository.

## Tools the skills call (install yourself)
| Tool | Used by | Source | Licence | Install |
|---|---|---|---|---|
| tokensave | MCP code graph | `aovestdipaperino/tokensave` | MIT | pinned release 7.12.1 + `SHA256SUMS`, see `mcp/README.md`. Held there on purpose (2026-10): from 7.13.0 the first launch of a new version silently reinstalls its agent integrations, rewriting rules text and git-hook sections, which this kit has not reviewed against its always-loaded budget and permission rules. `--with update-latest` does not move it (release-asset tools are never upgraded past their pin) |
| ctx | ctx-agent-history-search | `ctxrs/ctx` | Apache-2.0 | with `--with ctx`, setup fetches pinned release 2.2.8 (`ctx-windows-x64.exe`, about 212 MB), checks it against the SHA-256 in `bootstrap/packages.json`, and turns analytics, the daemon and self-upgrade off (see the skill) |
| SkillSpector | skill-scan | `NVIDIA/skillspector` | Apache-2.0 | clone a pinned tag, `uv sync`, set `SKILLSPECTOR_EXE` |
| GitHub CLI | github skill | `cli/cli` | MIT | your organisation's software portal, `winget install GitHub.cli`, or the release page |
| LibreOffice (optional) | office-render, office-xlsx fallback | libreoffice.org | MPL-2.0 | usually needs IT on Windows; real Office via COM is used first |
| Microsoft Edge | pdf-report (HTML to PDF engine) | Microsoft | Microsoft product terms | already on Windows 11; the skill never downloads a browser |
| uv (optional) | the postgres MCP entry (`uvx`) | `astral-sh/uv` | MIT or Apache-2.0 | your software portal, or the release page |

## Node packages (from each skill's `scripts/package.json`; installed with `npm install --ignore-scripts`)
| Package | Used by | Licence | Note |
|---|---|---|---|
| playwright-core 1.62.1 (exact pin) | vdi-drive, ui-build, capture, diagram | Apache-2.0 | no dependencies; drives the installed Edge or Chrome, downloads no browser. Setup installs the capture copy only with `--with capture` |
| axe-core 4.14.0 | ui-build | MPL-2.0 | installed, not shipped. MPL-2.0 is file-level copyleft: using it unmodified is fine; if you change and distribute its files, publish those files' source |

## Packages in the mcp-builder templates (installed only in a server you scaffold)
| Package | Template | Licence |
|---|---|---|
| mcp (Python SDK) 2.3.0 | Python | MIT |
| uvicorn 0.54.0 | Python | BSD-3-Clause |
| PyJWT 2.15.1 | Python | MIT |
| @modelcontextprotocol/server and /client 2.3.1 | TypeScript | **Apache-2.0** (not MIT) |
| @modelcontextprotocol/node 2.1.1 | TypeScript | Apache-2.0 |
| @modelcontextprotocol/inspector 2.10.1 | TypeScript (dev) | Apache-2.0, with older contributions still under MIT (see its LICENSE) |
| zod 4.6.5 | TypeScript | MIT |
| jose 6.2.12 | TypeScript | MIT |
| typescript 7.0.2 | TypeScript (dev) | Apache-2.0 |
Re-check these pins and licences at each release.

## Packages in the app-navigator templates (installed only in an app you copy them into)
| Package | Template | Licence |
|---|---|---|
| anthropic (Python SDK) 1.11.0 | Python | MIT |
| fastapi 0.142.2 | Python | MIT |
| uvicorn 0.54.0 | Python | BSD-3-Clause |
| @anthropic-ai/sdk 0.131.0 | TypeScript | MIT |
| hono 4.13.13 and @hono/node-server 2.1.3 | TypeScript | MIT |
| typescript 7.0.2 and @types/node 24.19.1 | TypeScript (dev) | Apache-2.0 and MIT |
The React widget uses the app's own React (18 or later) and adds no package.

## Skill packs fetched on request
| Pack | Source | Licence | Note |
|---|---|---|---|
| Product-management skills (eight) | `anthropics/knowledge-work-plugins`, pinned commit `ae1513ea94dcb74a7f1505ddcf3b0ec3fab327f1` | Apache-2.0 | `--with pm-pack` or `fetch_upstream.py --pm`; each skill's `SKILL.md` and `LICENSE` only. As shipped they do not upload to Claude on the web |

## Models
| Model | Used by | Source | Licence |
|---|---|---|---|
| bge-small-en-v1.5 (quantised ONNX export) | `find` meaning-based search | BAAI, exported by Qdrant; downloaded once from huggingface.co, or imported from `models/find-embedding-model.zip` (its `NOTICE-MODEL.txt` inside), SHA-256 checked against the pin in `find`'s script | MIT |

## GitHub Actions templates (`templates/github-actions/`, documentation only)
| Action | Licence | Note |
|---|---|---|
| `anthropics/claude-code-action` | MIT | pinned by commit |
| `actions/checkout` | MIT | pinned by commit |

## Optional tools named in skill references (not installed by anything here)
| What | Used by | Source | Licence |
|---|---|---|---|
| RapidOCR (+ onnxruntime) | vdi-drive `references/reading-the-screen.md`, optional OCR read-back | `RapidAI/RapidOCR` | Apache-2.0 (check the model weights you install) |
| `consol/debian-xfce-vnc` container image | vdi-drive `references/test-rig.md`, a disposable test desktop | `ConSol/docker-headless-vnc-container` | Apache-2.0 |

## Python packages (from each skill's `requirements.txt`)
| Package | Used by | Licence |
|---|---|---|
| markitdown `[docx,pptx,xlsx,pdf]` 0.1.8 | find; `[docx]` for office-docx `to-md` | MIT (pulls in magika Apache-2.0, onnxruntime MIT, pdfminer.six MIT, mammoth BSD-2-Clause, pandas BSD-3-Clause, python-pptx, openpyxl) |
| fastembed 0.9.0 | find (meaning-based search) | Apache-2.0 |
| numpy 2.5.3 | find | BSD-3-Clause, with bundled parts under 0BSD, MIT, Zlib and CC0-1.0 |
| truststore 0.10.4 | find (uses the system certificate store behind a TLS-inspecting proxy) | MIT |
| pywin32 312 | ingest (classic Outlook, Windows only; installed by `ingest.py setup`) | PSF |
| lxml (5 or newer) | office-render (`scrub.py`) | BSD-3-Clause |
| python-pptx | office-pptx | MIT |
| openpyxl | office-xlsx | MIT |
| pypdfium2 | office-render; pdf-report (check and PNG steps) | BSD-3-Clause or Apache-2.0 (bundles PDFium, BSD-3-Clause) |
| Pillow | office-render, office-pptx, pdf-report (blank-page check) | MIT-CMU |
| python-docx | office-docx (and find's tests) | MIT |
| pypdf 6.19.0 | pdf-report (merge, split, rotate, metadata, forms, structure checks) | BSD-3-Clause |
| Markdown 3.11 | pdf-report (Markdown to HTML) | BSD-3-Clause |
| olefile | draft-reply, reading Outlook `.msg` files | BSD-2-Clause style (its LICENSE also carries the original PIL notice) |
| anthropic | batch-review | MIT |
| PyMuPDF | **not used** | AGPL-3.0: deliberately avoided |

## MCP servers in `mcp/golden-config.template.json` (every entry is off until you enable it)
| Server | Package or endpoint | Licence | Egress |
|---|---|---|---|
| tokensave | local binary | MIT | none |
| playwright | npm `@playwright/mcp` 0.0.83 (`microsoft/playwright-mcp`) | Apache-2.0 | local browser |
| chrome-devtools | npm `chrome-devtools-mcp` 1.10.1 (`ChromeDevTools/chrome-devtools-mcp`) | Apache-2.0 | local; upstream usage statistics and CrUX trace-URL lookups are on by default and disabled in the template |
| context7 | `https://mcp.context7.com/mcp` (`upstash/context7`) | MIT | hosted |
| github, github-pat, github-ghe | GitHub's hosted MCP endpoint (read-only) | service terms; server code MIT | hosted |
| github-local | `github/github-mcp-server` v2.0.1, downloaded on demand and SHA-256 checked | MIT | local process calling the GitHub API |
| find | the kit's own `find_mcp.py` | MIT (this kit) | none |
| mslearn | Microsoft Learn's hosted MCP endpoint | service terms | hosted, public docs only |
| azure | npm `@azure/mcp` 2.0.5 | MIT | local process calling Azure with your sign-in |
| azure-devops | npm `@azure-devops/mcp` 2.10.0 | MIT | local process calling Azure DevOps with your sign-in |
| atlassian | Atlassian's hosted MCP endpoint | service terms | hosted |
| bigquery, gcloud | Google Cloud's hosted MCP endpoints (gcloud is a preview) | service terms | hosted |
| ms365 | npm `@softeria/ms-365-mcp-server` 0.159.1, not bundled, read-only, your own tenant app | MIT | Microsoft Graph only |
| brave-search | npm `@brave/brave-search-mcp-server` 2.1.4 | MIT | hosted API |
| exa | `https://mcp.exa.ai/mcp` (`exa-labs/exa-mcp-server`) | MIT | hosted |
| tavily | npm `tavily-mcp` 0.2.22 (`tavily-ai/tavily-mcp`) | MIT | hosted API |
| postgres (read-only) | PyPI `postgres-mcp` 0.3.0 (`crystaldba/postgres-mcp`), run with `uvx`, `--access-mode=restricted` | MIT | local; only the database you name |
