# kanged from dashezup tgvc-userbot
import os
import asyncio
import ffmpeg

from datetime import datetime, timedelta
from pyrogram import filters
from pyrogram.types import Message
from pyrogram.methods.messages.download_media import DEFAULT_DOWNLOAD_DIR
from pytgcalls import GroupCall

from nana import app, AdminSettings, COMMAND_PREFIXES, RADIO_GROUPS, RADIO_CHANNEL

__MODULE__ = 'Player'
__HELP__ = """
Play and control audio in Telegram voice chats.

──「 **Join** 」──
-> `joinvc`
Join voice chat of current group.

──「 **Leave** 」──
-> `leavevc`
Leave current voice chat.

──「 **Play** 」──
-> `play`
Reply with an audio to play/queue it, or show playlist.

──「 **Current** 」──
-> `current`
Show current playing time of current track.

──「 **Skip** 」──
-> `skip` (n)
Skip current song or n where n >= 2.

──「 **Stop** 」──
-> `stop`
Stop playing.

──「 **Pause** 」──
-> `pause`
Pause playing.

──「 **Resume** 」──
-> `resume`
Resume playing.

──「 **Replay** 」──
-> `replay`
Play from the beginning.

──「 **Voice** 」──
-> `vc`
Check which VC is joined.

──「 **Clean** 」──
-> `clean`
Remove unused RAW PCM files.

──「 **Mute** 」──
-> `mute`
Mute the VC userbot.

──「 **Unmute** 」──
-> `unmute`
Unmute the VC userbot.

──「 **Admin mode** 」──
-> `mode <mode>`
Set mode to `admin` to only allow administrators to add songs
or set mode to `all` to allow any group member to add songs
(default to all).
"""

AM_ENABLED = False

# - Pyrogram filters

main_filter = (
    filters.group
    & filters.text
    & ~filters.edited
    & ~filters.via_bot
)


async def admin_mode_filter(_, __, m: Message):
    user_id = m.from_user.id
    user = await m.chat.get_member(user_id)
    admin_strings = ["administrator", "creator"]
    is_admin = user.status in admin_strings
    is_sudo = user_id in AdminSettings
    if AM_ENABLED:
        if is_admin or is_sudo:
            return True
        else:
            return False
    else:
        return True

admin_mode = filters.create(admin_mode_filter)


async def current_vc_filter(_, __, m: Message):
    group_call = mp.group_call
    if not group_call.is_connected:
        return False
    chat_id = int("-100" + str(group_call.full_chat.id))
    if m.chat.id == chat_id:
        return True
    return False

current_vc = filters.create(current_vc_filter)


# - class


class MusicPlayer(object):
    def __init__(self):
        self.group_call = GroupCall(None, path_to_log_file='')
        self.chat_id = None
        self.start_time = None
        self.playlist = []
        self.msg = {}

    async def update_start_time(self, reset=False):
        self.start_time = (
            None if reset
            else datetime.utcnow().replace(microsecond=0)
        )

    async def send_playlist(self):
        playlist = self.playlist
        if not playlist:
            pl = "Empty playlist."
        else:
            if len(playlist) == 1:
                pl = "**Playlist**:\n"
            else:
                pl = "**Playlist**:\n"
            pl += "\n".join([
                f"**{i}**. **[{x.audio.title}]({x.link})**"
                for i, x in enumerate(playlist)
            ])
        if mp.msg.get('playlist') is not None:
            await mp.msg['playlist'].delete()
        mp.msg['playlist'] = await send_text(pl)


mp = MusicPlayer()


# - pytgcalls handlers


@mp.group_call.on_network_status_changed
async def network_status_changed_handler(gc: GroupCall, is_connected: bool):
    if is_connected:
        mp.chat_id = int("-100" + str(gc.full_chat.id))
        await send_text("Joined the voice chat.")
    else:
        await send_text("Left the voice chat.")
        mp.chat_id = None


@mp.group_call.on_playout_ended
async def playout_ended_handler(group_call, filename):
    await skip_current_playing()


# - Pyrogram handlers


@app.on_message(
    main_filter
    & current_vc
    & admin_mode
    & filters.command("play", COMMAND_PREFIXES)
)
async def play_track(client, m: Message):
    group_call = mp.group_call
    playlist = mp.playlist
    # show playlist
    if not m.reply_to_message or not m.reply_to_message.audio:
        await mp.send_playlist()
        await m.delete()
        return
    # check already added
    m_reply = m.reply_to_message
    if playlist and playlist[-1].audio.file_unique_id \
            == m_reply.audio.file_unique_id:
        reply = await m.reply_text("Already added.")
        return
    # add to playlist
    playlist.append(m_reply)
    if len(playlist) == 1:
        m_status = await m.reply_text("Downloading and transcoding...")
        await download_audio(playlist[0])
        group_call.input_filename = os.path.join(
            client.workdir,
            DEFAULT_DOWNLOAD_DIR,
            f"{playlist[0].audio.file_unique_id}.raw"
        )
        await mp.update_start_time()
        await m_status.delete()
        print(f"- START PLAYING: {playlist[0].audio.title}")
    await mp.send_playlist()
    for track in playlist[:2]:
        await download_audio(track)
    await m.delete()


@app.on_message(
    main_filter
    & current_vc
    & filters.regex("^(\\/|!)current$")
)
async def show_current_playing_time(client, m: Message):
    start_time = mp.start_time
    playlist = mp.playlist
    if not start_time:
        reply = await m.reply_text("Unknown.")
        return
    utcnow = datetime.utcnow().replace(microsecond=0)
    if mp.msg.get('current') is not None:
        await mp.msg['current'].delete()
    mp.msg['current'] = await playlist[0].reply_text(
        f"{utcnow - start_time} / "
        f"{timedelta(seconds=playlist[0].audio.duration)}",
        disable_notification=True
    )
    await m.delete()


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & current_vc
    & filters.command("skip", COMMAND_PREFIXES)
)
async def skip_track(client, m: Message):
    playlist = mp.playlist
    if len(m.command) == 1:
        await skip_current_playing()
    else:
        try:
            items = list(dict.fromkeys(m.command[1:]))
            items = [int(x) for x in items if x.isdigit()]
            items.sort(reverse=True)
            text = []
            for i in items:
                if 2 <= i <= (len(playlist) - 1):
                    audio = f"[{playlist[i].audio.title}]({playlist[i].link})"
                    playlist.pop(i)
                    text.append(f"{i}. **{audio}**")
                else:
                    text.append(f"{i}")
            reply = await m.reply_text("\n".join(text))
            await mp.send_playlist()
        except (ValueError, TypeError):
            reply = await m.reply_text("Invalid input.",
                                       disable_web_page_preview=True)


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & filters.command("joinvc", COMMAND_PREFIXES)
)
async def join_group_call(client, m: Message):
    group_call = mp.group_call
    group_call.client = client
    if group_call.is_connected:
        await m.reply_text("Already joined a voice chat.")
        return
    await group_call.start(m.chat.id)
    await m.delete()


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & current_vc
    & filters.command("leavevc", COMMAND_PREFIXES)
)
async def leave_voice_chat(client, m: Message):
    group_call = mp.group_call
    mp.playlist.clear()
    group_call.input_filename = ''
    await group_call.stop()
    await m.delete()


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & filters.command("vc", COMMAND_PREFIXES)
)
async def list_voice_chat(client, m: Message):
    group_call = mp.group_call
    if group_call.is_connected:
        chat_id = int("-100" + str(group_call.full_chat.id))
        chat = await client.get_chat(chat_id)
        reply = await m.reply_text(
            f"**Currently in the voice chat**:\n"
            f"- **{chat.title}**"
        )
    else:
        reply = await m.reply_text("Didn't join any voice chat yet.")


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & current_vc
    & filters.command("stop", COMMAND_PREFIXES)
)
async def stop_playing(_, m: Message):
    group_call = mp.group_call
    group_call.stop_playout()
    reply = await m.reply_text("Stopped playing.")
    await mp.update_start_time(reset=True)
    mp.playlist.clear()


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & current_vc
    & filters.command("replay", COMMAND_PREFIXES)
)
async def restart_playing(_, m: Message):
    group_call = mp.group_call
    if not mp.playlist:
        return
    group_call.restart_playout()
    await mp.update_start_time()
    reply = await m.reply_text("Playing from the beginning...")


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & current_vc
    & filters.command("pause", COMMAND_PREFIXES)
)
async def pause_playing(_, m: Message):
    mp.group_call.pause_playout()
    await mp.update_start_time(reset=True)
    reply = await m.reply_text("Paused.", quote=False)
    mp.msg['pause'] = reply
    await m.delete()


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & current_vc
    & filters.command("resume", COMMAND_PREFIXES)
)
async def resume_playing(_, m: Message):
    mp.group_call.resume_playout()
    reply = await m.reply_text("Resumed.", quote=False)
    if mp.msg.get('pause') is not None:
        await mp.msg['pause'].delete()
    await m.delete()


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & current_vc
    & filters.command("clean", COMMAND_PREFIXES)
)
async def clean_raw_pcm(client, m: Message):
    download_dir = os.path.join(client.workdir, DEFAULT_DOWNLOAD_DIR)
    all_fn = os.listdir(download_dir)
    for track in mp.playlist[:2]:
        track_fn = f"{track.audio.file_unique_id}.raw"
        if track_fn in all_fn:
            all_fn.remove(track_fn)
    count = 0
    if all_fn:
        for fn in all_fn:
            if fn.endswith(".raw"):
                count += 1
                os.remove(os.path.join(download_dir, fn))
    reply = await m.reply_text(f"Cleaned {count} files.")


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & current_vc
    & filters.command("mute", COMMAND_PREFIXES)
)
async def mute(_, m: Message):
    group_call = mp.group_call
    group_call.set_is_mute(True)
    reply = await m.reply_text("Muted.")


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & current_vc
    & filters.command("unmute", COMMAND_PREFIXES)
)
async def unmute(_, m: Message):
    group_call = mp.group_call
    group_call.set_is_mute(False)
    reply = await m.reply_text("Unmuted.")


@app.on_message(
    main_filter
    & filters.user(AdminSettings)
    & filters.command("mode", COMMAND_PREFIXES)
)
async def set_mode(_, m: Message):
    global AM_ENABLED
    args = m.command
    if len(args) >= 2:
        if args[1] == "admin":
            AM_ENABLED = True
            await m.reply_text("Admin mode enabled.")
        elif args[1] == "all":
            AM_ENABLED = False
            await m.reply_text("Admin mode disabled.")
        else:
            await m.reply_text("Mode not recognized, possible modes are `admin` or `all`.")
    else:
        await m.reply_text(f"Admin mode is enabled: {AM_ENABLED}")


# - Other functions


async def send_text(text):
    group_call = mp.group_call
    client = group_call.client
    chat_id = mp.chat_id
    message = await client.send_message(
        chat_id,
        text,
        disable_web_page_preview=True,
        disable_notification=True
    )
    return message


async def skip_current_playing():
    group_call = mp.group_call
    playlist = mp.playlist
    if not playlist:
        return
    if len(playlist) == 1:
        await mp.update_start_time()
        return
    client = group_call.client
    download_dir = os.path.join(client.workdir, DEFAULT_DOWNLOAD_DIR)
    group_call.input_filename = os.path.join(
        download_dir,
        f"{playlist[1].audio.file_unique_id}.raw"
    )
    await mp.update_start_time()
    # remove old track from playlist
    old_track = playlist.pop(0)
    print(f"- START PLAYING: {playlist[0].audio.title}")
    await mp.send_playlist()
    os.remove(os.path.join(
        download_dir,
        f"{old_track.audio.file_unique_id}.raw")
    )
    if len(playlist) == 1:
        return
    await download_audio(playlist[1])


async def download_audio(m: Message):
    group_call = mp.group_call
    client = group_call.client
    raw_file = os.path.join(client.workdir, DEFAULT_DOWNLOAD_DIR,
                            f"{m.audio.file_unique_id}.raw")
    if not os.path.isfile(raw_file):
        original_file = await m.download()
        ffmpeg.input(original_file).output(
            raw_file,
            format='s16le',
            acodec='pcm_s16le',
            ac=2,
            ar='48k',
            loglevel='error'
        ).overwrite_output().run()
        os.remove(original_file)
