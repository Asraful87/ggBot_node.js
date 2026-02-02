// Load encryption library FIRST before discord.js voice
require('./utils/sodium');

const { Client, GatewayIntentBits, Collection, REST, Routes } = require('discord.js');
const { readdirSync } = require('fs');
const { join } = require('path');
const yaml = require('js-yaml');
const fs = require('fs');
const dotenv = require('dotenv');
const play = require('play-dl');
const DatabaseManager = require('./database/db_manager');
const { setupLogging, getLogger } = require('./utils/logging');
const ffmpegStatic = require('ffmpeg-static');
const crypto = require('crypto');

dotenv.config();

// Set FFmpeg path for audio (portable)
// Allow user override via env var.
if (!process.env.FFMPEG_PATH && ffmpegStatic) {
    process.env.FFMPEG_PATH = ffmpegStatic;
}

// Load config (optional). In production (e.g., Heroku), prefer env vars and avoid committing secrets.
let config = {};
try {
    if (fs.existsSync('config.yaml')) {
        config = yaml.load(fs.readFileSync('config.yaml', 'utf8')) || {};
    } else {
        config = {};
    }
} catch (err) {
    // Keep the bot running even if config.yaml is malformed/missing.
    config = {};
}

// Setup logging
setupLogging();
const logger = getLogger('modbot');

// Configure play-dl tokens when provided.
// Prefer environment variables (Heroku/GitHub secrets) over config.yaml.
// IMPORTANT: This must work even when config.yaml is missing (e.g. Heroku).
const youtubeConfig = config?.music?.youtube || {};
{
    const youtubeTokens = {};

    const envCookie = process.env.YOUTUBE_COOKIE;
    const envIdentityToken = process.env.YOUTUBE_IDENTITY_TOKEN;
    const envSapisid = process.env.YOUTUBE_SAPISID;

    const finalCookie = (typeof envCookie === 'string' && envCookie.trim()) ? envCookie.trim() : youtubeConfig.cookie;
    const finalIdentityToken = (typeof envIdentityToken === 'string' && envIdentityToken.trim()) ? envIdentityToken.trim() : youtubeConfig.identity_token;
    const finalSapisid = (typeof envSapisid === 'string' && envSapisid.trim()) ? envSapisid.trim() : youtubeConfig.sapisid_cookie;

    if (finalCookie) youtubeTokens.cookie = finalCookie;
    if (finalIdentityToken) youtubeTokens.identity_token = finalIdentityToken;
    if (finalSapisid) youtubeTokens.sapisid = finalSapisid;

    if (Object.keys(youtubeTokens).length > 0) {
        try {
            play.setToken({ youtube: youtubeTokens });
            logger.info('Configured play-dl with provided YouTube tokens');
        } catch (error) {
            logger.error('Failed to configure play-dl tokens:', error);
        }
    }
}

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

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function withTimeout(promise, ms, label) {
    const timeout = sleep(ms).then(() => {
        throw new Error(`${label ?? 'Operation'} timed out after ${ms}ms`);
    });
    return Promise.race([promise, timeout]);
}

async function syncSlashCommands({ guildId }) {
    const token = process.env.DISCORD_TOKEN;
    if (!token) {
        throw new Error('DISCORD_TOKEN is not set; cannot sync slash commands.');
    }

    const commands = Array.from(bot.commands.values())
        .map(cmd => cmd.data?.toJSON?.() ?? cmd.data)
        .filter(Boolean);

    const scopeLabel = guildId ? `guild ${guildId}` : 'globally';
    const forceSync = ['1', 'true', 'yes', 'on'].includes(String(process.env.FORCE_SYNC_COMMANDS || '').toLowerCase());

    const rest = new REST({ version: '10' }).setToken(token);
    const applicationId = bot.user?.id;
    if (!applicationId) {
        throw new Error('Bot user id is not available; cannot build application command routes.');
    }

    const route = guildId
        ? Routes.applicationGuildCommands(applicationId, guildId)
        : Routes.applicationCommands(applicationId);

    // Avoid Discord bulk-overwrite rate limits on every restart.
    // If the current registered command *names* already match, skip overwrite unless forced.
    let existingCommands = null;
    try {
        existingCommands = await withTimeout(rest.get(route), 20000, `Slash command list (${scopeLabel})`);
    } catch (err) {
        logger.warn(`Could not fetch existing commands for ${scopeLabel}; will attempt sync anyway.`, err);
    }

    if (!forceSync && Array.isArray(existingCommands) && existingCommands.length > 0) {
        const existingNames = existingCommands.map(c => c?.name).filter(Boolean).sort();
        const desiredNames = commands.map(c => c?.name).filter(Boolean).sort();

        const sameNames = existingNames.length === desiredNames.length
            && crypto.timingSafeEqual(
                Buffer.from(JSON.stringify(existingNames)),
                Buffer.from(JSON.stringify(desiredNames))
            );

        if (sameNames) {
            logger.info(`✅ Slash commands already registered in ${scopeLabel} (${existingNames.length} commands); skipping overwrite. Set FORCE_SYNC_COMMANDS=1 to force a re-sync.`);
            return;
        }
    }

    logger.info(`⏳ Syncing ${commands.length} slash commands ${guildId ? 'to' : ''} ${scopeLabel}...`);

    const startedAt = Date.now();
    const slowWarn = setTimeout(() => {
        logger.warn(`Slash command sync is taking longer than 20s (${scopeLabel}). This is usually Discord REST rate limiting; it should still complete.`);
    }, 20000);

    try {
        await rest.put(route, { body: commands });
    } finally {
        clearTimeout(slowWarn);
    }

    logger.info(`✅ Synced ${commands.length} slash commands ${guildId ? 'to guild ' + guildId : 'globally'} in ${Date.now() - startedAt}ms`);

    // Extra verification in logs: fetch registered command names from API.
    try {
        const fetched = await withTimeout(rest.get(route), 20000, `Slash command fetch (${scopeLabel})`);
        const names = Array.isArray(fetched) ? fetched.map(c => c?.name).filter(Boolean) : [];
        logger.info(`ℹ️ Registered commands in ${scopeLabel}: ${names.length ? names.join(', ') : '(none)'}`);
    } catch (err) {
        logger.warn('Could not fetch registered command list after sync:', err);
    }
}

bot.once('ready', async () => {
    if (!bot.synced) {
        // Prefer environment variables for deployment, but allow config.yaml for local convenience.
        // Supports:
        // - GUILD_ID="123" (single guild)
        // - GUILD_IDS="123,456" (multiple guilds)
        // - config.yaml -> bot.guild_id (fallback)
        const configuredGuildIdsRaw =
            process.env.GUILD_IDS ||
            process.env.GUILD_ID ||
            bot.config?.bot?.guild_id ||
            bot.config?.bot?.guildId;

        const configuredGuildIds = (typeof configuredGuildIdsRaw === 'string' ? configuredGuildIdsRaw : String(configuredGuildIdsRaw || ''))
            .split(/[\s,]+/)
            .map(s => s.trim())
            .filter(Boolean);
        
        try {
            logger.info(`ℹ️ Loaded ${bot.commands.size} command module(s) from disk`);

            if (configuredGuildIds.length > 0) {
                let syncedAnyGuild = false;

                for (const guildId of configuredGuildIds) {
                    const guild = bot.guilds.cache.get(guildId) || (await bot.guilds.fetch(guildId).catch(() => null));
                    if (!guild) {
                        logger.warn(`GUILD_ID/GUILD_IDS includes ${guildId}, but the bot is not in that guild (or cannot fetch it).`);
                        continue;
                    }

                    // Fetch all guild members to populate cache for autocomplete
                    try {
                        await guild.members.fetch();
                        logger.info(`✅ Fetched ${guild.members.cache.size} members for autocomplete in ${guild.name}`);
                    } catch (err) {
                        logger.error(`Failed to fetch members for ${guild.name}:`, err);
                    }

                    await syncSlashCommands({ guildId });
                    syncedAnyGuild = true;
                }

                // If the configured guild id(s) were invalid, fall back to global so the bot still gets commands.
                if (!syncedAnyGuild) {
                    logger.warn('No configured guild ids were usable; falling back to global slash command sync. Remove/fix GUILD_ID or GUILD_IDS to avoid this.');
                    await syncSlashCommands({ guildId: null });
                    logger.info('ℹ️ Global command updates can take up to ~1 hour to appear everywhere. For instant updates in one server, set a valid GUILD_ID (or GUILD_IDS) and restart the bot.');
                }
            } else {
                // Fetch members for all guilds
                for (const guild of bot.guilds.cache.values()) {
                    try {
                        await guild.members.fetch();
                        logger.info(`✅ Fetched ${guild.members.cache.size} members for ${guild.name}`);
                    } catch (err) {
                        logger.error(`Failed to fetch members for ${guild.name}:`, err);
                    }
                }

                await syncSlashCommands({ guildId: null });
                logger.info('ℹ️ Global command updates can take up to ~1 hour to appear everywhere. For instant updates in one server, set GUILD_ID and restart the bot.');
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
    // Handle autocomplete interactions
    if (interaction.isAutocomplete()) {
        const command = bot.commands.get(interaction.commandName);
        if (!command || !command.autocomplete) return;
        
        try {
            await command.autocomplete(interaction);
        } catch (error) {
            logger.error('Autocomplete error:', error);
        }
        return;
    }
    
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
            const reason = `AutoMod: ${violation}`;

            if (action === 'warn') {
                try {
                    bot.db.addWarning(message.guild.id, message.author.id, bot.user.id, reason);
                    bot.db.logAction(message.guild.id, 'automod_warn', message.author.id, bot.user.id, reason);
                } catch (dbErr) {
                    logger.error('AutoMod warn DB error:', dbErr);
                }

                await message.channel
                    .send(`⚠️ ${message.author} has been warned. Reason: ${violation}`)
                    .then(m => setTimeout(() => m.delete().catch(() => {}), 5000));
            } else if (action === 'timeout') {
                await message.member.timeout(automod.repeat_timeout_minutes * 60 * 1000, reason);
                await message.channel
                    .send(`⚠️ ${message.author} has been timed out for ${automod.repeat_timeout_minutes} minutes. Reason: ${violation}`)
                    .then(m => setTimeout(() => m.delete().catch(() => {}), 5000));
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
    const recentMessages = userMessages.filter(t => t > cutoff);
    messageCache.set(userId, recentMessages);

    if (recentMessages.length > antispam.max_messages) {
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
    const recentDuplicateWindow = userDuplicates.filter(m => m.time > dupCutoff);
    duplicateCache.set(userId, recentDuplicateWindow);

    const recentDuplicates = recentDuplicateWindow.filter(m => m.content === message.content);
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
        throw new Error('DISCORD_TOKEN is not set. Set it as an environment variable (use a .env file locally, or Heroku Config Vars in production).');
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
