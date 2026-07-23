# Telegram setup and commands

Create the bot with BotFather and a private notification channel yourself. Add the bot as channel administrator only if it must post there. Channel commands remain disabled; use a private bot chat for control. Numeric user/chat IDs—not usernames—form the allowlist.

Run `install-telegram.sh ALLOWED_USER_ID [ALLOWED_CHAT_ID]`, paste the token through hidden stdin, and optionally configure `notification_channel_id`. The token is stored as an encrypted systemd credential when supported, otherwise as a 0600 file. It is never displayed again.

Commands include status, run/dry-run/diagnose, schedule/timezone, enable/disable, last/next/logs, model/prompt, timer, version/health, update status/check/apply, release list, and rollback. Run, prompt replacement, update, and rollback use owner-bound expiring confirmations. Unauthorized requests receive only `Unauthorized`; complete Telegram payloads are not logged.

The bot uses `getUpdates` long polling and opens no inbound port. The polling offset is atomically persisted. A bot lock prevents two long-running instances; per-user cooldown limits command bursts.
