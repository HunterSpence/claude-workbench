# redact-settings

Copy a Claude Code `settings.json` (or an MCP config) with every value that could be a secret masked, before you
share it with IT, a colleague or a bug report. The source is never changed.

```bash
py -3 tools/redact-settings/redact_settings.py "%USERPROFILE%\.claude\settings.json" settings.redacted.json
```
Masks everything under `env` and `headers` (any depth), the API-key and cloud-credential helper commands, and any
credential-shaped string the kit scanner finds elsewhere. Read the output before you send it.

Test: `py -3 -m unittest discover -s tools/redact-settings`.
