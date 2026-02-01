const { SlashCommandBuilder, PermissionFlagsBits, EmbedBuilder, StringSelectMenuBuilder, StringSelectMenuOptionBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle, ChannelType, PermissionsBitField } = require('discord.js');
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
        config = { tickets: {} };
    }
} catch (e) {
    console.error('Failed to load config.yaml:', e?.message || String(e));
    config = { tickets: {} };
}

const ticketConfig = config.tickets || {
    category_name: '🎫 TICKETS',
    support_role_name: 'Moderator',
    transcript_channel_name: 'mod-log',
    one_ticket_per_category_per_user: true,
    ping_staff_on_create: true,
    panel_title: '🎫 Open a Ticket',
    panel_description: 'Choose a category from the dropdown to open a private ticket.',
    options: [
        { label: 'Support', value: 'support', description: 'General help', emoji: '🛟' },
        { label: 'Report', value: 'report', description: 'Report a user', emoji: '🚨' },
        { label: 'Partnership', value: 'partner', description: 'Business / Collab', emoji: '🤝' }
    ]
};

// Utility functions
function safeName(str) {
    return str
        .toLowerCase()
        .trim()
        .replace(/\s+/g, '-')
        .replace(/[^a-z0-9\-_]/g, '')
        .substring(0, 90) || 'user';
}

function buildTopic(openerId, ticketType, status) {
    return `ticket_opener=${openerId};ticket_type=${ticketType};status=${status}`;
}

function parseTopic(topic) {
    const data = {};
    if (!topic) return data;
    
    const parts = topic.split(';').filter(p => p.trim());
    for (const part of parts) {
        if (part.includes('=')) {
            const [key, value] = part.split('=', 2);
            data[key.trim()] = value.trim();
        }
    }
    return data;
}

async function getLogChannel(bot, guild) {
    // Try to find mod-log channel by name
    const fallbackName = ticketConfig.transcript_channel_name || 'mod-log';
    const channel = guild.channels.cache.find(ch => 
        ch.type === ChannelType.GuildText && ch.name === fallbackName
    );
    return channel || null;
}

async function makeTranscript(channel, limit = 200) {
    try {
        const messages = await channel.messages.fetch({ limit });
        const lines = [];
        
        // Sort messages oldest first
        const sorted = Array.from(messages.values()).reverse();
        
        for (const msg of sorted) {
            const author = `${msg.author.tag} (${msg.author.id})`;
            const content = msg.content || '';
            const timestamp = msg.createdAt.toISOString().replace('T', ' ').split('.')[0] + ' UTC';
            lines.push(`[${timestamp}] ${author}: ${content}`);
            
            // Add attachments
            for (const attachment of msg.attachments.values()) {
                lines.push(`    [attachment] ${attachment.url}`);
            }
            
            // Note embeds
            if (msg.embeds.length > 0) {
                lines.push(`    [embed] (content omitted)`);
            }
        }
        
        return lines.length > 0 ? lines.join('\n') : '(no messages)';
    } catch (error) {
        console.error('Transcript error:', error);
        return '(error generating transcript)';
    }
}

module.exports = {
    data: new SlashCommandBuilder()
        .setName('post_ticket_panel')
        .setDescription('Post the ticket dropdown panel')
        .addChannelOption(option =>
            option.setName('channel')
                .setDescription('Channel to post ticket panel in (default: current channel)')
                .setRequired(false))
        .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),

    async execute(interaction, bot) {
        const targetChannel = interaction.options.getChannel('channel') || interaction.channel;

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
                .setTitle(ticketConfig.panel_title)
                .setDescription(ticketConfig.panel_description)
                .setColor('Blurple')
                .setTimestamp();

            // Create select menu options
            const options = ticketConfig.options.map(opt => 
                new StringSelectMenuOptionBuilder()
                    .setLabel(opt.label)
                    .setValue(opt.value)
                    .setDescription(opt.description || '')
                    .setEmoji(opt.emoji || '')
            );

            // Create select menu
            const select = new StringSelectMenuBuilder()
                .setCustomId('ticket:select')
                .setPlaceholder('Select a ticket category…')
                .addOptions(options);

            const row = new ActionRowBuilder().addComponents(select);

            // Send the panel
            await targetChannel.send({
                embeds: [embed],
                components: [row]
            });

            await interaction.editReply({
                embeds: [successEmbed('Success', `✅ Ticket panel posted in ${targetChannel}`)]
            });
        } catch (error) {
            console.error('Post ticket panel error:', error);
            await interaction.editReply({
                embeds: [errorEmbed('Error', `Failed to post ticket panel: ${error.message}`)]
            });
        }
    },

    // Handle ticket select menu
    async handleTicketSelect(interaction, bot) {
        try {
            const ticketType = interaction.values[0];
            const guild = interaction.guild;
            const member = interaction.member;

            await interaction.deferReply({ ephemeral: true });

            // Find or create category
            let category = guild.channels.cache.find(ch => 
                ch.type === ChannelType.GuildCategory && ch.name === ticketConfig.category_name
            );

            if (!category) {
                try {
                    category = await guild.channels.create({
                        name: ticketConfig.category_name,
                        type: ChannelType.GuildCategory,
                        reason: 'Ticket system category'
                    });
                } catch (err) {
                    return interaction.editReply({
                        embeds: [errorEmbed('Error', `Category \`${ticketConfig.category_name}\` not found and I cannot create it.`)]
                    });
                }
            }

            // Check for existing open ticket
            if (ticketConfig.one_ticket_per_category_per_user) {
                const existingTicket = guild.channels.cache.find(ch => {
                    if (ch.type !== ChannelType.GuildText) return false;
                    if (ch.parentId !== category.id) return false;
                    const meta = parseTopic(ch.topic);
                    return meta.ticket_opener === member.id.toString() &&
                           meta.ticket_type === ticketType &&
                           meta.status === 'open';
                });

                if (existingTicket) {
                    return interaction.editReply({
                        embeds: [errorEmbed('Error', 'You already have an open ticket in this category.')]
                    });
                }
            }

            // Find staff role
            const staffRole = guild.roles.cache.find(r => r.name === ticketConfig.support_role_name);

            // Create channel name
            const username = safeName(member.user.username);
            const channelName = `ticket-${ticketType}-${username}`;

            // Setup permissions
            const overwrites = [
                {
                    id: guild.id, // @everyone
                    deny: [PermissionsBitField.Flags.ViewChannel]
                },
                {
                    id: member.id,
                    allow: [
                        PermissionsBitField.Flags.ViewChannel,
                        PermissionsBitField.Flags.SendMessages,
                        PermissionsBitField.Flags.ReadMessageHistory
                    ]
                },
                {
                    id: bot.user.id,
                    allow: [
                        PermissionsBitField.Flags.ViewChannel,
                        PermissionsBitField.Flags.SendMessages,
                        PermissionsBitField.Flags.ManageChannels,
                        PermissionsBitField.Flags.ReadMessageHistory
                    ]
                }
            ];

            if (staffRole) {
                overwrites.push({
                    id: staffRole.id,
                    allow: [
                        PermissionsBitField.Flags.ViewChannel,
                        PermissionsBitField.Flags.SendMessages,
                        PermissionsBitField.Flags.ReadMessageHistory
                    ]
                });
            }

            // Create ticket channel
            let ticketChannel;
            try {
                ticketChannel = await guild.channels.create({
                    name: channelName,
                    type: ChannelType.GuildText,
                    parent: category.id,
                    topic: buildTopic(member.id, ticketType, 'open'),
                    permissionOverwrites: overwrites,
                    reason: `Ticket opened by ${member.user.tag} (${member.id})`
                });
            } catch (err) {
                console.error('Channel creation error:', err);
                return interaction.editReply({
                    embeds: [errorEmbed('Error', 'Failed to create ticket channel. Check my permissions.')]
                });
            }

            // Create ticket action buttons
            const closeButton = new ButtonBuilder()
                .setCustomId('ticket:close')
                .setLabel('Close Ticket')
                .setStyle(ButtonStyle.Danger)
                .setEmoji('🔒');

            const reopenButton = new ButtonBuilder()
                .setCustomId('ticket:reopen')
                .setLabel('Reopen Ticket')
                .setStyle(ButtonStyle.Success)
                .setEmoji('🔓');

            const deleteButton = new ButtonBuilder()
                .setCustomId('ticket:delete')
                .setLabel('Delete Ticket')
                .setStyle(ButtonStyle.Secondary)
                .setEmoji('🗑️');

            const actionRow = new ActionRowBuilder()
                .addComponents(closeButton, reopenButton, deleteButton);

            // Send welcome message
            const embed = new EmbedBuilder()
                .setTitle('🎫 Ticket Opened')
                .setDescription(
                    `Hello ${member}!\n` +
                    `Category: **${ticketType}**\n\n` +
                    `Explain your issue and staff will respond.`
                )
                .setColor('Blurple');

            const ping = ticketConfig.ping_staff_on_create && staffRole ? staffRole.toString() : '';
            await ticketChannel.send({
                content: ping,
                embeds: [embed],
                components: [actionRow]
            });

            await interaction.editReply({
                embeds: [successEmbed('Ticket Created', `Ticket created: ${ticketChannel}`)]
            });

            console.log(`Ticket created: ${ticketChannel.name} by ${member.user.tag}`);
        } catch (error) {
            console.error('Ticket select error:', error);
            const errorMsg = errorEmbed('Error', `Failed to create ticket: ${error.message}`);
            if (interaction.deferred) {
                await interaction.editReply({ embeds: [errorMsg] });
            } else {
                await interaction.reply({ embeds: [errorMsg], ephemeral: true });
            }
        }
    },

    // Handle ticket action buttons
    async handleTicketButton(interaction, bot, action) {
        const channel = interaction.channel;
        const member = interaction.member;
        const guild = interaction.guild;

        if (channel.type !== ChannelType.GuildText) {
            return interaction.reply({
                embeds: [errorEmbed('Error', 'Invalid channel type.')],
                ephemeral: true
            });
        }

        const meta = parseTopic(channel.topic);
        const openerId = meta.ticket_opener;
        const status = meta.status || 'open';
        const ticketType = meta.ticket_type || 'support';

        const isStaff = member.permissions.has(PermissionsBitField.Flags.ManageChannels);
        const isOpener = openerId === member.id.toString();

        if (action === 'close') {
            if (!isStaff && !isOpener) {
                return interaction.reply({
                    embeds: [errorEmbed('Error', "You can't close this ticket.")],
                    ephemeral: true
                });
            }

            if (status === 'closed') {
                return interaction.reply({
                    content: '✅ This ticket is already closed.',
                    ephemeral: true
                });
            }

            await interaction.reply({
                content: '✅ Closing ticket (locking + transcript)...',
                ephemeral: true
            });

            // Generate and send transcript
            const logChannel = await getLogChannel(bot, guild);
            if (logChannel) {
                try {
                    const transcript = await makeTranscript(channel, 200);
                    const buffer = Buffer.from(transcript, 'utf-8');
                    
                    const embed = new EmbedBuilder()
                        .setTitle('🎫 Ticket Closed (Transcript)')
                        .setDescription(`Channel: ${channel}\nClosed by: ${member}`)
                        .setColor('Orange')
                        .setTimestamp();

                    await logChannel.send({
                        embeds: [embed],
                        files: [{
                            attachment: buffer,
                            name: `ticket-${channel.id}-transcript.txt`
                        }]
                    });
                } catch (err) {
                    console.error('Transcript error:', err);
                }
            }

            // Update permissions - lock channel
            const opener = guild.members.cache.get(openerId);
            const staffRole = guild.roles.cache.find(r => r.name === ticketConfig.support_role_name);

            await channel.permissionOverwrites.set([
                {
                    id: guild.id,
                    deny: [PermissionsBitField.Flags.ViewChannel]
                },
                {
                    id: bot.user.id,
                    allow: [
                        PermissionsBitField.Flags.ViewChannel,
                        PermissionsBitField.Flags.SendMessages,
                        PermissionsBitField.Flags.ManageChannels,
                        PermissionsBitField.Flags.ReadMessageHistory
                    ]
                }
            ].concat(
                opener ? [{
                    id: opener.id,
                    allow: [PermissionsBitField.Flags.ViewChannel, PermissionsBitField.Flags.ReadMessageHistory],
                    deny: [PermissionsBitField.Flags.SendMessages]
                }] : []
            ).concat(
                staffRole ? [{
                    id: staffRole.id,
                    allow: [
                        PermissionsBitField.Flags.ViewChannel,
                        PermissionsBitField.Flags.SendMessages,
                        PermissionsBitField.Flags.ReadMessageHistory
                    ]
                }] : []
            ));

            // Update topic and name
            await channel.setTopic(buildTopic(openerId, ticketType, 'closed'));
            if (!channel.name.startsWith('closed-')) {
                await channel.setName(`closed-${channel.name}`.substring(0, 95));
            }

            await channel.send('🔒 Ticket closed. Staff can reopen if needed.');

        } else if (action === 'reopen') {
            if (!isStaff) {
                return interaction.reply({
                    embeds: [errorEmbed('Error', 'Only staff can reopen tickets.')],
                    ephemeral: true
                });
            }

            if (status !== 'closed') {
                return interaction.reply({
                    content: '✅ This ticket is already open.',
                    ephemeral: true
                });
            }

            // Restore permissions
            const opener = guild.members.cache.get(openerId);
            const staffRole = guild.roles.cache.find(r => r.name === ticketConfig.support_role_name);

            await channel.permissionOverwrites.set([
                {
                    id: guild.id,
                    deny: [PermissionsBitField.Flags.ViewChannel]
                },
                {
                    id: bot.user.id,
                    allow: [
                        PermissionsBitField.Flags.ViewChannel,
                        PermissionsBitField.Flags.SendMessages,
                        PermissionsBitField.Flags.ManageChannels,
                        PermissionsBitField.Flags.ReadMessageHistory
                    ]
                }
            ].concat(
                opener ? [{
                    id: opener.id,
                    allow: [
                        PermissionsBitField.Flags.ViewChannel,
                        PermissionsBitField.Flags.SendMessages,
                        PermissionsBitField.Flags.ReadMessageHistory
                    ]
                }] : []
            ).concat(
                staffRole ? [{
                    id: staffRole.id,
                    allow: [
                        PermissionsBitField.Flags.ViewChannel,
                        PermissionsBitField.Flags.SendMessages,
                        PermissionsBitField.Flags.ReadMessageHistory
                    ]
                }] : []
            ));

            await channel.setTopic(buildTopic(openerId, ticketType, 'open'));
            if (channel.name.startsWith('closed-')) {
                await channel.setName(channel.name.replace('closed-', '').substring(0, 95));
            }

            await interaction.reply({
                content: '🔓 Ticket reopened.',
                ephemeral: true
            });
            await channel.send(`🔓 Ticket reopened by ${member}.`);

        } else if (action === 'delete') {
            if (!isStaff) {
                return interaction.reply({
                    embeds: [errorEmbed('Error', 'Only staff can delete tickets.')],
                    ephemeral: true
                });
            }

            await interaction.reply({
                content: '🗑️ Deleting ticket channel...',
                ephemeral: true
            });

            setTimeout(async () => {
                try {
                    await channel.delete(`Ticket deleted by ${member.user.tag}`);
                } catch (err) {
                    console.error('Delete error:', err);
                }
            }, 2000);
        }
    }
};
