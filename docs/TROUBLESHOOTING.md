# Troubleshooting

- `API_KEY_DETECTED`: remove prohibited API/provider variables and `apiKeyHelper`; do not substitute another paid provider.
- `CLAUDE_NOT_AUTHENTICATED`: renew `claude setup-token`, store it securely, and repeat dry-run before a real request.
- `SSH_HOST_KEY_CHANGED` / `GIT_HOST_KEY_CHANGED`: stop. Verify the new key through an independent trusted channel before replacing known_hosts.
- `ALREADY_RAN_TODAY`: automatic duplicate protection worked; manual execution remains available.
- `MODEL_UNAVAILABLE`: `auto` retries the account default only when the Haiku probe failed before a successful response.
- `HEALTH_CHECK_FAILED`: the staged release is not activated, or post-switch rollback is attempted automatically.
- `NO_HEALTHY_PREVIOUS_RELEASE`: no locally installed healthy fallback exists; do not supply an arbitrary Telegram commit.
- Empty `claude auth status`: status is `unknown`, not authenticated. A controlled real smoke test is the final authentication proof.

Inspect `status --json`, `diagnose --server --json`, user service status, and sanitized JSONL logs. Do not paste credentials, raw environment dumps, complete stderr, Claude auth files, or Telegram update payloads into an issue.
