import os
import json
import asyncio
import random
import string
import logging
from github import Github
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, 
    CallbackQuery, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
ADMIN_ID = 8661283656

CHANNEL_ID = "@Premium_Giive"
GITHUB_REPO_NAME = "Premiumm0/telegram-orders"
GITHUB_FILE_PATH = "orders.txt"
CARD_REQUISITES = "4323 3473 5653 0466 (A-Bank)"

USERS_GITHUB_PATH = "users_db.json"
ORDERS_GITHUB_PATH = "orders_db.json"
# ===================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# --- Синхронизация JSON с GitHub ---
def _load_json_from_github(filepath: str) -> dict:
    if not GITHUB_TOKEN:
        return {}
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO_NAME)
        contents = repo.get_contents(filepath)
        content_str = contents.decoded_content.decode("utf-8")
        return json.loads(content_str)
    except Exception as e:
        logging.warning(f"Не удалось загрузить {filepath} из GitHub (будет создан новый): {e}")
        return {}

def _save_json_to_github(filepath: str, data: dict):
    if not GITHUB_TOKEN:
        return
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO_NAME)
        json_str = json.dumps(data, ensure_ascii=False, indent=4)
        
        try:
            contents = repo.get_contents(filepath)
            sha = contents.sha
            repo.update_file(filepath, f"Update {filepath}", json_str, sha)
        except Exception:
            repo.create_file(filepath, f"Create {filepath}", json_str)
    except Exception as e:
        logging.error(f"Ошибка сохранения {filepath} в GitHub: {e}")

async def load_db_async(filepath: str) -> dict:
    return await asyncio.to_thread(_load_json_from_github, filepath)

async def save_db_async(filepath: str, data: dict):
    await asyncio.to_thread(_save_json_to_github, filepath, data)

# Глобальные словари
users_db = {}
orders_db = {}

# --- Веб-сервер для поддержания Render ---
async def handle_ping(request):
    return web.Response(text="Bot is online!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def keep_alive():
    while True:
        await asyncio.sleep(900)

# FSM Состояния
class OrderFSM(StatesGroup):
    waiting_for_phone = State()
    waiting_for_receipt = State()

def generate_order_id():
    chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"#Prem{chars}"

def _sync_save_to_github_txt(order_id: str, user_id: int, username: str, phone: str, item: str, price: str):
    try:
        if not GITHUB_TOKEN:
            return False
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO_NAME)
        
        try:
            contents = repo.get_contents(GITHUB_FILE_PATH)
            current_data = contents.decoded_content.decode("utf-8")
            sha = contents.sha
        except Exception:
            current_data = ""
            sha = None

        user_str = f"@{username}" if username else "no_username"
        new_entry = f"Заказ: {order_id} | UserID: {user_id} | Username: {user_str} | Телефон: {phone} | Товар: {item} | Сумма: {price}\n"
        updated_data = current_data + new_entry

        if sha:
            repo.update_file(GITHUB_FILE_PATH, f"Добавлен заказ {order_id}", updated_data, sha)
        else:
            repo.create_file(GITHUB_FILE_PATH, f"Заказ {order_id}", updated_data)
        return True
    except Exception as e:
        logging.error(f"Ошибка сохранения заказов в orders.txt: {e}")
        return False

async def save_order_to_github_txt(order_id: str, user_id: int, username: str, phone: str, item: str, price: str):
    return await asyncio.to_thread(_sync_save_to_github_txt, order_id, user_id, username, phone, item, price)

# Клавиатуры
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💎 Купить Premium")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📞 Поддержка")]
        ],
        resize_keyboard=True
    )

def get_tariff_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 1 месяц — 160 грн", callback_data="buy_1_month")],
            [InlineKeyboardButton(text="📅 1 год — 1300 грн", callback_data="buy_1_year")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
        ]
    )

def get_back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_tariffs")]
        ]
    )

def get_payment_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📸 Отправить чек", callback_data="send_receipt")],
            [InlineKeyboardButton(text="❌ Отменить заказ", callback_data="cancel_order")]
        ]
    )

# Обработчики
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)
    
    if user_id not in users_db:
        users_db[user_id] = {
            "name": message.from_user.first_name,
            "username": message.from_user.username,
            "completed_orders": 0,
            "spent_money": 0
        }
    else:
        users_db[user_id]["name"] = message.from_user.first_name
        users_db[user_id]["username"] = message.from_user.username
        
    await save_db_async(USERS_GITHUB_PATH, users_db)

    text = (
        "👋 Добро пожаловать в магазин Telegram Premium!\n"
        "Здесь ты можешь быстро приобрести Premium на свой аккаунт.\n\n"
        "💎 Выберите действие:"
    )
    await message.answer(text, reply_markup=get_main_keyboard())

@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    user_id = str(message.from_user.id)
    
    if message.from_user.id == ADMIN_ID:
        total_users = len(users_db)
        total_orders = sum(u.get("completed_orders", 0) for u in users_db.values())
        total_revenue = sum(u.get("spent_money", 0) for u in users_db.values())
        
        admin_text = (
            "👑 <b>Панель Администратора</b>\n\n"
            f"👤 <b>Имя:</b> {message.from_user.first_name}\n"
            f"🆔 <b>ID:</b> <code>{message.from_user.id}</code>\n\n"
            f"📊 <b>Статистика бота:</b>\n"
            f"👥 Пользователей в боте: <b>{total_users}</b>\n"
            f"💎 Куплено Premium: <b>{total_orders}</b>\n"
            f"💰 Общая выручка: <b>{total_revenue} грн</b>"
        )
        await message.answer(admin_text, parse_mode="HTML")
        return

    user_data = users_db.get(user_id, {"name": message.from_user.first_name})
    text = (
        "👤 <b>Ваш профиль</b>\n\n"
        f"🆔 <b>ID:</b> <code>{message.from_user.id}</code>\n"
        f"👤 <b>Имя:</b> {user_data.get('name', 'Пользователь')}"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "📞 Поддержка")
async def show_support(message: Message):
    await message.answer("📞 По вопросам поддержки обращайтесь к администратору.")

@router.message(F.text == "💎 Купить Premium")
async def buy_premium_menu(message: Message):
    await message.answer("💎 Telegram Premium", reply_markup=get_tariff_keyboard())

@router.callback_query(F.data == "back_to_main")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer("💎 Выберите действие:", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("💎 Telegram Premium", reply_markup=get_tariff_keyboard())

@router.callback_query(F.data.in_({"buy_1_month", "buy_1_year"}))
async def select_tariff(call: CallbackQuery, state: FSMContext):
    if call.data == "buy_1_month":
        item_name = "Premium 1 месяц"
        price_num = 160
        price_str = "160 грн"
    else:
        item_name = "Premium 1 год"
        price_num = 1300
        price_str = "1300 грн"

    await state.update_data(item_name=item_name, price_str=price_str, price_num=price_num)
    await state.set_state(OrderFSM.waiting_for_phone)

    text = (
        "📱 Напишите номер телефона\n"
        "Введите номер телефона, на который зарегистрирован ваш Telegram-аккаунт.\n"
        "Например: +380XXXXXXXXX"
    )
    await call.message.edit_text(text, reply_markup=get_back_keyboard())

@router.message(OrderFSM.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    data = await state.get_data()
    
    order_id = generate_order_id()
    await state.update_data(phone=phone, order_id=order_id)
    
    orders_db[order_id] = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "full_name": message.from_user.full_name,
        "item": data["item_name"],
        "price_str": data["price_str"],
        "price_num": data["price_num"],
        "phone": phone,
        "status": "pending"
    }
    await save_db_async(ORDERS_GITHUB_PATH, orders_db)

    text = (
        "<b>💳 Оплата заказа</b>\n\n"
        f"<blockquote>Заказ: {order_id}\n"
        f"Товар: {data['item_name']}\n"
        f"Номер: {phone}\n"
        f"Стоимость: {data['price_str']}</blockquote>\n\n"
        "<b>💳 Реквизиты для перевода</b>\n\n"
        f"<blockquote>• Банк: A-Bank\n"
        f"• Реквизиты: {CARD_REQUISITES}</blockquote>\n\n"
        "<b>📌 Инструкция:</b>\n"
        "<blockquote>1. Выполните перевод по реквизитам выше.\n"
        "2. Нажмите «📸 Отправить чек» и прикрепите фото.\n"
        "3. После проверки заказ будет передан в обработку.</blockquote>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_payment_keyboard())

@router.callback_query(F.data == "cancel_order")
async def cancel_order(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id", "#Prem000000")
    item = data.get("item_name", "Premium 1 месяц")
    price = data.get("price_str", "160 грн")

    await state.clear()
    
    text = (
        "❌ <b>Заказ отменён</b>\n\n"
        f"<blockquote>Заказ: {order_id}\n"
        f"Товар: {item}\n"
        f"Стоимость: {price}</blockquote>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_to_main")]])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@router.callback_query(F.data == "send_receipt")
async def request_receipt(call: CallbackQuery, state: FSMContext):
    await state.set_state(OrderFSM.waiting_for_receipt)
    await call.message.answer("📸 Пожалуйста, отправьте фото чека об оплате:")

@router.message(OrderFSM.waiting_for_receipt, F.photo)
async def process_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    
    text = (
        "✅ <b>Чек получен!</b>\n\n"
        f"<blockquote>Заказ: {order_id}\n"
        "Статус: На проверке администратором</blockquote>\n\n"
        "⏳ Ожидайте подтверждения выполнения."
    )
    await message.answer(text, parse_mode="HTML")

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{order_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{order_id}")
            ]
        ]
    )
    
    username_str = f"@{message.from_user.username}" if message.from_user.username else "Нет юзернейма"
    
    admin_text = (
        "🔔 <b>Новый чек на проверку!</b>\n\n"
        f"<blockquote>Заказ: {order_id}\n"
        f"Пользователь: {message.from_user.full_name}\n"
        f"Юзернейм: {username_str}\n"
        f"ID: {message.from_user.id}\n"
        f"Товар: {data.get('item_name', 'Premium')}\n"
        f"Номер: {data.get('phone', 'Не указан')}\n"
        f"Сумма: {data.get('price_str', '160 грн')}</blockquote>"
    )
    
    await asyncio.sleep(1)
    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=admin_text,
        reply_markup=admin_kb,
        parse_mode="HTML"
    )
    await state.clear()

@router.callback_query(F.data.startswith("approve_"))
async def admin_approve(call: CallbackQuery):
    order_id = call.data.split("_")[1]
    order_info = orders_db.get(order_id)
    
    if not order_info:
        await call.answer("Заказ не найден.", show_alert=True)
        return

    if order_info.get("status") == "approved":
        await call.answer("Этот заказ уже одобрен!", show_alert=True)
        return

    order_info["status"] = "approved"
    orders_db[order_id] = order_info
    await save_db_async(ORDERS_GITHUB_PATH, orders_db)

    user_id = str(order_info["user_id"])
    username = order_info.get("username", "")
    phone = order_info.get("phone", "")
    item = order_info["item"]
    price_str = order_info["price_str"]
    price_num = order_info.get("price_num", 0)

    # Запись текстового лога в GitHub (orders.txt)
    await save_order_to_github_txt(order_id, int(user_id), username, phone, item, price_str)

    # Обновление статистики пользователя
    if user_id in users_db:
        users_db[user_id]["completed_orders"] = users_db[user_id].get("completed_orders", 0) + 1
        users_db[user_id]["spent_money"] = users_db[user_id].get("spent_money", 0) + price_num
        await save_db_async(USERS_GITHUB_PATH, users_db)

    user_text = (
        "🎉 <b>Оплата подтверждена!</b>\n\n"
        f"<blockquote>Заказ: {order_id}\n"
        f"Товар: {item}\n"
        f"Стоимость: {price_str}</blockquote>\n\n"
        "⏳ Заказ передан в обработку и скоро будет выполнен."
    )
    try:
        await bot.send_message(chat_id=int(user_id), text=user_text, parse_mode="HTML")
    except Exception:
        pass

    duration_text = "1 месяц" if "1 месяц" in item else "1 год"
    channel_text = (
        "💎 <b>Premium успешно выдан!</b>\n\n"
        f"<blockquote>Заказ: {order_id}\n"
        f"Подписка: {duration_text}\n"
        f"Стоимость: {price_str}</blockquote>\n\n"
        "✅ Заказ успешно выполнен!"
    )
    try:
        await asyncio.sleep(1)
        await bot.send_message(chat_id=CHANNEL_ID, text=channel_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка публикации в канал: {e}")

    await call.message.edit_caption(caption=call.message.caption + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML", reply_markup=None)
    await call.answer("Заказ успешно одобрен!")

@router.callback_query(F.data.startswith("reject_"))
async def admin_reject(call: CallbackQuery):
    order_id = call.data.split("_")[1]
    order_info = orders_db.get(order_id)
    
    if not order_info:
        await call.answer("Заказ не найден.", show_alert=True)
        return

    if order_info.get("status") == "rejected":
        await call.answer("Этот заказ уже отклонен!", show_alert=True)
        return

    order_info["status"] = "rejected"
    orders_db[order_id] = order_info
    await save_db_async(ORDERS_GITHUB_PATH, orders_db)

    user_id = str(order_info["user_id"])
    try:
        await bot.send_message(chat_id=int(user_id), text=f"❌ Ваш заказ {order_id} был отменён администратором.")
    except Exception:
        pass

    await call.message.edit_caption(caption=call.message.caption + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML", reply_markup=None)
    await call.answer("Заказ отклонён.")

async def main():
    logging.basicConfig(level=logging.INFO)
    
    global users_db, orders_db
    users_db = await load_db_async(USERS_GITHUB_PATH)
    orders_db = await load_db_async(ORDERS_GITHUB_PATH)

    asyncio.create_task(start_web_server())
    asyncio.create_task(keep_alive())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
