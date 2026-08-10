"""
Advanced Music Cog for Discord.py
Includes dynamically generated PIL images, interactive UI components,
and robust state management for a premium user experience.
"""

import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import logging
import io
import aiohttp
from typing import Optional, Dict
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ---------------------------------------------------------
# 1. LOGGING & CONFIGURATION
# ---------------------------------------------------------

logger = logging.getLogger("MusicCog")

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0', 
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


# ---------------------------------------------------------
# 2. ADVANCED PIL IMAGE GENERATOR
# ---------------------------------------------------------
class AudioCardGenerator:
    """
    A class dedicated to generating beautiful, dynamic images for the currently playing song using Pillow (PIL).
    It creates a stylized card with the thumbnail, title, and a visual progress bar.
    """
    
    @staticmethod
    def _create_rounded_mask(size: tuple, radius: int) -> Image.Image:
        """Helper method to create a rounded corner mask."""
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
        return mask

    @staticmethod
    def _add_corners(im: Image.Image, radius: int) -> Image.Image:
        """Applies rounded corners to a given PIL Image."""
        mask = AudioCardGenerator._create_rounded_mask(im.size, radius)
        rounded = Image.new("RGBA", im.size)
        rounded.paste(im, (0, 0), mask=mask)
        return rounded

    @classmethod
    async def generate_card(cls, thumbnail_url: str, title: str, duration: str) -> io.BytesIO:
        """
        Downloads the thumbnail and builds a rich UI card dynamically.
        Returns a BytesIO object ready to be sent as a discord.File.
        """
        # 1. Fetch the thumbnail image asynchronously
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(thumbnail_url) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                        thumb = Image.open(io.BytesIO(image_data)).convert("RGBA")
                    else:
                        # Fallback to a blank image if fetch fails
                        thumb = Image.new("RGBA", (300, 300), color=(50, 50, 50))
            except Exception as e:
                logger.error(f"Failed to fetch thumbnail: {e}")
                thumb = Image.new("RGBA", (300, 300), color=(50, 50, 50))

        # 2. Setup Canvas Sizes
        canvas_width, canvas_height = 800, 300
        canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
        
        # 3. Create the Background (Dark gray, rounded)
        bg = Image.new("RGBA", (canvas_width, canvas_height), (35, 39, 42, 255))
        bg = cls._add_corners(bg, radius=30)
        canvas.paste(bg, (0, 0), bg)

        # 4. Process Thumbnail
        # Crop to square and resize
        min_dim = min(thumb.size)
        left = (thumb.width - min_dim) / 2
        top = (thumb.height - min_dim) / 2
        right = (thumb.width + min_dim) / 2
        bottom = (thumb.height + min_dim) / 2
        
        thumb = thumb.crop((left, top, right, bottom))
        thumb = thumb.resize((240, 240), Image.Resampling.LANCZOS)
        thumb = cls._add_corners(thumb, radius=20)
        
        # Paste thumbnail onto canvas (padding: 30px from left, 30px from top)
        canvas.paste(thumb, (30, 30), thumb)

        # 5. Draw Text and UI Elements
        draw = ImageDraw.Draw(canvas)
        
        # Try to load a default font, scale it by using default size
        try:
            # If deploying on a system with standard fonts (like Windows/Mac)
            title_font = ImageFont.truetype("arial.ttf", 36)
            dur_font = ImageFont.truetype("arial.ttf", 24)
        except IOError:
            # Fallback for Railway/Linux environments
            title_font = ImageFont.load_default()
            dur_font = ImageFont.load_default()

        # Text: Title (truncate if too long)
        max_title_len = 35
        display_title = title if len(title) <= max_title_len else title[:max_title_len - 3] + "..."
        
        # Position for title: next to thumbnail
        text_x = 300
        text_y = 60
        draw.text((text_x, text_y), display_title, font=title_font, fill=(255, 255, 255, 255))
        
        # Text: Duration
        draw.text((text_x, text_y + 60), f"Duration: {duration}", font=dur_font, fill=(185, 187, 190, 255))
        
        # Draw a faux Progress Bar
        bar_x = 300
        bar_y = 210
        bar_width = 450
        bar_height = 8
        
        # Bar background
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + bar_width, bar_y + bar_height),
            radius=4, fill=(79, 84, 92, 255)
        )
        # Bar foreground (simulating some progress)
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + (bar_width // 4), bar_y + bar_height),
            radius=4, fill=(88, 101, 242, 255) # Discord Blurple
        )

        # 6. Save to buffer
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer


# ---------------------------------------------------------
# 3. YOUTUBE / AUDIO SOURCE MANAGER
# ---------------------------------------------------------
class YTDLSource(discord.PCMVolumeTransformer):
    """
    Wraps the discord.FFmpegPCMAudio to stream directly from yt-dlp.
    Also handles volume adjustment inherently.
    """
    def __init__(self, source, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown Title')
        self.url = data.get('url', '')
        self.duration = data.get('duration', 0)
        self.thumbnail = data.get('thumbnail', '')
        
        # Format duration to mm:ss
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        if h > 0:
            self.formatted_duration = f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
        else:
            self.formatted_duration = f"{int(m):02d}:{int(s):02d}"

    @classmethod
    async def create_source(cls, search: str, loop: asyncio.AbstractEventLoop):
        """
        Runs the yt-dlp extraction in a non-blocking executor thread.
        """
        # If it's not a URL, perform a search
        if not search.startswith("http"):
            search = f"ytsearch:{search}"
            
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
        
        if data is None:
            raise ValueError("Could not extract data from the provided search query.")
            
        if 'entries' in data:
            data = data['entries'][0]

        audio_url = data['url']
        return cls(discord.FFmpegPCMAudio(audio_url, **FFMPEG_OPTIONS), data=data)


# ---------------------------------------------------------
# 4. GUILD STATE MANAGER
# ---------------------------------------------------------
class GuildMusicState:
    """
    Manages the current state of music for a specific guild.
    Keeps track of volume, looping, and the currently/last played track to allow robust toggling.
    """
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.is_looping = False
        self.volume = 0.5
        self.current_song_data = None
        self.last_played_search = None  # Used to restart a stopped song
        self.voice_client: Optional[discord.VoiceClient] = None
        
    def set_client(self, vc: discord.VoiceClient):
        self.voice_client = vc

    def toggle_loop(self) -> bool:
        self.is_looping = not self.is_looping
        return self.is_looping
        
    def adjust_volume(self, amount: float) -> float:
        self.volume += amount
        # Clamp volume between 0.0 and 2.0 (200%)
        self.volume = max(0.0, min(self.volume, 2.0))
        if self.voice_client and self.voice_client.source:
            self.voice_client.source.volume = self.volume
        return self.volume


# ---------------------------------------------------------
# 5. INTERACTIVE UI (MEDIA CONTROLLER)
# ---------------------------------------------------------
class MediaControllerView(discord.ui.View):
    """
    A rich embed View that handles the buttons:
    Stop <-> Start
    Pause <-> Resume
    Volume Up, Volume Down
    Loop, Leave
    """
    def __init__(self, state: GuildMusicState, cog: 'MusicCog'):
        super().__init__(timeout=None) # Persistent view
        self.state = state
        self.cog = cog

    # --- ROW 1: Playback Controls ---

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏸️", row=0)
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.state.voice_client
        if not vc:
            await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
            return

        if vc.is_playing():
            vc.pause()
            button.label = "Resume"
            button.emoji = "▶️"
            button.style = discord.ButtonStyle.success
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"{interaction.user.mention} paused the song.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            button.label = "Pause"
            button.emoji = "⏸️"
            button.style = discord.ButtonStyle.secondary
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"{interaction.user.mention} resumed the song.", ephemeral=True)
        else:
            await interaction.response.send_message("No audio is currently playing to pause.", ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", row=0)
    async def stop_start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.state.voice_client
        if not vc:
            await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
            return

        # If it says Stop, we stop it and change to Start
        if button.label == "Stop":
            if vc.is_playing() or vc.is_paused():
                vc.stop()
            button.label = "Start"
            button.emoji = "🔄"
            button.style = discord.ButtonStyle.success
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"{interaction.user.mention} stopped the song.", ephemeral=True)
        
        # If it says Start, we fetch the last song and play it again
        else:
            if not self.state.last_played_search:
                await interaction.response.send_message("No previous song found to restart.", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            try:
                source = await YTDLSource.create_source(self.state.last_played_search, self.cog.bot.loop)
                source.volume = self.state.volume
                vc.play(source, after=lambda e: self.cog.play_next(interaction.guild_id, e))
                
                button.label = "Stop"
                button.emoji = "⏹️"
                button.style = discord.ButtonStyle.danger
                await interaction.message.edit(view=self)
                await interaction.followup.send(f"{interaction.user.mention} restarted the song.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Error restarting: {e}", ephemeral=True)

    @discord.ui.button(label="Loop", style=discord.ButtonStyle.secondary, emoji="🔁", row=0)
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_loop = self.state.toggle_loop()
        
        if is_loop:
            button.style = discord.ButtonStyle.primary
        else:
            button.style = discord.ButtonStyle.secondary
            
        await interaction.response.edit_message(view=self)
        
        status = "looped" if is_loop else "unlooped"
        await interaction.followup.send(f"{interaction.user.mention} song is {status}", ephemeral=True)

    # --- ROW 2: Volume & Utility Controls ---

    @discord.ui.button(label="Vol -", style=discord.ButtonStyle.secondary, emoji="🔉", row=1)
    async def vol_down_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        new_vol = self.state.adjust_volume(-0.1)
        await interaction.response.send_message(f"Volume decreased to {int(new_vol * 100)}%", ephemeral=True)

    @discord.ui.button(label="Vol +", style=discord.ButtonStyle.secondary, emoji="🔊", row=1)
    async def vol_up_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        new_vol = self.state.adjust_volume(0.1)
        await interaction.response.send_message(f"Volume increased to {int(new_vol * 100)}%", ephemeral=True)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger, emoji="🚪", row=1)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.state.voice_client
        if vc:
            await vc.disconnect()
            
        # Disable all buttons upon leaving
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"{interaction.user.mention} disconnected the bot.", ephemeral=False)


# ---------------------------------------------------------
# 6. THE COG IMPLEMENTATION
# ---------------------------------------------------------
class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Dictionary to store GuildMusicState instances mapped by Guild ID
        self.guild_states: Dict[int, GuildMusicState] = {}

    def get_state(self, guild_id: int) -> GuildMusicState:
        """Retrieves or creates a state for the guild."""
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = GuildMusicState(guild_id)
        return self.guild_states[guild_id]

    def play_next(self, guild_id: int, error):
        """
        Callback fired when a song finishes. 
        Handles looping if enabled.
        """
        if error:
            logger.error(f"Player error in guild {guild_id}: {error}")
            
        state = self.get_state(guild_id)
        
        # If loop is active and we have a last played search, replay it
        if state.is_looping and state.last_played_search and state.voice_client:
            # We must recreate the source for FFmpeg
            coro = YTDLSource.create_source(state.last_played_search, self.bot.loop)
            future = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
            
            try:
                source = future.result()
                source.volume = state.volume
                state.voice_client.play(source, after=lambda e: self.play_next(guild_id, e))
            except Exception as e:
                logger.error(f"Error looping track: {e}")

    # =========================================================
    # SLASH COMMAND: /play
    # =========================================================
    @app_commands.command(name="play", description="Search for and play a song with an advanced UI.")
    @app_commands.describe(song="The name or URL of the song you want to play.")
    async def play_command(self, interaction: discord.Interaction, song: str):
        # 1. Voice State Verification
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "❌ You need to be in a voice channel to use this command.", 
                ephemeral=True
            )
            
        voice_channel = interaction.user.voice.channel
        state = self.get_state(interaction.guild_id)
        
        # Defer response since processing takes time
        await interaction.response.defer(ephemeral=False)
        
        # Join channel if not already connected
        vc = interaction.guild.voice_client
        if not vc:
            vc = await voice_channel.connect()
            state.set_client(vc)
        elif vc.channel != voice_channel:
            await vc.move_to(voice_channel)
            state.set_client(vc)
            
        # 2. Simulate 10-second Search with dynamic message editing
        # To avoid rate limits, we'll edit at specific intervals rather than every single second
        status_msg = await interaction.followup.send("🔍 **Searching...** Analyzing best audio streams. Please wait 10 seconds.")
        
        await asyncio.sleep(3)
        await status_msg.edit(content="⏳ **Searching...** Filtering high-quality results. 7 seconds remaining.")
        
        await asyncio.sleep(4)
        await status_msg.edit(content="⚙️ **Processing...** Extracting audio metadata. 3 seconds remaining.")
        
        await asyncio.sleep(3)
        
        # Stop current audio if playing
        if vc.is_playing() or vc.is_paused():
            vc.stop()

        # 3. Extract Audio via yt-dlp
        try:
            source = await YTDLSource.create_source(song, self.bot.loop)
            source.volume = state.volume
        except Exception as e:
            return await status_msg.edit(content=f"❌ **An error occurred while searching:** `{e}`")

        # Update State
        state.last_played_search = song
        state.current_song_data = source.data

        # 4. Generate the Advanced PIL Image Card
        await status_msg.edit(content="🎨 **Rendering UI...** Generating rich media card.")
        try:
            image_buffer = await AudioCardGenerator.generate_card(
                thumbnail_url=source.thumbnail,
                title=source.title,
                duration=source.formatted_duration
            )
            file = discord.File(fp=image_buffer, filename="music_card.png")
        except Exception as e:
            logger.error(f"Failed to generate PIL image: {e}")
            file = None

        # 5. Construct the Rich Embed
        embed = discord.Embed(
            description=f"** {source.title} **\nDuration: **{source.formatted_duration}**",
            color=0x5865F2 # Blurple
        )
        if file:
            embed.set_image(url="attachment://music_card.png")
            
        embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        # 6. Create UI View
        view = MediaControllerView(state, self)

        # 7. Start Playback and Send Final Embed
        vc.play(source, after=lambda e: self.play_next(interaction.guild_id, e))
        
        if file:
            await status_msg.edit(content=None, embed=embed, view=view, attachments=[file])
        else:
            await status_msg.edit(content=None, embed=embed, view=view)


    # =========================================================
    # INDIVIDUAL CONTROL SLASH COMMANDS
    # =========================================================

    @app_commands.command(name="loop", description="Toggle looping for the current song.")
    async def loop_command(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        is_loop = state.toggle_loop()
        status = "looped" if is_loop else "unlooped"
        # Ephemeral = True as requested
        await interaction.response.send_message(f"{interaction.user.mention} song is {status}", ephemeral=True)

    @app_commands.command(name="stop", description="Stop the currently playing song.")
    async def stop_command(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            # Ephemeral = True as requested
            await interaction.response.send_message(f"{interaction.user.mention} stopped the song", ephemeral=True)
        else:
            await interaction.response.send_message("No audio is playing.", ephemeral=True)

    @app_commands.command(name="pause", description="Pause the currently playing song.")
    async def pause_command(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            # Ephemeral = True as requested
            await interaction.response.send_message(f"{interaction.user.mention} paused the song.", ephemeral=True)
        else:
            await interaction.response.send_message("No audio is playing to pause.", ephemeral=True)

    @app_commands.command(name="resume", description="Resume a paused song.")
    async def resume_command(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            # Ephemeral = True as requested
            await interaction.response.send_message(f"{interaction.user.mention} resumed the song.", ephemeral=True)
        else:
            await interaction.response.send_message("Audio is not paused.", ephemeral=True)

    @app_commands.command(name="disconnect", description="Disconnect the bot from the voice channel.")
    async def disconnect_command(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            await vc.disconnect()
            # Ephemeral = False as requested
            await interaction.response.send_message(f"Disconnected from the voice channel by {interaction.user.mention}.", ephemeral=False)
        else:
            await interaction.response.send_message("I am not in a voice channel.", ephemeral=False)

    @app_commands.command(name="connect", description="Connect the bot to your current voice channel.")
    async def connect_command(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("You must be in a voice channel.", ephemeral=False)
            
        channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        
        if vc:
            if vc.channel.id == channel.id:
                return await interaction.response.send_message("I am already in your voice channel.", ephemeral=False)
            else:
                await vc.move_to(channel)
        else:
            await channel.connect()
            
        state = self.get_state(interaction.guild_id)
        state.set_client(interaction.guild.voice_client)
        
        # Ephemeral = False as requested
        await interaction.response.send_message(f"Connected to {channel.mention}.", ephemeral=False)


# ---------------------------------------------------------
# 7. COG SETUP FUNCTION
# ---------------------------------------------------------
async def setup(bot: commands.Bot):
    """
    Called dynamically by the bot.py loader to add the cog.
    Also syncs the app commands so slash commands appear instantly.
    """
    await bot.add_cog(MusicCog(bot))
    # Note: Syncing globally on every reload is bad practice for large bots,
    # but for a personal project on Railway, it ensures your commands show up immediately.
    try:
        await bot.tree.sync()
        logger.info("Successfully synced Slash Commands for MusicCog.")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")
