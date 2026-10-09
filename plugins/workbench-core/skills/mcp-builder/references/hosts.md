# Host compatibility

Limits move between releases; re-check the vendor pages when you rely on one.

| Capability | Web and Desktop apps | Claude Code | Notes |
|---|---|---|---|
| Remote streamable HTTP | yes (the only kind the web reaches) | yes | deprecated HTTP-plus-SSE still appears in old servers |
| Local stdio | Desktop only (as an extension bundle) | yes | never for web connectors |
| Tool result cap | about 150,000 characters | 25,000 tokens by default (`MAX_MCP_OUTPUT_TOKENS`) | page to the smaller cap |
| Call time limit | about 240 seconds | `MCP_TOOL_TIMEOUT` | |
| Resource subscriptions | no | not relied on | |
| Sampling, roots, draft capabilities | no | sampling no | do not depend on them |
| Handshake | 2025-era `initialize` | 2025-era and newer | serve both when the SDK allows |
| OAuth | authorization-code with PKCE S256, client ID metadata document or dynamic registration, hosted callback | loopback redirect on an ephemeral port | no `client_credentials` |
| Static header | beta for some organizations | via the client config | identifies the deployment |
| Tool listing | per connection; permission prompts follow `readOnlyHint` and `destructiveHint` | same | annotations are advice |

## Fill in per server
| Question | Answer |
|---|---|
| Which hosts must it work in? | |
| Largest result it can return (characters) and how it pages | |
| Slowest call (seconds) | |
| Auth pattern and who completes it | |
| Public host names the allowlist needs | |
| Anything a host does not support that the server uses | |
