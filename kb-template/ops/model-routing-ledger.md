---
title: Model routing ledger
domain: ops
tags: [models, routing]
status: active
---
# Model routing ledger

Append-only. One row per non-obvious routing pick, or per pick that turned out wrong (UNDER: failed
and re-ran on a bigger model; OVER: the bigger model added nothing). A matching row beats the
default table in `rules/model-policy.md`; it never edits that table.

| date | task shape | picked (persona, model, effort) | outcome | lesson |
|---|---|---|---|---|
