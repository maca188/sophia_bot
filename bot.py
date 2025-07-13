import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import os
import time
import random 
from dotenv import load_dotenv
from math import ceil
from typing import Optional
intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)

from database import setup_db, get_random_card, give_card_to_user, get_user_inventory, get_user_card_count, connect, get_card_by_code

ADMIN_COMMAND_NAMES = {"admin_add_card", "admin_remove_card", "admin_give", "admin_edit_card", "admin_pay", "event_add", "event_remove"}

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    setup_db()
    with connect() as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS currency (
                user_id TEXT PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        """)
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

    activity = discord.Activity(type=discord.ActivityType.listening, name="Gnarly")
    await bot.change_presence(status=discord.Status.online, activity=activity)

user_cooldowns = {}

# Store cooldown info: {command_name: cooldown_seconds}
command_cooldowns = {
    "drop": 60,
    "work": 1800  # 1 minute cooldown for drop command
    # Add other commands with cooldown here if needed
}

# Store per-user last use timestamps: {command_name: {user_id: last_used_timestamp}}
user_command_timestamps = {
    "drop": {},
    "work": {}  
    # Add others here if you add cooldown to other commands
}

def convert_rarity(rarity):
    mapping = {
        "1s": "⭐",
        "2s": "⭐⭐",
        "3s": "⭐⭐⭐",
        "4s": "⭐⭐⭐⭐",
        "5s": "⭐⭐⭐⭐⭐"
    }
    return mapping.get(rarity.lower(), rarity)

BURN_PRICES = {
    "⭐": 250,
    "⭐⭐": 350,
    "⭐⭐⭐": 450,
    "⭐⭐⭐⭐": 600,
    "⭐⭐⭐⭐⭐": 1200,
    "event": 5000
}
PACK_OPTIONS = {
    "1": {"name": "Normal pack", "cards": 3, "price": 3000},
    "2": {"name": "Medium pack", "cards": 5, "price": 7500},
    "3": {"name": "Epic pack", "cards": 10, "price": 13000}
}

def get_weighted_random_cards(num_cards: int):
    with connect() as con:
        cur = con.cursor()
        # Only cards not excluded from drop and only rarities 1s to 5s (⭐ to ⭐⭐⭐⭐⭐)
        cur.execute("""
            SELECT * FROM cards WHERE excluded_from_drop = 0 AND rarity IN ('⭐','⭐⭐','⭐⭐⭐','⭐⭐⭐⭐','⭐⭐⭐⭐⭐') AND is_event = 0
        """)
        all_cards = cur.fetchall()

    weighted = []
    for card in all_cards:
        code, member, group_name, rarity, era, image_url, is_event, excluded_from_drop = card

        # Adjust weights - bump 5⭐ cards chance to between 1% and 2%
        if rarity == "⭐⭐⭐⭐⭐":
            weight = random.uniform(10, 20)  # 1% to 2% * 10 (scaled)
        elif rarity == "⭐":
            weight = 40
        elif rarity == "⭐⭐":
            weight = 25
        elif rarity == "⭐⭐⭐":
            weight = 15
        elif rarity == "⭐⭐⭐⭐":
            weight = 10
        else:
            weight = 5

        weighted.extend([card] * int(weight))

    if not weighted:
        return []

    selected_cards = random.choices(weighted, k=num_cards)
    return selected_cards
    

@bot.tree.command(name="drop", description="Drop a random card.")
async def drop(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    now = time.time()

    command_name = "drop"
    cooldown = command_cooldowns.get(command_name, 60)  # fallback to 60s
    user_times = user_command_timestamps.setdefault(command_name, {})
    last_used = user_times.get(user_id, 0)
    elapsed = now - last_used

    if elapsed < cooldown:
        remaining = int(cooldown - elapsed)
        await interaction.response.send_message(
            f"⏳ You must wait {remaining} seconds before dropping another card.",
            ephemeral=False
        )
        return

    # Get all cards excluding those excluded from drop
    from database import connect

    with connect() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM cards WHERE excluded_from_drop IS NULL OR excluded_from_drop = 0")
        available_cards = cur.fetchall()

    if not available_cards:
        await interaction.response.send_message(
            "🚫 No cards available to drop. Please ask an admin to add cards first.",
            ephemeral=False
        )
        return

    # Weighted random choice for cards, based on rarity and event status
    weighted = []
    for card in available_cards:
        code, member, group_name, rarity, era, image_url, is_event, excluded_from_drop = card

        if is_event:
            weight = 0.7
        else:
            if rarity == "⭐":
                weight = 40
            elif rarity == "⭐⭐":
                weight = 25
            elif rarity == "⭐⭐⭐":
                weight = 15
            elif rarity == "⭐⭐⭐⭐":
                weight = 10
            elif rarity == "⭐⭐⭐⭐⭐":
                weight = 1
            else:
                weight = 5

        weighted.extend([card] * int(weight * 10))

    if not weighted:
        await interaction.response.send_message(
            "🚫 No cards available to drop. Please ask an admin to add cards first.",
            ephemeral=False
        )
        return

    card = random.choice(weighted)

    code, member, group_name, rarity, era, image_url, is_event, excluded_from_drop = card
    give_card_to_user(user_id, code)
    count = get_user_card_count(user_id, code)

    embed = discord.Embed(
        title="🎉 Event drop:" if is_event else "**Normal drop:**",
        description=(
            f"**Member:** {member}\n"
            f"**Group:** {group_name}\n"
            f"**Rarity:** {rarity}\n"
            f"**Era:** {era}\n"
            f"**Code:** {code}"
        ),
        color=discord.Color.gold() if is_event else discord.Color.blue()
    )
    embed.set_image(url=image_url)
    embed.set_footer(text=f"You now have {count} copies of this card.")

    user_times[user_id] = now  # Update cooldown timestamp

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="inventory", description="Check your card inventory.")
@app_commands.describe(
    user="View another user's inventory",
    member="Filter by member name",
    group="Filter by group name",
    era="Filter by era",
    rarity="Filter by rarity"
)
async def inventory(
    interaction: discord.Interaction,
    user: discord.User = None,
    member: str = None,
    group: str = None,
    era: str = None,
    rarity: str = None
):
    target = user or interaction.user
    inventory = get_user_inventory(str(target.id))

    if not inventory:
        await interaction.response.send_message(f"{target.display_name} doesn't own any cards yet!")
        return

    filtered = []
    for card in inventory:
        code, m, g, r, e, _, count = card
        if member and member.lower() not in m.lower():
            continue
        if group and group.lower() not in g.lower():
            continue
        if era and era.lower() not in e.lower():
            continue
        if rarity and rarity.lower() != r.lower():
            continue
        filtered.append(card)

    if not filtered:
        await interaction.response.send_message("No cards found with the applied filters.")
        return

    total_cards = sum(card[-1] for card in filtered)
    items_per_page = 5
    pages = ceil(len(filtered) / items_per_page)
    current_page = 0

    def build_embed(page_idx: int):
        embed = discord.Embed(
            title=f"{target.display_name}'s Inventory – Total Cards: {total_cards}",
            color=discord.Color.purple()
        )
        start = page_idx * items_per_page
        end = start + items_per_page
        for code, m, g, r, e, _, count in filtered[start:end]:
            embed.add_field(
                name=f"{m} ({g})",
                value=f"Rarity: {r}\nEra: {e}\nCode: `{code}`\nQuantity: {count}",
                inline=False
            )
        embed.set_footer(text=f"Page {page_idx+1}/{pages}")
        return embed

    class InventoryView(View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
        async def previous(self, interaction_btn: discord.Interaction, button: Button):
            nonlocal current_page
            if current_page > 0:
                current_page -= 1
                await interaction_btn.response.edit_message(embed=build_embed(current_page), view=self)
            else:
                await interaction_btn.response.defer()

        @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
        async def next(self, interaction_btn: discord.Interaction, button: Button):
            nonlocal current_page
            if current_page < pages - 1:
                current_page += 1
                await interaction_btn.response.edit_message(embed=build_embed(current_page), view=self)
            else:
                await interaction_btn.response.defer()

    await interaction.response.send_message(embed=build_embed(current_page), view=InventoryView())


@bot.tree.command(name="admin_add_card", description="(Admin) Add a new card to the system.")
@app_commands.describe(
    code="Unique code for the card",
    member="Name of the idol/member",
    group="Group name",
    rarity="Card rarity (use 1s, 2s, 3s, 4s, 5s for stars)",
    era="Era or generation of the card",
    image="Card image to upload"
)
async def admin_add_card(
    interaction: discord.Interaction,
    code: str,
    member: str,
    group: str,
    rarity: str,
    era: str,
    image: discord.Attachment 
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You must be an admin to use this command.", ephemeral=False)
        return

    # Convert rarity input (e.g. "1s") to stars (⭐)
    rarity_map = {
        "1s": "⭐",
        "2s": "⭐⭐",
        "3s": "⭐⭐⭐",
        "4s": "⭐⭐⭐⭐",
        "5s": "⭐⭐⭐⭐⭐"
    }
    rarity_stars = rarity_map.get(rarity.lower(), rarity)

    image_url = image.url if image else "https://example.com/default.jpg"

    from database import connect
    with connect() as con:
        cur = con.cursor()
        try:
            cur.execute(
                "INSERT INTO cards (code, member, group_name, rarity, era, image_url, is_event) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (code, member, group, rarity_stars, era, image_url, 0)  
            )
            await interaction.response.send_message(f"✅ Card `{code}` added successfully with image.")
        except Exception as e:
            await interaction.response.send_message(f"❌ Card with code `{code}` already exists or error occurred.", ephemeral=False)

@bot.tree.command(name="admin_remove_card", description="(Admin) Remove a card from the system by code.")
@app_commands.describe(
    code="The card code to remove"
)
async def admin_remove_card(
    interaction: discord.Interaction,
    code: str
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You must be an admin to use this command.", ephemeral=False)
        return

    from database import connect
    with connect() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM cards WHERE code = ?", (code,))
        if not cur.fetchone():
            await interaction.response.send_message(f"❌ Card `{code}` does not exist.", ephemeral=False)
            return

        cur.execute("DELETE FROM cards WHERE code = ?", (code,))
        cur.execute("DELETE FROM inventory WHERE code = ?", (code,))
        await interaction.response.send_message(f"🗑️ Card `{code}` removed from system and all inventories.")

    
# Autocomplete function for groups
async def group_autocomplete(interaction: discord.Interaction, current: str):
    from database import connect
    with connect() as con:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT group_name FROM cards WHERE group_name LIKE ? ORDER BY group_name ASC", (f"%{current}%",))
        groups = [row[0] for row in cur.fetchall()]
    return [
        app_commands.Choice(name=group, value=group)
        for group in groups[:25]  # max 25 options
    ]

@bot.tree.command(name="group_cards", description="Show cards from a specific group.")
@app_commands.describe(group="Select a group")
@app_commands.autocomplete(group=group_autocomplete)
async def group_cards(
    interaction: discord.Interaction,
    group: str
):
    from database import connect

    with connect() as con:
        cur = con.cursor()
        cur.execute("SELECT code, member, group_name, rarity, era, image_url FROM cards WHERE group_name = ?", (group,))
        cards = cur.fetchall()

    if not cards:
        await interaction.response.send_message(f"No cards found for group: {group}", ephemeral=False)
        return

    items_per_page = 5
    pages = ceil(len(cards) / items_per_page)
    current_page = 0

    def build_embed(page_idx: int):
        embed = discord.Embed(
            title=f"Cards in group: {group}",
            color=discord.Color.green()
        )
        start = page_idx * items_per_page
        end = start + items_per_page
        for code, member, group_name, rarity, era, image_url in cards[start:end]:
            embed.add_field(
                name=f"{member} ({group_name})",
                value=f"Rarity: {rarity}\nEra: {era}\nCode: {code}",
                inline=False
            )
        embed.set_footer(text=f"Page {page_idx + 1}/{pages}")
        return embed

    class GroupCardsView(View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
        async def previous(self, interaction_btn: discord.Interaction, button: Button):
            nonlocal current_page
            if current_page > 0:
                current_page -= 1
                await interaction_btn.response.edit_message(embed=build_embed(current_page), view=self)
            else:
                await interaction_btn.response.defer()

        @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
        async def next(self, interaction_btn: discord.Interaction, button: Button):
            nonlocal current_page
            if current_page < pages - 1:
                current_page += 1
                await interaction_btn.response.edit_message(embed=build_embed(current_page), view=self)
            else:
                await interaction_btn.response.defer()

    await interaction.response.send_message(embed=build_embed(current_page), view=GroupCardsView())

@bot.tree.command(name="commands", description="List all active bot commands.")
async def commands_list(interaction: discord.Interaction):
    commands = [
        cmd for cmd in bot.tree.get_commands()
        if cmd.name not in ADMIN_COMMAND_NAMES and not cmd.name.startswith("_")
    ]
    commands.sort(key=lambda c: c.name)

    items_per_page = 10
    pages = ceil(len(commands) / items_per_page)
    current_page = 0

    def build_embed(page_idx: int):
        embed = discord.Embed(
            title="Bot Commands",
            description="List of all public bot slash commands:",
            color=discord.Color.gold()
        )
        start = page_idx * items_per_page
        end = start + items_per_page
        page_cmds = commands[start:end]

        for cmd in page_cmds:
            desc = cmd.description or "No description"
            embed.add_field(name=f"/{cmd.name}", value=desc, inline=False)

        embed.set_footer(text=f"Page {page_idx + 1}/{pages}")
        return embed

    class CommandsView(View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
        async def previous(self, interaction_btn: discord.Interaction, button: Button):
            nonlocal current_page
            if current_page > 0:
                current_page -= 1
                await interaction_btn.response.edit_message(embed=build_embed(current_page), view=self)
            else:
                await interaction_btn.response.defer()

        @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
        async def next(self, interaction_btn: discord.Interaction, button: Button):
            nonlocal current_page
            if current_page < pages - 1:
                current_page += 1
                await interaction_btn.response.edit_message(embed=build_embed(current_page), view=self)
            else:
                await interaction_btn.response.defer()

    await interaction.response.send_message(embed=build_embed(current_page), view=CommandsView())

@bot.tree.command(name="admin_give", description="(Admin) Give a user a specific card and quantity.")
@app_commands.describe(
    user="User to receive the card",
    code="Card code to give",
    amount="How many copies to give"
)
async def admin_give(interaction: discord.Interaction, user: discord.User, code: str, amount: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=False)
        return

    card = get_card_by_code(code)
    if not card:
        await interaction.response.send_message("❌ Card with that code does not exist.", ephemeral=False)
        return

    for _ in range(amount):
        give_card_to_user(str(user.id), code)

    await interaction.response.send_message(f"✅ Gave {amount} copies of card `{code}` to {user.mention}.")

@bot.tree.command(name="view_card", description="View a specific card by its code.")
@app_commands.describe(code="Code of the card to view")
async def view_card(interaction: discord.Interaction, code: str):
    user_id = str(interaction.user.id)
    card = get_card_by_code(code)

    if not card:
        await interaction.response.send_message("❌ Card with that code does not exist.", ephemeral=False)
        return

    # Unpack all 7 fields now (with is_event included)
    code, member, group_name, rarity, era, image_url, is_event = card
    count = get_user_card_count(user_id, code)

    embed = discord.Embed(
        title="**Viewing card:**",
        description=(
            f"**Member:** {member}\n"
            f"**Group:** {group_name}\n"
            f"**Rarity:** {rarity}\n"
            f"**Era:** {era}\n"
            f"**Type:** {'🎉 Event Card' if is_event else 'Normal Card'}\n"
            f"**Code:** {code}"
        ),
        color=discord.Color.teal()
    )
    embed.set_image(url=image_url)
    embed.set_footer(text=f"You have {count} copies of this card.")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="gift", description="Gift a card to another user.")
@app_commands.describe(
    user="The user you want to gift the card to",
    code="The card code to gift",
    amount="How many copies you want to gift"
)
async def gift(interaction: discord.Interaction, user: discord.User, code: str, amount: int):
    giver_id = str(interaction.user.id)
    receiver_id = str(user.id)

    if giver_id == receiver_id:
        await interaction.response.send_message("❌ You can't gift cards to yourself.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive number.", ephemeral=True)
        return

    card = get_card_by_code(code)
    if not card:
        await interaction.response.send_message("❌ Card with that code does not exist.", ephemeral=True)
        return

    current_count = get_user_card_count(giver_id, code)
    if current_count < amount:
        await interaction.response.send_message(
            f"❌ You only have {current_count} copies of `{code}`, can't gift {amount}.",
            ephemeral=True
        )
        return

    # Remove cards from giver and add to receiver
    with connect() as con:
        cur = con.cursor()
        # Decrease giver's card count
        cur.execute(
            "UPDATE inventory SET count = count - ? WHERE user_id = ? AND code = ?",
            (amount, giver_id, code)
        )
        # Delete if it drops to 0 or below
        cur.execute(
            "DELETE FROM inventory WHERE user_id = ? AND code = ? AND count <= 0",
            (giver_id, code)
        )
        # Increase receiver's count
        cur.execute(
            """
            INSERT INTO inventory (user_id, code, count)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, code) DO UPDATE SET count = count + excluded.count
            """,
            (receiver_id, code, amount)
        )

    await interaction.response.send_message(
        f"🎁 {interaction.user.mention} gifted **{amount}x `{code}`** to {user.mention}!"
    )

from typing import Optional

@bot.tree.command(name="admin_edit_card", description="(Admin) Edit an existing card. Only update fields you provide.")
@app_commands.describe(
    old_code="The current code of the card to edit",
    new_code="The new code for the card (optional)",
    member="New member name (optional)",
    group="New group name (optional)",
    rarity="New rarity (optional, use 1s to 5s for stars)",
    era="New era (optional)",
    image_url="New image URL (optional)"
)
async def admin_edit_card(
    interaction: discord.Interaction,
    old_code: str,
    new_code: Optional[str] = None,
    member: Optional[str] = None,
    group: Optional[str] = None,
    rarity: Optional[str] = None,
    era: Optional[str] = None,
    image_url: Optional[str] = None
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return

    from database import connect, get_card_by_code

    card = get_card_by_code(old_code)
    if not card:
        await interaction.response.send_message(f"❌ Card with code `{old_code}` does not exist.", ephemeral=True)
        return

    # If new_code provided, check for conflicts
    if new_code and new_code != old_code and get_card_by_code(new_code):
        await interaction.response.send_message(f"❌ New code `{new_code}` already exists. Choose a different code.", ephemeral=True)
        return

    # Convert rarity shorthand to stars if needed
    rarity_map = {
        "1s": "⭐",
        "2s": "⭐⭐",
        "3s": "⭐⭐⭐",
        "4s": "⭐⭐⭐⭐",
        "5s": "⭐⭐⭐⭐⭐"
    }
    if rarity:
        rarity = rarity_map.get(rarity.lower(), rarity)

    # Build dynamic update query based on provided fields
    fields = []
    values = []

    if new_code:
        fields.append("code = ?")
        values.append(new_code)
    if member:
        fields.append("member = ?")
        values.append(member)
    if group:
        fields.append("group_name = ?")
        values.append(group)
    if rarity:
        fields.append("rarity = ?")
        values.append(rarity)
    if era:
        fields.append("era = ?")
        values.append(era)
    if image_url:
        fields.append("image_url = ?")
        values.append(image_url)

    if not fields:
        await interaction.response.send_message("⚠️ No fields to update provided.", ephemeral=True)
        return

    values.append(old_code)  # for WHERE clause

    query = f"UPDATE cards SET {', '.join(fields)} WHERE code = ?"

    with connect() as con:
        cur = con.cursor()
        cur.execute(query, tuple(values))

        # Update inventory code if changed
        if new_code and new_code != old_code:
            cur.execute(
                "UPDATE inventory SET code = ? WHERE code = ?",
                (new_code, old_code)
            )
        con.commit()

    await interaction.response.send_message(f"✅ Card `{old_code}` updated successfully.")

@bot.tree.command(name="cooldowns", description="Check your cooldown status for commands.")
async def cooldowns(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    now = time.time()

    embed = discord.Embed(
        title="🕒 Your Command Cooldowns",
        description="Check the status of your cooldowns below:",
        color=discord.Color.orange()
    )

    for cmd_name, cooldown in command_cooldowns.items():
        user_times = user_command_timestamps.get(cmd_name, {})
        last_used = user_times.get(user_id, 0)
        elapsed = now - last_used
        remaining = max(0, int(cooldown - elapsed))

        if remaining == 0:
            status = "✅"
        else:
            minutes, seconds = divmod(remaining, 60)
            status = f"⏳ {minutes:02}:{seconds:02}"

        label = cmd_name.capitalize()
        embed.add_field(name=f"{label}:", value=status, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=False)

@bot.tree.command(name="balance", description="Check your Katscoins balance.")
@app_commands.describe(user="The user whose balance you want to check")
async def balance(interaction: discord.Interaction, user: discord.User = None):
    target = user or interaction.user
    user_id = str(target.id)

    with connect() as con:
        cur = con.cursor()
        cur.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        balance = row[0] if row else 0

    title = f"✨ {target.display_name}'s balance:" if user else "✨ Your balance:"
    embed = discord.Embed(
        title=title,
        description=f"**Katscoins: **{balance:,} 💸 ",
        color=discord.Color.pink()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="work", description="Work and earn Katscoins.")
async def work(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    now = time.time()

    command_name = "work"
    cooldown = command_cooldowns[command_name]
    user_times = user_command_timestamps.setdefault(command_name, {})
    last_used = user_times.get(user_id, 0)
    elapsed = now - last_used

    if elapsed < cooldown:
        remaining = int(cooldown - elapsed)
        minutes, seconds = divmod(remaining, 60)
        formatted_time = f"{minutes:02}:{seconds:02}"
        await interaction.response.send_message(
            f"⏳ You must wait **{formatted_time}** before working again.",
            ephemeral=False
        )
        return

    earned = random.randint(800, 2000)
    with connect() as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO currency (user_id, balance) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?",
            (user_id, earned, earned)
        )
        con.commit()

    user_command_timestamps[command_name][user_id] = now

    await interaction.response.send_message(
        f"💼 You worked hard and earned **{earned:,} Katscoins**! 💸"
    )

@bot.tree.command(name="pay", description="Pay another user Katscoins from your balance.")
@app_commands.describe(
    user="The user you want to pay",
    amount="The amount of Katscoins to send"
)
async def pay(interaction: discord.Interaction, user: discord.User, amount: int):
    sender_id = str(interaction.user.id)
    receiver_id = str(user.id)

    if sender_id == receiver_id:
        await interaction.response.send_message("❌ You can't pay yourself.", ephemeral=False)
        return

    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be greater than zero.", ephemeral=False)
        return

    with connect() as con:
        cur = con.cursor()

        # Get sender's balance
        cur.execute("SELECT balance FROM currency WHERE user_id = ?", (sender_id,))
        sender_balance = cur.fetchone()
        sender_balance = sender_balance[0] if sender_balance else 0

        if sender_balance < amount:
            await interaction.response.send_message("❌ You don't have enough Katscoins.", ephemeral=False)
            return

        # Deduct from sender
        cur.execute("UPDATE currency SET balance = balance - ? WHERE user_id = ?", (amount, sender_id))

        # Add to receiver
        cur.execute("""
            INSERT INTO currency (user_id, balance)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
        """, (receiver_id, amount, amount))

        con.commit()

    await interaction.response.send_message(
        f"💸 You paid **{amount:,} Katscoins** to {user.mention}!"
    )

@bot.tree.command(name="admin_pay", description="(Admin) Give Katscoins to a user.")
@app_commands.describe(
    user="User to receive Katscoins",
    amount="Amount of Katscoins to give"
)
async def admin_pay(interaction: discord.Interaction, user: discord.User, amount: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You do not have permission to use this command.",
            ephemeral=False
        )
        return

    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=False)
        return

    user_id = str(user.id)
    with connect() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO currency (user_id, balance) 
            VALUES (?, ?) 
            ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
        """, (user_id, amount, amount))
        con.commit()

    await interaction.response.send_message(
        f"✅ Gave **{amount:,} Katscoins** to {user.mention}. 💸"
    )
@bot.tree.command(name="event_add", description="(Admin) Add an event card to the system.")
@app_commands.describe(
    code="Unique code for the event card",
    member="Name of the idol/member",
    group="Group name",
    rarity="Card rarity (any value is accepted)",
    era="Era or generation of the card",
    image="Card image to upload"
)
async def event_add(
    interaction: discord.Interaction,
    code: str,
    member: str,
    group: str,
    rarity: str,
    era: str,
    image: discord.Attachment
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You must be an admin to use this command.", ephemeral=False)
        return

    image_url = image.url if image else "https://example.com/default.jpg"

    from database import connect
    with connect() as con:
        cur = con.cursor()
        try:
            cur.execute(
                "INSERT INTO cards (code, member, group_name, rarity, era, image_url, is_event) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (code, member, group, rarity, era, image_url, 1)  # is_event=1
            )
            await interaction.response.send_message(f"✅ Event card `{code}` added successfully with image.")
        except Exception as e:
            await interaction.response.send_message(f"❌ Event card with code `{code}` already exists or error occurred.", ephemeral=False)

@bot.tree.command(name="event_remove", description="Exclude one or more cards from being dropped.")
@app_commands.describe(code="One or more card codes separated by commas")
async def event_remove(interaction: discord.Interaction, code: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You must be an admin to use this command.", ephemeral=True)
        return

    from database import connect, get_card_by_code

    codes = [c.strip() for c in code.split(",") if c.strip()]
    updated = []
    failed = []

    with connect() as con:
        cur = con.cursor()
        for card_code in codes:
            card = get_card_by_code(card_code)
            if card:
                cur.execute("UPDATE cards SET excluded_from_drop = 1 WHERE code = ?", (card_code,))
                updated.append(card_code)
            else:
                failed.append(card_code)

    msg = ""
    if updated:
        msg += f"✅ These cards were removed from drop pool: `{', '.join(updated)}`\n"
    if failed:
        msg += f"⚠️ These codes were not found: `{', '.join(failed)}`"

    await interaction.response.send_message(msg or "⚠️ No valid card codes provided.", ephemeral=False)

@bot.tree.command(name="burn", description="Burn cards to earn Katscoins.")
@app_commands.describe(
    codes="Comma-separated list of card codes to burn (1 copy each)"
)
async def burn(interaction: discord.Interaction, codes: str):
    user_id = str(interaction.user.id)
    code_list = [code.strip() for code in codes.split(",") if code.strip()]
    if not code_list:
        await interaction.response.send_message("❌ Please provide at least one valid card code.", ephemeral=False)
        return

    from database import connect, get_card_by_code, get_user_card_count

    total_earned = 0
    burned_cards = []
    not_owned = []

    with connect() as con:
        cur = con.cursor()
        for code in code_list:
            card = get_card_by_code(code)
            if not card:
                not_owned.append(code)
                continue

            # Unpack card including is_event
            # card schema: code, member, group_name, rarity, era, image_url, is_event, excluded_from_drop (excluded_from_drop may be None if not added)
            # To be safe, unpack minimum needed, ignoring excluded_from_drop if present
            code_db, member, group_name, rarity, era, image_url, is_event = card[:7]

            count = get_user_card_count(user_id, code)
            if count < 1:
                not_owned.append(code)
                continue

            # Determine burn price
            if is_event:
                price = BURN_PRICES["event"]
            else:
                price = BURN_PRICES.get(rarity, 0)  # 0 if unknown rarity

            if price == 0:
                # Skip if price is 0, e.g. unknown rarity
                continue

            # Remove 1 card from inventory
            cur.execute(
                "UPDATE inventory SET count = count - 1 WHERE user_id = ? AND code = ?",
                (user_id, code)
            )
            # If count reaches 0, delete the row
            cur.execute(
                "DELETE FROM inventory WHERE user_id = ? AND code = ? AND count <= 0",
                (user_id, code)
            )

            # Add Katscoins to user's balance
            cur.execute(
                "INSERT INTO currency (user_id, balance) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?",
                (user_id, price, price)
            )

            total_earned += price
            burned_cards.append((code, member, price))

        con.commit()

    if not burned_cards and not_owned:
        await interaction.response.send_message(
            f"❌ You do not own any of the specified cards or invalid codes: {', '.join(not_owned)}",
            ephemeral=False
        )
        return

    embed = discord.Embed(
        title="🔥 Burning Cards 🔥",
        color=discord.Color.orange()
    )

    if burned_cards:
        desc_lines = [f"✅ Burned **{member}** (`{code}`) for **{price:,} Katscoins**" for code, member, price in burned_cards]
        embed.description = "\n".join(desc_lines)
        embed.add_field(name="Total Katscoins earned:", value=f"**{total_earned:,} 💸**")

    if not_owned:
        embed.add_field(name="Cards not owned or invalid codes:", value=", ".join(not_owned), inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="shop", description="View the shop and available card packs.")
async def shop(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛒 Viewing Shop:",
        description=(
            "1. **Normal pack**\n"
            " Random 3 cards \n"
            "Price: 3000 Katscoins\n\n"
            "2. **Medium pack**\n"
            " Random 5 cards \n"
            "Price: 7500 Katscoins\n\n"
            "3. **Epic pack**\n"
            " Random 10 cards \n"
            "Price: 13000 Katscoins"
        ),
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="buy", description="Buy a card pack from the shop.")
@app_commands.describe(option="Select pack option (1, 2 or 3)")
async def buy(interaction: discord.Interaction, option: str):
    user_id = str(interaction.user.id)
    option = option.strip()

    if option not in PACK_OPTIONS:
        await interaction.response.send_message("❌ Invalid pack option. Please choose 1, 2, or 3.", ephemeral=False)
        return

    pack = PACK_OPTIONS[option]
    price = pack["price"]
    num_cards = pack["cards"]
    pack_name = pack["name"]

    from database import connect, get_user_card_count

    with connect() as con:
        cur = con.cursor()
        # Check user's Katscoins balance
        cur.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        balance = row[0] if row else 0

        if balance < price:
            await interaction.response.send_message(f"❌ You need {price} Katscoins but only have {balance}.", ephemeral=False)
            return

        # Deduct price
        cur.execute("UPDATE currency SET balance = balance - ? WHERE user_id = ?", (price, user_id))

        # Get random cards from the adjusted weighted function
        cards_picked = get_weighted_random_cards(num_cards)

        # Give cards to user and count them
        given = {}
        for card in cards_picked:
            code, member, group_name, rarity, era, image_url, is_event, excluded_from_drop = card
            # Give card to user
            cur.execute("SELECT count FROM inventory WHERE user_id = ? AND code = ?", (user_id, code))
            inv_row = cur.fetchone()
            if inv_row:
                cur.execute("UPDATE inventory SET count = count + 1 WHERE user_id = ? AND code = ?", (user_id, code))
            else:
                cur.execute("INSERT INTO inventory (user_id, code, count) VALUES (?, ?, 1)", (user_id, code))

            given_key = f"{code} ({rarity})"
            given[given_key] = given.get(given_key, 0) + 1

        con.commit()

    # Build embed with cards bought
    embed = discord.Embed(
        title=f"🎉 Cards bought: {pack_name}",
        color=discord.Color.gold()
    )
    description_lines = [f"{code} x{count}" for code, count in given.items()]
    embed.description = "\n".join(description_lines)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="help", description="Show help information about the bot.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Help!",
        description=(
            "Welcome to Sophia bot! A K-pop themed card collecting bot. Here you can collect various cards, trade with others, buy card packs and much more.\n\n"
            "Here is how it works:\n\n"
            "Run `/commands` to see all available commands.\n"
            "Now do `/drop` command to start collecting.\n\n"
            "Now you can start your collecting journey and have fun!\n\n"
            "If you need any help or if you have any questions, please contact staff in our support server.\n"
            "**Link:** \n\n"
            "Please keep in mind that bot is currently in beta which means errors could happen and data can be lost but don't worry because staff is working hard to keep everything going okay."
        ),
        color=discord.Color(0xfaffbf)
    )
    await interaction.response.send_message(embed=embed, ephemeral=False)

bot.run(os.getenv('DISCORD_TOKEN'))
