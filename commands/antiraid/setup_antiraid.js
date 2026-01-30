const { SlashCommandBuilder, EmbedBuilder, PermissionFlagsBits } = require('discord.js');
const fs = require('fs');
const yaml = require('js-yaml');
const path = require('path');

module.exports = {
    data: new SlashCommandBuilder()
        .setName('setup_antiraid')
        .setDescription('Configure Anti-Raid settings')
        .addSubcommand(subcommand =>
            subcommand
                .setName('toggle')
                .setDescription('Enable or disable Anti-Raid')
                .addBooleanOption(option =>
                    option.setName('enabled')
                        .setDescription('Enable Anti-Raid protection')
                        .setRequired(true)))
        .addSubcommand(subcommand =>
            subcommand
                .setName('status')
                .setDescription('Check Anti-Raid status'))
        .addSubcommand(subcommand =>
            subcommand
                .setName('lockdown')
                .setDescription('Lock down the server to prevent raids'))
        .addSubcommand(subcommand =>
            subcommand
                .setName('unlock')
                .setDescription('Remove server lockdown'))
        .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),

    async execute(interaction) {
        const subcommand = interaction.options.getSubcommand();
        const configPath = path.join(__dirname, '../../config.yaml');
        const config = yaml.load(fs.readFileSync(configPath, 'utf8'));

        if (subcommand === 'toggle') {
            const enabled = interaction.options.getBoolean('enabled');
            config.antiraid.enabled = enabled;
            
            fs.writeFileSync(configPath, yaml.dump(config));
            
            const embed = new EmbedBuilder()
                .setColor(enabled ? 0x00ff00 : 0xff0000)
                .setTitle('⚙️ Anti-Raid Configuration')
                .setDescription(`Anti-Raid protection has been **${enabled ? 'enabled' : 'disabled'}**`)
                .setTimestamp();
            
            await interaction.reply({ embeds: [embed] });
        } 
        else if (subcommand === 'status') {
            const antiraid = config.antiraid;
            
            const embed = new EmbedBuilder()
                .setColor(antiraid.enabled ? 0x00ff00 : 0xff0000)
                .setTitle('🛡️ Anti-Raid Status')
                .addFields(
                    { name: 'Status', value: antiraid.enabled ? '✅ Enabled' : '❌ Disabled', inline: true },
                    { name: 'Join Threshold', value: `${antiraid.join_threshold} users`, inline: true },
                    { name: 'Join Interval', value: `${antiraid.join_interval_seconds} seconds`, inline: true },
                    { name: 'Min Account Age', value: `${antiraid.min_account_age_days} days`, inline: true },
                    { name: 'Auto Timeout', value: `${antiraid.auto_timeout_minutes} minutes`, inline: true },
                    { name: '\u200B', value: '\u200B', inline: true }
                )
                .setDescription('Monitors for suspicious join patterns and new accounts')
                .setTimestamp();
            
            await interaction.reply({ embeds: [embed] });
        }
        else if (subcommand === 'lockdown') {
            await interaction.deferReply();
            
            const guild = interaction.guild;
            let channelsLocked = 0;
            
            // Get @everyone role
            const everyoneRole = guild.roles.everyone;
            
            // Lock all text channels
            for (const [, channel] of guild.channels.cache) {
                if (channel.isTextBased() && !channel.isThread()) {
                    try {
                        await channel.permissionOverwrites.edit(everyoneRole, {
                            SendMessages: false,
                            AddReactions: false,
                            CreatePublicThreads: false,
                            CreatePrivateThreads: false
                        });
                        channelsLocked++;
                    } catch (error) {
                        console.error(`Failed to lock ${channel.name}:`, error);
                    }
                }
            }
            
            const embed = new EmbedBuilder()
                .setColor(0xff0000)
                .setTitle('🔒 Server Lockdown Activated')
                .setDescription(`Locked ${channelsLocked} channels to prevent raid damage`)
                .addFields(
                    { name: 'Locked Permissions', value: '• Send Messages\n• Add Reactions\n• Create Threads' }
                )
                .setFooter({ text: 'Use /setup_antiraid unlock to remove lockdown' })
                .setTimestamp();
            
            await interaction.editReply({ embeds: [embed] });
        }
        else if (subcommand === 'unlock') {
            await interaction.deferReply();
            
            const guild = interaction.guild;
            let channelsUnlocked = 0;
            
            // Get @everyone role
            const everyoneRole = guild.roles.everyone;
            
            // Unlock all text channels
            for (const [, channel] of guild.channels.cache) {
                if (channel.isTextBased() && !channel.isThread()) {
                    try {
                        await channel.permissionOverwrites.edit(everyoneRole, {
                            SendMessages: null,
                            AddReactions: null,
                            CreatePublicThreads: null,
                            CreatePrivateThreads: null
                        });
                        channelsUnlocked++;
                    } catch (error) {
                        console.error(`Failed to unlock ${channel.name}:`, error);
                    }
                }
            }
            
            const embed = new EmbedBuilder()
                .setColor(0x00ff00)
                .setTitle('🔓 Server Lockdown Removed')
                .setDescription(`Unlocked ${channelsUnlocked} channels`)
                .setFooter({ text: 'Normal server operations resumed' })
                .setTimestamp();
            
            await interaction.editReply({ embeds: [embed] });
        }
    }
};
