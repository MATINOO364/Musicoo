# -*- coding: utf-8 -*-
"""
Ø±Ø¨Ø§Øª Ù…ÙˆØ²ÛŒÚ© ØªÙ„Ú¯Ø±Ø§Ù… - Ù‡Ù…Ù‡ Ú†ÛŒØ² Ø¯Ø± ÛŒÚ© ÙØ§ÛŒÙ„
Ù†ÛŒØ§Ø²Ù…Ù†Ø¯ÛŒâ€ŒÙ‡Ø§: aiogram==3.*  aiosqlite
Ø§Ø¬Ø±Ø§: python bot.py
"""
import asyncio
import datetime
import logging

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from config import BOT_TOKEN, ADMIN_IDS, CHANNEL_ID, DB_PATH, MAX_CONSECUTIVE_MISSES, INDEX_DELAY

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ==================================================================
#                              Ø¯ÛŒØªØ§Ø¨ÛŒØ³
# ==================================================================

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code INTEGER UNIQUE NOT NULL,
            title TEXT, artist TEXT, file_id TEXT NOT NULL,
            duration INTEGER, lyrics TEXT, cover_file_id TEXT,
            channel_msg_id INTEGER, plays INTEGER DEFAULT 0,
            downloads INTEGER DEFAULT 0, added_date TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS song_qualities (
            id INTEGER PRIMARY KEY AUTOINCREMENT, song_id INTEGER NOT NULL,
            label TEXT NOT NULL, file_id TEXT NOT NULL)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            joined_date TEXT, is_banned INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL, song_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, song_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS playlist_songs (
            playlist_id INTEGER NOT NULL, song_id INTEGER NOT NULL,
            PRIMARY KEY (playlist_id, song_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS downloads_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            song_id INTEGER NOT NULL, ts TEXT)""")
        await db.commit()


async def q(sql, params=(), fetch=None, row=True):
    """Ø§Ø¬Ø±Ø§ÛŒ Ú©ÙˆØ¦Ø±ÛŒ Ú©Ù…Ú©ÛŒ: fetch=None -> ÙÙ‚Ø· Ø§Ø¬Ø±Ø§ØŒ 'one' ÛŒØ§ 'all' -> Ø¯Ø±ÛŒØ§ÙØª Ù†ØªÛŒØ¬Ù‡"""
    async with aiosqlite.connect(DB_PATH) as db:
        if row:
            db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, params)
        if fetch == "one":
            result = await cur.fetchone()
        elif fetch == "all":
            result = await cur.fetchall()
        else:
            result = cur.lastrowid
        await db.commit()
        return result


async def add_user(user_id, username, first_name):
    row = await q("SELECT user_id FROM users WHERE user_id=?", (user_id,), fetch="one")
    if not row:
        await q("INSERT INTO users (user_id, username, first_name, joined_date) VALUES (?,?,?,?)",
                 (user_id, username, first_name, datetime.datetime.now().isoformat()))


async def get_next_code():
    row = await q("SELECT MAX(code) FROM songs", fetch="one", row=False)
    return (row[0] or 0) + 1


async def get_max_indexed_channel_msg_id():
    row = await q("SELECT MAX(channel_msg_id) FROM songs WHERE channel_msg_id IS NOT NULL", fetch="one", row=False)
    return row[0] or 0


async def add_song(title, artist, file_id, duration=None, channel_msg_id=None, code=None):
    if code is None:
        code = await get_next_code()
    await q("""INSERT INTO songs (code, title, artist, file_id, duration, channel_msg_id, added_date)
               VALUES (?,?,?,?,?,?,?)""",
            (code, title, artist, file_id, duration, channel_msg_id, datetime.datetime.now().isoformat()))
    return code


# ==================================================================
#                             Ú©ÛŒØ¨ÙˆØ±Ø¯Ù‡Ø§
# ==================================================================

def main_menu(user_id):
    rows = [
        [KeyboardButton(text="ðŸ” Ø¬Ø³ØªØ¬Ùˆ"), KeyboardButton(text="ðŸŽµ Ø¢Ø®Ø±ÛŒÙ† Ø¢Ù‡Ù†Ú¯â€ŒÙ‡Ø§")],
        [KeyboardButton(text="ðŸŽ² Ø¢Ù‡Ù†Ú¯ ØªØµØ§Ø¯ÙÛŒ"), KeyboardButton(text="ðŸ“ˆ Ù…Ø­Ø¨ÙˆØ¨â€ŒØªØ±ÛŒÙ† Ø¢Ù‡Ù†Ú¯â€ŒÙ‡Ø§")],
        [KeyboardButton(text="â¤ï¸ Ø¹Ù„Ø§Ù‚Ù‡â€ŒÙ…Ù†Ø¯ÛŒâ€ŒÙ‡Ø§"), KeyboardButton(text="ðŸŽ§ Ù¾Ù„ÛŒâ€ŒÙ„ÛŒØ³Øªâ€ŒÙ‡Ø§ÛŒ Ù…Ù†")],
        [KeyboardButton(text="ðŸ‘¤ Ù¾Ø±ÙˆÙØ§ÛŒÙ„ Ù…Ù†")],
    ]
    if is_admin(user_id):
        rows.append([KeyboardButton(text="ðŸ‘¨â€ðŸ’» Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu():
    rows = [
        [KeyboardButton(text="âž• Ø§ÙØ²ÙˆØ¯Ù† Ø¢Ù‡Ù†Ú¯ ØªÚ©ÛŒ"), KeyboardButton(text="ðŸ”„ Ø§ÛŒÙ†Ø¯Ú©Ø³ Ú©Ù„ Ú©Ø§Ù†Ø§Ù„")],
        [KeyboardButton(text="âœï¸ ÙˆÛŒØ±Ø§ÛŒØ´ Ø¢Ù‡Ù†Ú¯"), KeyboardButton(text="âŒ Ø­Ø°Ù Ø¢Ù‡Ù†Ú¯")],
        [KeyboardButton(text="ðŸ“Š Ø¢Ù…Ø§Ø± Ø±Ø¨Ø§Øª"), KeyboardButton(text="ðŸ”” Ø§Ø±Ø³Ø§Ù„ Ø§Ø·Ù„Ø§Ø¹ÛŒÙ‡ Ø¨Ù‡ Ù‡Ù…Ù‡")],
        [KeyboardButton(text="â¬…ï¸ Ø¨Ø§Ø²Ú¯Ø´Øª Ø¨Ù‡ Ù…Ù†ÙˆÛŒ Ø§ØµÙ„ÛŒ")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Ù„ØºÙˆ âœ–ï¸")]], resize_keyboard=True)


def skip_cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Ø±Ø¯ Ú©Ø±Ø¯Ù† â­"), KeyboardButton(text="Ù„ØºÙˆ âœ–ï¸")]], resize_keyboard=True)


def song_card_kb(song_id, code, is_fav):
    fav_text = "ðŸ’” Ø­Ø°Ù Ø§Ø² Ø¹Ù„Ø§Ù‚Ù‡â€ŒÙ…Ù†Ø¯ÛŒâ€ŒÙ‡Ø§" if is_fav else "â¤ï¸ Ø§ÙØ²ÙˆØ¯Ù† Ø¨Ù‡ Ø¹Ù„Ø§Ù‚Ù‡â€ŒÙ…Ù†Ø¯ÛŒâ€ŒÙ‡Ø§"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ðŸ“¥ Ø¯Ø§Ù†Ù„ÙˆØ¯", callback_data=f"dl:{song_id}"),
         InlineKeyboardButton(text="ðŸŽš Ú©ÛŒÙÛŒØªâ€ŒÙ‡Ø§ÛŒ Ø¯ÛŒÚ¯Ø±", callback_data=f"qual:{song_id}")],
        [InlineKeyboardButton(text="ðŸŽ¤ Ù…ØªÙ† Ø¢Ù‡Ù†Ú¯", callback_data=f"lyr:{song_id}"),
         InlineKeyboardButton(text="ðŸ“€ Ú©Ø§ÙˆØ± Ø¢Ù„Ø¨ÙˆÙ…", callback_data=f"cov:{song_id}")],
        [InlineKeyboardButton(text=fav_text, callback_data=f"fav:{song_id}")],
        [InlineKeyboardButton(text="ðŸŽ§ Ø§ÙØ²ÙˆØ¯Ù† Ø¨Ù‡ Ù¾Ù„ÛŒâ€ŒÙ„ÛŒØ³Øª", callback_data=f"addpl:{song_id}"),
         InlineKeyboardButton(text="ðŸ“¤ Ø§Ø´ØªØ±Ø§Ú©â€ŒÚ¯Ø°Ø§Ø±ÛŒ", switch_inline_query=str(code))],
    ])


def qualities_kb(song_id, qualities):
    buttons = [[InlineKeyboardButton(text=f"ðŸŽš {qq['label']}", callback_data=f"dlq:{qq['id']}")] for qq in qualities]
    buttons.append([InlineKeyboardButton(text="ðŸ“¥ Ú©ÛŒÙÛŒØª Ø§ØµÙ„ÛŒ/Ù¾ÛŒØ´â€ŒÙØ±Ø¶", callback_data=f"dl:{song_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def song_list_kb(songs, prefix="open"):
    buttons = []
    for s in songs:
        title = s["title"] or "Ø¨Ø¯ÙˆÙ† Ø¹Ù†ÙˆØ§Ù†"
        artist = s["artist"] or ""
        text = f"#{s['code']} | {title} - {artist}" if artist else f"#{s['code']} | {title}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"{prefix}:{s['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def playlists_kb(playlists, song_id=None):
    prefix = f"pladd:{song_id}:" if song_id else "plopen:"
    buttons = [[InlineKeyboardButton(text=f"ðŸŽ§ {p['name']}", callback_data=f"{prefix}{p['id']}")] for p in playlists]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================================================================
#                          Ø§Ø³ØªÛŒØªâ€ŒÙ‡Ø§ÛŒ FSM
# ==================================================================

class SearchState(StatesGroup):
    waiting_query = State()


class AddSongState(StatesGroup):
    waiting_audio = State()
    waiting_title = State()
    waiting_artist = State()
    waiting_lyrics = State()
    waiting_cover = State()


class EditSongState(StatesGroup):
    waiting_code = State()
    waiting_field = State()
    waiting_value = State()


class DeleteSongState(StatesGroup):
    waiting_code = State()


class BroadcastState(StatesGroup):
    waiting_message = State()


class PlaylistState(StatesGroup):
    waiting_name = State()


class AddQualityState(StatesGroup):
    waiting_code = State()
    waiting_label = State()
    waiting_audio = State()


# ==================================================================
#                       Ø§Ø±Ø³Ø§Ù„ Ú©Ø§Ø±Øª Ø¢Ù‡Ù†Ú¯ Ø¨Ù‡ Ú©Ø§Ø±Ø¨Ø±
# ==================================================================

async def send_song_card(chat_id, song, user_id):
    is_fav = await q("SELECT 1 FROM favorites WHERE user_id=? AND song_id=?",
                      (user_id, song["id"]), fetch="one")
    caption = f"ðŸŽµ <b>{song['title'] or 'Ø¨Ø¯ÙˆÙ† Ø¹Ù†ÙˆØ§Ù†'}</b>\nðŸ‘¤ {song['artist'] or 'Ù†Ø§Ù…Ø´Ø®Øµ'}\nðŸ”¢ Ú©Ø¯: <code>{song['code']}</code>\nâ–¶ï¸ Ù¾Ø®Ø´: {song['plays']}  |  ðŸ“¥ Ø¯Ø§Ù†Ù„ÙˆØ¯: {song['downloads']}"
    kb = song_card_kb(song["id"], song["code"], bool(is_fav))
    if song["cover_file_id"]:
        await bot.send_photo(chat_id, song["cover_file_id"], caption=caption, reply_markup=kb)
    else:
        await bot.send_message(chat_id, caption, reply_markup=kb)


# ==================================================================
#                        Ù‡Ù†Ø¯Ù„Ø±Ù‡Ø§ÛŒ Ú©Ø§Ø±Ø¨Ø± Ø¹Ø§Ø¯ÛŒ
# ==================================================================

@router.message(CommandStart())
async def cmd_start(message: Message):
    await add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await message.answer(
        "ðŸŽ¶ Ø¨Ù‡ Ø±Ø¨Ø§Øª Ù…ÙˆØ²ÛŒÚ© Ø®ÙˆØ´ Ø§ÙˆÙ…Ø¯ÛŒ!\nØ§Ø² Ù…Ù†ÙˆÛŒ Ø²ÛŒØ± Ø§Ø³ØªÙØ§Ø¯Ù‡ Ú©Ù† ÛŒØ§ Ú©Ø¯ Ø¢Ù‡Ù†Ú¯ Ø±Ùˆ Ù…Ø³ØªÙ‚ÛŒÙ… Ø¨ÙØ±Ø³Øª.",
        reply_markup=main_menu(message.from_user.id)
    )


@router.message(F.text == "ðŸ” Ø¬Ø³ØªØ¬Ùˆ")
async def start_search(message: Message, state: FSMContext):
    await state.set_state(SearchState.waiting_query)
    await message.answer("Ù†Ø§Ù… Ø¢Ù‡Ù†Ú¯ØŒ Ù†Ø§Ù… Ø®ÙˆØ§Ù†Ù†Ø¯Ù‡ ÛŒØ§ Ú©Ø¯ Ø¢Ù‡Ù†Ú¯ Ø±Ùˆ Ø¨ÙØ±Ø³Øª:", reply_markup=cancel_kb())


@router.message(F.text == "Ù„ØºÙˆ âœ–ï¸")
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Ù„ØºÙˆ Ø´Ø¯.", reply_markup=main_menu(message.from_user.id))


@router.message(SearchState.waiting_query)
async def do_search(message: Message, state: FSMContext):
    await state.clear()
    text = message.text.strip()
    if text.isdigit():
        song = await q("SELECT * FROM songs WHERE code=?", (int(text),), fetch="one")
        if song:
            await increment_plays_and_send(message.chat.id, song, message.from_user.id)
        else:
            await message.answer("Ø¢Ù‡Ù†Ú¯ÛŒ Ø¨Ø§ Ø§ÛŒÙ† Ú©Ø¯ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", reply_markup=main_menu(message.from_user.id))
        return
    like = f"%{text}%"
    songs = await q("SELECT * FROM songs WHERE title LIKE ? OR artist LIKE ? ORDER BY code LIMIT 20",
                     (like, like), fetch="all")
    if not songs:
        await message.answer("Ú†ÛŒØ²ÛŒ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯ ðŸ˜”", reply_markup=main_menu(message.from_user.id))
        return
    await message.answer(f"Ù†ØªØ§ÛŒØ¬ Ø¬Ø³ØªØ¬Ùˆ ({len(songs)}):", reply_markup=main_menu(message.from_user.id))
    await message.answer("ÛŒÚ©ÛŒ Ø±Ùˆ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†:", reply_markup=song_list_kb(songs))


# Ø§Ú¯Ø± Ú©Ø§Ø±Ø¨Ø± Ù…Ø³ØªÙ‚ÛŒÙ… ÙÙ‚Ø· Ú©Ø¯ Ø±Ø§ Ø¨ÙØ±Ø³ØªØ¯ (Ø¨Ø¯ÙˆÙ† Ø±ÙØªÙ† Ø¨Ù‡ Ø­Ø§Ù„Øª Ø¬Ø³ØªØ¬Ùˆ)
@router.message(F.text.regexp(r"^\d+$"))
async def direct_code(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        return
    code = int(message.text.strip())
    song = await q("SELECT * FROM songs WHERE code=?", (code,), fetch="one")
    if song:
        await increment_plays_and_send(message.chat.id, song, message.from_user.id)
    else:
        await message.answer("Ø¢Ù‡Ù†Ú¯ÛŒ Ø¨Ø§ Ø§ÛŒÙ† Ú©Ø¯ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.")


async def increment_plays_and_send(chat_id, song, user_id):
    await q("UPDATE songs SET plays = plays + 1 WHERE id=?", (song["id"],))
    await send_song_card(chat_id, song, user_id)


@router.message(F.text == "ðŸŽµ Ø¢Ø®Ø±ÛŒÙ† Ø¢Ù‡Ù†Ú¯â€ŒÙ‡Ø§")
async def latest_songs(message: Message):
    songs = await q("SELECT * FROM songs ORDER BY id DESC LIMIT 10", fetch="all")
    if not songs:
        await message.answer("Ù‡Ù†ÙˆØ² Ø¢Ù‡Ù†Ú¯ÛŒ Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡.")
        return
    await message.answer("ðŸŽµ Ø¢Ø®Ø±ÛŒÙ† Ø¢Ù‡Ù†Ú¯â€ŒÙ‡Ø§:", reply_markup=song_list_kb(songs))


@router.message(F.text == "ðŸŽ² Ø¢Ù‡Ù†Ú¯ ØªØµØ§Ø¯ÙÛŒ")
async def random_song(message: Message):
    song = await q("SELECT * FROM songs ORDER BY RANDOM() LIMIT 1", fetch="one")
    if not song:
        await message.answer("Ù‡Ù†ÙˆØ² Ø¢Ù‡Ù†Ú¯ÛŒ Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡.")
        return
    await increment_plays_and_send(message.chat.id, song, message.from_user.id)


@router.message(F.text == "ðŸ“ˆ Ù…Ø­Ø¨ÙˆØ¨â€ŒØªØ±ÛŒÙ† Ø¢Ù‡Ù†Ú¯â€ŒÙ‡Ø§")
async def top_songs(message: Message):
    songs = await q("SELECT * FROM songs ORDER BY (plays+downloads) DESC LIMIT 10", fetch="all")
    if not songs:
        await message.answer("Ù‡Ù†ÙˆØ² Ø¢Ù‡Ù†Ú¯ÛŒ Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡.")
        return
    await message.answer("ðŸ“ˆ Ù…Ø­Ø¨ÙˆØ¨â€ŒØªØ±ÛŒÙ† Ø¢Ù‡Ù†Ú¯â€ŒÙ‡Ø§:", reply_markup=song_list_kb(songs))


@router.message(F.text == "â¤ï¸ Ø¹Ù„Ø§Ù‚Ù‡â€ŒÙ…Ù†Ø¯ÛŒâ€ŒÙ‡Ø§")
async def my_favorites(message: Message):
    songs = await q("""SELECT s.* FROM songs s JOIN favorites f ON f.song_id=s.id
                        WHERE f.user_id=? ORDER BY s.code""", (message.from_user.id,), fetch="all")
    if not songs:
        await message.answer("Ù„ÛŒØ³Øª Ø¹Ù„Ø§Ù‚Ù‡â€ŒÙ…Ù†Ø¯ÛŒâ€ŒÙ‡Ø§ÛŒ ØªÙˆ Ø®Ø§Ù„ÛŒÙ‡.")
        return
    await message.answer("â¤ï¸ Ø¹Ù„Ø§Ù‚Ù‡â€ŒÙ…Ù†Ø¯ÛŒâ€ŒÙ‡Ø§ÛŒ ØªÙˆ:", reply_markup=song_list_kb(songs))


@router.message(F.text == "ðŸ‘¤ Ù¾Ø±ÙˆÙØ§ÛŒÙ„ Ù…Ù†")
async def my_profile(message: Message):
    uid = message.from_user.id
    user = await q("SELECT * FROM users WHERE user_id=?", (uid,), fetch="one")
    fav_count = (await q("SELECT COUNT(*) FROM favorites WHERE user_id=?", (uid,), fetch="one", row=False))[0]
    dl_count = (await q("SELECT COUNT(*) FROM downloads_log WHERE user_id=?", (uid,), fetch="one", row=False))[0]
    joined = user["joined_date"][:10] if user else "-"
    await message.answer(
        f"ðŸ‘¤ <b>Ù¾Ø±ÙˆÙØ§ÛŒÙ„ ØªÙˆ</b>\nØ¢ÛŒØ¯ÛŒ: <code>{uid}</code>\nØ¹Ø¶ÙˆÛŒØª: {joined}\n"
        f"ðŸ“¥ ØªØ¹Ø¯Ø§Ø¯ Ø¯Ø§Ù†Ù„ÙˆØ¯: {dl_count}\nâ¤ï¸ ØªØ¹Ø¯Ø§Ø¯ Ø¹Ù„Ø§Ù‚Ù‡â€ŒÙ…Ù†Ø¯ÛŒ: {fav_count}"
    )


@router.message(F.text == "ðŸŽ§ Ù¾Ù„ÛŒâ€ŒÙ„ÛŒØ³Øªâ€ŒÙ‡Ø§ÛŒ Ù…Ù†")
async def my_playlists(message: Message, state: FSMContext):
    pls = await q("SELECT * FROM playlists WHERE user_id=?", (message.from_user.id,), fetch="all")
    if not pls:
        await state.set_state(PlaylistState.waiting_name)
        await message.answer("Ù‡Ù†ÙˆØ² Ù¾Ù„ÛŒâ€ŒÙ„ÛŒØ³ØªÛŒ Ù†Ø³Ø§Ø®ØªÛŒ. Ø¨Ø±Ø§ÛŒ Ø³Ø§Ø®ØªØŒ Ø§Ø³Ù… Ù¾Ù„ÛŒâ€ŒÙ„ÛŒØ³Øª Ø¬Ø¯ÛŒØ¯ Ø±Ùˆ Ø¨ÙØ±Ø³Øª:", reply_markup=cancel_kb())
        return
    kb = playlists_kb(pls)
    kb.inline_keyboard.append([InlineKeyboardButton(text="âž• Ø³Ø§Ø®Øª Ù¾Ù„ÛŒâ€ŒÙ„ÛŒØ³Øª Ø¬Ø¯ÛŒØ¯", callback_data="newpl")])
    await message.answer("ðŸŽ§ Ù¾Ù„ÛŒâ€ŒÙ„ÛŒØ³Øªâ€ŒÙ‡Ø§ÛŒ ØªÙˆ:", reply_markup=kb)


@router.callback_query(F.data == "newpl")
async def cb_new_playlist(call: CallbackQuery, state: FSMContext):
    await state.set_state(PlaylistState.waiting_name)
    await call.message.answer("Ø§Ø³Ù… Ù¾Ù„ÛŒâ€ŒÙ„ÛŒØ³Øª Ø¬Ø¯ÛŒØ¯ Ø±Ùˆ Ø¨ÙØ±Ø³Øª:", reply_markup=cancel_kb())
    await call.answer()


@router.message(PlaylistState.waiting_name)
async def create_playlist_handler(message: Message, state: FSMContext):
    await state.clear()
    name = message.text.strip()
    await q("INSERT INTO playlists (user_id, name) VALUES (?,?)", (message.from_user.id, name))
    await message.answer(f"Ù¾Ù„ÛŒâ€ŒÙ„ÛŒØ³Øª Â«{name}Â» Ø³Ø§Ø®ØªÙ‡ Ø´Ø¯ âœ…")


# ---------------- Ú©Ø§Ù„â€ŒØ¨Ú©â€ŒÙ‡Ø§ÛŒ Ù…Ø±Ø¨ÙˆØ· Ø¨Ù‡ Ú©Ø§Ø±Øª Ø¢Ù‡Ù†Ú¯ ----------------

@router.callback_query(F.data.startswith("open:"))
async def cb_open_song(call: CallbackQuery):
    song_id = int(call.data.split(":")[1])
    song = await q("SELECT * FROM songs WHERE id=?", (song_id,), fetch="one")
    if song:
        await q("UPDATE songs SET plays = plays + 1 WHERE id=?", (song_id,))
        await send_song_card(call.message.chat.id, song, call.from_user.id)
    await call.answer()


@router.callback_query(F.data.startswith("dl:"))
async def cb_download(call: CallbackQuery):
    song_id = int(call.data.split(":")[1])
    song = await q("SELECT * FROM songs WHERE id=?", (song_id,), fetch="one")
    if not song:
        await call.answer("Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True)
        return
    await bot.send_audio(call.message.chat.id, song["file_id"],
                          caption=f"ðŸŽµ {song['title'] or ''} - {song['artist'] or ''}\nðŸ”¢ Ú©Ø¯: {song['code']}")
    await q("UPDATE songs SET downloads = downloads + 1 WHERE id=?", (song_id,))
    await q("INSERT INTO downloads_log (user_id, song_id, ts) VALUES (?,?,?)",
            (call.from_user.id, song_id, datetime.datetime.now().isoformat()))
    await call.answer("Ø¯Ø± Ø­Ø§Ù„ Ø§Ø±Ø³Ø§Ù„ ðŸ“¥")


@router.callback_query(F.data.startswith("qual:"))
async def cb_qualities(call: CallbackQuery):
    song_id = int(call.data.split(":")[1])
    quals = await q("SELECT * FROM song_qualities WHERE song_id=?", (song_id,), fetch="all")
    if not quals:
        await call.answer("Ú©ÛŒÙÛŒØª Ø¯ÛŒÚ¯Ù‡â€ŒØ§ÛŒ Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡ØŒ Ù‡Ù…ÙˆÙ† Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ø§Ø±Ø³Ø§Ù„ Ù…ÛŒØ´Ù‡.", show_alert=True)
        return
    await call.message.answer("Ú©ÛŒÙÛŒØª Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± Ø±Ùˆ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†:", reply_markup=qualities_kb(song_id, quals))
    await call.answer()


@router.callback_query(F.data.startswith("dlq:"))
async def cb_download_quality(call: CallbackQuery):
    qid = int(call.data.split(":")[1])
    row = await q("SELECT * FROM song_qualities WHERE id=?", (qid,), fetch="one")
    if not row:
        await call.answer("Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True)
        return
    await bot.send_audio(call.message.chat.id, row["file_id"], caption=f"ðŸŽš Ú©ÛŒÙÛŒØª: {row['label']}")
    await q("UPDATE songs SET downloads = downloads + 1 WHERE id=?", (row["song_id"],))
    await q("INSERT INTO downloads_log (user_id, song_id, ts) VALUES (?,?,?)",
            (call.from_user.id, row["song_id"], datetime.datetime.now().isoformat()))
    await call.answer("Ø¯Ø± Ø­Ø§Ù„ Ø§Ø±Ø³Ø§Ù„ ðŸ“¥")


@router.callback_query(F.data.startswith("lyr:"))
async def cb_lyrics(call: CallbackQuery):
    song_id = int(call.data.split(":")[1])
    song = await q("SELECT * FROM songs WHERE id=?", (song_id,), fetch="one")
    if song and song["lyrics"]:
        await call.message.answer(f"ðŸŽ¤ <b>Ù…ØªÙ† Ø¢Ù‡Ù†Ú¯</b>\n\n{song['lyrics']}")
    else:
        await call.answer("Ù…ØªÙ† Ø¢Ù‡Ù†Ú¯ Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡.", show_alert=True)
        return
    await call.answer()


@router.callback_query(F.data.startswith("cov:"))
async def cb_cover(call: CallbackQuery):
    song_id = int(call.data.split(":")[1])
    song = await q("SELECT * FROM songs WHERE id=?", (song_id,), fetch="one")
    if song and song["cover_file_id"]:
        await bot.se
