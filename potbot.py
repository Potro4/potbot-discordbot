from typing import Union, Dict, Set
import os
import discord
from discord.ext import commands, tasks
import aiohttp
import logging
from datetime import datetime, timedelta
import asyncio
import time
from dotenv import load_dotenv
import json
import random
import math
import psutil
import signal
from functools import lru_cache

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s: %(message)s'
)
logger = logging.getLogger("discord_bot")

CONFIG = {
    "token": os.getenv("DISCORD_BOT_TOKEN"),
    "prefix": "!",
    "embed_color": 0x5865F2,
    "top_talkers_limit": 10,
    "antispam_cooldown_sec": 5,
    "greeting_channel": "general",
    "stats_channel": "daily-stats",  # Channel for stats updates
    "data_file": "bot_data.json",
    "admin_user": "potr.o",
    "admin_user_id": 627710864081944580,  # Replace with actual potr.o user ID
    "status_types": {
        "playing": discord.ActivityType.playing,
        "listening": discord.ActivityType.listening,
        "watching": discord.ActivityType.watching,
        "streaming": discord.ActivityType.streaming,
        "competing": discord.ActivityType.competing
    },
    # XP System
    "base_message_xp": 2,
    "bonus_xp_chance": 0.15,
    "bonus_xp_min": 1,
    "bonus_xp_max": 5,
    "voice_xp_per_minute": 0.3,
    "daily_bonus_multiplier": 1.5,
    "streak_bonus_days": 7,
    "streak_bonus_multiplier": 2.0,
    "voice_weight_factor": 10,
    
    # Level System
    "base_xp_requirement": 15,
    "xp_multiplier": 1.4,
    "prestige_threshold": 50,
    
    # Stats System
    "stats_update_hours": 4,  # How often to post stats (in hours)
    "stats_top_count": 5,     # How many top users to show in stats
}

if not CONFIG["token"]:
    logger.critical("Bot token not found. Set DISCORD_BOT_TOKEN in your environment.")
    exit(1)

# Global state storage with type hints for better performance
class BotState:
    session: aiohttp.ClientSession = None
    events_message: str = "No upcoming events."
    user_xp: Dict[int, float] = {}
    user_level: Dict[int, int] = {}
    user_prestige: Dict[int, int] = {}
    user_last_message: Dict[int, float] = {}  # Using float for timestamp
    user_daily_streak: Dict[int, int] = {}
    user_last_daily: Dict[int, str] = {}
    user_achievements: Dict[int, Set[str]] = {}
    voice_start_times: Dict[int, float] = {}  # Using float for timestamp
    user_message_count: Dict[int, int] = {}
    user_voice_time: Dict[int, float] = {}
    total_server_messages: int = 0
    locked_channels: Set[int] = set()
    
    # Use slots for memory optimization
    __slots__ = ()
    
    # Daily stats tracking with efficient data types
    daily_stats: Dict[str, Union[str, int, float, Set[int]]] = {
        "date": "",
        "messages": 0,
        "xp_gained": 0.0,
        "voice_time": 0.0,
        "active_users": set(),
        "level_ups": 0,
        "prestiges": 0,
        "new_members": 0
    }
    
    # Historical daily stats with compact structure
    daily_history: Dict[str, Dict[str, Union[int, float]]] = {}

weather_cache = {}
CACHE_TTL = 600

# Achievement definitions
ACHIEVEMENTS = {
    "first_message": {"name": "First Steps", "description": "Send your first message", "emoji": "👶"},
    "100_xp": {"name": "Getting Started", "description": "Reach 100 XP", "emoji": "🌱"},
    "1000_xp": {"name": "Experienced", "description": "Reach 1000 XP", "emoji": "💪"},
    "level_10": {"name": "Double Digits", "description": "Reach level 10", "emoji": "🔟"},
    "level_25": {"name": "Quarter Century", "description": "Reach level 25", "emoji": "🎯"},
    "first_prestige": {"name": "Prestige Master", "description": "Achieve your first prestige", "emoji": "⭐"},
    "10_day_streak": {"name": "Dedicated", "description": "Maintain a 10-day streak", "emoji": "🔥"},
    "voice_hour": {"name": "Socializer", "description": "Spend 60 minutes in voice", "emoji": "🎤"},
    "top_3": {"name": "Podium Finish", "description": "Reach top 3 on leaderboard", "emoji": "🏆"},
}

# Stats functions
def reset_daily_stats():
    """Reset daily stats for a new day"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Save previous day's stats to history if it exists
    if BotState.daily_stats["date"] and BotState.daily_stats["date"] != today:
        BotState.daily_history[BotState.daily_stats["date"]] = {
            "messages": BotState.daily_stats["messages"],
            "xp_gained": BotState.daily_stats["xp_gained"],
            "voice_time": BotState.daily_stats["voice_time"],
            "active_users": len(BotState.daily_stats["active_users"]),
            "level_ups": BotState.daily_stats["level_ups"],
            "prestiges": BotState.daily_stats["prestiges"],
            "new_members": BotState.daily_stats["new_members"]
        }
    
    # Reset for new day
    BotState.daily_stats = {
        "date": today,
        "messages": 0,
        "xp_gained": 0.0,
        "voice_time": 0.0,
        "active_users": set(),
        "level_ups": 0,
        "prestiges": 0,
        "new_members": 0
    }

def update_daily_stats(user_id: int, messages: int = 0, xp: float = 0.0, voice_time: float = 0.0, 
                      level_up: bool = False, prestige: bool = False, new_member: bool = False):
    """Update daily statistics"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Reset stats if it's a new day
    if BotState.daily_stats["date"] != today:
        reset_daily_stats()
    
    # Update stats
    BotState.daily_stats["messages"] += messages
    BotState.daily_stats["xp_gained"] += xp
    BotState.daily_stats["voice_time"] += voice_time
    if user_id:
        BotState.daily_stats["active_users"].add(user_id)
    if level_up:
        BotState.daily_stats["level_ups"] += 1
    if prestige:
        BotState.daily_stats["prestiges"] += 1
    if new_member:
        BotState.daily_stats["new_members"] += 1

def get_stats_comparison():
    """Get comparison with previous day's stats"""
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    today_stats = BotState.daily_stats if BotState.daily_stats["date"] == today else None
    yesterday_stats = BotState.daily_history.get(yesterday)
    
    return today_stats, yesterday_stats

# XP and Level calculations
@lru_cache(maxsize=100)
def calculate_level_requirement(level: int) -> float:
    if level == 0:
        return 0
    return math.floor(CONFIG["base_xp_requirement"] * (CONFIG["xp_multiplier"] ** (level - 1)))

@lru_cache(maxsize=1000)
def calculate_level_from_xp(xp: float) -> int:
    level = 0
    total_required = 0
    threshold = CONFIG["prestige_threshold"]
    base_req = CONFIG["base_xp_requirement"]
    multiplier = CONFIG["xp_multiplier"]
    
    # Binary search for level
    left, right = 0, threshold
    while left < right:
        mid = (left + right + 1) // 2
        req = base_req * ((multiplier ** mid - 1) / (multiplier - 1))
        if req <= xp:
            left = mid
        else:
            right = mid - 1
            
    return left

def get_total_xp_for_level(level: int) -> float:
    total = 0
    for i in range(1, level + 1):
        total += calculate_level_requirement(i)
    return total

def get_progress_in_level(xp: float, level: int) -> tuple:
    total_for_current = get_total_xp_for_level(level)
    next_level_req = calculate_level_requirement(level + 1)
    progress = xp - total_for_current
    return progress, next_level_req

def calculate_message_xp(user_id: int) -> float:
    base_xp = CONFIG["base_message_xp"]
    today = datetime.now().strftime('%Y-%m-%d')
    last_daily = BotState.user_last_daily.get(user_id, "")
    
    multiplier = 1.0
    if last_daily != today:
        multiplier = CONFIG["daily_bonus_multiplier"]
        BotState.user_last_daily[user_id] = today
        
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        if last_daily == yesterday:
            BotState.user_daily_streak[user_id] = BotState.user_daily_streak.get(user_id, 0) + 1
        else:
            BotState.user_daily_streak[user_id] = 1
    
    streak = BotState.user_daily_streak.get(user_id, 0)
    if streak >= CONFIG["streak_bonus_days"]:
        multiplier *= CONFIG["streak_bonus_multiplier"]
    
    bonus = 0
    if random.random() < CONFIG["bonus_xp_chance"]:
        bonus = random.randint(CONFIG["bonus_xp_min"], CONFIG["bonus_xp_max"])
    
    return (base_xp * multiplier) + bonus

def add_xp(user_id: int, amount: float) -> tuple:
    old_xp = BotState.user_xp.get(user_id, 0.0)
    new_xp = old_xp + amount
    BotState.user_xp[user_id] = new_xp
    
    old_level = BotState.user_level.get(user_id, 0)
    new_level = calculate_level_from_xp(new_xp)
    BotState.user_level[user_id] = new_level
    
    # Check achievements
    check_achievements(user_id, new_xp, new_level)
    
    prestiged = False
    if new_level >= CONFIG["prestige_threshold"] and old_level < CONFIG["prestige_threshold"]:
        BotState.user_prestige[user_id] = BotState.user_prestige.get(user_id, 0) + 1
        BotState.user_xp[user_id] = 0.0
        BotState.user_level[user_id] = 0
        new_level = 0
        prestiged = True
        award_achievement(user_id, "first_prestige")
        # Update daily stats
        update_daily_stats(user_id, prestige=True)
    
    leveled_up = new_level > old_level and not prestiged
    if leveled_up:
        # Update daily stats
        update_daily_stats(user_id, level_up=True)
    
    return leveled_up, new_level, prestiged

def check_achievements(user_id: int, xp: float, level: int):
    achievements = BotState.user_achievements.get(user_id, set())
    
    if xp >= 100 and "100_xp" not in achievements:
        award_achievement(user_id, "100_xp")
    if xp >= 1000 and "1000_xp" not in achievements:
        award_achievement(user_id, "1000_xp")
    if level >= 10 and "level_10" not in achievements:
        award_achievement(user_id, "level_10")
    if level >= 25 and "level_25" not in achievements:
        award_achievement(user_id, "level_25")
    
    streak = BotState.user_daily_streak.get(user_id, 0)
    if streak >= 10 and "10_day_streak" not in achievements:
        award_achievement(user_id, "10_day_streak")
    
    voice_time = BotState.user_voice_time.get(user_id, 0.0)
    if voice_time >= 60 and "voice_hour" not in achievements:
        award_achievement(user_id, "voice_hour")

def award_achievement(user_id: int, achievement_id: str):
    if user_id not in BotState.user_achievements:
        BotState.user_achievements[user_id] = set()
    BotState.user_achievements[user_id].add(achievement_id)

@lru_cache(maxsize=1)
def get_prestige_bonus_multiplier() -> float:
    return get_total_xp_for_level(CONFIG["prestige_threshold"])

def get_leaderboard_score(user_id: int) -> float:
    xp = BotState.user_xp.get(user_id, 0.0)
    voice_time = BotState.user_voice_time.get(user_id, 0.0)
    prestige = BotState.user_prestige.get(user_id, 0)
    
    prestige_bonus = prestige * get_prestige_bonus_multiplier() if prestige > 0 else 0
    return xp + (voice_time * CONFIG["voice_weight_factor"]) + prestige_bonus

def get_sorted_leaderboard() -> list:
    scores = []
    for user_id in BotState.user_xp:
        score = get_leaderboard_score(user_id)
        if score > 0:
            scores.append((user_id, score))
    return sorted(scores, key=lambda x: x[1], reverse=True)

def get_user_rank(user_id: int) -> int:
    if not BotState.user_xp:
        return 1
    
    target_score = get_leaderboard_score(user_id)
    leaderboard = get_sorted_leaderboard()
    for i, (uid, score) in enumerate(leaderboard, 1):
        if uid == user_id:
            return i
    return len(leaderboard) + 1

# Data persistence
def load_data():
    try:
        if os.path.exists(CONFIG["data_file"]):
            with open(CONFIG["data_file"], 'r') as f:
                data = json.load(f)
                BotState.user_xp = {int(k): v for k, v in data.get('user_xp', {}).items()}
                BotState.user_level = {int(k): v for k, v in data.get('user_level', {}).items()}
                BotState.user_prestige = {int(k): v for k, v in data.get('user_prestige', {}).items()}
                BotState.user_daily_streak = {int(k): v for k, v in data.get('user_daily_streak', {}).items()}
                BotState.user_last_daily = {int(k): v for k, v in data.get('user_last_daily', {}).items()}
                BotState.user_message_count = {int(k): v for k, v in data.get('user_message_count', {}).items()}
                BotState.user_voice_time = {int(k): v for k, v in data.get('user_voice_time', {}).items()}
                BotState.user_achievements = {int(k): set(v) for k, v in data.get('user_achievements', {}).items()}
                BotState.events_message = data.get('events_message', "No upcoming events.")
                BotState.total_server_messages = data.get('total_server_messages', 0)
                
                # Load daily stats and history
                BotState.daily_stats = data.get('daily_stats', {
                    "date": "",
                    "messages": 0,
                    "xp_gained": 0.0,
                    "voice_time": 0.0,
                    "active_users": set(),
                    "level_ups": 0,
                    "prestiges": 0,
                    "new_members": 0
                })
                # Convert active_users back to set if it's a list
                if isinstance(BotState.daily_stats.get("active_users"), list):
                    BotState.daily_stats["active_users"] = set(BotState.daily_stats["active_users"])
                
                BotState.daily_history = data.get('daily_history', {})
                
                logger.info("Data loaded successfully")
        else:
            logger.info("No existing data file found, starting fresh")
            reset_daily_stats()
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def save_data():
    try:
        data = {
            'user_xp': {str(k): v for k, v in BotState.user_xp.items()},
            'user_level': {str(k): v for k, v in BotState.user_level.items()},
            'user_prestige': {str(k): v for k, v in BotState.user_prestige.items()},
            'user_daily_streak': {str(k): v for k, v in BotState.user_daily_streak.items()},
            'user_last_daily': {str(k): v for k, v in BotState.user_last_daily.items()},
            'user_message_count': {str(k): v for k, v in BotState.user_message_count.items()},
            'user_voice_time': {str(k): v for k, v in BotState.user_voice_time.items()},
            'user_achievements': {str(k): list(v) for k, v in BotState.user_achievements.items()},
            'events_message': BotState.events_message,
            'total_server_messages': BotState.total_server_messages,
            'daily_stats': {
                **BotState.daily_stats,
                'active_users': list(BotState.daily_stats["active_users"])  # Convert set to list for JSON
            },
            'daily_history': BotState.daily_history
        }
        with open(CONFIG["data_file"], 'w') as f:
            json.dump(data, f, indent=2)
        logger.info("Data saved successfully")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

# Weather API function
async def fetch_weather(location: str) -> Union[dict, str]:
    current_time = time.time()
    loc_key = location.lower()
    cached = weather_cache.get(loc_key)
    if cached and (current_time - cached[0]) < CACHE_TTL:
        return cached[1]

    if BotState.session is None:
        connector = aiohttp.TCPConnector(limit_per_host=10)
        timeout = aiohttp.ClientTimeout(total=10)
        BotState.session = aiohttp.ClientSession(connector=connector, timeout=timeout)

    headers = {'User-Agent': 'Discord Bot - Contact: itkutus@gmail.com'}
    
    try:
        url = f"https://wttr.in/{location}?format=j1"
        async with BotState.session.get(url, headers=headers) as response:
            if response.status != 200:
                return f"Error: {response.status} - Could not fetch weather data"
            data = await response.json()
            weather_cache[loc_key] = (current_time, data)
            return data
    except Exception as e:
        logger.error(f"Weather fetch error: {e}")
        return str(e)

# Bot setup
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.members = True
intents.presences = True
intents.voice_states = True

bot = commands.Bot(command_prefix=CONFIG['prefix'], intents=intents, help_command=None)

async def create_embed(title: str, description: str = "", color: int = CONFIG['embed_color']):
    return discord.Embed(title=title, description=description, color=color)

# Daily Stats Update Task
@tasks.loop(minutes=60)  # Check every hour
async def post_daily_stats():
    """Post daily server statistics at midnight"""
    try:
        current_time = datetime.now()
        # Only post stats at midnight (00:00)
        if current_time.hour != 0 or current_time.minute != 0:
            return
            
        # Find the stats channel
        guild = None
        stats_channel = None
        
        for g in bot.guilds:
            guild = g
            stats_channel = discord.utils.get(g.channels, name=CONFIG["stats_channel"])
            if stats_channel:
                break
        
        if not stats_channel:
            logger.warning(f"Stats channel '{CONFIG['stats_channel']}' not found")
            return
        
        # Get current stats
        today_stats, yesterday_stats = get_stats_comparison()
        
        if not today_stats:
            logger.info("No stats to post yet")
            return
        
        # Create stats embed
        current_time = datetime.now()
        embed = await create_embed(
            f"📊 Daily Server Statistics - {current_time.strftime('%B %d, %Y')}",
            f"📅 **Update Time:** {current_time.strftime('%H:%M')} UTC"
        )
        
        # Today's stats
        active_count = len(today_stats["active_users"])
        embed.add_field(
            name="📈 Today's Activity",
            value=f"💬 **Messages:** {today_stats['messages']:,}\n"
                  f"👥 **Active Users:** {active_count}\n"
                  f"⭐ **XP Gained:** {today_stats['xp_gained']:,.0f}\n"
                  f"🔊 **Voice Time:** {today_stats['voice_time']:.0f}m\n"
                  f"📊 **Level Ups:** {today_stats['level_ups']}\n"
                  f"🌟 **Prestiges:** {today_stats['prestiges']}\n"
                  f"👋 **New Members:** {today_stats['new_members']}",
            inline=True
        )
        
        # Comparison with yesterday
        if yesterday_stats:
            msg_change = today_stats['messages'] - yesterday_stats['messages']
            active_change = active_count - yesterday_stats['active_users']
            xp_change = today_stats['xp_gained'] - yesterday_stats['xp_gained']
            
            msg_arrow = "📈" if msg_change > 0 else "📉" if msg_change < 0 else "➡️"
            active_arrow = "📈" if active_change > 0 else "📉" if active_change < 0 else "➡️"
            xp_arrow = "📈" if xp_change > 0 else "📉" if xp_change < 0 else "➡️"
            
            embed.add_field(
                name="📊 vs Yesterday",
                value=f"{msg_arrow} **Messages:** {msg_change:+,}\n"
                      f"{active_arrow} **Active Users:** {active_change:+}\n"
                      f"{xp_arrow} **XP Gained:** {xp_change:+,.0f}",
                inline=True
            )
        
        # Top performers today
        if today_stats["active_users"]:
            top_users = []
            for user_id in today_stats["active_users"]:
                user = guild.get_member(user_id)
                if user:
                    score = get_leaderboard_score(user_id)
                    level = BotState.user_level.get(user_id, 0)
                    prestige = BotState.user_prestige.get(user_id, 0)
                    top_users.append((score, user, level, prestige))
            
            top_users.sort(key=lambda x: x[0], reverse=True)
            top_users = top_users[:CONFIG["stats_top_count"]]
            
            if top_users:
                top_list = []
                medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
                for i, (score, user, level, prestige) in enumerate(top_users):
                    medal = medals[i] if i < len(medals) else f"{i+1}."
                    prestige_text = f"⭐{prestige}" if prestige > 0 else ""
                    top_list.append(f"{medal} **{user.display_name}** - Lv.{level}{prestige_text}")
                
                embed.add_field(
                    name="🏆 Top Active Users",
                    value="\n".join(top_list),
                    inline=False
                )
        
        # Server totals
        total_xp = sum(BotState.user_xp.values())
        total_voice = sum(BotState.user_voice_time.values())
        total_prestiges = sum(BotState.user_prestige.values())
        
        embed.add_field(
            name="🎯 All-Time Server Stats",
            value=f"💬 **Total Messages:** {BotState.total_server_messages:,}\n"
                  f"⭐ **Total XP:** {total_xp:,.0f}\n"
                  f"🔊 **Total Voice Time:** {total_voice:,.0f}m\n"
                  f"🌟 **Total Prestiges:** {total_prestiges}",
            inline=False
        )
        
        # Fun facts
        fun_facts = []
        if today_stats['messages'] > 0:
            avg_xp = today_stats['xp_gained'] / today_stats['messages']
            fun_facts.append(f"💡 Average XP per message today: {avg_xp:.1f}")
        
        if active_count > 0 and today_stats['voice_time'] > 0:
            avg_voice = today_stats['voice_time'] / active_count
            fun_facts.append(f"🎤 Average voice time per user: {avg_voice:.0f}m")
        
        if fun_facts:
            embed.add_field(
                name="🎲 Fun Facts",
                value="\n".join(fun_facts),
                inline=False
            )
        
        embed.set_footer(text="Next update at midnight • Use !leaderboards for live rankings")
        
        # Add some color based on activity level
        if active_count >= 10:
            embed.color = 0x00ff00  # Green for high activity
        elif active_count >= 5:
            embed.color = 0xffff00  # Yellow for moderate activity
        else:
            embed.color = 0xff6600  # Orange for low activity
        
        await stats_channel.send(embed=embed)
        logger.info(f"Posted daily stats to #{stats_channel.name}")
        
    except Exception as e:
        logger.error(f"Error posting daily stats: {e}")

# Commands
@bot.command()
async def help(ctx):
    embed = await create_embed("📜 Available Commands", "Complete list of bot commands")
    
    embed.add_field(name="🧭 **General Commands**", 
                   value="**!help** - Shows this command list\n"
                         "**!weather <city>** - Current weather via wttr.in\n"
                         "**!events** - Display current events\n"
                         "**!setevents <text>** - Set events (admin only)\n"
                         "**!info** - Server info + total messages\n"
                         "**!system** - Show system resource usage\n"
                         "**!leaderboards** - Top 10 users by XP + voice\n"
                         "**!profile [@user]** - User's level, XP, and rank\n"
                         "**!dailystats** - Show today's server statistics", 
                   inline=False)
    
    embed.add_field(name="📊 **XP & Leveling System**", 
                   value="• Messages: 2 XP + bonuses\n"
                         "• Voice: 0.3 XP/minute\n"
                         "• Daily bonus: 1.5x first message\n"
                         "• 7-day streak: 2x multiplier\n"
                         "• Prestige at level 50\n"
                         f"• Daily stats at midnight in #{CONFIG['stats_channel']}", 
                   inline=False)
    
    if ctx.author.guild_permissions.manage_messages:
        embed.add_field(name="🛡️ **Moderation Commands**", 
                       value="**!lock** - Disable messages in channel\n"
                             "**!unlock** - Re-enable messages in channel\n"
                             "**!kick <@user>** - Kick user\n"
                             "**!ban <@user>** - Ban user permanently\n"
                             "**!softban <@user>** - Ban + unban (delete messages)\n"
                             "**!tempban <@user> <seconds>** - Temporary ban", 
                       inline=False)
    
    embed.set_footer(text="💾 All data is saved persistently")
    await ctx.send(embed=embed)

@bot.command()
async def dailystats(ctx):
    """Show current daily statistics"""
    today_stats, yesterday_stats = get_stats_comparison()
    
    if not today_stats or today_stats["messages"] == 0:
        embed = await create_embed("📊 Daily Statistics", "No activity recorded today yet. Start chatting!")
        await ctx.send(embed=embed)
        return
    
    current_time = datetime.now()
    active_count = len(today_stats["active_users"])
    
    embed = await create_embed(
        f"📊 Today's Server Statistics - {current_time.strftime('%B %d, %Y')}",
        f"📅 **Current Time:** {current_time.strftime('%H:%M')} UTC"
    )
    
    embed.add_field(
        name="📈 Today's Activity",
        value=f"💬 **Messages:** {today_stats['messages']:,}\n"
              f"👥 **Active Users:** {active_count}\n"
              f"⭐ **XP Gained:** {today_stats['xp_gained']:,.0f}\n"
              f"🔊 **Voice Time:** {today_stats['voice_time']:.0f} minutes\n"
              f"📊 **Level Ups:** {today_stats['level_ups']}\n"
              f"🌟 **Prestiges:** {today_stats['prestiges']}\n"
              f"👋 **New Members:** {today_stats['new_members']}",
        inline=False
    )
    
    if yesterday_stats:
        msg_change = today_stats['messages'] - yesterday_stats['messages']
        active_change = active_count - yesterday_stats['active_users']
        xp_change = today_stats['xp_gained'] - yesterday_stats['xp_gained']
        
        msg_arrow = "📈" if msg_change > 0 else "📉" if msg_change < 0 else "➡️"
        active_arrow = "📈" if active_change > 0 else "📉" if active_change < 0 else "➡️"
        xp_arrow = "📈" if xp_change > 0 else "📉" if xp_change < 0 else "➡️"
        
        embed.add_field(
            name="📊 Compared to Yesterday",
            value=f"{msg_arrow} **Messages:** {msg_change:+,}\n"
                  f"{active_arrow} **Active Users:** {active_change:+}\n"
                  f"{xp_arrow} **XP Gained:** {xp_change:+,.0f}",
            inline=False
        )
    
    embed.set_footer(text=f"Next auto-update in #{CONFIG['stats_channel']} • Use !leaderboards for rankings")
    await ctx.send(embed=embed)

@bot.command()
async def weather(ctx, *, location):
    async with ctx.typing():
        data = await fetch_weather(location)
        if isinstance(data, str):
            await ctx.send(f"❌ {data}")
            return
        
        try:
            current = data['current_condition'][0]
            nearest_area = data['nearest_area'][0]
            
            temp_c = current['temp_C']
            feels_like = current['FeelsLikeC']
            humidity = current['humidity']
            wind_speed = current['windspeedKmph']
            wind_dir = current['winddir16Point']
            visibility = current['visibility']
            uv_index = current['uvIndex']
            desc = current['weatherDesc'][0]['value']
            
            area_name = nearest_area['areaName'][0]['value']
            country = nearest_area['country'][0]['value']
            region = nearest_area['region'][0]['value']
            
            weather_emoji = "🌤️"
            desc_lower = desc.lower()
            if "rain" in desc_lower or "drizzle" in desc_lower:
                weather_emoji = "🌧️"
            elif "snow" in desc_lower:
                weather_emoji = "❄️"
            elif "cloud" in desc_lower:
                weather_emoji = "☁️"
            elif "sunny" in desc_lower or "clear" in desc_lower:
                weather_emoji = "☀️"
            elif "thunder" in desc_lower or "storm" in desc_lower:
                weather_emoji = "⛈️"
            elif "fog" in desc_lower or "mist" in desc_lower:
                weather_emoji = "🌫️"
            
            embed = await create_embed(
                f"{weather_emoji} Weather in {area_name}, {country}",
                f"**{desc}**\n"
                f"🌡️ **Temperature:** {temp_c}°C (feels like {feels_like}°C)\n"
                f"💧 **Humidity:** {humidity}%\n"
                f"💨 **Wind:** {wind_speed} km/h {wind_dir}\n"
                f"👁️ **Visibility:** {visibility} km\n"
                f"☀️ **UV Index:** {uv_index}"
            )
            
            if region and region != area_name:
                embed.add_field(name="📍 Region", value=region, inline=True)
            
            if 'weather' in data and len(data['weather']) > 0:
                today = data['weather'][0]
                max_temp = today['maxtempC']
                min_temp = today['mintempC']
                embed.add_field(name="📊 Today's Range", value=f"{min_temp}°C - {max_temp}°C", inline=True)
            
            embed.set_footer(text="Weather data provided by wttr.in")
            await ctx.send(embed=embed)
            
        except KeyError as e:
            logger.error(f"Weather parsing error: {e}")
            await ctx.send("❌ Error parsing weather data.")
        except Exception as e:
            logger.error(f"Weather display error: {e}")
            await ctx.send("❌ An error occurred while displaying weather information.")

@bot.command()
async def events(ctx):
    embed = await create_embed("📅 Current Events", BotState.events_message)
    await ctx.send(embed=embed)

@bot.command()
async def setevents(ctx, *, event_message):
    if ctx.author.name.lower() == CONFIG["admin_user"]:
        BotState.events_message = event_message
        save_data()
        await ctx.send("✅ Events updated successfully.")
    else:
        await ctx.send(f"❌ Only '{CONFIG['admin_user']}' can update events.")

@bot.command()
async def info(ctx):
    guild = ctx.guild
    owner = guild.owner if guild.owner else "N/A"
    created_at = guild.created_at.strftime('%Y-%m-%d %H:%M:%S')
    online_count = sum(1 for m in guild.members if m.status != discord.Status.offline)
    offline_count = sum(1 for m in guild.members if m.status == discord.Status.offline)
    
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    roles = len(guild.roles)
    
    total_xp = sum(BotState.user_xp.values())
    total_voice_time = sum(BotState.user_voice_time.values())
    
    desc = (
        f"👑 **Owner:** {owner}\n"
        f"👥 **Members:** {guild.member_count}\n"
        f"📅 **Created:** {created_at}\n"
        f"🟢 **Online:** {online_count}\n"
        f"⚫ **Offline:** {offline_count}\n"
        f"💬 **Text Channels:** {text_channels}\n"
        f"🔊 **Voice Channels:** {voice_channels}\n"
        f"🎭 **Roles:** {roles}\n"
        f"⚡ **Boost Level:** {guild.premium_tier}\n"
        f"💎 **Boosts:** {guild.premium_subscription_count}\n\n"
        f"📊 **Server Activity:**\n"
        f"💬 **Total Messages Tracked:** {BotState.total_server_messages:,}\n"
        f"⭐ **Total XP Earned:** {total_xp:,.0f}\n"
        f"🔊 **Total Voice Time:** {total_voice_time:,.0f} minutes"
    )
    
    embed = await create_embed(f"ℹ️ Server Info - {guild.name}", desc)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    if guild.banner:
        embed.set_image(url=guild.banner.url)
    await ctx.send(embed=embed)

@bot.command()
async def leaderboards(ctx):
    try:
        if not BotState.user_xp:
            embed = await create_embed("🏆 Leaderboards", "No activity data yet. Start chatting to appear on the leaderboard!")
            await ctx.send(embed=embed)
            return
        
        user_scores = []
        for user_id in BotState.user_xp.keys():
            try:
                score = get_leaderboard_score(user_id)
                if score > 0:
                    user_scores.append((user_id, score))
            except Exception as e:
                logger.error(f"Error calculating score for user {user_id}: {e}")
                continue
        
        if not user_scores:
            embed = await create_embed("🏆 Leaderboards", "No activity data yet. Start chatting to appear on the leaderboard!")
            await ctx.send(embed=embed)
            return
        
        user_scores.sort(key=lambda x: x[1], reverse=True)
        sorted_users = user_scores[:CONFIG["top_talkers_limit"]]
        
        desc_lines = []
        medals = ["🥇", "🥈", "🥉"]
        
        for i, (user_id, score) in enumerate(sorted_users, 1):
            try:
                user = ctx.guild.get_member(user_id)
                if user:
                    level = BotState.user_level.get(user_id, 0)
                    prestige = BotState.user_prestige.get(user_id, 0)
                    xp = BotState.user_xp.get(user_id, 0.0)
                    voice_time = BotState.user_voice_time.get(user_id, 0.0)
                    
                    medal = medals[i-1] if i <= 3 else f"{i}."
                    prestige_text = f" ⭐{prestige}" if prestige > 0 else ""
                    
                    desc_lines.append(
                        f"{medal} **{user.display_name}** - Lv.{level}{prestige_text}\n"
                        f"    💎 {xp:.0f} XP • 🔊 {voice_time:.0f}m • 📊 {score:.0f} total"
                    )
            except Exception as e:
                logger.error(f"Error processing user {user_id} in leaderboard: {e}")
                continue
        
        if not desc_lines:
            embed = await create_embed("🏆 Leaderboards", "No valid users found. Start chatting to appear on the leaderboard!")
            await ctx.send(embed=embed)
            return
        
        embed = await create_embed("🏆 Activity Leaderboards", "\n\n".join(desc_lines))
        embed.add_field(name="📊 Scoring System", 
                       value=f"XP + (Voice minutes × {CONFIG['voice_weight_factor']}) + Prestige bonus", 
                       inline=False)
        embed.set_footer(text="💬 2 XP per message • 🔊 0.3 XP per voice minute")
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Error in leaderboards command: {e}")
        embed = await create_embed("🏆 Leaderboards", "No activity data yet. Start chatting and join voice channels to appear on the leaderboard!")
        await ctx.send(embed=embed)

@bot.command()
async def system(ctx):
    """Shows system resource usage information"""
    try:
        # Get CPU information
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_freq = psutil.cpu_freq()
        cpu_count = psutil.cpu_count()
        
        # Get memory information
        memory = psutil.virtual_memory()
        memory_total = memory.total / (1024 ** 3)  # Convert to GB
        memory_used = memory.used / (1024 ** 3)
        memory_percent = memory.percent
        
        # Get disk information
        disk = psutil.disk_usage('/')
        disk_total = disk.total / (1024 ** 3)
        disk_used = disk.used / (1024 ** 3)
        disk_percent = disk.percent
        
        # Get network information
        net_io = psutil.net_io_counters()
        bytes_sent = net_io.bytes_sent / (1024 ** 2)  # Convert to MB
        bytes_recv = net_io.bytes_recv / (1024 ** 2)
        
        embed = discord.Embed(
            title="🖥️ System Resource Usage",
            color=CONFIG['embed_color']
        )
        
        # CPU Section
        cpu_info = (
            f"Usage: {cpu_percent}%\n"
            f"Cores: {cpu_count}\n"
            f"Frequency: {cpu_freq.current:.1f} MHz"
        )
        embed.add_field(name="📊 CPU", value=cpu_info, inline=False)
        
        # Memory Section
        memory_info = (
            f"Usage: {memory_percent}%\n"
            f"Used: {memory_used:.1f} GB\n"
            f"Total: {memory_total:.1f} GB"
        )
        embed.add_field(name="💾 Memory", value=memory_info, inline=False)
        
        # Disk Section
        disk_info = (
            f"Usage: {disk_percent}%\n"
            f"Used: {disk_used:.1f} GB\n"
            f"Total: {disk_total:.1f} GB"
        )
        embed.add_field(name="💿 Disk", value=disk_info, inline=False)
        
        # Network Section
        network_info = (
            f"Sent: {bytes_sent:.1f} MB\n"
            f"Received: {bytes_recv:.1f} MB"
        )
        embed.add_field(name="🌐 Network", value=network_info, inline=False)
        
        # Add process info
        process = psutil.Process()
        bot_memory = process.memory_info().rss / (1024 * 1024)  # Convert to MB
        bot_cpu = process.cpu_percent()
        bot_info = (
            f"Memory Usage: {bot_memory:.1f} MB\n"
            f"CPU Usage: {bot_cpu}%"
        )
        embed.add_field(name="🤖 Bot Process", value=bot_info, inline=False)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ Error getting system information: {e}")

@bot.command()
async def profile(ctx, member: discord.Member = None):
    user = member or ctx.author
    user_id = user.id
    
    xp = BotState.user_xp.get(user_id, 0.0)
    level = BotState.user_level.get(user_id, 0)
    prestige = BotState.user_prestige.get(user_id, 0)
    voice_time = BotState.user_voice_time.get(user_id, 0.0)
    messages = BotState.user_message_count.get(user_id, 0)
    streak = BotState.user_daily_streak.get(user_id, 0)
    rank = get_user_rank(user_id)
    
    progress, next_req = get_progress_in_level(xp, level)
    achievements = BotState.user_achievements.get(user_id, set())
    
    prestige_text = f" ⭐{prestige}" if prestige > 0 else ""
    
    embed = await create_embed(
        f"👤 {user.display_name}'s Profile{prestige_text}",
        f"🏆 **Level:** {level}{prestige_text}\n"
        f"💎 **Total XP:** {xp:,.0f}\n"
        f"📊 **Progress:** {progress:.0f}/{next_req:.0f} XP\n"
        f"🥇 **Server Rank:** #{rank}\n"
        f"💬 **Messages:** {messages:,}\n"
        f"🔊 **Voice Time:** {voice_time:.0f} minutes\n"
        f"🔥 **Current Streak:** {streak} days\n"
        f"📅 **Joined:** {user.joined_at.strftime('%Y-%m-%d') if user.joined_at else 'Unknown'}"
    )
    
    if next_req > 0:
        percent = (progress / next_req) * 100
        progress_bar_length = 20
        filled_length = int(progress_bar_length * percent // 100)
        bar = "█" * filled_length + "░" * (progress_bar_length - filled_length)
        embed.add_field(name="📈 Level Progress", value=f"`{bar}` {percent:.1f}%", inline=False)
    
    if achievements:
        achievement_list = []
        for ach_id in achievements:
            if ach_id in ACHIEVEMENTS:
                ach = ACHIEVEMENTS[ach_id]
                achievement_list.append(f"{ach['emoji']} {ach['name']}")
        
        if achievement_list:
            embed.add_field(name="🏅 Achievements", value="\n".join(achievement_list[:5]), inline=False)
            if len(achievement_list) > 5:
                embed.add_field(name="", value=f"+ {len(achievement_list) - 5} more...", inline=False)
    
    if user.avatar:
        embed.set_thumbnail(url=user.avatar.url)
    
    await ctx.send(embed=embed)

# Moderation commands
@bot.command()
@commands.has_permissions(manage_messages=True)
async def lock(ctx):
    BotState.locked_channels.add(ctx.channel.id)
    await ctx.send("🔒 This channel has been locked. Only staff can send messages.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def unlock(ctx):
    BotState.locked_channels.discard(ctx.channel.id)
    await ctx.send("🔓 This channel has been unlocked.")

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if member == ctx.author:
        await ctx.send("❌ You cannot kick yourself.")
        return
    if member.top_role >= ctx.author.top_role:
        await ctx.send("❌ You cannot kick someone with equal or higher role.")
        return
    try:
        await member.kick(reason=f"Kicked by {ctx.author}: {reason}")
        embed = await create_embed("👢 Member Kicked", f"✅ {member.mention} has been kicked.\n📝 **Reason:** {reason}")
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error kicking member: {e}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    if member == ctx.author:
        await ctx.send("❌ You cannot ban yourself.")
        return
    if member.top_role >= ctx.author.top_role:
        await ctx.send("❌ You cannot ban someone with equal or higher role.")
        return
    try:
        await member.ban(reason=f"Banned by {ctx.author}: {reason}")
        embed = await create_embed("🔨 Member Banned", f"✅ {member.mention} has been banned.\n📝 **Reason:** {reason}")
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error banning member: {e}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def softban(ctx, member: discord.Member, *, reason="No reason provided"):
    if member == ctx.author:
        await ctx.send("❌ You cannot softban yourself.")
        return
    if member.top_role >= ctx.author.top_role:
        await ctx.send("❌ You cannot softban someone with equal or higher role.")
        return
    try:
        await member.ban(reason=f"Softbanned by {ctx.author}: {reason}", delete_message_days=7)
        await ctx.guild.unban(member, reason="Softban - unban")
        embed = await create_embed("🔨 Member Softbanned", f"✅ {member.mention} has been softbanned.\n📝 **Reason:** {reason}")
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error softbanning member: {e}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def tempban(ctx, member: discord.Member, duration: int, *, reason="No reason provided"):
    if member == ctx.author:
        await ctx.send("❌ You cannot ban yourself.")
        return
    if member.top_role >= ctx.author.top_role:
        await ctx.send("❌ You cannot ban someone with equal or higher role.")
        return
    try:
        await member.ban(reason=f"Temp banned by {ctx.author}: {reason}")
        embed = await create_embed("⏰ Member Temporarily Banned", 
                                 f"✅ {member.mention} has been banned for {duration} seconds.\n📝 **Reason:** {reason}")
        await ctx.send(embed=embed)
        
        await asyncio.sleep(duration)
        await ctx.guild.unban(member, reason=f"Temporary ban expired")
        
    except Exception as e:
        await ctx.send(f"❌ Error temp banning member: {e}")

@bot.command(hidden=True)
async def purge_self(ctx, amount: int = 10):
    if ctx.author.name.lower() != CONFIG["admin_user"]:
        return
    
    if amount > 100:
        await ctx.send("❌ Cannot purge more than 100 messages at once.", delete_after=5)
        return
        
    def is_bot_message(m):
        return m.author == bot.user
    
    try:
        deleted = await ctx.channel.purge(limit=amount, check=is_bot_message)
        await ctx.send(f"✅ Purged {len(deleted)} bot messages.", delete_after=5)
    except Exception as e:
        await ctx.send(f"❌ Error purging messages: {e}", delete_after=5)

# Auto-save task
@tasks.loop(minutes=5)
async def auto_save():
    save_data()
    logger.info("Auto-saved data")

# Bot events
@bot.event
async def on_disconnect():
    """Handle disconnection from Discord"""
    logger.warning("Bot disconnected from Discord. Waiting for automatic reconnection...")
    # Let discord.py handle reconnection automatically. No manual connect() call needed.

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Handle DM to general chat relay
    if isinstance(message.channel, discord.DMChannel):
        if message.author.name.lower() != CONFIG["admin_user"]:
            await message.channel.send("❌ Sorry, only the bot administrator can use DM commands.")
            return
            
        content = message.content.strip()
        if content.startswith('!speak '):
            speak_message = content[7:]  # Remove !speak prefix
            if speak_message:  # Check if there's a message after !speak
                for guild in bot.guilds:
                    general_channel = discord.utils.get(guild.text_channels, name="general")
                    if general_channel:
                        # Format the message to indicate it's from admin
                        await general_channel.send(f"� **Announcement from {message.author.name}**: {speak_message}")
                await message.channel.send("✅ Message sent to general chat!")
            else:
                await message.channel.send("❌ Please include a message after !speak")
        return
    
    # Process commands and continue with regular message handling
    await bot.process_commands(message)

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    load_data()
    
    # Start the auto-save task if not already running
    if not auto_save.is_running():
        auto_save.start()
        logger.info("Started auto-save task")
    
    # Start the daily stats posting task
    if not post_daily_stats.is_running():
        post_daily_stats.start()
        logger.info(f"Started daily stats posting task (every {CONFIG['stats_update_hours']} hours)")
    
    activity = discord.Activity(type=discord.ActivityType.watching, name="you")
    await bot.change_presence(activity=activity)

@bot.event
async def on_member_join(member):
    # Update daily stats for new member
    update_daily_stats(None, new_member=True)
    
    channel = discord.utils.get(member.guild.channels, name=CONFIG["greeting_channel"])
    if channel:
        embed = await create_embed(
            f"Welcome to {member.guild.name}! 👋",
            f"Hello {member.mention}! Welcome to our server.\n\n"
            f"📝 Make sure to read the rules\n"
            f"💬 Introduce yourself in the chat\n"
            f"🎉 Have fun and enjoy your stay!\n\n"
            f"Type `!help` to see available commands.\n"
            f"🎮 Start earning XP by chatting and joining voice channels!"
        )
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
        await channel.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    # Check if channel is locked
    if message.channel.id in BotState.locked_channels:
        if not message.author.guild_permissions.manage_messages:
            await message.delete()
            return
    
    # Handle DM commands for status functionality
    if isinstance(message.channel, discord.DMChannel):
        if message.author.id == CONFIG["admin_user_id"]:
            content = message.content.lower().strip()
            
            # Status change commands
            if content.startswith('status '):
                parts = message.content[7:].split(' ', 1)
                if len(parts) == 2:
                    status_type, status_text = parts
                    status_type = status_type.lower()
                    
                    if status_type in CONFIG["status_types"]:
                        try:
                            activity = discord.Activity(
                                type=CONFIG["status_types"][status_type],
                                name=status_text
                            )
                            await bot.change_presence(activity=activity)
                            await message.channel.send(f"✅ Status changed to: **{status_type.capitalize()} {status_text}**")
                        except Exception as e:
                            await message.channel.send(f"❌ Error changing status: {e}")
                    else:
                        valid_types = ", ".join(CONFIG["status_types"].keys())
                        await message.channel.send(f"❌ Invalid status type. Use one of: {valid_types}\nExample: `status playing Minecraft`")
                else:
                    await message.channel.send("❌ Invalid format. Use: `status <type> <text>`\nExample: `status listening to music`")
            
            # Reset to default status
            elif content == 'status reset':
                try:
                    activity = discord.Activity(type=discord.ActivityType.watching, name="the server")
                    await bot.change_presence(activity=activity)
                    await message.channel.send("✅ Status reset to default")
                except Exception as e:
                    await message.channel.send(f"❌ Error resetting status: {e}")
            
            # Help command for status controls
            elif content == 'status help':
                embed = discord.Embed(title="🤖 Bot Status Controls", color=CONFIG['embed_color'])
                embed.description = "Change the bot's status from DMs (Admin only)"
                embed.add_field(
                    name="Available Commands",
                    value="• `status <type> <text>` - Change status\n"
                          "• `status reset` - Reset to default\n"
                          "• `status help` - Show this help",
                    inline=False
                )
                embed.add_field(
                    name="Status Types",
                    value="• `playing` - Playing a game\n"
                          "• `listening` - Listening to something\n"
                          "• `watching` - Watching something\n"
                          "• `streaming` - Streaming (add URL if needed)\n"
                          "• `competing` - Competing in something",
                    inline=False
                )
                embed.add_field(
                    name="Examples",
                    value="• `status playing Minecraft`\n"
                          "• `status listening to lofi`\n"
                          "• `status watching the chat`\n"
                          "• `status competing in tournament`",
                    inline=False
                )
                await message.channel.send(embed=embed)
            
            return
    
    # XP and message tracking for guild messages only
    if message.guild:
        current_time = time.time()
        user_id = message.author.id
        last_message_time = BotState.user_last_message.get(user_id, 0)
        
        # Track total server messages
        BotState.total_server_messages += 1
        
        # Award first message achievement
        if user_id not in BotState.user_message_count:
            award_achievement(user_id, "first_message")
        
        # XP cooldown check
        if current_time - last_message_time >= CONFIG["antispam_cooldown_sec"]:
            xp_gained = calculate_message_xp(user_id)
            leveled_up, new_level, prestiged = add_xp(user_id, xp_gained)
            
            BotState.user_message_count[user_id] = BotState.user_message_count.get(user_id, 0) + 1
            BotState.user_last_message[user_id] = current_time
            
            # Update daily stats
            update_daily_stats(user_id, messages=1, xp=xp_gained)
            
            # Prestige notification
            if prestiged:
                prestige_level = BotState.user_prestige.get(user_id, 0)
                embed = await create_embed(
                    "🌟 PRESTIGE ACHIEVED! 🌟",
                    f"🎊 {message.author.mention} has achieved **Prestige {prestige_level}**!\n"
                    f"⭐ Your journey begins anew with ultimate bragging rights! ⭐"
                )
                embed.set_color(0xFFD700)
                await message.channel.send(embed=embed, delete_after=15)
            
            # Level up notification
            elif leveled_up:
                milestone_msg = ""
                if new_level == 10:
                    milestone_msg = "\n🎯 First milestone reached!"
                elif new_level == 25:
                    milestone_msg = "\n🚀 Quarter century!"
                elif new_level == 49:
                    milestone_msg = "\n⚠️ One level away from Prestige!"
                
                embed = await create_embed(
                    "🎉 Level Up!",
                    f"{message.author.mention} reached **Level {new_level}**! 🎊{milestone_msg}"
                )
                await message.channel.send(embed=embed, delete_after=10)
            
            # Show bonus XP reaction
            elif xp_gained > CONFIG["base_message_xp"] * 1.5:
                if random.random() < 0.3:
                    await message.add_reaction("✨")
            
            # Check for top 3 achievement
            rank = get_user_rank(user_id)
            if rank <= 3:
                achievements = BotState.user_achievements.get(user_id, set())
                if "top_3" not in achievements:
                    award_achievement(user_id, "top_3")

    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    user_id = member.id
    current_time = time.time()
    
    # User joined voice channel
    if before.channel is None and after.channel is not None:
        BotState.voice_start_times[user_id] = current_time
    
    # User left voice channel
    elif before.channel is not None and after.channel is None:
        if user_id in BotState.voice_start_times:
            start_time = BotState.voice_start_times.pop(user_id)
            duration_minutes = (current_time - start_time) / 60
            
            # Only give XP if in voice for at least 1 minute
            if duration_minutes >= 1.0:
                xp_gained = duration_minutes * CONFIG["voice_xp_per_minute"]
                leveled_up, new_level, prestiged = add_xp(user_id, xp_gained)
                
                # Update voice time tracking
                BotState.user_voice_time[user_id] = BotState.user_voice_time.get(user_id, 0.0) + duration_minutes
                
                # Update daily stats
                update_daily_stats(user_id, xp=xp_gained, voice_time=duration_minutes)
                
                # Prestige notification
                if prestiged:
                    prestige_level = BotState.user_prestige.get(user_id, 0)
                    guild = member.guild
                    channel = discord.utils.get(guild.channels, name="general") or guild.system_channel
                    if channel:
                        embed = await create_embed(
                            "🌟 PRESTIGE ACHIEVED! 🌟",
                            f"🎊 {member.mention} achieved **Prestige {prestige_level}** from voice activity!\n"
                            f"⭐ Your journey begins anew with ultimate bragging rights! ⭐"
                        )
                        embed.set_color(0xFFD700)
                        await channel.send(embed=embed, delete_after=15)
                
                # Level up notification
                elif leveled_up:
                    guild = member.guild
                    channel = discord.utils.get(guild.channels, name="general") or guild.system_channel
                    if channel:
                        embed = await create_embed(
                            "🎉 Level Up!",
                            f"{member.mention} reached **Level {new_level}** from voice activity! 🎊"
                        )
                        await channel.send(embed=embed, delete_after=10)

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Member not found.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Invalid argument provided.")
    elif isinstance(error, commands.CommandNotFound):
        return
    else:
        logger.error(f"Command error: {error}")
        await ctx.send("❌ An error occurred while executing the command.")

# Graceful shutdown
def signal_handler(signum, frame):
    logger.info("Received shutdown signal, saving data...")
    save_data()
    loop = asyncio.get_event_loop()
    loop.create_task(bot.close())

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Run the bot
async def main():
    try:
        await bot.start(CONFIG["token"])
    except Exception as e:
        logger.error(f"Bot failed to start: {e}")
    finally:
        if BotState.session:
            await BotState.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested")
    finally:
        save_data()
        logger.info("Bot shutdown complete")
        