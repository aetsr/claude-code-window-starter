# Telegram setup

1. Create a bot with BotFather.
2. Paste the token into the SecureField in the application and press the Save Token to Keychain button.
3. Enter your numeric Telegram user ID and private chat ID into the allowlist fields.
4. Add a notification chat/channel ID if needed.
5. Enable Telegram and save the settings.
6. Press the Test Telegram connection button.

The bot uses long polling and does not open any inbound port. The channel is a notification target only; commands are accepted from private chats present in the allowlist.

Execution and prompt changes require a confirmation nonce. The token is never shown again or logged.

`/usage` requires an active Claude Code session in the frontmost Terminal or iTerm2 tab on the Mac. The bot sends `/usage` to that tab, reads the resulting usage block, and reformats it for Telegram. If the active tab is not a Claude session, or macOS automation access is denied, the bot returns a readable error message.
