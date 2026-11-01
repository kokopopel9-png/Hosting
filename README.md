# Coding Agent Telegram Bot

Professional, modular Telegram Coding Agent Bot built with **pyTelegramBotAPI**.

## Structure

```
bot.py                  # entry point: imports modules, builds bot, runs polling
bot_legacy.py           # original monolith (preserved — nothing deleted)
requirements.txt        # dependencies
config/
  settings.py           # env vars, paths, branding, glyphs, BotConfig
  __init__.py
utils/
  logging.py            # rotating logger + catch_errors decorator
  storage.py            # JSON (default) + SQLite user/bot data store
  rate.py               # sliding-window rate limiter + anti-spam + auto-ban
  security.py           # blocked-command patterns + static code scanner
  formatting.py         # esc, rich_table, progress_bar, chunk_text
  crypto.py             # Fernet file encryption + in-memory key ring
  __init__.py
handlers/
  base.py               # TeleBot instance, owner/admin/banned decorators
  commands.py           # /start /help /menu /id /cancel /ping /admin
                        # coding agent: /code /read /write /exec /fix /review /selfcorrect
                        # admin: /stats /ban /broadcast
  callbacks.py          # prefix/exact callback-query router
  messages.py           # photo / document / text handlers
  admin.py              # inline admin panel (stats, broadcast, ban/unban)
  agent.py              # self-correction loop (read->scan->fix->rescan)
  __init__.py
```

## Setup & Run

```bash
# 1. Install Python 3.9+ and dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 2. Create a bot via @BotFather, get the token, then export:
export BOT_TOKEN="123456:ABC-DEF..."
export OWNER_ID="YOUR_TELEGRAM_USER_ID"   # optional; first /start user becomes owner

# 3. (Optional) Use SQLite storage for production instead of JSON
export USE_SQLITE=1

# 4. Run
python bot.py
```

Then message your bot: `/start`, `/help`, `/code`, `/exec`, `/stats`, `/ban`, `/broadcast`.

## Coding Agent commands

- `/code <path>` — read & display a project file (rich table)
- `/read <path>` — alias for /code
- `/write <path>` — send new content for a file
- `/exec <cmd>` — run a terminal command (destructive commands blocked)
- `/fix <path>` — auto-fix common errors in a file
- `/review <path>` — review code quality & security
- `/selfcorrect <path>` — read → static scan → fix → re-scan until safe

## Admin commands (owner only)

- `/stats` — bot statistics dashboard
- `/ban <user_id>` — ban/unban a user
- `/broadcast <text>` — announce to all non-banned users
- `/admin` — inline admin panel

## Features

Type hints + docstrings on all public functions/classes · Centralised logging
(console + rotating `logs/bot.log`) · Structured error handling
(`catch_errors`, `BotError`/`SecurityError`) · Rate limiting / anti-spam with
auto-ban escalation · User data persistence (JSON default, SQLite optional)
· Inline keyboards + prefix/exact callback routing · Rich HTML tables
· Path-traversal protection · Security watchdog for terminal commands ·
Graceful shutdown (SIGINT/SIGTERM) · Bot API 9.4 button-style ready
