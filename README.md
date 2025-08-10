Here’s a polished GitHub README description for your bot:

---

# PotBot – Feature-Packed Discord Server Manager 🤖

**PotBot** is a powerful, all-in-one Discord bot designed to keep your community active, informed, and engaged. It combines **XP & leveling systems**, **voice activity tracking**, **daily statistics**, **weather lookups**, **event announcements**, and **moderation tools**—all with persistent data saving.

---

## ✨ Features

### 🎮 XP & Leveling System

* Earn XP from sending messages (2 XP + random bonuses)
* Gain XP from voice activity (0.3 XP/minute)
* Daily bonus multiplier & streak bonuses for active users
* Prestige system at Level 50
* Achievements for milestones (levels, streaks, leaderboard positions, voice time)

### 📊 Server Statistics

* Tracks daily activity: messages, active users, XP gained, voice minutes, level ups, prestiges, and new members
* Auto-posts daily stats at midnight in a designated channel
* Compare today’s performance with yesterday’s
* View real-time stats with `!dailystats`

### 🏆 Leaderboards & Profiles

* View top users with `!leaderboards`
* Detailed user profiles with levels, XP, rank, voice time, messages sent, streaks, and achievements (`!profile`)

### 🌦 Weather Integration

* Get current weather and daily forecasts from **wttr.in** using `!weather <city>`

### 📅 Event Announcements

* Display upcoming events with `!events`
* Admins can update event info via `!setevents`

### 🛡 Moderation Tools

* Lock & unlock channels (`!lock`, `!unlock`)
* Kick, ban, softban, and tempban commands
* Anti-spam cooldown for XP gains
* Persistent channel locks

### 🖥 System & Info Commands

* `!system` – View bot host system resource usage
* `!info` – Display server details and total activity stats

### 🛠 Admin DM Controls

* Change bot status remotely via DM (`status playing <game>`, etc.)
* Broadcast messages to #general from admin DMs

---

## 🚀 Getting Started

1. **Clone the repository**

   ```bash
   git clone https://github.com/yourusername/potbot.git
   cd potbot
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   Create a `.env` file and add your Discord bot token:

   ```env
   DISCORD_BOT_TOKEN=your_token_here
   ```

4. **Run the bot**

   ```bash
   python potbot.py
   ```

---

## ⚙ Requirements

* Python 3.8+
* `discord.py`
* `aiohttp`
* `psutil`
* `python-dotenv`

---

## 📜 License

This project is open-source under the MIT License.

---

If you want, I can also make you a **shorter GitHub-friendly tagline** that grabs attention right at the top. That would make the README pop even more.
