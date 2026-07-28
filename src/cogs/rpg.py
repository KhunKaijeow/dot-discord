import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import random
import logging
from datetime import datetime

logger = logging.getLogger("discord.rpg")

DATA_FILE = "data/rpg_players.json"

CLASSES = {
    "Warrior": {"max_hp": 150, "atk": 12, "icon": "🛡️", "desc": "พลังชีวิตสูง เหมาะสำหรับสายอึดทน"},
    "Mage": {"max_hp": 90, "atk": 22, "icon": "🔮", "desc": "พลังโจมตีสูงมาก แต่พลังชีวิตค่อนข้างบอบบาง"},
    "Rogue": {"max_hp": 115, "atk": 16, "icon": "🗡️", "desc": "สมดุลรอบด้าน มีความว่องไวสูง"}
}

MONSTERS = [
    # Level 1-2
    {"name": "Slime (สไลม์)", "hp": 40, "atk": 5, "min_level": 1, "exp": 25, "gold": 15, "icon": "🟢"},
    {"name": "Goblin (ก็อบลิน)", "hp": 60, "atk": 8, "min_level": 1, "exp": 40, "gold": 25, "icon": "👺"},
    # Level 3-4
    {"name": "Dire Wolf (หมาป่าสีเทา)", "hp": 90, "atk": 12, "min_level": 3, "exp": 70, "gold": 45, "icon": "🐺"},
    {"name": "Zombie (ซอมบี้หิวกระหาย)", "hp": 120, "atk": 10, "min_level": 3, "exp": 90, "gold": 55, "icon": "🧟"},
    # Level 5+
    {"name": "Orc Warrior (ออร์คนักรบ)", "hp": 170, "atk": 18, "min_level": 5, "exp": 150, "gold": 90, "icon": "👹"},
    {"name": "Stone Golem (โกเลมหิน)", "hp": 240, "atk": 14, "min_level": 5, "exp": 200, "gold": 120, "icon": "🗿"},
    {"name": "Red Dragon (มังกรแดงโบราณ)", "hp": 400, "atk": 26, "min_level": 8, "exp": 450, "gold": 300, "icon": "🐉"}
]

class RPGPlayer:
    def __init__(self, user_id, class_name, level=1, exp=0, gold=100, hp=None, max_hp=None, atk=None, potions=3, weapon_level=1, armor_level=1):
        self.user_id = str(user_id)
        self.class_name = class_name
        self.level = level
        self.exp = exp
        self.gold = gold
        self.potions = potions
        self.weapon_level = weapon_level
        self.armor_level = armor_level
        
        # Load base stats from class if not provided
        class_base = CLASSES.get(class_name, CLASSES["Warrior"])
        self.max_hp = max_hp or (class_base["max_hp"] + (level - 1) * 15 + (armor_level - 1) * 20)
        self.hp = hp or self.max_hp
        self.atk = atk or (class_base["atk"] + (level - 1) * 3 + (weapon_level - 1) * 4)

    def to_dict(self):
        return {
            "class_name": self.class_name,
            "level": self.level,
            "exp": self.exp,
            "gold": self.gold,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "atk": self.atk,
            "potions": self.potions,
            "weapon_level": self.weapon_level,
            "armor_level": self.armor_level
        }

    def heal(self, amount=40):
        if self.potions > 0:
            self.potions -= 1
            self.hp = min(self.max_hp, self.hp + amount)
            return True
        return False

    def add_exp(self, amount):
        self.exp += amount
        needed = self.level * 100
        leveled_up = False
        while self.exp >= needed:
            self.exp -= needed
            self.level += 1
            self.max_hp += 15
            self.atk += 3
            self.hp = self.max_hp
            needed = self.level * 100
            leveled_up = True
        return leveled_up

    def upgrade_weapon(self, cost):
        if self.gold >= cost:
            self.gold -= cost
            self.weapon_level += 1
            self.atk += 4
            return True
        return False

    def upgrade_armor(self, cost):
        if self.gold >= cost:
            self.gold -= cost
            self.armor_level += 1
            self.max_hp += 20
            self.hp += 20
            return True
        return False


class ClassSelectView(discord.ui.View):
    def __init__(self, cog, player_id):
        super().__init__(timeout=60.0)
        self.cog = cog
        self.player_id = str(player_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.player_id:
            await interaction.response.send_message("❌ เฉพาะผู้เรียกใช้งานเท่านั้นที่กดปุ่มนี้ได้ครับ", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Warrior (นักรบ)", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def select_warrior(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_class(interaction, "Warrior")

    @discord.ui.button(label="Mage (นักเวท)", style=discord.ButtonStyle.danger, emoji="🔮")
    async def select_mage(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_class(interaction, "Mage")

    @discord.ui.button(label="Rogue (นักฆ่า)", style=discord.ButtonStyle.success, emoji="🗡️")
    async def select_rogue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_class(interaction, "Rogue")

    async def register_class(self, interaction, class_name):
        player = RPGPlayer(self.player_id, class_name)
        self.cog.players[self.player_id] = player
        self.cog.save_players()
        
        class_info = CLASSES[class_name]
        embed = discord.Embed(
            title="🎮 สร้างตัวละครสำเร็จ!",
            description=f"ยินดีต้อนรับสู่โลกแฟนตาซี! คุณได้เข้าสู่การเดินทางในฐานะ **{class_name}**\n"
                        f"• {class_info['icon']} **พลังชีวิตสูงสุด:** `{player.max_hp}`\n"
                        f"• ⚔️ **พลังโจมตี:** `{player.atk}`\n"
                        f"• 💰 **เงินตั้งต้น:** `{player.gold} ทอง` | 🧪 **ยาฟื้นพลัง:** `{player.potions} ขวด`",
            color=0x2ecc71
        )
        self.stop()
        await interaction.response.edit_message(embed=embed, view=None)


class BattleView(discord.ui.View):
    def __init__(self, cog, player, monster):
        super().__init__(timeout=120.0)
        self.cog = cog
        self.player = player
        self.monster = monster
        self.monster_hp = monster["hp"]
        self.monster_max_hp = monster["hp"]
        self.battle_log = []

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.player.user_id:
            await interaction.response.send_message("❌ เฉพาะผู้ท้าสู้เท่านั้นที่ควบคุมการต่อสู้ได้ครับ", ephemeral=True)
            return False
        return True

    def get_battle_embed(self):
        # Format HP Bars
        player_bar = f"`{'❤️' * (int(self.player.hp / self.player.max_hp * 10)) or '💔'}`"
        monster_bar = f"`{'💚' * (int(self.monster_hp / self.monster_max_hp * 10)) or '💀'}`"

        embed = discord.Embed(
            title=f"⚔️ การปะทะกับ {self.monster['name']}",
            color=0xe74c3c
        )
        embed.add_field(
            name=f"🤠 ผู้เล่น ({self.player.class_name} Lv.{self.player.level})",
            value=f"**HP:** `{self.player.hp}/{self.player.max_hp}`\n{player_bar}\n🧪 ยาฟื้นพลัง: `{self.player.potions}` ขวด",
            inline=True
        )
        embed.add_field(
            name=f"{self.monster['icon']} {self.monster['name']}",
            value=f"**HP:** `{self.monster_hp}/{self.monster_max_hp}`\n{monster_bar}\n⚔️ พลังโจมตี: `{self.monster['atk']}`",
            inline=True
        )

        if self.battle_log:
            embed.add_field(name="📜 รายงานการรบ", value="\n".join(self.battle_log[-4:]), inline=False)
        else:
            embed.add_field(name="📜 รายงานการรบ", value="เตรียมพร้อมเข้าต่อสู้! คุณเริ่มเปิดฉากโจมตีก่อน", inline=False)

        return embed

    async def monster_counter_attack(self):
        """Calculates monster counter-attack on player."""
        if self.monster_hp <= 0:
            return
        
        # Monster attack damage with minor variance (+-15%)
        variance = random.uniform(0.85, 1.15)
        dmg = int(self.monster["atk"] * variance)
        self.player.hp = max(0, self.player.hp - dmg)
        self.battle_log.append(f"💥 **{self.monster['name']}** ตีสวนกลับใส่คุณอย่างรุนแรง ได้รับความเสียหาย `{dmg}` หน่วย")

    @discord.ui.button(label="โจมตี (Attack)", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def attack_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Calculate critical hit (Rogue has higher crit rate)
        crit_chance = 0.25 if self.player.class_name == "Rogue" else 0.10
        is_crit = random.random() < crit_chance
        
        variance = random.uniform(0.85, 1.15)
        player_dmg = int(self.player.atk * variance)
        if is_crit:
            player_dmg = int(player_dmg * 2.0)
            self.battle_log.append(f"✨ **โจมตีคริติคอล!** คุณสร้างความเสียหายใส่ศัตรูอย่างมหาศาล `{player_dmg}` หน่วย")
        else:
            self.battle_log.append(f"⚔️ คุณฟันใส่ **{self.monster['name']}** สร้างความเสียหาย `{player_dmg}` หน่วย")

        self.monster_hp = max(0, self.monster_hp - player_dmg)

        # Counter attack if monster alive
        await self.monster_counter_attack()

        await self.check_battle_status(interaction)

    @discord.ui.button(label="ใช้ยา (Heal)", style=discord.ButtonStyle.success, emoji="🧪")
    async def heal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.player.potions <= 0:
            await interaction.response.send_message("❌ คุณไม่มียาฟื้นพลังหลงเหลืออยู่แล้ว!", ephemeral=True)
            return

        self.player.heal(40)
        self.battle_log.append(f"🧪 คุณดื่มขวดยาฟื้นพลัง ได้รับพลังชีวิตเพิ่มขึ้น `40` หน่วย")

        # Monster counter attack
        await self.monster_counter_attack()

        await self.check_battle_status(interaction)

    @discord.ui.button(label="หนี (Run)", style=discord.ButtonStyle.secondary, emoji="🏃")
    async def run_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        success = random.random() < 0.50
        if success:
            embed = discord.Embed(
                title="🏃 หนีสำเร็จ!",
                description=f"คุณสามารถหลบหนีออกจากพื้นที่ปะทะกับ **{self.monster['name']}** ได้อย่างปลอดภัย",
                color=0x95a5a6
            )
            self.cog.save_players()
            self.stop()
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            self.battle_log.append(f"🏃 คุณพยายามหนีแต่ **{self.monster['name']}** ขวางทางไว้ทัน!")
            
            # Counter attack
            await self.monster_counter_attack()
            await self.check_battle_status(interaction)

    async def check_battle_status(self, interaction):
        # Player Wins
        if self.monster_hp <= 0:
            gold_loot = int(self.monster["gold"] * random.uniform(0.8, 1.2))
            exp_loot = self.monster["exp"]
            
            # Potion drop chance
            potion_drop = random.random() < 0.25
            drop_text = ""
            if potion_drop:
                self.player.potions += 1
                drop_text = "\n🧪 **ดรอปไอเทม:** ได้รับ ยาฟื้นพลัง `1 ขวด`!"

            leveled_up = self.player.add_exp(exp_loot)
            self.player.gold += gold_loot
            self.player.hp = self.player.max_hp  # Restore HP to max after fight ends
            
            self.cog.save_players()
            self.stop()

            embed = discord.Embed(
                title=f"🎉 ชัยชนะเหนือ {self.monster['name']}!",
                description=f"คุณสังหารศัตรูสำเร็จ!\n\n"
                            f"💰 **ได้รับทองคำ:** `{gold_loot} ทอง` (มีสะสมทั้งหมด: {self.player.gold})\n"
                            f"🌟 **ได้รับ EXP:** `{exp_loot}`{drop_text}",
                color=0x2ecc71
            )
            
            if leveled_up:
                embed.description += f"\n\n⚡ **เลเวลอัป!** ตัวละครของคุณอัปเกรดขึ้นสู่ **Lv.{self.player.level}** แล้ว! พลังชีวิตและโจมตีเพิ่มขึ้นถาวร"

            await interaction.response.edit_message(embed=embed, view=None)
            return

        # Player Dies
        if self.player.hp <= 0:
            gold_lost = int(self.player.gold * 0.15)
            self.player.gold = max(0, self.player.gold - gold_lost)
            self.player.hp = self.player.max_hp  # Revive
            self.cog.save_players()
            self.stop()

            embed = discord.Embed(
                title="☠️ คุณพ่ายแพ้ในการต่อสู้...",
                description=f"คุณพลังชีวิตหมดลงระหว่างสู้กับ **{self.monster['name']}**\n"
                            f"ชาวเมืองช่วยพาคุณกลับมารักษาที่ปลอดภัย\n\n"
                            f"💔 **สูญเสียเงินทอง:** `- {gold_lost} ทอง` ป้องกันภัย (มีเหลือ: {self.player.gold})\n"
                            f"🩺 *พลังชีวิตได้รับการฟื้นฟูกลับมาเต็มพร้อมออกลุยอีกครั้ง*",
                color=0x7f8c8d
            )
            await interaction.response.edit_message(embed=embed, view=None)
            return

        # Update board
        await interaction.response.edit_message(embed=self.get_battle_embed(), view=self)


class ShopView(discord.ui.View):
    def __init__(self, cog, player):
        super().__init__(timeout=60.0)
        self.cog = cog
        self.player = player

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.player.user_id:
            await interaction.response.send_message("❌ เฉพาะผู้เปิดร้านค้าเท่านั้นที่เลือกซื้อของได้ครับ", ephemeral=True)
            return False
        return True

    def get_shop_embed(self):
        # Calculate costs
        potion_cost = 45
        weapon_cost = 100 * self.player.weapon_level
        armor_cost = 100 * self.player.armor_level

        embed = discord.Embed(
            title="🛒 ร้านค้าอุปกรณ์และเสบียง (Adventure Shop)",
            description=f"ใช้ทองคำอัปเกรดเพื่อลุยชั้นดันเจี้ยนที่ลึกขึ้น!\n**ทองคำของคุณ:** `{self.player.gold} ทอง`",
            color=0xf1c40f
        )
        embed.add_field(name="🧪 ขวดยาฟื้นพลัง (Potion)", value=f"• เพิ่มพลังชีวิต 40 หน่วยระหว่างสู้\n• **ราคา:** `{potion_cost} ทอง`", inline=False)
        embed.add_field(name="⚔️ อัปเกรดอาวุธ (Upgrade Weapon)", value=f"• เพิ่มพลังโจมตีถาวร +4\n• เลเวลปัจจุบัน: `{self.player.weapon_level}`\n• **ราคาอัปเกรด:** `{weapon_cost} ทอง`", inline=False)
        embed.add_field(name="🛡️ อัปเกรดชุดเกราะ (Upgrade Armor)", value=f"• เพิ่มพลังชีวิตสูงสุดถาวร +20\n• เลเวลปัจจุบัน: `{self.player.armor_level}`\n• **ราคาอัปเกรด:** `{armor_cost} ทอง`", inline=False)
        return embed

    @discord.ui.button(label="ซื้อยาฟื้นพลัง (45 ทอง)", style=discord.ButtonStyle.success, emoji="🧪")
    async def buy_potion(self, interaction: discord.Interaction, button: discord.ui.Button):
        cost = 45
        if self.player.gold >= cost:
            self.player.gold -= cost
            self.player.potions += 1
            self.cog.save_players()
            await interaction.response.edit_message(embed=self.get_shop_embed(), view=self)
            await interaction.followup.send("✅ ซื้อยาฟื้นพลังเรียบร้อย!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ คุณมีทองคำไม่เพียงพอ!", ephemeral=True)

    @discord.ui.button(label="อัปเกรดอาวุธ", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def buy_weapon(self, interaction: discord.Interaction, button: discord.ui.Button):
        cost = 100 * self.player.weapon_level
        if self.player.upgrade_weapon(cost):
            self.cog.save_players()
            await interaction.response.edit_message(embed=self.get_shop_embed(), view=self)
            await interaction.followup.send("✅ อัปเกรดอาวุธของคุณสำเร็จ! พลังโจมตีเพิ่มขึ้นถาวร", ephemeral=True)
        else:
            await interaction.response.send_message("❌ คุณมีทองคำไม่เพียงพอ!", ephemeral=True)

    @discord.ui.button(label="อัปเกรดเกราะ", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def buy_armor(self, interaction: discord.Interaction, button: discord.ui.Button):
        cost = 100 * self.player.armor_level
        if self.player.upgrade_armor(cost):
            self.cog.save_players()
            await interaction.response.edit_message(embed=self.get_shop_embed(), view=self)
            await interaction.followup.send("✅ อัปเกรดชุดเกราะของคุณสำเร็จ! เลือดสูงสุดเพิ่มขึ้นถาวร", ephemeral=True)
        else:
            await interaction.response.send_message("❌ คุณมีทองคำไม่เพียงพอ!", ephemeral=True)


class RPGCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}
        self.load_players()

    def load_players(self):
        """Loads all player profiles from database JSON."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for uid, stats in data.items():
                        self.players[uid] = RPGPlayer(
                            user_id=uid,
                            class_name=stats["class_name"],
                            level=stats["level"],
                            exp=stats["exp"],
                            gold=stats["gold"],
                            hp=stats["hp"],
                            max_hp=stats["max_hp"],
                            atk=stats["atk"],
                            potions=stats["potions"],
                            weapon_level=stats["weapon_level"],
                            armor_level=stats["armor_level"]
                        )
            except Exception as e:
                logger.error(f"Error loading RPG players data: {e}")

    def save_players(self):
        """Saves current player statistics state to JSON."""
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        try:
            data = {uid: player.to_dict() for uid, player in self.players.items()}
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Error saving RPG players data: {e}")

    def get_player(self, user_id) -> RPGPlayer:
        return self.players.get(str(user_id))

    @app_commands.command(name="rpg-start", description="เริ่มต้นสร้างตัวละคร RPG และออกผจญภัย")
    async def rpg_start(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid in self.players:
            player = self.players[uid]
            embed = discord.Embed(
                description=f"⚠️ **คุณมีตัวละครอยู่แล้ว!**\nตัวละครของคุณในปัจจุบันคือ **{player.class_name} เลเวล {player.level}** ใช้คำสั่ง `/rpg-status` เพื่อตรวจสอบรายละเอียดครับ",
                color=0xf1c40f
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="⚔️ การสร้างตัวละครนักผจญภัย",
            description="กรุณาเลือกสายอาชีพหลักของคุณเพื่อเริ่มต้นผจญภัยตะลุยดันเจี้ยน:",
            color=0x3498db
        )
        for class_name, info in CLASSES.items():
            embed.add_field(name=f"{info['icon']} {class_name}", value=info["desc"], inline=False)

        view = ClassSelectView(self, uid)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="rpg-status", description="เช็คเลเวลและสถานะตัวละครปัจจุบันของคุณ")
    async def rpg_status(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = self.get_player(uid)
        
        if not player:
            await interaction.response.send_message("❌ คุณยังไม่มีตัวละคร! พิมพ์ `/rpg-start` เพื่อเริ่มก่อนครับ", ephemeral=True)
            return

        # Build stats card
        class_info = CLASSES.get(player.class_name, {"icon": "❓"})
        exp_needed = player.level * 100
        exp_percent = int((player.exp / exp_needed) * 100)
        exp_bar = f"`{'★' * int(player.exp / exp_needed * 10)}{'☆' * (10 - int(player.exp / exp_needed * 10))}`"

        embed = discord.Embed(
            title=f"{class_info['icon']} โปรไฟล์นักผจญภัย: {interaction.user.name}",
            color=0x3498db
        )
        embed.add_field(name="🛡️ สายอาชีพ", value=f"`{player.class_name}`", inline=True)
        embed.add_field(name="⚡ เลเวล", value=f"`Lv.{player.level}`", inline=True)
        embed.add_field(name="🌟 ประสบการณ์ (EXP)", value=f"{exp_bar} {exp_percent}% (`{player.exp}/{exp_needed}`)", inline=False)
        
        embed.add_field(name="❤️ พลังชีวิตสูงสุด", value=f"`{player.max_hp} HP`", inline=True)
        embed.add_field(name="⚔️ พลังโจมตีรวม", value=f"`{player.atk} ATK`", inline=True)
        embed.add_field(name="🧪 ขวดยาฟื้นพลัง", value=f"`{player.potions} ขวด`", inline=True)
        
        embed.add_field(name="🗡️ ระดับระดับดาบ", value=f"`Lv.{player.weapon_level}`", inline=True)
        embed.add_field(name="🛡️ ระดับระดับเกราะ", value=f"`Lv.{player.armor_level}`", inline=True)
        embed.add_field(name="💰 ทองสะสมทั้งหมด", value=f"`{player.gold} ทอง`", inline=True)

        avatar_url = interaction.user.display_avatar.url
        embed.set_thumbnail(url=avatar_url)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rpg-dungeon", description="ก้าวเข้าสู่ดันเจี้ยนเพื่อท้าสู้กับมอนสเตอร์และรับรางวัล")
    async def rpg_dungeon(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = self.get_player(uid)
        
        if not player:
            await interaction.response.send_message("❌ คุณยังไม่มีตัวละคร! พิมพ์ `/rpg-start` เพื่อเริ่มสร้างตัวก่อนครับ", ephemeral=True)
            return

        # Restore HP to max before starting a dungeon fight just in case
        player.hp = player.max_hp

        # Filter monsters suitable for player's level
        available_monsters = [m for m in MONSTERS if player.level >= m["min_level"]]
        if not available_monsters:
            available_monsters = [MONSTERS[0]]

        # Pick random monster
        monster = random.choice(available_monsters).copy()
        
        # Add slight HP/ATK variance to the monster
        monster["hp"] = int(monster["hp"] * random.uniform(0.9, 1.1))
        monster["atk"] = int(monster["atk"] * random.uniform(0.9, 1.1))

        view = BattleView(self, player, monster)
        await interaction.response.send_message(embed=view.get_battle_embed(), view=view)

    @app_commands.command(name="rpg-shop", description="เปิดร้านค้าอัปเกรดอาวุธและซื้อเสบียง")
    async def rpg_shop(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = self.get_player(uid)
        
        if not player:
            await interaction.response.send_message("❌ คุณยังไม่มีตัวละคร! พิมพ์ `/rpg-start` เพื่อเริ่มก่อนครับ", ephemeral=True)
            return

        view = ShopView(self, player)
        await interaction.response.send_message(embed=view.get_shop_embed(), view=view)

async def setup(bot):
    await bot.add_cog(RPGCog(bot))
