# Telegram setup

1. Create a bot with BotFather.
2. Paste the token into the SecureField in the application and press the Save Token to Keychain button.
3. Enter your numeric Telegram user ID and private chat ID into the allowlist fields.
4. Add a notification chat/channel ID if needed.
5. Enable Telegram and save the settings.
6. Press the Test Telegram connection button.

The bot uses long polling and does not open any inbound port. The channel is a notification target only; commands are accepted from private chats present in the allowlist.

Execution and prompt changes require a confirmation nonce. The token is never shown again or logged.
