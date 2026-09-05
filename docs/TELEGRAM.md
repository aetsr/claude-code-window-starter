# Telegram setup

1. Create a bot with BotFather.
2. Paste the token into the SecureField in the application and press the Save Token to Keychain button.
3. Use the displayed `/pair CODE` flow and **Pair and activate** button, or enter numeric user/private chat IDs into the allowlists. Keep pairing codes private.
4. Add a notification chat/channel ID if needed.
5. Enable Telegram and save the settings.
6. Press the Test Telegram connection button.

The bot uses long polling and does not open any inbound port. The channel is a notification target only; commands are accepted from private chats present in the allowlist.

Execution and prompt changes require a confirmation nonce. The token is never shown again or logged.

`/workhours 08:00 17:00` selects the adaptive weekday plan; global automation must also be enabled for execution. `/schedule` shows work hours, planned requests (anchors), observed reset, confidence and next action. `/sync_usage` uses the same cache-aware query as `/usage`, not a forced network refresh.

`/usage` and `/sync_usage` send a typing indicator and check cached data (up to 300 seconds), then Anthropic's OAuth usage endpoint with the Claude Code Keychain credential. The fallback reads CLI `/usage` in an invisible app-owned PTY. Neither path launches Terminal/iTerm or needs Terminal Automation permission, a settings-file edit or statusLine configuration. Endpoint and CLI formats can change; see [security details](../SECURITY.md).

Before the first `/usage` request, run `claude auth login` once interactively on the Mac. Login is intentionally not automated. Authentication, lock contention, unsupported `/usage`, empty output, and timeouts are returned as short Turkish messages. The polling worker checks its Swift supervisor before and after each approximately 10-second long poll, so an old release exits promptly after an upgrade.
