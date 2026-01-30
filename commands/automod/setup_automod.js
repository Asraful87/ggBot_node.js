const { SlashCommandBuilder, EmbedBuilder, PermissionFlagsBits } = require('discord.js');
const fs = require('fs');
const yaml = require('js-yaml');
const path = require('path');

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

    async execute(interaction) {
        const subcommand = interaction.options.getSubcommand();
        const configPath = path.join(__dirname, '../../config.yaml');
        const config = yaml.load(fs.readFileSync(configPath, 'utf8'));

        if (subcommand === 'toggle') {
            const enabled = interaction.options.getBoolean('enabled');
            config.automod.enabled = enabled;
            
            fs.writeFileSync(configPath, yaml.dump(config));
            
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
                fs.writeFileSync(configPath, yaml.dump(config));
                
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
                fs.writeFileSync(configPath, yaml.dump(config));
                
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
