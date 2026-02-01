const { SlashCommandBuilder, EmbedBuilder, PermissionFlagsBits } = require('discord.js');
const fs = require('fs');
const yaml = require('js-yaml');
const path = require('path');

const DEFAULT_CONFIG = {
    automod: {
        enabled: false,
        action_on_violation: 'warn',
        max_mentions: 5,
        block_discord_invites: true,
        block_links: false,
        blocked_words: []
    },
    antispam: {
        enabled: false,
        max_messages: 6,
        per_seconds: 8,
        spam_action: 'timeout'
    }
};

function loadConfig(configPath, bot) {
    try {
        if (fs.existsSync(configPath)) {
            const parsed = yaml.load(fs.readFileSync(configPath, 'utf8')) || {};
            return parsed;
        }
    } catch (e) {
        // fall through to defaults
    }

    // If the main bot already loaded config into memory, use it as a base.
    if (bot && bot.config && typeof bot.config === 'object') {
        return bot.config;
    }

    return { ...DEFAULT_CONFIG };
}

function ensureAutomodShape(config) {
    if (!config || typeof config !== 'object') config = {};

    if (!config.automod || typeof config.automod !== 'object') config.automod = {};
    if (!config.antispam || typeof config.antispam !== 'object') config.antispam = {};

    config.automod.enabled = Boolean(config.automod.enabled);
    config.automod.action_on_violation = config.automod.action_on_violation || DEFAULT_CONFIG.automod.action_on_violation;
    config.automod.max_mentions = Number.isFinite(Number(config.automod.max_mentions)) ? Number(config.automod.max_mentions) : DEFAULT_CONFIG.automod.max_mentions;
    config.automod.block_discord_invites = config.automod.block_discord_invites !== undefined ? Boolean(config.automod.block_discord_invites) : DEFAULT_CONFIG.automod.block_discord_invites;
    config.automod.block_links = config.automod.block_links !== undefined ? Boolean(config.automod.block_links) : DEFAULT_CONFIG.automod.block_links;
    if (!Array.isArray(config.automod.blocked_words)) config.automod.blocked_words = [];

    config.antispam.enabled = Boolean(config.antispam.enabled);
    config.antispam.max_messages = Number.isFinite(Number(config.antispam.max_messages)) ? Number(config.antispam.max_messages) : DEFAULT_CONFIG.antispam.max_messages;
    config.antispam.per_seconds = Number.isFinite(Number(config.antispam.per_seconds)) ? Number(config.antispam.per_seconds) : DEFAULT_CONFIG.antispam.per_seconds;
    config.antispam.spam_action = config.antispam.spam_action || DEFAULT_CONFIG.antispam.spam_action;

    return config;
}

function saveConfig(configPath, config) {
    const dir = path.dirname(configPath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(configPath, yaml.dump(config), 'utf8');
}

module.exports = {
    data: new SlashCommandBuilder()
        .setName('setup_automod')
        .setDescription('Configure AutoMod settings')
        .addSubcommand(subcommand =>
            subcommand
                .setName('toggle')
                .setDescription('Enable or disable AutoMod')
                .addBooleanOption(option =>
                    option.setName('enabled')
                        .setDescription('Enable AutoMod')
                        .setRequired(true)))
        .addSubcommand(subcommand =>
            subcommand
                .setName('status')
                .setDescription('Check AutoMod status'))
        .addSubcommand(subcommand =>
            subcommand
                .setName('add_word')
                .setDescription('Add a blocked word/phrase')
                .addStringOption(option =>
                    option.setName('word')
                        .setDescription('The word or phrase to block')
                        .setRequired(true)))
        .addSubcommand(subcommand =>
            subcommand
                .setName('remove_word')
                .setDescription('Remove a blocked word/phrase')
                .addStringOption(option =>
                    option.setName('word')
                        .setDescription('The word or phrase to unblock')
                        .setRequired(true)))
        .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),

    async execute(interaction, bot) {
        const subcommand = interaction.options.getSubcommand();
        const configPath = path.join(__dirname, '../../config.yaml');
        let config = ensureAutomodShape(loadConfig(configPath, bot));

        if (subcommand === 'toggle') {
            const enabled = interaction.options.getBoolean('enabled');
            config.automod.enabled = enabled;
            
            try {
                saveConfig(configPath, config);
            } catch (e) {
                console.error('Failed to save config.yaml:', e);
            }

            if (bot && bot.config) {
                bot.config.automod = config.automod;
                bot.config.antispam = config.antispam;
            }
            
            const embed = new EmbedBuilder()
                .setColor(enabled ? 0x00ff00 : 0xff0000)
                .setTitle('⚙️ AutoMod Configuration')
                .setDescription(`AutoMod has been **${enabled ? 'enabled' : 'disabled'}**`)
                .setTimestamp();
            
            await interaction.reply({ embeds: [embed] });
        } 
        else if (subcommand === 'status') {
            const automod = config.automod;
            const antispam = config.antispam;
            
            const embed = new EmbedBuilder()
                .setColor(automod.enabled ? 0x00ff00 : 0xff0000)
                .setTitle('🛡️ AutoMod Status')
                .addFields(
                    { name: 'Status', value: automod.enabled ? '✅ Enabled' : '❌ Disabled', inline: true },
                    { name: 'Action on Violation', value: automod.action_on_violation, inline: true },
                    { name: 'Max Mentions', value: automod.max_mentions.toString(), inline: true },
                    { name: 'Block Discord Invites', value: automod.block_discord_invites ? 'Yes' : 'No', inline: true },
                    { name: 'Block Links', value: automod.block_links ? 'Yes' : 'No', inline: true },
                    { name: 'Blocked Words', value: `${automod.blocked_words.length} words/phrases`, inline: true },
                    { name: '\u200B', value: '**Anti-Spam Settings**' },
                    { name: 'Anti-Spam', value: antispam.enabled ? '✅ Enabled' : '❌ Disabled', inline: true },
                    { name: 'Rate Limit', value: `${antispam.max_messages} messages/${antispam.per_seconds}s`, inline: true },
                    { name: 'Spam Action', value: antispam.spam_action, inline: true }
                )
                .setTimestamp();
            
            await interaction.reply({ embeds: [embed] });
        }
        else if (subcommand === 'add_word') {
            const word = interaction.options.getString('word').toLowerCase();
            
            if (!config.automod.blocked_words.includes(word)) {
                config.automod.blocked_words.push(word);
                try {
                    saveConfig(configPath, config);
                } catch (e) {
                    console.error('Failed to save config.yaml:', e);
                }

                if (bot && bot.config) {
                    bot.config.automod = config.automod;
                    bot.config.antispam = config.antispam;
                }
                
                const embed = new EmbedBuilder()
                    .setColor(0x00ff00)
                    .setTitle('✅ Word Added')
                    .setDescription(`Added \`${word}\` to blocked words list`)
                    .setTimestamp();
                
                await interaction.reply({ embeds: [embed] });
            } else {
                await interaction.reply({ content: '❌ That word is already in the blocked list!', ephemeral: true });
            }
        }
        else if (subcommand === 'remove_word') {
            const word = interaction.options.getString('word').toLowerCase();
            const index = config.automod.blocked_words.indexOf(word);
            
            if (index > -1) {
                config.automod.blocked_words.splice(index, 1);
                try {
                    saveConfig(configPath, config);
                } catch (e) {
                    console.error('Failed to save config.yaml:', e);
                }

                if (bot && bot.config) {
                    bot.config.automod = config.automod;
                    bot.config.antispam = config.antispam;
                }
                
                const embed = new EmbedBuilder()
                    .setColor(0x00ff00)
                    .setTitle('✅ Word Removed')
                    .setDescription(`Removed \`${word}\` from blocked words list`)
                    .setTimestamp();
                
                await interaction.reply({ embeds: [embed] });
            } else {
                await interaction.reply({ content: '❌ That word is not in the blocked list!', ephemeral: true });
            }
        }
    }
};
