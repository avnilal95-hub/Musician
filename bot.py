import discord
from discord.ext import commands, tasks
import os
import logging
import itertools
import traceback

# ---------------------------------------------------------
# 1. ADVANCED LOGGING SETUP
# ---------------------------------------------------------
# This ensures Railway captures detailed, professional logs.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("BotMaster")

# ---------------------------------------------------------
# 2. MASTER BOT CLASS
# ---------------------------------------------------------
class AdvancedMusicBot(commands.Bot):
    def __init__(self):
        # Setting up privileged intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True 
        intents.voice_states = True
        
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents,
            help_command=commands.MinimalHelpCommand(),
            case_insensitive=True
        )
        
        # Define the rotating activities
        self.presence_cycle = itertools.cycle([
            discord.Activity(type=discord.ActivityType.listening, name="Spotify & Commands"),
            discord.Activity(type=discord.ActivityType.watching, name="over the server"),
            discord.Streaming(name="24/7 Lo-Fi Beats", url="https://twitch.tv/monstercat"),
            discord.Game(name="with Cogs & Python")
        ])

    # ---------------------------------------------------------
# 3. DYNAMIC COG LOADER (The "Manager")
# ---------------------------------------------------------
    async def setup_hook(self):
        logger.info("Initializing Master setup_hook...")
        
        # Ensure the cogs directory exists
        if not os.path.exists('./cogs'):
            os.makedirs('./cogs')
            logger.warning("Created 'cogs' directory. Please place your command files there.")

        # Dynamically load all .py files in the /cogs folder
        loaded_cogs = 0
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and not filename.startswith('__'):
                cog_name = f"cogs.{filename[:-3]}"
                try:
                    await self.load_extension(cog_name)
                    logger.info(f"[+] Successfully loaded cog: {filename}")
                    loaded_cogs += 1
                except Exception as e:
                    logger.error(f"[-] Failed to load cog {filename}:\n{traceback.format_exc()}")
        
        logger.info(f"Finished loading {loaded_cogs} cogs.")
        
        # Start the background task for dynamic status
        self.change_status.start()

# ---------------------------------------------------------
# 4. BACKGROUND TASKS & EVENTS
# ---------------------------------------------------------
    @tasks.loop(seconds=6)
    async def change_status(self):
        """Cycles the bot's rich presence every 3 minutes."""
        new_presence = next(self.presence_cycle)
        await self.change_presence(status=discord.Status.online, activity=new_presence)
        logger.info(f"Changed presence to: {new_presence.type.name} {new_presence.name}")

    @change_status.before_loop
    async def before_change_status(self):
        """Waits for the bot to be fully ready before starting the status loop."""
        await self.wait_until_ready()

    async def on_ready(self):
        logger.info("="*40)
        logger.info(f"Bot successfully logged in as: {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} servers.")
        logger.info("="*40)

# ---------------------------------------------------------
# 5. EMBED-RICH GLOBAL ERROR HANDLER
# ---------------------------------------------------------
    async def on_command_error(self, ctx, error):
        # Ignore commands that don't exist
        if isinstance(error, commands.CommandNotFound):
            return

        # Create a rich embed for errors
        embed = discord.Embed(
            title="⚠️ Command Execution Error",
            color=discord.Color.brand_red(),
            timestamp=discord.utils.utcnow()
        )
        
        if isinstance(error, commands.MissingRequiredArgument):
            embed.description = f"You are missing a required argument.\n**Usage:** `{ctx.prefix}{ctx.command.name} {ctx.command.signature}`"
        elif isinstance(error, commands.BotMissingPermissions):
            embed.description = "I don't have the required permissions to execute this command."
        else:
            # Generic fallback for other errors
            embed.description = f"An unexpected error occurred:\n```py\n{str(error)}\n```"
            logger.error(f"Error executing command '{ctx.command}': {error}")

        embed.set_footer(text="Advanced Bot Architecture", icon_url=self.user.display_avatar.url)
        await ctx.send(embed=embed)

# ---------------------------------------------------------
# 6. EXECUTION & RAILWAY TOKEN HANDLING
# ---------------------------------------------------------
if __name__ == "__main__":
    bot = AdvancedMusicBot()
    
    # Fetch token securely from Railway environment variables
    TOKEN = os.environ.get("DISCORD_TOKEN")
    
    if not TOKEN:
        logger.critical("DISCORD_TOKEN is missing! Please set it in your Railway project variables.")
    else:
        logger.info("Token found. Starting bot sequence...")
        bot.run(TOKEN, log_handler=None) # We set log_handler=None because we configured our own logger above
      
