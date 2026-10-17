"""One home for model prices and facts, kept equal everywhere they are shown; plus the routing parity snapshot.

  py -3 tools/test_models_doc.py --render     rewrite the generated blocks of docs/models.md and docs/evidence/haiku-5-5.md
  python -m unittest discover -s tools -p "test_models_doc.py"      the checks (WB_REQUIRE_ALL=1: nothing skips)

The prices live in settings/model-evidence.json (key `prices`, each entry citing a vendor evidence row). docs/models.md and
docs/evidence/haiku-5-5.md render from it between `<!-- begin:NAME -->` and `<!-- end:NAME -->` lines, docs/token-diet.md shows
the same numbers in its own table, and tools/token-split/token_split.py loads them. The tests assert all four agree, that every
provider model id appears in models.md, and that settings/model-routing.json plus the persona files still match the frozen
snapshot below (change the snapshot only together with an intentional routing change and its evidence).
"""
import os

REQUIRE = os.environ.get("WB_REQUIRE_ALL") == "1"   # house convention: no test below skips; a missing file fails

import importlib.util  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

KIT = Path(__file__).resolve().parent.parent
EVIDENCE = "settings/model-evidence.json"
ROUTING = "settings/model-routing.json"
MODELS_MD = "docs/models.md"
HAIKU_MD = "docs/evidence/haiku-5-5.md"
TOKEN_DIET = "docs/token-diet.md"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
FIELDS = ("input", "output", "cache_write", "cache_read")

# Evidence rows the Haiku 5.5 compendium shows (all re-read from the vendor's or the third party's own page when this was
# written); the tag comes from the row's kind. Internal-run rows are never shown: the compendium is public pages only.
HAIKU_ROWS = ("E12", "E13", "E11", "E35", "E2", "E8", "E29", "E14", "E1", "E7", "E10", "E3", "E30")
TAGS = {"vendor": "PUBLISHED", "independent": "3P-PUBLISHED"}
ALL_TAGS = ("PUBLISHED", "3P-PUBLISHED", "RUMOUR")

# Vendor default effort per model (E31 and E33) and the limits shown in the models table.
NAMES = {"claude-fable-5-1": "Claude Fable 5.1", "claude-opus-5-5": "Claude Opus 5.5",
         "claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-haiku-5-5": "Claude Haiku 5.5"}
DEFAULT_EFFORT = {"claude-fable-5-1": "high", "claude-opus-5-5": "medium", "claude-sonnet-5-5": "high", "claude-haiku-5-5": "medium"}
LIMITS = ("1M tokens", "128K tokens")
# Claude Code's own default effort (E38): its model-config page names the three 5.5 models as medium and does not name Fable.
CLAUDE_CODE_DEFAULT = {"claude-fable-5-1": "not named", "claude-opus-5-5": "`medium`", "claude-sonnet-5-5": "`medium`",
                       "claude-haiku-5-5": "`medium`"}

# Frozen parity snapshot: row id, persona, preference order of (model, effort). It mirrors the persona/model/effort routing
# table the kit's model policy teaches; the persona files must carry the first entry of their row.
ROUTING_SNAPSHOT = [
    ("R-code", "implementer", (("claude-sonnet-5-5", "xhigh"), ("claude-opus-5-5", "high"))),
    ("R-breadth", "general-purpose", (("claude-sonnet-5-5", "xhigh"), ("claude-opus-5-5", "high"))),
    ("R-read", "scout", (("claude-haiku-5-5", "high"), ("claude-sonnet-5-5", "high"))),
    ("R-build", "flagship", (("claude-opus-5-5", "xhigh"), ("claude-sonnet-5-5", "xhigh"))),
    ("R-gate", "blue-verify", (("claude-opus-5-5", "xhigh"), ("claude-sonnet-5-5", "xhigh"))),
    ("R-research", "researcher", (("claude-opus-5-5", "high"), ("claude-sonnet-5-5", "xhigh"))),
    ("R-ops", "ops-runner", (("claude-opus-5-5", "high"), ("claude-sonnet-5-5", "xhigh"))),
    ("R-deliverable", "flagship", (("claude-opus-5-5", "xhigh"), ("claude-sonnet-5-5", "xhigh"))),
    ("R-security", "security-auditor", (("claude-opus-5-5", "high"), ("claude-sonnet-5-5", "xhigh"))),
    ("R-regulated", "flagship", (("claude-opus-5-5", "xhigh"), ("claude-sonnet-5-5", "xhigh"))),
    ("R-red", "red-team", (("claude-sonnet-5-5", "xhigh"), ("claude-opus-5-5", "high"))),
    ("R-green", "green-team", (("claude-sonnet-5-5", "xhigh"), ("claude-opus-5-5", "high"))),
]


def load(rel, root=KIT):
    return json.loads((Path(root) / rel).read_text(encoding="utf-8"))


def read(rel, root=KIT):
    return (Path(root) / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


# ---- renderers: the only place a price or an id becomes markdown ---------------------------------------------------
def money(v):
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    if "." in s and len(s.split(".")[1]) < 2:
        s += "0" * (2 - len(s.split(".")[1]))
    return "$" + s


def _tier(over):
    return f"{over // 1000}K"


def price_rows(prices):
    """[(label, id, {field: value})] highest input price first; a long-prompt tier follows its model."""
    out = []
    for mid, p in sorted(prices.items(), key=lambda kv: -kv[1]["input"]):
        lc = p.get("long_context")
        out.append((f"`{mid}`" + (f", prompt up to {_tier(lc['over_tokens'])} tokens" if lc else ""), mid, {k: p[k] for k in FIELDS}))
        if lc:
            out.append((f"`{mid}`, prompt over {_tier(lc['over_tokens'])} tokens", mid, {k: lc[k] for k in FIELDS}))
    return out


def render_prices(prices):
    L = ["| Model | Input | Output | Cache write (5 min) | Cache read |", "|---|---|---|---|---|"]
    for label, _, v in price_rows(prices):
        L.append(f"| {label} | {money(v['input'])} | {money(v['output'])} | {money(v['cache_write'])} | {money(v['cache_read'])} |")
    return "\n".join(L)


def render_ids(routing):
    L = ["| Model | Claude API | Bedrock | Google Cloud | Foundry |", "|---|---|---|---|---|"]
    for m, p in routing["provider_ids"].items():
        L.append(f"| `{m}` | `{p['anthropic']}` | `{p['bedrock']}` | `{p['vertex']}` | `{p['foundry']}` |")
    return "\n".join(L)


def render_haiku_prices(prices):
    keep = {k: v for k, v in prices.items() if k in ("claude-haiku-5-5", "claude-sonnet-5-5")}
    return render_prices(keep)


def render_haiku_rows(evidence):
    rows = {r["id"]: r for r in evidence["rows"]}
    L = []
    for i in HAIKU_ROWS:
        r = rows[i]
        L += [f"### {i} · {TAGS[r['kind']]}", "", f"- **Source:** {r['source']}", f"- **Finding:** {r['claim']}"]
        if r.get("value"):
            L.append(f"- **Numbers:** {r['value']}")
        L.append("")
    return "\n".join(L).rstrip("\n")


def blocks(root=KIT):
    """{(file, block name): generated text}"""
    ev, routing = load(EVIDENCE, root), load(ROUTING, root)
    return {(MODELS_MD, "prices"): render_prices(ev["prices"]), (MODELS_MD, "ids"): render_ids(routing),
            (HAIKU_MD, "haiku-prices"): render_haiku_prices(ev["prices"]), (HAIKU_MD, "rows"): render_haiku_rows(ev)}


def block_re(name):
    return re.compile(rf"(<!-- begin:{re.escape(name)} -->\n)(.*?)(\n<!-- end:{re.escape(name)} -->)", re.S)


def current(text, name):
    m = block_re(name).search(text)
    return m.group(2) if m else None


def render_all(root=KIT, write=True):
    """Rewrite every generated block; returns the (file, block) pairs that were out of date."""
    stale, files = [], {}
    for (rel, name), want in blocks(root).items():
        text = files.setdefault(rel, read(rel, root))
        if current(text, name) != want:
            stale.append((rel, name))
            if not block_re(name).search(text):
                raise SystemExit(f"{rel}: no <!-- begin:{name} --> ... <!-- end:{name} --> markers")
            files[rel] = block_re(name).sub(lambda m: m.group(1) + want + m.group(3), text, count=1)
    if write:
        for rel, text in files.items():
            (Path(root) / rel).write_text(text, encoding="utf-8", newline="\n")
    return stale


def load_module(name, rel):
    spec = importlib.util.spec_from_file_location(name, KIT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def table_cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def money_value(cell):
    return float(cell.replace("$", ""))


# ---- tests ---------------------------------------------------------------------------------------------------------
class Prices(unittest.TestCase):
    def setUp(self):
        self.ev, self.routing = load(EVIDENCE), load(ROUTING)
        self.prices = self.ev["prices"]

    def test_the_price_table_is_complete_and_cites_a_vendor_row(self):
        self.assertEqual(set(self.prices), set(self.routing["provider_ids"]))
        rows = {r["id"]: r for r in self.ev["rows"]}
        for mid, p in self.prices.items():
            self.assertEqual(set(p), {*FIELDS, "long_context", "evidence", "as_of"}, mid)
            self.assertEqual(rows[p["evidence"]]["kind"], "vendor", mid)
            self.assertRegex(p["as_of"], r"^20\d\d-\d\d$")
            self.assertTrue(all(isinstance(p[k], (int, float)) and p[k] > 0 for k in FIELDS), mid)
            self.assertTrue(p["cache_read"] < p["input"] < p["cache_write"] < p["output"], mid)
            lc = p["long_context"]
            if lc:
                self.assertEqual(set(lc), {*FIELDS, "over_tokens"}, mid)
                self.assertTrue(all(lc[k] > p[k] for k in FIELDS), mid)
        self.assertEqual([m for m, p in self.prices.items() if p["long_context"]], ["claude-haiku-5-5"])

    def test_the_cited_evidence_row_states_every_number(self):
        """Each price appears in the cited row's value text, so the table cannot drift from what was quoted."""
        value = {r["id"]: r["value"] for r in self.ev["rows"]}["E32"]
        for mid, p in self.prices.items():
            for k in FIELDS:
                for v in [p[k]] + ([p["long_context"][k]] if p["long_context"] else []):
                    s = f"{v:.3f}".rstrip("0").rstrip(".")
                    self.assertTrue(re.search(rf"(?<![\d.]){re.escape(s)}0?(?![\d])", value), f"{mid} {k} {v}")

    def test_models_md_price_block_is_the_render_of_the_json(self):
        self.assertEqual(current(read(MODELS_MD), "prices"), render_prices(self.prices))

    def test_models_md_prices_parse_back_to_the_json_numbers(self):
        text = read(MODELS_MD)
        got = {}
        for line in current(text, "prices").splitlines()[2:]:
            c = table_cells(line)
            got[(re.search(r"`([^`]+)`", c[0]).group(1), "over" in c[0])] = [money_value(x) for x in c[1:]]
        want = {(mid, "over" in label): [v[k] for k in FIELDS] for label, mid, v in price_rows(self.prices)}
        self.assertEqual(got, want)

    def test_token_diet_table_equals_the_json(self):
        cols = {"Haiku 5.5, prompt up to 100K tokens": ("claude-haiku-5-5", False), "Haiku 5.5, prompt over 100K": ("claude-haiku-5-5", True),
                "Sonnet 5.5": ("claude-sonnet-5-5", False), "Opus 5.5": ("claude-opus-5-5", False)}
        rows = {"Input": "input", "Output": "output", "Cache write (5 minutes)": "cache_write", "Cache read": "cache_read"}
        lines = [x for x in read(TOKEN_DIET).splitlines() if x.startswith("|")]
        head = table_cells(lines[0])
        self.assertEqual(head[0], "Token class")
        self.assertEqual(set(head[1:]), set(cols), "the columns of the table in docs/token-diet.md")
        seen = set()
        for line in lines[2:]:
            c = table_cells(line)
            for col, cell in zip(head[1:], c[1:]):
                mid, long = cols[col]
                p = self.prices[mid]["long_context"] if long else self.prices[mid]
                self.assertEqual(money_value(cell), p[rows[c[0]]], f"{col} / {c[0]}")
                seen.add((col, c[0]))
        self.assertEqual(len(seen), len(cols) * len(rows))

    def test_token_split_loads_the_same_table(self):
        ts = load_module("wb_token_split", "tools/token-split/token_split.py")
        got = ts.load_prices()
        self.assertEqual(set(got), set(self.prices))
        for mid, p in self.prices.items():
            self.assertEqual(got[mid]["base"], {k: float(p[k]) for k in FIELDS}, mid)
            lc = p["long_context"]
            self.assertEqual(got[mid]["long"], {k: float(lc[k]) for k in FIELDS} if lc else None, mid)
            self.assertEqual(got[mid]["over"], lc["over_tokens"] if lc else 0, mid)


class RoutingParity(unittest.TestCase):
    def test_routing_rows_equal_the_frozen_snapshot(self):
        got = [(r["id"], r["persona"], tuple((s["model"], s["effort"]) for s in r["chain"])) for r in load(ROUTING)["rows"]]
        self.assertEqual(got, ROUTING_SNAPSHOT)
        self.assertEqual(len(got), 12)

    def test_every_snapshot_effort_and_model_is_valid(self):
        known = set(load(ROUTING)["provider_ids"])
        for _, _, chain in ROUTING_SNAPSHOT:
            for model, effort in chain:
                self.assertIn(model, known)
                self.assertIn(effort, EFFORTS)

    def test_persona_files_carry_the_first_choice_of_their_row(self):
        seen = set()
        for _, persona, chain in ROUTING_SNAPSHOT:
            f = KIT / "plugins" / "workbench-core" / "agents" / f"{persona}.md"
            if persona == "general-purpose":      # the built-in persona has no file
                self.assertFalse(f.exists())
                continue
            head = f.read_text(encoding="utf-8").split("---")[1]
            model, effort = (re.search(rf"^{k}:\s*(\S+)", head, re.M).group(1) for k in ("model", "effort"))
            self.assertEqual((model, effort), chain[0], persona)
            seen.add(persona)
        self.assertEqual(len(seen), 9)


class ModelsPage(unittest.TestCase):
    def setUp(self):
        self.text, self.ev = read(MODELS_MD), load(EVIDENCE)
        self.routing = load(ROUTING)
        self.e31 = {r["id"]: r["value"] for r in self.ev["rows"]}["E31"]

    def test_as_of_line_and_the_link_to_the_routing_page(self):
        self.assertIn("As of October 2026", self.text)
        self.assertIn("(model-routing.md)", self.text)
        self.assertTrue((KIT / "docs" / "model-routing.md").is_file())

    def test_the_routing_table_is_not_copied_here(self):
        self.assertFalse(re.search(r"\bR-[a-z]+\b", self.text))
        self.assertNotIn("| Row | Task shape", self.text)
        self.assertIsNone(re.search(r"claude-[a-z]+-\d+(?:-\d+)* \((?:low|medium|high|xhigh|max)\)", self.text))

    def test_every_provider_id_is_shown_and_the_ids_block_is_the_render(self):
        for model, p in self.routing["provider_ids"].items():
            for provider, pid in p.items():
                self.assertIn(f"`{pid}`", self.text, f"{model} {provider}")
        self.assertEqual(current(self.text, "ids"), render_ids(self.routing))

    def test_the_overview_table_states_limits_and_default_effort_from_the_evidence(self):
        rows = {}
        for line in self.text.splitlines():
            m = re.match(r"\| Claude [^|]+\| `([^`]+)` \|", line)
            if m:
                rows[m.group(1)] = table_cells(line)
        self.assertEqual(set(rows), set(NAMES))
        for mid, c in rows.items():
            self.assertEqual((c[2], c[3], c[4].strip("`")), (LIMITS[0], LIMITS[1], DEFAULT_EFFORT[mid]), mid)
            self.assertIn(f"{NAMES[mid]} {DEFAULT_EFFORT[mid]}", self.e31, mid)
        self.assertIn(f"context window {LIMITS[0]}, max output {LIMITS[1]}", self.e31)

    def test_claude_code_default_effort_column_follows_e38(self):
        e38 = {r["id"]: r["value"] for r in self.ev["rows"]}["E38"]
        for want in ("Opus 5.5, Sonnet 5.5, and Haiku 5.5 default to medium", "Fable 5.1 is not named"):
            self.assertIn(want, e38)
        head = next(x for x in self.text.splitlines() if x.startswith("| Model | API id |"))
        self.assertEqual(table_cells(head)[4:6], ["API default effort", "Claude Code default effort"])
        seen = {}
        for line in self.text.splitlines():
            m = re.match(r"\| Claude [^|]+\| `([^`]+)` \|", line)
            if m:
                seen[m.group(1)] = table_cells(line)[5]
        self.assertEqual(set(seen), set(CLAUDE_CODE_DEFAULT))
        for mid, cell in seen.items():
            self.assertTrue(cell.startswith(CLAUDE_CODE_DEFAULT[mid]), f"{mid}: {cell}")

    def test_each_model_has_best_for_never_for_and_effort_guidance(self):
        for mid, name in NAMES.items():
            m = re.search(rf"^### {re.escape(name)}\n(.*?)(?=^#{{2,3}} |\Z)", self.text, re.S | re.M)
            self.assertIsNotNone(m, name)
            for label in ("Best for", "Never for", "Effort"):
                self.assertRegex(m.group(1), rf"(?m)^- \*\*{label}:\*\* \S", f"{name} {label}")
            efforts = re.findall(r"`(low|medium|high|xhigh|max)`", m.group(1))
            self.assertTrue(efforts, name)
            self.assertIn(f"`{DEFAULT_EFFORT[mid]}`", m.group(1), f"{name} names its default effort")

    def test_every_evidence_id_named_exists(self):
        have = {r["id"] for r in self.ev["rows"]}
        named = set(re.findall(r"\bE\d+\b", self.text))
        self.assertTrue(named)
        self.assertEqual(named - have, set())


class HaikuCompendium(unittest.TestCase):
    def setUp(self):
        self.text, self.ev = read(HAIKU_MD), load(EVIDENCE)
        self.rows = {r["id"]: r for r in self.ev["rows"]}

    def test_generated_blocks_are_current(self):
        for name, want in ((n, w) for (rel, n), w in blocks().items() if rel == HAIKU_MD):
            self.assertEqual(current(self.text, name), want, name)

    def test_only_public_page_rows_with_a_valid_tag(self):
        for i in HAIKU_ROWS:
            self.assertIn(self.rows[i]["kind"], TAGS, i)
        body = current(self.text, "rows")
        tags = re.findall(r"^### E\d+ · (\S+)$", body, re.M)
        self.assertEqual(len(tags), len(HAIKU_ROWS))
        self.assertTrue(set(tags) <= set(ALL_TAGS))
        self.assertNotRegex(self.text, r"\bO\d\b")
        for t in ALL_TAGS:
            self.assertIn(t, self.text.split("<!-- begin:", 1)[0], f"{t} is explained before the tables")

    def test_haiku_rows_are_the_small_models_pages(self):
        for i in HAIKU_ROWS:
            r = self.rows[i]
            self.assertTrue("Haiku" in r["source"] or "Haiku" in (r["value"] or "") or "small model" in r["claim"], i)

    def test_every_evidence_id_named_exists(self):
        named = set(re.findall(r"\bE\d+\b", self.text))
        self.assertEqual(named - set(self.rows), set())


class OtherDocs(unittest.TestCase):
    def test_routing_method_names_its_rules(self):
        text = read("docs/engineering/routing-method.md")
        for needle in ("published", "direction", "settings/model-evidence.json", "--render-routing", "R0"):
            self.assertIn(needle, text)
        self.assertNotRegex(text, r"\bO\d\b")

    def test_token_diet_has_the_prompt_cache_section_with_real_evidence_ids(self):
        diet, have = read(TOKEN_DIET), {r["id"] for r in load(EVIDENCE)["rows"]}
        self.assertIn("\n## 8. Prompt cache\n", diet)
        section = diet.split("\n## 8. Prompt cache\n", 1)[1]
        named = set(re.findall(r"\bE\d+\b", section))
        self.assertTrue({"E37", "E39", "E41", "E42", "E43"} <= named, named)
        self.assertEqual(named - have, set())
        for want in ("Does an effort change break it?", "`/usage`", "`/insights`", "seven times", "Command-line tools over MCP"):
            self.assertIn(want, section, want)

    def test_haiku_page_marks_deferred_mcp_tools_untested(self):
        text = read(HAIKU_MD)
        self.assertIn("Deferred MCP tools with Haiku 5.5: UNTESTED", text)
        self.assertEqual({r["id"]: r["kind"] for r in load(EVIDENCE)["rows"]}["E44"], "vendor")

    def test_guide_49_has_the_guide_shape(self):
        howto = load_module("wb_test_howto", "tools/test_howto.py")
        guides = sorted((KIT / "docs" / "howto").glob("49-*.md"))
        self.assertEqual(len(guides), 1)
        self.assertEqual(howto.guide_errors(guides[0].read_text(encoding="utf-8")), [])
        docs = load_module("wb_test_docs", "tools/test_docs.py")
        self.assertEqual(docs.check_paths(guides[0], KIT), [])

    def test_the_generated_blocks_have_no_stale_pair_in_the_working_tree(self):
        self.assertEqual(render_all(write=False), [])


if __name__ == "__main__":
    if "--render" in sys.argv[1:]:
        out = render_all(write=True)
        print("rewrote: " + (", ".join(f"{f}:{n}" for f, n in out) if out else "nothing (already current)"))
        sys.exit(0)
    unittest.main()
