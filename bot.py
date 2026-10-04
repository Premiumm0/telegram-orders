import os
import json
import asyncio
import random
import string
import logging
import time
from typing import Any, Awaitable, Callable, Dict
from dotenv import load_dotenv
from github import Github
from aiohttp import web

from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, 
    CallbackQuery, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    TelegramObject,
    ReplyKeyboardRemove
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# Загрузка переменных окружения
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Premium_Giive")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME", "Premiumm0/telegram-orders")
GITHUB_FILE_PATH = os.getenv("GITHUB_FILE_PATH", "orders.txt")
CARD_REQUISITES = os.getenv("CARD_REQUISITES", "4323 3473 5653 0466 (A-Bank)")

USERS_GITHUB_PATH = "users_db.json"
ORDERS_GITHUB_PATH = "orders_db.json"

if not BOT_TOKEN:
    raise ValueError("Ошибка: BOT_TOKEN не указан в .env файле!")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# ==================== MIDDLEWARE (ЗАЩИТА ОТ СПАМА) ====================
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, slow_mode_delay: float = 0.7):
        self.user_timeouts = {}
        self.slow_mode_delay = slow_mode_delay
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id:
            current_time = time.time()
            last_time = self.user_timeouts.get(user_id, 0)
            if current_time - last_time < self.slow_mode_delay:
                if isinstance(event, CallbackQuery):
                    await event.answer("⚠️ Пожалуйста, не нажимайте кнопки так часто!", show_alert=False)
                return
            self.user_timeouts[user_id] = current_time

        return await handler(event, data)

router.message.middleware(ThrottlingMiddleware())
router.callback_query.middleware(ThrottlingMiddleware())
dp.include_router(router)

# ==================== РАБОТА С СИНХРОНИЗАЦИЕЙ / БАЗОЙ ====================
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
        logging.warning(f"Не удалось загрузить {filepath} из GitHub: {e}")
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

users_db = {}
orders_db = {}

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
        logging.error(f"Ошибка сохранения заказов в txt: {e}")
        return False

async def save_order_to_github_txt(order_id: str, user_id: int, username: str, phone: str, item: str, price: str):
    return await asyncio.to_thread(_sync_save_to_github_txt, order_id, user_id, username, phone, item, price)

# ==================== ВЕБ-СЕРВЕРДЛЯ KEEP-ALIVE ====================
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

# ==================== FSM СОСТОЯНИЯ ====================
class OrderFSM(StatesGroup):
    waiting_for_phone = State()
    waiting_for_receipt = State()

def generate_order_id() -> str:
    chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"#Prem{chars}"

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💎 Купить Premium")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📞 Поддержка")]
        ],
        resize_keyboard=True
    )

def get_phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поделиться контактом", request_contact=True)],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def get_tariff_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 1 месяц — 160 грн", callback_data="buy_1_month")],
            [InlineKeyboardButton(text="📅 1 год — 1300 грн", callback_data="buy_1_year")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
        ]
    )

def get_payment_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📸 Отправить чек", callback_data="send_receipt")],
            [InlineKeyboardButton(text="❌ Отменить заказ", callback_data="cancel_order")]
        ]
    )

# ==================== ОБРАБОТЧИКИ ====================
@router.message(CommandStart())
@router.message(F.text == "❌ Отмена")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)
    
    global users_db
    latest_db = await load_db_async(USERS_GITHUB_PATH)
    if latest_db:
        users_db = latest_db

    if user_id not in users_db:
        users_db[user_id] = {
            "name": message.from_user.first_name,
            "username": message.from_user.username or "",
            "completed_orders": 0,
            "spent_money": 0
        }
    else:
        users_db[user_id]["name"] = message.from_user.first_name
        users_db[user_id]["username"] = message.from_user.username or ""
        
    await save_db_async(USERS_GITHUB_PATH, users_db)

    text = (
        "👋 **Добро пожаловать в магазин цифровых подписок!**\n\n"
        "Выберите интересующий раздел в меню ниже:"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    user_id = str(message.from_user.id)
    
    global users_db
    latest_db = await load_db_async(USERS_GITHUB_PATH)
    if latest_db:
        users_db = latest_db

    user_data = users_db.get(user_id, {
        "name": message.from_user.first_name,
        "completed_orders": 0,
        "spent_money": 0
    })

    if message.from_user.id == ADMIN_ID:
        total_users = len(users_db)
        total_orders = sum(u.get("completed_orders", 0) for u in users_db.values())
        total_revenue = sum(u.get("spent_money", 0) for u in users_db.values())
        
        admin_text = (
            "👑 <b>Панель Администратора</b>\n\n"
            f"👤 <b>Имя:</b> {message.from_user.first_name}\n"
            f"🆔 <b>ID:</b> <code>{message.from_user.id}</code>\n\n"
            f"📊 <b>Статистика сервиса:</b>\n"
            f"👥 Пользователей: <b>{total_users}</b>\n"
            f"💎 Выполнено заказов: <b>{total_orders}</b>\n"
            f"💰 Общая выручка: <b>{total_revenue} грн</b>\n"
        )
        await message.answer(admin_text, parse_mode="HTML")
        return

    text = (
        "👤 <b>Ваш профиль</b>\n\n"
        f"🆔 <b>ID:</b> <code>{message.from_user.id}</code>\n"
        f"👤 <b>Имя:</b> {user_data.get('name', 'Пользователь')}\n\n"
        f"📊 <b>Ваши покупки:</b>\n"
        f"💎 Завершено заказов: <b>{user_data.get('completed_orders', 0)}</b>\n"
        f"💰 Потрачено: <b>{user_data.get('spent_money', 0)} грн</b>"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "📞 Поддержка")
async def show_support(message: Message):
    await message.answer("📞 По всем вопросам обратитесь к администратору магазина.")

@router.message(F.text == "💎 Купить Premium")
async def buy_premium_menu(message: Message):
    await message.answer("💎 **Выберите период подписки Premium:**", parse_mode="Markdown", reply_markup=get_tariff_keyboard())

@router.callback_query(F.data == "back_to_main")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer("💎 Выберите действие:", reply_markup=get_main_keyboard())

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
        "📱 Нажмите на кнопку **«📱 Поделиться контактом»** ниже, "
        "чтобы подтвердить аккаунт для оформления подписки."
    )
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer(text, parse_mode="Markdown", reply_markup=get_phone_keyboard())

@router.message(OrderFSM.waiting_for_phone, F.contact)
async def process_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    data = await state.get_data()
    
    order_id = generate_order_id()
    await state.update_data(phone=phone, order_id=order_id)
    
    orders_db[order_id] = {
        "user_id": message.from_user.id,
        "username": message.from_user.username or "",
        "full_name": message.from_user.full_name,
        "item": data["item_name"],
        "price_str": data["price_str"],
        "price_num": data["price_num"],
        "phone": phone,
        "status": "pending_payment"
    }
    await save_db_async(ORDERS_GITHUB_PATH, orders_db)

    text = (
        "<b>💳 Реквизиты для оплаты</b>\n\n"
        f"<b>Заказ:</b> <code>{order_id}</code>\n"
        f"<b>Товар:</b> {data['item_name']}\n"
        f"<b>Сумма к оплате:</b> {data['price_str']}\n\n"
        f"<b>Карта (A-Bank):</b> <code>{CARD_REQUISITES}</code>\n\n"
        "📌 <b>Инструкция:</b>\n"
        "1. Совершите перевод на указанную сумму.\n"
        "2. Нажмите кнопку <b>«📸 Отправить чек»</b> и прикрепите фото/скриншот чека."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_payment_keyboard())

@router.callback_query(F.data == "cancel_order")
async def cancel_order(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Заказ был отменен.", reply_markup=None)
    await call.message.answer("Главное меню:", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "send_receipt")
async def request_receipt(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("order_id"):
        await call.answer("Ошибка заказа. Начните оформление заново.", show_alert=True)
        await state.clear()
        return

    await state.set_state(OrderFSM.waiting_for_receipt)
    await call.message.answer("📸 Отправьте фото или скриншот чека об оплате:")

@router.message(OrderFSM.waiting_for_receipt, F.photo)
async def process_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    
    order_info = orders_db.get(order_id)
    if not order_info or order_info.get("status") in ["approved", "verifying"]:
        await message.answer("⚠️ Этот заказ уже обрабатывается или был завершен.")
        await state.clear()
        return

    order_info["status"] = "verifying"
    orders_db[order_id] = order_info
    await save_db_async(ORDERS_GITHUB_PATH, orders_db)

    await message.answer(
        f"✅ **Чек по заказу {order_id} принят!**\n"
        "Ожидайте подтверждения от администратора.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{order_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{order_id}")
            ]
        ]
    )
    
    username_str = f"@{message.from_user.username}" if message.from_user.username else "Без юзернейма"
    admin_text = (
        "🔔 <b>Новый чек на проверку!</b>\n\n"
        f"<b>Заказ:</b> {order_id}\n"
        f"<b>Пользователь:</b> {message.from_user.full_name} ({username_str})\n"
        f"<b>ID:</b> <code>{message.from_user.id}</code>\n"
        f"<b>Товар:</b> {data.get('item_name')}\n"
        f"<b>Сумма:</b> {data.get('price_str')}"
    )
    
    try:
        await bot.send_photo(
            chat_id=ADMIN_ID,
            photo=message.photo[-1].file_id,
            caption=admin_text,
            reply_markup=admin_kb,
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Не удалось отправить уведомление админу: {e}")

    await state.clear()

@router.callback_query(F.data.startswith("approve_"))
async def admin_approve(call: CallbackQuery):
    order_id = call.data.split("_")[1]
    order_info = orders_db.get(order_id)
    
    if not order_info:
        await call.answer("Заказ не найден.", show_alert=True)
        return

    # Защита от повторного выполнения
    if order_info.get("status") == "approved":
        await call.answer("⚠️️ Этот заказ УЖЕ был обработан и выдан!", show_alert=True)
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

    # Сохранение текстовой записи
    await save_order_to_github_txt(order_id, int(user_id), username, phone, item, price_str)

    # Обновление баланса пользователя
    global users_db
    latest_db = await load_db_async(USERS_GITHUB_PATH)
    if latest_db:
        users_db = latest_db

    if user_id not in users_db:
        users_db[user_id] = {
            "name": order_info.get("full_name", "Пользователь"),
            "username": username,
            "completed_orders": 0,
            "spent_money": 0
        }
        
    users_db[user_id]["completed_orders"] = users_db[user_id].get("completed_orders", 0) + 1
    users_db[user_id]["spent_money"] = users_db[user_id].get("spent_money", 0) + price_num
    await save_db_async(USERS_GITHUB_PATH, users_db)

    # Уведомление покупателю
    user_text = (
        "🎉 <b>Оплата подтверждена!</b>\n\n"
        f"<b>Заказ:</b> {order_id}\n"
        f"<b>Товар:</b> {item}\n\n"
        "Ваша подписка отправлена в активацию!"
    )
    try:
        await bot.send_message(chat_id=int(user_id), text=user_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

    # Публикация в канал
    channel_text = (
        "💎 <b>Новая покупка!</b>\n\n"
        f"Заказ <code>{order_id}</code> на {item} успешно выполнен!"
    )
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=channel_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка отправки в канал {CHANNEL_ID}: {e}")

    await call.message.edit_caption(
        caption=(call.message.caption or "") + "\n\n✅ <b>ОДОБРЕНО (Товар выдан)</b>", 
        parse_mode="HTML", 
        reply_markup=None
    )
    await call.answer("Заказ успешно подтвержден!")

@router.callback_query(F.data.startswith("reject_"))
async def admin_reject(call: CallbackQuery):
    order_id = call.data.split("_")[1]
    order_info = orders_db.get(order_id)
    
    if not order_info:
        await call.answer("Заказ не найден.", show_alert=True)
        return

    if order_info.get("status") in ["approved", "rejected"]:
        await call.answer("Заказ уже был обработан ранее!", show_alert=True)
        return

    order_info["status"] = "rejected"
    orders_db[order_id] = order_info
    await save_db_async(ORDERS_GITHUB_PATH, orders_db)

    user_id = str(order_info["user_id"])
    try:
        await bot.send_message(chat_id=int(user_id), text=f"❌ Ваш заказ {order_id} был отклонен администратором.")
    except Exception:
        pass

    await call.message.edit_caption(
        caption=(call.message.caption or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>", 
        parse_mode="HTML", 
        reply_markup=None
    )
    await call.answer("Заказ отклонен.")

# ==================== ЗАПУСК ====================
async def main():
    global users_db, orders_db
    users_db = await load_db_async(USERS_GITHUB_PATH)
    orders_db = await load_db_async(ORDERS_GITHUB_PATH)

    asyncio.create_task(start_web_server())
    
    # Удаление вебхука и запуск long-polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
