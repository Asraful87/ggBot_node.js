const { SlashCommandBuilder, PermissionFlagsBits, EmbedBuilder, ButtonBuilder, ButtonStyle, ActionRowBuilder } = require('discord.js');
const { successEmbed, errorEmbed } = require('../../utils/embeds');
const yaml = require('js-yaml');
const fs = require('fs');
const path = require('path');

// Load config
let config;
try {
    const configPath = path.join(__dirname, '../../config.yaml');
    if (fs.existsSync(configPath)) {
        config = yaml.load(fs.readFileSync(configPath, 'utf8'));
    } else {
        config = {
            verification: {
                role_name: 'Verified',
                panel_title: '✅ Verification',
                panel_description: 'Click **Verify** to unlock the server.'
            }
        };
    }
} catch (e) {
    console.error('Failed to load config.yaml:', e?.message || String(e));
    config = {
        verification: {
            role_name: 'Verified',
            panel_title: '✅ Verification',
            panel_description: 'Click **Verify** to unlock the server.'
        }
    };
}

const verificationConfig = config.verification || {
    role_name: 'Verified',
    panel_title: '✅ Verification',
    panel_description: 'Click **Verify** to unlock the server.'
};

module.exports = {
    data: new SlashCommandBuilder()
        .setName('post_verify')
        .setDescription('Post the verification panel with button')
        .addChannelOption(option =>
            option.setName('channel')
                .setDescription('Channel to post verification panel in (default: current channel)')
                .setRequired(false))
        .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),

    async execute(interaction, bot) {
        const targetChannel = interaction.options.getChannel('channel') || interaction.channel;

        // Check if target is a text channel
        if (!targetChannel.isTextBased()) {
            return interaction.reply({
                embeds: [errorEmbed('Error', 'Target must be a text channel.')],
                ephemeral: true
            });
        }

        await interaction.deferReply({ ephemeral: true });

        try {
            // Create embed
            const embed = new EmbedBuilder()
                .setTitle(verificationConfig.panel_title)
                .setDescription(verificationConfig.panel_description)
                .setColor('Green')
                .setTimestamp();

            // Create button
            const button = new ButtonBuilder()
                .setCustomId('verify:button')
                .setLabel('Verify')
                .setStyle(ButtonStyle.Success)
                .setEmoji('✅');

            const row = new ActionRowBuilder()
                .addComponents(button);

            // Send the panel
            await targetChannel.send({
                embeds: [embed],
                components: [row]
            });

            await interaction.editReply({
                embeds: [successEmbed('Success', `✅ Verification panel posted in ${targetChannel}`)]
            });
        } catch (error) {
            console.error('Post verify error:', error);
            await interaction.editReply({
                embeds: [errorEmbed('Error', `Failed to post verification panel: ${error.message}`)]
            });
        }
    },

    // This function handles the button interaction
    async handleVerifyButton(interaction, bot) {
        try {
            const member = interaction.member;
            const guild = interaction.guild;

            // Find the verification role
            const roleName = verificationConfig.role_name;
            const role = guild.roles.cache.find(r => r.name === roleName);

            if (!role) {
                return interaction.reply({
                    embeds: [errorEmbed('Error', `Role \`${roleName}\` not found. Please ask an administrator to create it.`)],
                    ephemeral: true
                });
            }

            // Check if user already has the role
            if (member.roles.cache.has(role.id)) {
                return interaction.reply({
                    content: '✅ You are already verified.',
                    ephemeral: true
                });
            }

            // Add the role
            try {
                await member.roles.add(role, 'User verified via bot');
                
                await interaction.reply({
                    embeds: [successEmbed('Verified!', '✅ You are now verified! Welcome to the server.')],
                    ephemeral: true
                });

                console.log(`${member.user.tag} verified in ${guild.name}`);
            } catch (roleError) {
                if (roleError.code === 50013) {
                    return interaction.reply({
                        embeds: [errorEmbed('Error', "I don't have permission to assign that role. Please ask an administrator to move my bot role above the Verified role.")],
                        ephemeral: true
                    });
                }
                throw roleError;
            }
        } catch (error) {
            console.error('Verify button error:', error);
            
            // Handle if response already sent
            const errorMessage = errorEmbed('Error', `An error occurred: ${error.message}`);
            if (interaction.replied || interaction.deferred) {
                await interaction.followUp({
                    embeds: [errorMessage],
                    ephemeral: true
                }).catch(() => {});
            } else {
                await interaction.reply({
                    embeds: [errorMessage],
                    ephemeral: true
                }).catch(() => {});
            }
        }
    }
};
