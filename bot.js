const { Client, GatewayIntentBits, Collection } = require('discord.js');
const { readdirSync } = require('fs');
const { join } = require('path');
const yaml = require('js-yaml');
const fs = require('fs');
const dotenv = require('dotenv');
const DatabaseManager = require('./database/db_manager');
const { setupLogging, getLogger } = require('./utils/logging');

dotenv.config();

// Load config
const config = yaml.load(fs.readFileSync('config.yaml', 'utf8'));

// Setup logging
setupLogging();
const logger = getLogger('modbot');

class ModBot extends Client {
    constructor() {
        super({
            intents: [
                GatewayIntentBits.Guilds,
                GatewayIntentBits.GuildMembers,
                GatewayIntentBits.GuildMessages,
                GatewayIntentBits.MessageContent,
                GatewayIntentBits.GuildVoiceStates,
                GatewayIntentBits.GuildPresences
            ]
        });

        this.config = config;
        this.db = new DatabaseManager();
        this.commands = new Collection();
        this.synced = false;
    }

    async loadCommands() {
        const commandsPath = join(__dirname, 'commands');
        
        if (!fs.existsSync(commandsPath)) {
            fs.mkdirSync(commandsPath, { recursive: true });
        }

        const commandFolders = readdirSync(commandsPath);

        for (const folder of commandFolders) {
            const folderPath = join(commandsPath, folder);
            if (!fs.statSync(folderPath).isDirectory()) continue;

            const commandFiles = readdirSync(folderPath).filter(file => file.endsWith('.js'));

            for (const file of commandFiles) {
                try {
                    const command = require(join(folderPath, file));
                    if ('data' in command && 'execute' in command) {
                        this.commands.set(command.data.name, command);
                        logger.info(`Loaded command: ${folder}/${file}`);
                    }
                } catch (error) {
                    logger.error(`Failed to load command ${folder}/${file}:`, error);
                }
            }
        }
    }

    async setupHook() {
        try {
            await this.db.initDb();
            logger.info('Database initialized');
        } catch (error) {
            logger.error('DB init failed:', error);
        }

        await this.loadCommands();
    }
}

const bot = new ModBot();

bot.once('ready', async () => {
    if (!bot.synced) {
        const guildId = process.env.GUILD_ID;
        
        try {
            if (guildId) {
                const guild = bot.guilds.cache.get(guildId);
                if (guild) {
                    const commands = Array.from(bot.commands.values()).map(cmd => cmd.data);
                    await guild.commands.set(commands);
                    logger.info(`✅ Guild-synced ${commands.length} slash commands to guild ${guildId}`);
                }
            } else {
                const commands = Array.from(bot.commands.values()).map(cmd => cmd.data);
                await bot.application.commands.set(commands);
                logger.info(`✅ Globally synced ${commands.length} slash commands`);
            }
            bot.synced = true;
        } catch (error) {
            logger.error('Failed to sync commands:', error);
        }
    }

    logger.info(`Logged in as ${bot.user.tag} (ID: ${bot.user.id})`);
    logger.info(`Connected to ${bot.guilds.cache.size} guild(s)`);
});

bot.on('interactionCreate', async interaction => {
    // Handle button interactions
    if (interaction.isButton()) {
        const [action, type] = interaction.customId.split(':');
        
        if (action === 'verify' && type === 'button') {
            // Handle verification button
            const verifyCommand = bot.commands.get('post_verify');
            if (verifyCommand && verifyCommand.handleVerifyButton) {
                try {
                    await verifyCommand.handleVerifyButton(interaction, bot);
                } catch (error) {
                    logger.error('Verify button error:', error);
                }
            }
            return;
        }
        
        // Handle ticket buttons
        if (action === 'ticket') {
            const ticketCommand = bot.commands.get('post_ticket_panel');
            if (ticketCommand && ticketCommand.handleTicketButton) {
                try {
                    await ticketCommand.handleTicketButton(interaction, bot, type);
                } catch (error) {
                    logger.error('Ticket button error:', error);
                }
            }
            return;
        }
    }
    
    // Handle select menu interactions
    if (interaction.isStringSelectMenu()) {
        const [action, type] = interaction.customId.split(':');
        
        if (action === 'ticket' && type === 'select') {
            const ticketCommand = bot.commands.get('post_ticket_panel');
            if (ticketCommand && ticketCommand.handleTicketSelect) {
                try {
                    await ticketCommand.handleTicketSelect(interaction, bot);
                } catch (error) {
                    logger.error('Ticket select error:', error);
                }
            }
            return;
        }
    }
    
    // Handle slash commands
    if (!interaction.isChatInputCommand()) return;

    const command = bot.commands.get(interaction.commandName);
    if (!command) return;

    try {
        await command.execute(interaction, bot);
    } catch (error) {
        logger.error(`Command error in ${interaction.commandName}:`, error);
        
        const errorMessage = `❌ An error occurred: ${error.message}`;
        
        try {
            if (!interaction.replied && !interaction.deferred) {
                await interaction.reply({ content: errorMessage, ephemeral: true });
            } else {
                await interaction.followUp({ content: errorMessage, ephemeral: true });
            }
        } catch (err) {
            logger.error(`Failed to send error message for interaction ${interaction.id}`);
        }
    }
});

// AutoMod: Message monitoring
bot.on('messageCreate', async (message) => {
    if (message.author.bot || !message.guild) return;
    
    const automod = bot.config.automod;
    if (!automod.enabled) return;
    
    // Check exempt roles/channels
    if (automod.exempt_channel_ids.includes(message.channel.id)) return;
    const memberRoles = message.member.roles.cache.map(r => r.id);
    if (automod.exempt_role_ids.some(roleId => memberRoles.includes(roleId))) return;
    
    let violation = null;
    
    // Check mention spam
    const mentions = message.mentions.users.size + message.mentions.roles.size;
    if (mentions > automod.max_mentions) {
        violation = `Mention spam (${mentions} mentions)`;
    }
    
    // Check Discord invites
    if (automod.block_discord_invites && /discord(?:\.gg|app\.com\/invite)\/[\w-]+/i.test(message.content)) {
        violation = 'Discord invite link';
    }
    
    // Check all links
    if (automod.block_links && /https?:\/\/[\w\-\.]+/i.test(message.content)) {
        const memberRole = message.guild.roles.cache.find(r => r.name === automod.member_role_name);
        if (memberRole && message.member.roles.cache.has(memberRole.id)) {
            violation = 'Link posted by member';
        }
    }
    
    // Check blocked words
    const content = message.content.toLowerCase();
    for (const word of automod.blocked_words) {
        if (content.includes(word.toLowerCase())) {
            violation = `Blocked word: ${word}`;
            break;
        }
    }
    
    if (violation) {
        try {
            await message.delete();
            
            const action = automod.action_on_violation;
            if (action === 'warn' || action === 'timeout') {
                const reason = `AutoMod: ${violation}`;
                
                if (action === 'timeout') {
                    await message.member.timeout(automod.repeat_timeout_minutes * 60 * 1000, reason);
                    await message.channel.send(`⚠️ ${message.author} has been timed out for ${automod.repeat_timeout_minutes} minutes. Reason: ${violation}`).then(m => setTimeout(() => m.delete(), 5000));
                }
            }
            
            logger.info(`AutoMod: Deleted message from ${message.author.tag} - ${violation}`);
        } catch (error) {
            logger.error('AutoMod error:', error);
        }
    }
});

// Anti-Spam: Rate limiting
const messageCache = new Map(); // userId -> array of timestamps
const duplicateCache = new Map(); // userId -> array of message contents

bot.on('messageCreate', async (message) => {
    if (message.author.bot || !message.guild) return;
    
    const antispam = bot.config.antispam;
    if (!antispam.enabled) return;
    
    const userId = message.author.id;
    const now = Date.now();
    
    // Rate limiting
    if (!messageCache.has(userId)) {
        messageCache.set(userId, []);
    }
    const userMessages = messageCache.get(userId);
    userMessages.push(now);
    
    // Remove old messages
    const cutoff = now - (antispam.per_seconds * 1000);
    messageCache.set(userId, userMessages.filter(t => t > cutoff));
    
    if (userMessages.length > antispam.max_messages) {
        try {
            await message.delete();
            
            if (antispam.spam_action === 'timeout') {
                await message.member.timeout(antispam.spam_timeout_minutes * 60 * 1000, 'Anti-Spam: Message rate limit exceeded');
                await message.channel.send(`⚠️ ${message.author} has been timed out for ${antispam.spam_timeout_minutes} minutes for spamming.`).then(m => setTimeout(() => m.delete(), 5000));
            }
            
            messageCache.delete(userId);
            logger.info(`Anti-Spam: Timed out ${message.author.tag} for rate limit`);
            return;
        } catch (error) {
            logger.error('Anti-Spam error:', error);
        }
    }
    
    // Duplicate detection
    if (!duplicateCache.has(userId)) {
        duplicateCache.set(userId, []);
    }
    const userDuplicates = duplicateCache.get(userId);
    userDuplicates.push({ content: message.content, time: now });
    
    // Remove old duplicates
    const dupCutoff = now - (antispam.duplicate_window_seconds * 1000);
    duplicateCache.set(userId, userDuplicates.filter(m => m.time > dupCutoff));
    
    const recentDuplicates = userDuplicates.filter(m => m.content === message.content);
    if (recentDuplicates.length >= antispam.max_duplicates) {
        try {
            await message.delete();
            
            if (antispam.spam_action === 'timeout') {
                await message.member.timeout(antispam.spam_timeout_minutes * 60 * 1000, 'Anti-Spam: Duplicate messages');
                await message.channel.send(`⚠️ ${message.author} has been timed out for ${antispam.spam_timeout_minutes} minutes for duplicate spam.`).then(m => setTimeout(() => m.delete(), 5000));
            }
            
            duplicateCache.delete(userId);
            logger.info(`Anti-Spam: Timed out ${message.author.tag} for duplicate spam`);
        } catch (error) {
            logger.error('Anti-Spam duplicate error:', error);
        }
    }
});

// Anti-Raid: Join monitoring
const joinCache = new Map(); // guildId -> array of join timestamps

bot.on('guildMemberAdd', async (member) => {
    const antiraid = bot.config.antiraid;
    if (!antiraid.enabled) return;
    
    const guildId = member.guild.id;
    const now = Date.now();
    
    // Track joins
    if (!joinCache.has(guildId)) {
        joinCache.set(guildId, []);
    }
    const guildJoins = joinCache.get(guildId);
    guildJoins.push(now);
    
    // Remove old joins
    const cutoff = now - (antiraid.join_interval_seconds * 1000);
    joinCache.set(guildId, guildJoins.filter(t => t > cutoff));
    
    // Check account age
    const accountAge = (now - member.user.createdTimestamp) / (1000 * 60 * 60 * 24);
    const isNewAccount = accountAge < antiraid.min_account_age_days;
    
    // Detect raid
    if (guildJoins.length >= antiraid.join_threshold) {
        logger.warn(`Anti-Raid: Possible raid detected in ${member.guild.name} (${guildJoins.length} joins in ${antiraid.join_interval_seconds}s)`);
        
        // Auto-timeout new joiners
        if (isNewAccount) {
            try {
                await member.timeout(antiraid.auto_timeout_minutes * 60 * 1000, 'Anti-Raid: New account during raid');
                logger.info(`Anti-Raid: Timed out ${member.user.tag} (account age: ${accountAge.toFixed(1)} days)`);
            } catch (error) {
                logger.error('Anti-Raid timeout error:', error);
            }
        }
    } else if (isNewAccount && guildJoins.length >= antiraid.join_threshold / 2) {
        // Suspicious new account
        try {
            await member.timeout(antiraid.auto_timeout_minutes * 60 * 1000, 'Anti-Raid: Suspicious new account');
            logger.info(`Anti-Raid: Timed out suspicious new account ${member.user.tag} (age: ${accountAge.toFixed(1)} days)`);
        } catch (error) {
            logger.error('Anti-Raid timeout error:', error);
        }
    }
});

async function main() {
    const token = process.env.DISCORD_TOKEN;
    
    if (!token) {
        throw new Error('DISCORD_TOKEN is not set. Add it to your .env file.');
    }

    try {
        await bot.setupHook();
        await bot.login(token);
    } catch (error) {
        if (error.code === 'TOKEN_INVALID') {
            logger.error('Discord login failed: invalid DISCORD_TOKEN. Regenerate the bot token and update your .env file.');
        } else {
            logger.error('Unexpected error during bot execution:', error);
        }
        process.exit(1);
    }
}

process.on('SIGINT', () => {
    logger.info('Bot stopped');
    bot.destroy();
    process.exit(0);
});

process.on('unhandledRejection', error => {
    logger.error('Unhandled promise rejection:', error);
});

main().catch(error => {
    logger.error('Fatal error:', error);
    process.exit(1);
});
