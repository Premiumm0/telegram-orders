import os
import json
import asyncio
import random
import string
import logging
import aiohttp
from github import Github
from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, 
    CallbackQuery, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    TelegramObject
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7837011810"))

CHANNEL_ID = "@Premium_Giive"
GITHUB_REPO_NAME = "Premiumm0/telegram-orders"
GITHUB_DB_PATH = "database.json"
CARD_REQUISITES = "4323347356530466 (A-Bank)"
PING_URL = "https://telegram-orders-yvf0.onrender.com/"
# ===================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# ==================== РАБОТА С ГЛОБАЛЬНОЙ БАЗОЙ (GITHUB) ====================
db_cache = {
    "users": {},
    "orders": {}
}

def _sync_load_from_github():
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO_NAME)
        try:
            contents = repo.get_contents(GITHUB_DB_PATH)
            data = json.loads(contents.decoded_content.decode("utf-8"))
            return data
        except Exception:
            # Если файла нет — создаем пустую структуру
            initial_db = {"users": {}, "orders": {}}
            repo.create_file(GITHUB_DB_PATH, "Инициализация БД", json.dumps(initial_db, ensure_ascii=False, indent=2))
            return initial_db
    except Exception as e:
        logging.error(f"Ошибка загрузки БД с GitHub: {e}")
        return {"users": {}, "orders": {}}

def _sync_save_to_github(data):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO_NAME)
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            contents = repo.get_contents(GITHUB_DB_PATH)
            repo.update_file(GITHUB_DB_PATH, "Обновление БД бота", json_str, contents.sha)
        except Exception:
            repo.create_file(GITHUB_DB_PATH, "Создание БД бота", json_str)
    except Exception as e:
        logging.error(f"Ошибка сохранения БД в GitHub: {e}")

async def load_db():
    global db_cache
    db_cache = await asyncio.to_thread(_sync_load_from_github)

async def save_db():
    await asyncio.to_thread(_sync_save_to_github, db_cache)

# ==================== MIDDLEWARE ДЛЯ ПРОВЕРКИ USERNAME ====================
class CheckUsernameMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler,
        event: TelegramObject,
        data: dict
    ):
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user:
            # Не требуем username у админа
            if user.id != ADMIN_ID and not user.username:
                error_text = (
                    "⚠️ **У вас не установлен Юзернейм (@username)!**\n\n"
                    "Чтобы пользоваться ботом и покупать товары, вам нужно установить имя пользователя (@username) в настройках Telegram.\n\n"
                    "⚙️ **Как добавить юзернейм:**\n"
                    "1. Зайдите в **Настройки** Telegram.\n"
                    "2. Нажмите **Имя пользователя**.\n"
                    "3. Придумайте любой свободный юзернейм и сохраните.\n"
                    "4. После этого отправьте команду `/start`."
                )
                if isinstance(event, Message):
                    await event.answer(error_text, parse_mode="Markdown")
                elif isinstance(event, CallbackQuery):
                    await event.answer("⚠️ Установите @username в настройках Telegram!", show_alert=True)
                return

        return await handler(event, data)

router.message.outer_middleware(CheckUsernameMiddleware())
router.callback_query.outer_middleware(CheckUsernameMiddleware())
dp.include_router(router)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
class OrderFSM(StatesGroup):
    waiting_for_phone = State()
    waiting_for_receipt = State()

def generate_order_id():
    chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"#Prem{chars}"

async def keep_alive():
    """Фоновый автопинг каждые 5 минут с бесконечными повторами"""
    while True:
        await asyncio.sleep(300)
        success = False
        retry_delay = 5

        while not success:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(PING_URL, timeout=10) as response:
                        if response.status == 200:
                            logging.info(f"[Ping OK] Сервер активен.")
                            success = True
                        else:
                            logging.warning(f"[Ping Status {response.status}] Повторный пробой через {retry_delay} сек...")
            except Exception as e:
                logging.error(f"[Ping Err] {e}. Повтор через {retry_delay} сек...")

            if not success:
                await asyncio.sleep(retry_delay)

# ==================== КЛАВИАТУРЫ ====================
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

# ==================== ХЭНДЛЕРЫ ====================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)
    
    # Сохраняем пользователя в БД
    if user_id not in db_cache["users"]:
        db_cache["users"][user_id] = {
            "name": message.from_user.first_name,
            "username": message.from_user.username or "",
            "completed_orders": 0,
            "spent_money": 0
        }
    else:
        db_cache["users"][user_id]["name"] = message.from_user.first_name
        db_cache["users"][user_id]["username"] = message.from_user.username or ""
        
    await save_db()

    text = (
        "👋 Добро пожаловать в магазин Telegram Premium!\n"
        "Здесь ты можешь быстро приобрести Premium на свой аккаунт.\n\n"
        "💎 Выберите действие:"
    )
    await message.answer(text, reply_markup=get_main_keyboard())

@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    user_id = str(message.from_user.id)
    
    # Панель Администратора
    if message.from_user.id == ADMIN_ID:
        total_users = len(db_cache["users"])
        total_orders = sum(u.get("completed_orders", 0) for u in db_cache["users"].values())
        total_revenue = sum(u.get("spent_money", 0) for u in db_cache["users"].values())
        
        admin_text = (
            "👑 **Панель Администратора**\n\n"
            f"👤 **Имя:** {message.from_user.first_name}\n"
            f"🆔 **ID:** `{message.from_user.id}`\n\n"
            f"📊 **Статистика бота:**\n"
            f"👥 Пользователей в боте: **{total_users}**\n"
            f"💎 Куплено Premium: **{total_orders}**\n"
            f"💰 Общая выручка: **{total_revenue} грн**"
        )
        await message.answer(admin_text, parse_mode="Markdown")
        return

    # Профиль обычного пользователя
    user_data = db_cache["users"].get(user_id, {"name": message.from_user.first_name, "completed_orders": 0})
    username_str = f"@{message.from_user.username}" if message.from_user.username else "Не установлен"
    text = (
        "👤 Ваш профиль\n\n"
        f"🆔 ID: {message.from_user.id}\n"
        f"👤 Имя: {user_data.get('name', 'Пользователь')}\n"
        f"🏷 Юзернейм: {username_str}\n"
        f"📦 Заказов: {user_data.get('completed_orders', 0)}"
    )
    await message.answer(text)

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
    
    db_cache["orders"][order_id] = {
        "user_id": message.from_user.id,
        "item": data["item_name"],
        "price_str": data["price_str"],
        "price_num": data["price_num"],
        "phone": phone,
        "status": "pending"
    }
    await save_db()

    text = (
        "💳 Оплата заказа\n"
        f"🧾 Заказ: {order_id}\n"
        f"📱 Товар: {data['item_name']}\n"
        f"📞 Номер: {phone}\n"
        f"💸 Стоимость: {data['price_str']}\n"
        "🏦 Банк: MonoBank\n"
        f"💳 Карта: {CARD_REQUISITES}\n\n"
        "💛 Оплатите заказ по реквизитам выше.\n"
        "📸 После оплаты отправьте чек для проверки.\n\n"
        "🔐 Выдача Premium:\n"
        "Premium будет выдаваться со входом в аккаунт.\n"
        "⏳ После подтверждения оплаты ожидайте выполнения заказа."
    )
    await message.answer(text, reply_markup=get_payment_keyboard())

@router.callback_query(F.data == "cancel_order")
async def cancel_order(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id", "#Prem000000")
    item = data.get("item_name", "Premium 1 месяц")
    price = data.get("price_str", "160 грн")

    await state.clear()
    
    text = (
        "❌ Заказ отменён\n"
        f"🧾 Заказ: {order_id}\n"
        f"📱 Товар: {item}\n"
        f"💰 Стоимость: {price}\n"
        "Заказ был отменён."
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_to_main")]])
    await call.message.edit_text(text, reply_markup=kb)

@router.callback_query(F.data == "send_receipt")
async def request_receipt(call: CallbackQuery, state: FSMContext):
    await state.set_state(OrderFSM.waiting_for_receipt)
    await call.message.answer("📸 Пожалуйста, отправьте фото чека об оплате:")

@router.message(OrderFSM.waiting_for_receipt, F.photo)
async def process_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    
    text = (
        "✅ Чек отправлен!\n"
        f"🧾 Заказ: {order_id}\n"
        "⏳ Оплата находится на проверке.\n"
        "После подтверждения оплаты ваш заказ будет передан в обработку."
    )
    await message.answer(text)

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
        "🔔 Новый чек на проверку!\n\n"
        f"🧾 Заказ: {order_id}\n"
        f"👤 Пользователь: {message.from_user.full_name} ({username_str} | ID: `{message.from_user.id}`)\n"
        f"📱 Товар: {data['item_name']}\n"
        f"📞 Номер: {data['phone']}\n"
        f"💸 Сумма: {data['price_str']}"
    )
    
    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=admin_text,
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )
    await state.clear()

@router.callback_query(F.data.startswith("approve_"))
async def admin_approve(call: CallbackQuery):
    order_id = call.data.split("_")[1]
    order_info = db_cache["orders"].get(order_id)
    
    if not order_info:
        await call.answer("Заказ не найден.", show_alert=True)
        return

    if order_info.get("status") == "approved":
        await call.answer("Этот заказ уже одобрен!", show_alert=True)
        return

    order_info["status"] = "approved"
    db_cache["orders"][order_id] = order_info

    user_id = str(order_info["user_id"])
    item = order_info["item"]
    price_str = order_info["price_str"]
    price_num = order_info.get("price_num", 0)

    # Обновляем статистику покупателя в глобальной базе
    if user_id in db_cache["users"]:
        db_cache["users"][user_id]["completed_orders"] = db_cache["users"][user_id].get("completed_orders", 0) + 1
        db_cache["users"][user_id]["spent_money"] = db_cache["users"][user_id].get("spent_money", 0) + price_num

    await save_db()

    user_text = (
        "🎉 Оплата подтверждена!\n"
        f"🧾 Заказ: {order_id}\n"
        f"📱 Товар: {item}\n"
        f"💰 Стоимость: {price_str}\n"
        "🔄 Заказ передан в обработку.\n"
        "⏳ Ожидайте выполнения заказа."
    )
    try:
        await bot.send_message(chat_id=int(user_id), text=user_text)
    except Exception:
        pass

    duration_text = "1 месяц" if "1 месяц" in item else "1 год"
    channel_text = (
        "💎 Premium успешно выдан!\n"
        f"🧾 Номер заказа: {order_id}\n"
        f"💎 Premium: {duration_text}\n"
        f"💰 Стоимость: {price_str}\n"
        "✅ Заказ успешно выполнен!"
    )
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=channel_text)
    except Exception as e:
        logging.error(f"Ошибка публикации в канал: {e}")

    await call.message.edit_caption(caption=call.message.caption + "\n\n✅ **ОДОБРЕНО**", reply_markup=None)
    await call.answer("Заказ успешно одобрен!")

@router.callback_query(F.data.startswith("reject_"))
async def admin_reject(call: CallbackQuery):
    order_id = call.data.split("_")[1]
    order_info = db_cache["orders"].get(order_id)
    
    if not order_info:
        await call.answer("Заказ не найден.", show_alert=True)
        return

    if order_info.get("status") == "rejected":
        await call.answer("Этот заказ уже отклонен!", show_alert=True)
        return

    order_info["status"] = "rejected"
    db_cache["orders"][order_id] = order_info
    await save_db()

    user_id = str(order_info["user_id"])
    try:
        await bot.send_message(chat_id=int(user_id), text=f"❌ Ваш заказ {order_id} был отменён администратором.")
    except Exception:
        pass

    await call.message.edit_caption(caption=call.message.caption + "\n\n❌ **ОТКЛОНЕНО**", reply_markup=None)
    await call.answer("Заказ отклонён.")

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # Загружаем актуальную базу данных с GitHub при старте
    await load_db()
    
    # Запуск автопинга
    asyncio.create_task(keep_alive())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
