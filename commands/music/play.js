const { SlashCommandBuilder, PermissionsBitField, ChannelType } = require('discord.js');
const {
    joinVoiceChannel,
    createAudioPlayer,
    createAudioResource,
    demuxProbe,
    NoSubscriberBehavior,
    AudioPlayerStatus,
    VoiceConnectionStatus,
    entersState
} = require('@discordjs/voice');
const play = require('play-dl');
const ytdl = require('@distube/ytdl-core');
const { successEmbed, errorEmbed } = require('../../utils/embeds');
const { getQueue, destroyQueue } = require('../../utils/music_state');

const SEARCH_TIMEOUT_MS = 20000;
const VIDEO_INFO_TIMEOUT_MS = 20000;

async function withTimeout(promise, ms, label = 'Operation') {
    return Promise.race([
        promise,
        new Promise((_, reject) => setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms))
    ]);
}

async function searchYouTube(query) {
    // play-dl search can fail due to network slowness, rate limits, or CAPTCHA.
    // We'll retry once and try a fallback mode. If play-dl parsing breaks, fall back to @distube/ytsr.
    const attempts = [
        async () => withTimeout(play.search(query, { limit: 1 }), SEARCH_TIMEOUT_MS, 'YouTube search'),
        async () => withTimeout(play.search(query, { limit: 1, source: { youtube: 'video' } }), SEARCH_TIMEOUT_MS, 'YouTube search (fallback)'),
        async () => withTimeout(play.search(query, { limit: 3 }), SEARCH_TIMEOUT_MS, 'YouTube search (wider)')
    ];

    let lastError;
    for (const attempt of attempts) {
        try {
            const results = await attempt();
            if (Array.isArray(results) && results.length > 0) return results;
        } catch (err) {
            lastError = err;
        }
    }

    // Final fallback: external search provider
    try {
        const ytsr = require('@distube/ytsr');
        const res = await withTimeout(ytsr(query, { limit: 5 }), SEARCH_TIMEOUT_MS, 'YouTube search (ytsr)');
        const items = Array.isArray(res) ? res : (res && res.items) ? res.items : [];
        const videos = items.filter(i => i && (i.type === 'video' || i.url));
        if (videos.length > 0) {
            // normalize into play-dl-like objects the rest of the code can handle
            return videos.map(v => ({
                title: v.name || v.title,
                url: v.url,
                id: v.id,
                durationInSec: typeof v.duration === 'number' ? v.duration : undefined,
                thumbnails: v.thumbnail ? [{ url: v.thumbnail }] : (v.thumbnail?.url ? [{ url: v.thumbnail.url }] : [])
            }));
        }
    } catch (fallbackErr) {
        lastError = lastError || fallbackErr;
    }

    throw lastError || new Error('No results returned');
}

async function playSong(guild, queue) {
    if (queue.songs.length === 0) {
        queue.current = null;
        return false;
    }

    const song = queue.songs.shift();
    queue.current = song;

    try {
        console.log(`[MUSIC] Starting playback for: ${song.title}`);
        if (!isLikelyUrl(song.url)) {
            throw new Error(`Invalid song URL: ${song.url}`);
        }

        // Primary: ytdl-core (fast/reliable when not blocked). If it fails (403/decipher/etc), fall back to play-dl.
        let audioStream;
        try {
            const ytdlOptions = {
                filter: 'audioonly',
                quality: 'highestaudio',
                highWaterMark: 1 << 25,
                liveBuffer: 1 << 25
            };

            if (queue.ytdlCookie && typeof queue.ytdlCookie === 'string' && queue.ytdlCookie.trim()) {
                ytdlOptions.requestOptions = {
                    headers: {
                        cookie: queue.ytdlCookie.trim()
                    }
                };
            }

            audioStream = ytdl(song.url, ytdlOptions);
        } catch (primaryErr) {
            console.warn('[MUSIC] ytdl-core stream failed, falling back to play-dl:', primaryErr);
            const streamInfo = await play.stream(song.url);
            audioStream = streamInfo.stream;
        }

        // Probe stream type so discord.js voice decodes it correctly
        const probed = await demuxProbe(audioStream);
        const resource = createAudioResource(probed.stream, {
            inputType: probed.type,
            inlineVolume: true,
            metadata: {
                title: song.title,
                url: song.url,
                duration: song.duration,
                thumbnail: song.thumbnail,
                requestedBy: song.requestedBy
            }
        });
        
        // Set volume to 100% for testing
        if (resource.volume) {
            resource.volume.setVolume(1.0);
            console.log(`[MUSIC] Volume set to 100%`);
        }

        // attach resource so /volume can control it
        queue.current = { ...song, resource };

        console.log(`[MUSIC] Starting player, current state: ${queue.player.state.status}`);
        queue.player.play(resource);
        await entersState(queue.player, AudioPlayerStatus.Playing, 10_000);
        console.log(`[MUSIC] Player is now playing: ${queue.player.state.status}`);
        return true;
    } catch (error) {
        queue.lastError = error;
        console.error('Error playing song:', error);
        // If another song is queued, try it. Otherwise clear current.
        queue.current = null;
        if (queue.songs.length > 0) {
            return playSong(guild, queue);
        }
        return false;
    }
}

function isLikelyUrl(value) {
    if (!value || typeof value !== 'string') return false;
    const v = value.trim();
    if (!v) return false;
    if (v === 'undefined' || v === 'null') return false;
    if (!/^https?:\/\//i.test(v)) return false;
    try {
        // eslint-disable-next-line no-new
        new URL(v);
        return true;
    } catch {
        return false;
    }
}

function normalizeYoutubeUrl(video) {
    const rawUrl = video && (video.url || video.link || video.video_url);
    if (isLikelyUrl(rawUrl)) return rawUrl;

    const id = video && (video.id || video.videoId || video.video_id);
    if (id && typeof id === 'string') {
        return `https://www.youtube.com/watch?v=${id}`;
    }

    return null;
}

module.exports = {
    data: new SlashCommandBuilder()
        .setName('play')
        .setDescription('Play music from YouTube')
        .addStringOption(option =>
            option.setName('query')
                .setDescription('Song name or YouTube URL')
                .setRequired(true)),

    async execute(interaction, bot) {
        // Defer reply immediately to avoid timeout
        await interaction.deferReply();

        const query = interaction.options.getString('query');
        const member = interaction.member;
        const voiceChannel = member.voice.channel;

        if (!voiceChannel) {
            return interaction.followUp({
                embeds: [errorEmbed('Error', 'You need to be in a voice channel to use this command!')]
            });
        }

        // Ensure the bot can connect + speak
        const me = interaction.guild.members.me || (await interaction.guild.members.fetchMe().catch(() => null));
        if (!me) {
            return interaction.followUp({
                embeds: [errorEmbed('Error', 'Could not resolve bot member in this guild.')]
            });
        }

        const perms = voiceChannel.permissionsFor(me);
        if (!perms || !perms.has([PermissionsBitField.Flags.Connect, PermissionsBitField.Flags.Speak])) {
            return interaction.followUp({
                embeds: [errorEmbed('Missing Permissions', 'I need **Connect** and **Speak** permission in your voice channel.')]
            });
        }

        try {
            // Search for the song with timeout
            let song;
            
            // Check if it's a URL
            const isURL = query.includes('youtube.com') || query.includes('youtu.be');
            
            if (isURL) {
                try {
                    console.log('[SEARCH] Fetching video info for URL...');
                    const info = await withTimeout(play.video_info(query), VIDEO_INFO_TIMEOUT_MS, 'Video info');
                    console.log('[SEARCH] Video info received');

                    const details = info.video_details;
                    const videoUrl = normalizeYoutubeUrl({ url: details.url, id: details.id });
                    const finalUrl = videoUrl || (isLikelyUrl(query) ? query : null);
                    if (!finalUrl) {
                        throw new Error('Could not determine a valid YouTube URL for this video');
                    }

                    song = {
                        title: details.title,
                        url: finalUrl,
                        duration: details.durationInSec,
                        thumbnail: details.thumbnails[0]?.url || 'https://via.placeholder.com/150',
                        requestedBy: interaction.user
                    };
                } catch (urlError) {
                    console.error('Error fetching URL info:', urlError.message);
                    return interaction.followUp({
                        embeds: [errorEmbed('Error', `Failed to fetch video information. The video may be unavailable/restricted, or the request failed.\n\nDetails: ${urlError.message}`)]
                    });
                }
            } else {
                // Use YouTube search - simplified
                try {
                    console.log('[SEARCH] Searching YouTube for:', query);
                    const yt_info = await searchYouTube(query);
                    
                    if (!yt_info || yt_info.length === 0) {
                        return interaction.followUp({
                            embeds: [errorEmbed('Error', 'No results found! Try using a YouTube URL instead.')]
                        });
                    }
                    
                    const video = yt_info[0];
                    console.log('[SEARCH] Found video:', video.title);
                    
                    const videoUrl = normalizeYoutubeUrl(video);
                    if (!videoUrl) {
                        console.error('Search returned video without URL:', video);
                        return interaction.followUp({
                            embeds: [errorEmbed('Error', 'Found a video but couldn\'t get its URL. Try a direct YouTube link.')]
                        });
                    }
                    
                    song = {
                        title: video.title || 'Unknown Title',
                        url: videoUrl,
                        duration: video.durationInSec || 0,
                        thumbnail: video.thumbnails?.[0]?.url || 'https://via.placeholder.com/150',
                        requestedBy: interaction.user
                    };
                } catch (searchError) {
                    console.error('YouTube search error:', searchError);
                    return interaction.followUp({
                        embeds: [errorEmbed('Error', `YouTube search failed. Try a direct YouTube URL.\n\nDetails: ${searchError.message || searchError}`)]
                    });
                }
            }

            const queue = getQueue(interaction.guild.id);
            queue.lastError = null;

            // Join voice channel if not already connected
            if (!queue.connection) {
                queue.connection = joinVoiceChannel({
                    channelId: voiceChannel.id,
                    guildId: interaction.guild.id,
                    adapterCreator: interaction.guild.voiceAdapterCreator,
                    selfDeaf: false,
                    selfMute: false,
                });

                queue.player = createAudioPlayer({
                    behaviors: {
                        noSubscriber: NoSubscriberBehavior.Play
                    }
                });
                queue.connection.subscribe(queue.player);

                // Wait until the connection is ready before streaming audio
                try {
                    await entersState(queue.connection, VoiceConnectionStatus.Ready, 15_000);
                } catch (error) {
                    console.error('Voice connection failed to become ready:', error);
                    destroyQueue(interaction.guild.id);
                    return interaction.followUp({
                        embeds: [errorEmbed('Error', 'Failed to join the voice channel. Please try again.')]
                    });
                }

                // If this is a Stage channel, the bot may be suppressed and cannot output audio.
                // Attempt to request-to-speak / unsuppress.
                try {
                    const meAfterJoin = interaction.guild.members.me || (await interaction.guild.members.fetchMe().catch(() => null));
                    const vs = meAfterJoin && meAfterJoin.voice;
                    if (vs && voiceChannel.type === ChannelType.GuildStageVoice) {
                        // These calls require appropriate permissions in the Stage.
                        await vs.setRequestToSpeak(true).catch(() => {});
                        await vs.setSuppressed(false).catch(() => {});
                    }

                    if (vs && (vs.serverMute || vs.suppress)) {
                        const reasons = [
                            vs.serverMute ? 'server-muted' : null,
                            vs.suppress ? 'suppressed (Stage)' : null
                        ].filter(Boolean).join(', ');

                        await interaction.followUp({
                            embeds: [errorEmbed('Voice Output Blocked', `I joined the channel but I am **${reasons}**.\n\nUnmute/allow me to speak in that channel and try again.`)],
                            ephemeral: true
                        }).catch(() => {});
                    }
                } catch (stageErr) {
                    console.error('Stage/voice state check failed:', stageErr);
                }

                // Attach listeners only once per guild queue
                if (!queue._eventsAttached) {
                    queue._eventsAttached = true;

                    queue.player.on(AudioPlayerStatus.Idle, () => {
                        console.log(`[MUSIC] Player became idle, loopMode: ${queue.loopMode}`);
                        if (queue.loopMode && queue.current) {
                            const { title, url, duration, thumbnail, requestedBy } = queue.current;
                            queue.songs.unshift({ title, url, duration, thumbnail, requestedBy });
                        }
                        playSong(interaction.guild, queue);
                    });

                    queue.player.on('error', error => {
                        queue.lastError = error;
                        console.error('Audio player error:', error);
                        playSong(interaction.guild, queue);
                    });
                }

                queue.connection.on(VoiceConnectionStatus.Disconnected, async () => {
                    try {
                        await Promise.race([
                            entersState(queue.connection, VoiceConnectionStatus.Signalling, 5_000),
                            entersState(queue.connection, VoiceConnectionStatus.Connecting, 5_000),
                        ]);
                    } catch (error) {
                        destroyQueue(interaction.guild.id);
                    }
                });
            }

            // Add to queue or play immediately
            if (!queue.player || queue.player.state.status === AudioPlayerStatus.Idle) {
                queue.songs.push(song);

                const started = await playSong(interaction.guild, queue);
                if (!started) {
                    const msg = queue.lastError?.message || 'Unknown error while starting playback.';
                    const hint = /sign in|confirm your age|private video|unavailable|premieres/i.test(msg)
                        ? '\n\nThis can be caused by **YouTube restrictions** (age/region/login). Try another video URL.'
                        : '';

                    return interaction.followUp({
                        embeds: [errorEmbed('Playback Failed', `${msg}${hint}`)]
                    });
                }

                const playing = queue.current || song;
                const embed = successEmbed('🎵 Now Playing', `[${playing.title}](${playing.url})`)
                    .setThumbnail(playing.thumbnail)
                    .addFields(
                        { name: 'Duration', value: formatDuration(playing.duration || 0), inline: true },
                        { name: 'Requested by', value: playing.requestedBy.toString(), inline: true }
                    );

                await interaction.followUp({ embeds: [embed] });
            } else {
                queue.songs.push(song);

                const embed = successEmbed('📝 Added to Queue', `[${song.title}](${song.url})`)
                    .addFields({ name: 'Position', value: `#${queue.songs.length}`, inline: true });

                await interaction.followUp({ embeds: [embed] });
            }
        } catch (error) {
            console.error('Play command error:', error);
            await interaction.followUp({
                embeds: [errorEmbed('Error', `An error occurred: ${error.message}`)]
            });
        }
    }
};

function formatDuration(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}
