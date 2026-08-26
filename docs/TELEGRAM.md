# Telegram setup

1. Create a bot with BotFather.
2. Paste the token into the SecureField in the application and press the Save Token to Keychain button.
3. Enter your numeric Telegram user ID and private chat ID into the allowlist fields.
4. Add a notification chat/channel ID if needed.
5. Enable Telegram and save the settings.
6. Press the Test Telegram connection button.

The bot uses long polling and does not open any inbound port. The channel is a notification target only; commands are accepted from private chats present in the allowlist.

Execution and prompt changes require a confirmation nonce. The token is never shown again or logged.

`/workhours 08:00 17:00` enables the adaptive weekday/max-quota plan. `/schedule` shows the busy period, today's anchors, observed reset, source confidence, and next action. `/sync_usage` refreshes the real server observation immediately.

`/usage` and `/sync_usage` send a typing indicator, start Claude Code in an invisible, app-owned pseudo-terminal (PTY), validate the real five-hour/weekly usage block, and exit the child process. They never launch Terminal or iTerm and need no macOS Terminal Automation permission. No private OAuth endpoint, settings-file edit, or statusLine configuration is used.

Before the first `/usage` request, run `claude auth login` once interactively on the Mac. Login is intentionally not automated. Authentication, lock contention, unsupported `/usage`, empty output, and timeouts are returned as short Turkish messages. The polling worker checks its Swift supervisor before and after each approximately 10-second long poll, so an old release exits promptly after an upgrade.
