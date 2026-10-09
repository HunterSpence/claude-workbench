# Deploy checklist for web connectors

Reasons and the failure catalog: `docs/engineering/mcp-servers.md` sections 6 and 7. Tick every line before you hand over the URL.

- [ ] Public HTTPS with globally routable DNS. No redirect to another host (the connector drops `Authorization` on one).
- [ ] The server answers the 2025-era handshake; handlers are stateless so any replica can answer.
- [ ] Host allowlist includes the public or tunnel host name (`MCP_ALLOWED_HOSTS`); body-size cap set (`MCP_MAX_BODY`).
- [ ] WAF, CDN and bot rules exempt the MCP and OAuth paths, or allow the vendor's published egress ranges (read them from the
      vendor's page; do not copy them into documents).
- [ ] `curl -i <url>` from a public network returns `401` or `405`, never a timeout. `/.well-known/oauth-protected-resource` and
      one authorization-server metadata path return `200` JSON.
- [ ] Authorization server: S256 PKCE, both redirect URIs, form-encoded token endpoint, answers in under 10 seconds,
      `invalid_grant` on refresh errors, rotating refresh tokens for public clients, metadata document and dynamic registration.
- [ ] Every tool result is under 150,000 characters and every call under 240 seconds; nothing needs subscriptions, sampling or
      draft features.
- [ ] Secrets come from the environment or a secret store, never from the image or the repository.
- [ ] Logs go to stderr or OpenTelemetry and contain no tokens.
- [ ] Private network: a tunnel or a public endpoint with auth; split-horizon DNS will fail from the web.
- [ ] Real-client test done: connected, tools listed, one approved call, server log shows the arguments.
- [ ] Distribution: an organization owner adds the connector under organization settings; members connect with their own
      accounts. Adding a plugin does not add its bundled connectors.
- [ ] Anything added by URL shows as Custom; a directory listing needs review (no catch-all tools, titles and hints on every tool,
      names at most 64 characters, no generic errors).
- [ ] Do not branch behaviour on `clientInfo` names; they vary and are unauthenticated.
