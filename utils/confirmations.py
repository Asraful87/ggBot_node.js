"""
Confirmation views for destructive actions
"""
import discord
from discord import ui


class ConfirmView(ui.View):
    """A view with confirm and cancel buttons"""
    
    def __init__(self, author: discord.Member, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.author = author
        self.value = None
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the command author can use the buttons"""
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "You cannot use this button.",
                ephemeral=True
            )
            return False
        return True
    
    @ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        """Confirm button"""
        self.value = True
        self.stop()
        await interaction.response.defer()
    
    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        """Cancel button"""
        self.value = False
        self.stop()
        await interaction.response.defer()
    #yyyyy
    async def on_timeout(self):
        """Called when the view times out"""
        self.value = False
        self.stop()
