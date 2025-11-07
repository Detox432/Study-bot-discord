import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import logging
import sqlite3
import json
import asyncio
import signal
import sys
import atexit

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

DB_PATH = "entries.db"
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("""
  CREATE TABLE IF NOT EXISTS daily (
    date TEXT,
    user_id INTEGER,
    seconds REAL,
    PRIMARY KEY (date, user_id)
  )
""")

c.execute("""
CREATE TABLE IF NOT EXISTS bot_state (
key TEXT PRIMARY KEY,
value TEXT
)
""")

conn.commit()

handler = logging.FileHandler(filename="debug.log", encoding='utf-8', mode = 'w')
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

users_list = {}
weekly_entries = {}
embed_messages = {}
daily_goals = {}
channel_id = 
simulated_offset = 0

current_date = datetime.now().date()

def save_bot_state():
    """Save current bot state to database"""
    try:

        c.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", 
                 ("users_list", json.dumps(users_list, default=str)))
        

        c.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", 
                 ("daily_goals", json.dumps(daily_goals)))
        

        c.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", 
                 ("current_date", current_date.isoformat()))
        c.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", 
                 ("simulated_offset", str(simulated_offset)))
        
        conn.commit()
        print("✅ Bot state saved to database")
    except Exception as e:
        print(f"❌ Error saving bot state: {e}")

def load_bot_state():
    """Load bot state from database"""
    global users_list, daily_goals, current_date, simulated_offset
    
    try:

        result = c.execute("SELECT value FROM bot_state WHERE key = ?", ("users_list",)).fetchone()
        if result:
            loaded_users = json.loads(result[0])
            # Convert datetime strings back to datetime objects
            for uid, data in loaded_users.items():
                if isinstance(data.get('Start'), str) and data['Start'] != 'Paused':
                    try:
                        data['Start'] = datetime.fromisoformat(data['Start'])
                    except:
                        data['Start'] = 'Paused'
                if isinstance(data.get('Since'), str):
                    try:
                        data['Since'] = datetime.fromisoformat(data['Since'])
                    except:
                        data['Since'] = datetime.now()
            users_list = {int(k): v for k, v in loaded_users.items()}
        

        result = c.execute("SELECT value FROM bot_state WHERE key = ?", ("daily_goals",)).fetchone()
        if result:
            daily_goals = {int(k): v for k, v in json.loads(result[0]).items()}
        

        result = c.execute("SELECT value FROM bot_state WHERE key = ?", ("current_date",)).fetchone()
        if result:
            current_date = datetime.fromisoformat(result[0]).date()
        
        # Load simulated_offset
        result = c.execute("SELECT value FROM bot_state WHERE key = ?", ("simulated_offset",)).fetchone()
        if result:
            simulated_offset = int(result[0])
            
        print("✅ Bot state loaded from database")
    except Exception as e:
        print(f"❌ Error loading bot state: {e}")


@bot.command()
async def goal(ctx, hours: float):
    secs = int(hours * 3600)
    daily_goals[ctx.author.id] = secs

    if ctx.author.id in users_list:
        users_list[ctx.author.id]['Goal'] = secs

    await ctx.send(f"{ctx.author.display_name}, daily goal set to {hours} hour(s).")


@tasks.loop(seconds=15)
async def check_date_change():
    global current_date, simulated_offset
    simulated_now = datetime.now().date() + timedelta(days=simulated_offset)
    if simulated_now != current_date:
        old_date = current_date.isoformat()
        current_date = simulated_now

        daily_totals = {}
        for uid, data in users_list.items():
            total = data['total']
            if isinstance(data['Start'], datetime):
                total += (datetime.now() - data['Start']).total_seconds()
            daily_totals[uid] = total

        SaveDaily(old_date, daily_totals)
        await send_daily_summary(old_date, daily_totals)
        weekly_entries[old_date] = daily_totals
        users_list.clear()
        embed_messages.clear()
        save_bot_state()

        if len(weekly_entries) == 7:
            await send_weekly_result()

def make_progress_bar(current, goal, length=10):
    pct = min(current / goal, 1.0) if goal > 0 else 0
    filled = int(pct * length)
    bar = '▰' * filled + '▱' * (length - filled)
    return f"{bar}  {int(pct * 100)}%"


def SaveDaily(date, daily_totals):
    for uid, secs in daily_totals.items():
        c.execute("""
          INSERT OR REPLACE INTO daily (date, user_id, seconds)
          VALUES (?, ?, ?)
        """, (date, uid, secs))
    conn.commit()
    print(f"✅ Saved daily data for {date} into SQLite")

def load_weekly_from_db():
    """Load last 7 calendar days into weekly_entries."""
    global weekly_entries
    weekly_entries = {}
    c.execute("""
      SELECT date, user_id, seconds
      FROM daily
      WHERE date >= date('now','-6 days')
      ORDER BY date ASC
    """)
    for date_str, uid, secs in c.fetchall():
        weekly_entries.setdefault(date_str, {})[uid] = secs
    print(f"✅ Loaded {len(weekly_entries)} days from SQLite")

def WeeklyResult():
    pass



def UpdateTotal(user):
    user_id = user.id
    if user_id in users_list and isinstance(users_list[user_id]['Start'], datetime):
        elapsed = (datetime.now() - users_list[user_id]['Start']).total_seconds()
        users_list[user_id]['total'] += elapsed
        users_list[user_id]['Start'] = 'Paused'
    else:
        print("ERROR UPDATING")


def format_time(seconds):
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


@tasks.loop(hours=24)
async def daily_reset():
    pass

async def create_embed_message(user, total_seconds, goal, is_paused=False):
    

    embed = discord.Embed(
        title="🎯 Study Session",
        description=f"*by {user.display_name}*",
        color=0x00ff00 if not is_paused else 0xff9900
    )
    elapsed_str = format_time(total_seconds)  
    embed.add_field(
        name="⏱️ Time Elapsed",
        value=elapsed_str,
        inline=False
    )
    
    embed.add_field(
        name=f"📊 Daily Goal ({format_time(goal)})",
        value=make_progress_bar(total_seconds, goal),
        inline=False
    )

    since_ts = users_list[user.id]['Since']
    status_text = "🟢 Active" if not is_paused else "🟠 Paused"
    embed.add_field(
        name="Status & Since",
        value=f"{status_text}\nSince: {since_ts.strftime('%Y-%m-%d %H:%M')}",
        inline=False
    )

    embed.set_footer(text="⏸️ Pause • ▶️ Resume • 📊 Stats • 🎯 Set Goal")

    return embed


@tasks.loop(seconds=1)
async def update_embed_message():
    for user_id, msg_data in list(embed_messages.items()):
        if user_id not in users_list:
            continue

        udata = users_list[user_id]
        msg = msg_data['message']
        user = msg_data['user']
        goal = udata.get('Goal', 2 * 3600)


        is_paused = not isinstance(udata['Start'], datetime)


        total_time = udata['total']
        if not is_paused:
            total_time += (datetime.now() - udata['Start']).total_seconds()


        curr_seconds = int(total_time)

        last_seconds, last_paused = udata.get('last_state', (-1, None))

        # Only update if seconds changed or paused status changed
        if curr_seconds != last_seconds or is_paused != last_paused:
            # Save new state
            udata['last_state'] = (curr_seconds, is_paused)

            embed = await create_embed_message(user, total_time, goal, is_paused)
            try:
                await msg.edit(embed=embed)
            except discord.NotFound:
                del embed_messages[user_id]
            except discord.HTTPException:
                # Rate limited; skip this update
                pass

@bot.command()
async def study(ctx):
    user = ctx.author
    if user.voice and user.voice.channel:
        if user.id not in users_list:
            users_list[user.id] = {
                'Start': datetime.now(),
                'Since': datetime.now(), 
                'total': 0, 
                'Goal': daily_goals.get(user.id, 2*3600)
            }
            await ctx.send(f"🎯 {ctx.author.display_name} has started studying! @everyone")
        else:
            if users_list[user.id]['Start'] == 'Paused':
                users_list[user.id]['Start'] = datetime.now()
                users_list[user.id]['Since'] = datetime.now()
                await ctx.send(f"{ctx.author.display_name} has resumed studying!")
            else:
                await ctx.send("Your study session is already active!")
        
        total_time = users_list[user.id]['total']
        if isinstance(users_list[user.id]['Start'], datetime):
            total_time += (datetime.now() - users_list[user.id]['Start']).total_seconds()
            
        embed = await create_embed_message(user, total_time, users_list[user.id].get('Goal'), 
                                         users_list[user.id]['Start'] == 'Paused')
        msg = await ctx.send(embed=embed)
        
        for emoji in ["⏸️", "▶️", "📊"]:
            await msg.add_reaction(emoji)
            
        embed_messages[user.id] = {'message': msg, 'user': user}
        
    else:
        await ctx.send("YOU NEED TO BE CONNECTED TO A VOICE CHANNEL")

@bot.event
async def on_reaction_add(reaction, user):
    #checking if reaction is from bot
    if user.bot:                   
        return
    if user.id in embed_messages and reaction.message.id == embed_messages[user.id]['message'].id:
        emoji = str(reaction.emoji)
        if emoji == "⏸️":  
            if users_list[user.id]['Start'] != "Paused":
                UpdateTotal(user)
                await reaction.message.channel.send(f"⏸️ {user.display_name}'s timer paused.")

        elif emoji == "▶️":  
            if users_list[user.id]['Start'] == "Paused":
                users_list[user.id]['Start'] = datetime.now()
                await reaction.message.channel.send(f"▶️ {user.display_name}'s timer resumed.")

        elif emoji == "📊":  
            total_sec = users_list[user.id]['total']
            if isinstance(users_list[user.id]['Start'], datetime):
                total_sec += (datetime.now() - users_list[user.id]['Start']).total_seconds()
            await reaction.message.channel.send(
                f"📊 {user.display_name}: {int(total_sec//3600)}h {int((total_sec%3600)//60)}m"
            )

        try:
            await reaction.remove(user)
        except:
            pass

@bot.command()
async def resume(ctx):
    user = ctx.author
    if user.voice and user.voice.channel:
        if user.id in users_list and users_list[user.id]['Start'] == 'Paused':
            users_list[user.id]['Start'] = datetime.now()
            await ctx.send(f"▶️ {user.display_name}'s timer resumed.")
        else:
            await ctx.send(f"▶️ {user.display_name}'s timer is already running.")
    else:
        await ctx.send("YOU NEED TO BE CONNECTED TO A VOICE CHANNEL")

@bot.command()
async def pause(ctx):
    user = ctx.author
    if user.voice and user.voice.channel:
        if user.id in users_list and users_list[user.id]['Start'] != 'Paused':
            UpdateTotal(user)
            await ctx.send(f"⏸️ {user.display_name}'s timer paused.")
        else:
            await ctx.send(f"⏸️ {user.display_name}'s timer is already paused.")
    else:
        await ctx.send("YOU NEED TO BE CONNECTED TO A VOICE CHANNEL")

@bot.command()
async def display(ctx):
    user = ctx.author
    if user.id in users_list:
        total_sec = users_list[user.id]['total']
        if isinstance(users_list[user.id]['Start'], datetime):
            total_sec += (datetime.now() - users_list[user.id]['Start']).total_seconds()
        
        hours = int(total_sec // 3600)
        mins = int((total_sec % 3600) // 60)
        await ctx.send(f"📊 {user.display_name}: {hours} hours {mins} minutes")
    else:
        await ctx.send("NO RECORD FOUND")

@bot.command()
async def status(ctx):
    user = ctx.author
    if user.id in users_list:
        await ctx.send(users_list[user.id])

@bot.command()
async def skiptime(ctx, days: int = 1):
    """
    Advance the simulated date by `days`.
    Use this to trigger daily reset logic immediately.
    """
    global simulated_offset
    simulated_offset += days
    await ctx.send(f"⏭️ Simulated time advanced by {days} day(s).")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    load_bot_state()
    load_weekly_from_db()
    update_embed_message.start()
    check_date_change.start()
    await bot.get_channel(channel_id).send(f"17vi is here, type !info for more information. @everyone")


@bot.event
async def on_voice_state_update(user, before, after):
    if user.id in users_list and isinstance(users_list[user.id]['Start'], datetime):
        if before.channel is not None and after.channel is None:
            UpdateTotal(user)
            if user.id  in embed_messages:
                channel = embed_messages[user.id]['message'].channel
                await channel.send(f"You have left the voice channel, so your time has been PAUSED, join a voice channel and type !resume to continue.")

async def send_daily_summary(date_str, daily_totals):
    lines = [f"**Study Summary for {date_str}**"]
    for uid, secs in daily_totals.items():
        user = await bot.fetch_user(uid)
        hours = int(secs // 3600)
        mins  = int((secs % 3600) // 60)
        lines.append(f"• {user.display_name}: {hours}h {mins}m")
    channel = bot.get_channel(channel_id)
    await channel.send("\n".join(lines))

async def send_weekly_result():
    week_total = {}
    for data in weekly_entries.values():
        for uid, seconds in data.items():
            week_total[uid] = week_total.get(uid, 0) + seconds   #checks if uid exists, if it doesnt returns 0 instead of None
    winner_id, winner_secs = max(week_total.items(), key=lambda kv: kv[1])
    winner = await bot.fetch_user(winner_id)
    lines = ["**Weekly Winner**"]
    hours = int(winner_secs // 3600)
    mins  = int((winner_secs % 3600) // 60)
    lines.append(f"🏅 {winner.display_name}: {hours}h {mins}m")
    lines.append("\n**Full Weekly Standings:**")
    for uid, secs in week_total.items():
        user = await bot.fetch_user(uid)
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        lines.append(f"• {user.display_name}: {h}h {m}m")
    channel = bot.get_channel(channel_id)
    await channel.send("\n".join(lines))
    
    with open("history.txt","a") as f:
        f.write(f"{datetime.now().date()} | Winner: {winner.display_name} {hours}h{mins}m\n")
        for uid, secs in week_total.items():
            user = await bot.fetch_user(uid)
            h = int(secs // 3600)
            m = int((secs % 3600) // 60)
            f.write(f"  {user.display_name}: {h}h{m}m\n")
        f.write("\n")

    weekly_entries.clear() #clears the weekly data, after saving it in history.txt

@bot.command()
async def daily(ctx):
    # Build current daily totals
    daily_totals = {}
    for uid, data in users_list.items():
        secs = data["total"]
        if isinstance(data["Start"], datetime):
            secs += (datetime.now() - data["Start"]).total_seconds()
        daily_totals[uid] = secs

    if not daily_totals:
        return await ctx.send("No study data for today yet.")

    lines = [f"**Today's Standings ({current_date.isoformat()}):**"]
    for uid, secs in daily_totals.items():
        user = await bot.fetch_user(uid)
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        lines.append(f"• {user.display_name}: {h}h {m}m")

    msg = "\n".join(lines)
    for chunk in [msg[i:i+2000] for i in range(0, len(msg), 2000)]:
        await ctx.send(chunk)
@bot.command()
async def weekly(ctx):
    if not weekly_entries:
        return await ctx.send("No weekly data available yet.")

    lines = ["**Weekly Standings:**"]

    for date_str in sorted(weekly_entries):
        lines.append(f"\n__{date_str}__")
        for uid, secs in weekly_entries[date_str].items():
            user = await bot.fetch_user(uid)
            h = int(secs // 3600)
            m = int((secs % 3600) // 60)
            lines.append(f"• {user.display_name}: {h}h {m}m")

    msg = "\n".join(lines)
    for chunk in [msg[i:i+2000] for i in range(0, len(msg), 2000)]:
        await ctx.send(chunk)
@bot.command()
async def addtime(ctx, time: float=0.0):
    user = ctx.author
    if user.id in users_list:
        users_list[user.id]['total'] += time*3600
        await ctx.send(f"{time} hours have been added to your study time.")
    else:
        await ctx.send("You need to have atleast one study session to add time.")
@bot.command()
async def info(ctx):
    """Display information about all available commands"""
    embed = discord.Embed(
        title="📚 Study Bot Commands",
        description="Here are all the commands you can use:",
        color=0x3498db
    )
    
    embed.add_field(
        name="🎯 !study",
        value="Start a new study session or resume/refresh an existing one. Requires being in a voice channel.",
        inline=False
    )
    
    embed.add_field(
        name="⏸️ !pause",
        value="Pause your currently active study session. Time will stop counting.",
        inline=False
    )
    
    embed.add_field(
        name="▶️ !resume", 
        value="Resume your paused study session. Time will continue counting.",
        inline=False
    )
    
    embed.add_field(
        name="📊 !display",
        value="Display your current total study time for today.",
        inline=False
    )
    
    embed.add_field(
        name="📈 !daily",
        value="View today's study standings showing all users' study times.",
        inline=False
    )
    
    embed.add_field(
        name="📅 !weekly", 
        value="View this week's study standings across all days.",
        inline=False
    )
    
    embed.add_field(
        name="🎯 !goal <hours>",
        value="Set your daily study goal in hours (e.g., !goal 3.5). Default is 2 hours.",
        inline=False
    )
    
    embed.add_field(
        name="⏰ !addtime <hours>",
        value="Manually add time to your study session (e.g., !addtime 1.5 for 1.5 hours).",
        inline=False
    )
    
    embed.set_footer(text="Use reactions on study embeds for quick controls!")
    await ctx.send(embed=embed)


def save_and_exit(sig=None, frame=None):
    """Save bot state and exit gracefully"""
    print('\nSaving bot state before shutdown...')
    save_bot_state()
    print('Bot state saved successfully!')
    sys.exit(0)

signal.signal(signal.SIGINT, save_and_exit)
signal.signal(signal.SIGTERM, save_and_exit)
atexit.register(save_bot_state)

@bot.event
async def on_disconnect():
    save_bot_state()
    print("💾 Bot state saved on disconnect")

if __name__ == "__main__":
    try:
        bot.run(token, log_handler=handler, log_level=logging.DEBUG )
    finally: 

        save_bot_state()
