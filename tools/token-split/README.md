# token-split

Shows where the spend in your own Claude Code sessions goes: uncached input, cache writes, cache reads, thinking, prose and
tool-call arguments. Context size is usually the big lever, and this puts a number on it before you change anything
(`docs/token-diet.md`, `docs/howto/11-keep-token-use-low.md`).

```
py -3 <KIT>/tools/token-split/token_split.py [--days 14] [--projects DIR] [--prices FILE] [--json]
py -3 <KIT>/tools/token-split/token_split.py --self-test
```

- Reads only the usage fields of each assistant message and the character count of its text and tool-call blocks, from
  `<CH>/projects/**/*.jsonl`. It never prints, stores or sends text, tool arguments, paths or folder names.
- Claude Code repeats the usage on every content block of a message, so usage is taken as the maximum per message id.
- Visible output is split into prose and tool-call arguments by character share. Thinking tokens come from the transcript's
  thinking count when it has one; otherwise the report says so.
- Prices come from the `prices` key of `settings/model-evidence.json`, the one home for them (rendered in `docs/models.md`,
  checked against `docs/token-diet.md` by `tools/test_models_doc.py`). A model that table does not list is counted and
  named, never priced at another model's rate. Add it to the table, with its vendor evidence row, to price it.
- The total is what the same tokens would cost at the vendor's API rates. It is not your bill.

Exit 0 on a report, 2 when the transcript folder or the price table is unusable.
