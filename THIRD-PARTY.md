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
| security-guidance, hookify, frontend-design, claude-code-setup | `anthropics/claude-plugins-official` (`plugins/<name>`) | Apache-2.0 (each plugin's LICENSE) | `/plugin marketplace add anthropics/claude-plugins-official` then `/plugin install <name>@claude-plugins-official`. `--upstream-plugins` enables security-guidance and frontend-design (and adamsreview below); the others are registered but off |
| superpowers | `obra/superpowers` (also listed in the official marketplace) | MIT | `/plugin install superpowers@claude-plugins-official` |
| adamsreview (multi-agent PR review) | `adamjgmiller/adamsreview` | MIT | `/plugin marketplace add adamjgmiller/adamsreview` then `/plugin install adamsreview@adamsreview` |
| ponytail (upstream plugin; this kit carries an adapted skill) | `DietrichGebert/ponytail` | MIT | `/plugin marketplace add DietrichGebert/ponytail` then `/plugin install ponytail@ponytail` |
| humanizer (de-AI prose rewriting) | `blader/humanizer` | MIT | `tools/fetch-upstream` (pinned v3.1.0), or `/plugin marketplace add blader/humanizer` then `/plugin install humanizer@humanizer` |
| playwright-cli skill | npm `@playwright/cli` (`microsoft/playwright-cli`) | Apache-2.0 | `npm install -g @playwright/cli@<version>`; skill via `tools/fetch-upstream` (pinned 0.1.22) |
| grilling (stress-test a plan in rounds of questions) | `mattpocock/skills` (`skills/productivity/grilling`) | MIT | `/plugin marketplace add mattpocock/skills` then `/plugin install mattpocock-skills@mattpocock` |
| evals skills (build product-specific AI evals) | `ai-evals-course/evals-skills` | Apache-2.0 | registered, off, by `--upstream-plugins-optional`; enable with `/plugin` |
| Trail of Bits security skills | `trailofbits/skills` | **CC-BY-SA-4.0 (share-alike)** | `/plugin marketplace add trailofbits/skills` then `/plugin install <skill>@trailofbits`. Share-alike: anything you derive from these skills and distribute must carry the same licence and attribution. Use them as installed; do not copy their text into your own skills or repositories |
| **document-skills** (docx, pptx, xlsx, pdf) | `anthropics/skills` | **Proprietary, source-available**: their LICENSE.txt forbids copying them outside Anthropic's services, derivative works and redistribution | `/plugin marketplace add anthropics/skills` then `/plugin install document-skills@anthropic-agent-skills`, only after legal or IT has read the licence. Never copy these files into a repository. This kit's office-pptx, office-xlsx and office-render skills are independent and use only the open-source libraries below |

## Not recommended on a managed laptop
These are permissively licensed and popular, but each does something a managed corporate laptop
usually should not allow without a security review. They are kept out of the default
`tools/fetch-upstream` set and listed only in `tools/fetch-upstream/upstream.optional.lock.json`.

| What | Source | Licence | Why not by default |
|---|---|---|---|
| gstack skills (design-review, qa, diagram, investigate, ...) | `garrytan/gstack` | MIT (its NOTICE.md lists Apache-2.0-derived files) | every skill starts with a preamble that runs gstack helper scripts and writes usage logs under `~/.gstack` (remote telemetry is opt-in); the full `./setup` installs Bun, builds binaries and downloads a browser. This kit's `investigate` skill is a separate, original text |
| impeccable (frontend design; critique, polish, layout shortcuts) | `pbakaus/impeccable` | Apache-2.0 | its launcher downloads and caches an engine binary on first run, and its hooks can trigger that download outside model-tool approval |
| web-design-guidelines | `vercel-labs/agent-skills` | MIT per the repository README; the skill folder ships no LICENSE file | each run fetches its instructions live from the `main` branch of another repository, so what it tells Claude can change at any time |

## Microsoft 365 options (no install from this kit)
The Claude for Excel, PowerPoint and Word add-ins work inside Office if your tenant administrator
deploys or allows them; Microsoft 365 Copilot's agents may also use Anthropic models where your
organisation enabled that. Ask IT; neither needs anything from this repository.

## Tools the skills call (install yourself)
| Tool | Used by | Source | Licence | Install |
|---|---|---|---|---|
| tokensave | MCP code graph | `aovestdipaperino/tokensave` | MIT | pinned release + `SHA256SUMS`, see `mcp/README.md` |
| ctx | ctx-agent-history-search | `ctxrs/ctx` | Apache-2.0 | pinned release + `SHA256SUMS`; analytics, daemon and auto-upgrade off (see the skill) |
| SkillSpector | skill-scan | `NVIDIA/skillspector` | Apache-2.0 | clone a pinned tag, `uv sync`, set `SKILLSPECTOR_EXE` |
| GitHub CLI | github skill | `cli/cli` | MIT | your organisation's software portal, `winget install GitHub.cli`, or the release page |
| LibreOffice (optional) | office-render, office-xlsx fallback | libreoffice.org | MPL-2.0 | usually needs IT on Windows; real Office via COM is used first |
| uv (optional) | the postgres MCP entry (`uvx`) | `astral-sh/uv` | MIT or Apache-2.0 | your software portal, or the release page |

## Node packages (from each skill's `scripts/package.json`; you run `npm install --ignore-scripts` in a copy)
| Package | Used by | Licence | Note |
|---|---|---|---|
| playwright-core 1.62.1 | vdi-drive, ui-build | Apache-2.0 | no dependencies; drives the installed Edge or Chrome, downloads no browser |
| axe-core 4.14.0 | ui-build | MPL-2.0 | installed, not shipped. MPL-2.0 is file-level copyleft: using it unmodified is fine; if you change and distribute its files, publish those files' source |

## Optional tools named in skill references (not installed by anything here)
| What | Used by | Source | Licence |
|---|---|---|---|
| RapidOCR (+ onnxruntime) | vdi-drive `references/reading-the-screen.md`, optional OCR read-back | `RapidAI/RapidOCR` | Apache-2.0 (check the model weights you install) |
| `consol/debian-xfce-vnc` container image | vdi-drive `references/test-rig.md`, a disposable test desktop | `ConSol/docker-headless-vnc-container` | Apache-2.0 |

## Python packages (from each skill's `requirements.txt`)
| Package | Used by | Licence |
|---|---|---|
| markitdown `[docx,pptx,xlsx,pdf]` | doc-index; `[docx]` for office-docx `to-md` | MIT (pulls in magika Apache-2.0, onnxruntime MIT, pdfminer.six MIT, mammoth BSD-2-Clause, pandas BSD-3-Clause, python-pptx, openpyxl) |
| python-pptx | office-pptx | MIT |
| openpyxl | office-xlsx | MIT |
| pypdfium2 | office-render | BSD-3-Clause or Apache-2.0 (bundles PDFium, BSD-3-Clause) |
| Pillow | office-render, office-pptx | MIT-CMU |
| python-docx | office-docx (and doc-index tests) | MIT |
| olefile | draft-reply, reading Outlook `.msg` files | BSD-2-Clause style (its LICENSE also carries the original PIL notice) |
| anthropic | batch-review | MIT |
| PyMuPDF | **not used** | AGPL-3.0: deliberately avoided |

## MCP servers in `mcp/golden-config.template.json`
| Server | Package or endpoint | Licence | Egress |
|---|---|---|---|
| playwright | npm `@playwright/mcp` (`microsoft/playwright-mcp`) | Apache-2.0 | local browser |
| chrome-devtools | npm `chrome-devtools-mcp` (`ChromeDevTools/chrome-devtools-mcp`) | Apache-2.0 | local; upstream usage statistics and CrUX trace-URL lookups are on by default and disabled in the template |
| context7 | `https://mcp.context7.com/mcp` (`upstash/context7`) | MIT | hosted |
| GitHub | `https://api.githubcopilot.com/mcp/readonly` or local `github/github-mcp-server` | MIT | hosted (remote) |
| brave-search | npm `@brave/brave-search-mcp-server` | MIT | hosted API |
| exa | `https://mcp.exa.ai/mcp` (`exa-labs/exa-mcp-server`) | MIT | hosted |
| tavily | npm `tavily-mcp` (`tavily-ai/tavily-mcp`) | MIT | hosted API |
| tokensave | local binary | MIT | none |
| postgres (optional, read-only) | PyPI `postgres-mcp` (`crystaldba/postgres-mcp`), run with `uvx`, `--access-mode=restricted` | MIT | local; only the database you name |
