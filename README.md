# PING TABLET TEAM SCORE

Telegram bot: [@newscorept_bot](https://t.me/newscorept_bot)

## Features
- Telegram HTML Widget inside the bot's private chat
- 10 teams, initially 0 points
- Only Telegram user ID 128835770 can change scores
- +1, +5, -1, -5 controls; score cannot go below zero
- Team renaming through `/rename 3 New name`
- Score reset through `/reset`
- SQLite score and event history

## Railway setup
1. Deploy this repository as a Railway worker.
2. Add variables:
   - `BOT_TOKEN` = token from @BotFather
   - `ADMIN_ID` = `128835770`
   - `DB_PATH` = `/data/scores.sqlite3`
3. Add a Railway Volume and mount it at `/data`. This is important: without a volume, the database can be lost when the container is replaced.
4. Keep one running replica because this version uses long polling.
5. Open [@newscorept_bot](https://t.me/newscorept_bot) and send `/start`.

## Commands
- `/start` — send the score widget
- `/rename 3 New name` — rename a team (admin only)
- `/reset` — reset all scores to zero (admin only)

## Important
Telegram HTML Widgets are currently supported in production only in private chats with the bot. They are not Mini Apps: the widget has no network access and communicates with the bot using Telegram's `widget_query` updates. Team scores are stored in SQLite; the widget's visible state is updated by the bot.
