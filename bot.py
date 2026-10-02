import os
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
GITHUB_ORDERS_PATH = "orders.txt"
CARD_REQUISITES = "4323 3473 5653 0466 (A-Bank)"
PING_URL = "https://telegram-orders-yvf0.onrender.com/"
# ===================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# Хранилища данных
active_orders = {}      # Заказы по clean_code
user_orders = {}        # Последний заказ пользователя по user_id
all_users = set()       # Уникальные пользователи
total_purchases = 0     # Количество покупок
total_earned = 0        # Всего заработано (грн)

# ==================== СИНХРОНИЗАЦИЯ С GITHUB ====================
def _sync_append_to_github(text_line):
    try:
        if not GITHUB_TOKEN:
            return
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO_NAME)
        try:
            contents = repo.get_contents(GITHUB_ORDERS_PATH)
            old_content = contents.decoded_content.decode("utf-8")
            new_content = old_content + "\n" + text_line
            repo.update_file(GITHUB_ORDERS_PATH, "Запись данных", new_content, contents.sha)
        except Exception:
            repo.create_file(GITHUB_ORDERS_PATH, "Инициализация", text_line)
    except Exception as e:
        logging.error(f"Ошибка записи в GitHub: {e}")

async def append_to_github(text_line):
    await asyncio.to_thread(_sync_append_to_github, text_line)

def _sync_load_data_from_github():
    global total_purchases, total_earned, all_users
    try:
        if not GITHUB_TOKEN:
            return
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO_NAME)
        try:
            contents = repo.get_contents(GITHUB_ORDERS_PATH)
            lines = contents.decoded_content.decode("utf-8").splitlines()
            
            p_count = 0
            earned = 0
            users = set()

            for line in lines:
                if "USER_REGISTERED:" in line:
                    try:
                        uid = int(line.split(":")[1].strip())
                        users.add(uid)
                    except Exception:
                        pass
                elif "UserID:" in line:
                    try:
                        parts = line.split("|")
                        for p in parts:
                            if "UserID:" in p:
                                uid = int(p.split(":")[1].strip())
                                users.add(uid)
                    except Exception:
                        pass

                if "SUCCESS_ORDER:" in line or "OrderDone:" in line:
                    p_count += 1
                    if "160" in line:
                        earned += 160
                    elif "1300" in line:
                        earned += 1300

            total_purchases = p_count
            total_earned = earned
            all_users = users
            logging.info(f"[GitHub] Загружено юзеров: {len(all_users)}, Покупок: {p_count}, Доход: {earned} грн")
        except Exception:
            logging.warning("Файл orders.txt еще не создан на GitHub.")
    except Exception as e:
        logging.error(f"Ошибка при считывании с GitHub: {e}")

async def load_data_from_github():
    await asyncio.to_thread(_sync_load_data_from_github)

# ==================== MIDDLEWARE ПРОВЕРКИ ЮЗЕРНЕЙМА ====================
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
            if user.id not in all_users:
                all_users.add(user.id)
                asyncio.create_task(append_to_github(f"USER_REGISTERED: {user.id}"))

            if user.id == ADMIN_ID:
                return await handler(event, data)

            if not user.username:
                error_text = (
                    "⚠️ У вас не установлен Юзернейм (@username)!\n\n"
                    "Чтобы сделать заказ, добавьте имя пользователя (@username) в настройках Telegram, "
                    "затем отправьте /start."
                )
                if isinstance(event, Message):
                    await event.answer(error_text)
                elif isinstance(event, CallbackQuery):
                    await event.answer("⚠️ Установите @username в настройках Telegram!", show_alert=True)
                return

        return await handler(event, data)

router.message.outer_middleware(CheckUsernameMiddleware())
router.callback_query.outer_middleware(CheckUsernameMiddleware())
dp.include_router(router)

# ==================== FSM СОСТОЯНИЯ ====================
class OrderFSM(StatesGroup):
    waiting_for_phone = State()
    waiting_for_receipt = State()

def generate_order_id():
    chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"Prem{chars}"

async def keep_alive():
    while True:
        await asyncio.sleep(300)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(PING_URL, timeout=10) as response:
                    logging.info(f"[Ping OK] Статус: {response.status}")
        except Exception as e:
            logging.error(f"[Ping Err] {e}")

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

# ==================== ОБРАБОТКА КОМАНД И МЕНЮ ====================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user.id not in all_users:
        all_users.add(message.from_user.id)
        await append_to_github(f"USER_REGISTERED: {message.from_user.id}")

    if message.from_user.id == ADMIN_ID:
        text = (
            "👑 Вы авторизованы как Владелец бота!\n"
            "Все новые заявки и чеки от клиентов будут приходить прямо сюда в ЛС.\n\n"
            "Выберите пункт меню ниже:"
        )
    else:
        text = (
            "👋 Добро пожаловать в магазин Telegram Premium!\n"
            "Выберите интересующий пункт ниже:"
        )
    await message.answer(text, reply_markup=get_main_keyboard())

@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    username_str = f"@{message.from_user.username}" if message.from_user.username else "Отсутствует"

    if message.from_user.id == ADMIN_ID:
        text = (
            "👤 Профиль Администратора\n\n"
            f"👤 Имя: {message.from_user.first_name}\n"
            f"🆔 ID: {message.from_user.id}\n"
            f"🏷 Юзернейм: {username_str}\n\n"
            f"📊 Статистика магазина:\n"
            f"👥 Пользователей в боте: {len(all_users)}\n"
            f"💎 Купили Premium: {total_purchases}\n"
            f"💰 Всего заработано: {total_earned} грн"
        )
    else:
        text = (
            "👤 Ваш профиль\n\n"
            f"🆔 ID: {message.from_user.id}\n"
            f"👤 Имя: {message.from_user.first_name}\n"
            f"🏷 Юзернейм: {username_str}\n"
            f"📦 Заказов: {total_purchases}"
        )
    await message.answer(text)

@router.message(F.text == "📞 Поддержка")
async def show_support(message: Message):
    await message.answer("📞 По вопросам покупки обращайтесь к администратору.")

@router.message(F.text == "💎 Купить Premium")
async def buy_premium_menu(message: Message):
    await message.answer("💎 Выберите период Telegram Premium:", reply_markup=get_tariff_keyboard())

@router.callback_query(F.data == "back_to_main")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer("💎 Главное меню:", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("💎 Выберите период Telegram Premium:", reply_markup=get_tariff_keyboard())

# ==================== ОФОРМЛЕНИЕ ЗАКАЗА ====================
@router.callback_query(F.data.in_({"buy_1_month", "buy_1_year"}))
async def select_tariff(call: CallbackQuery, state: FSMContext):
    if call.data == "buy_1_month":
        item_name = "Premium 1 месяц"
        price_str = "160 грн"
        price_num = 160
    else:
        item_name = "Premium 1 год"
        price_str = "1300 грн"
        price_num = 1300

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
    clean_code = generate_order_id()
    order_id = f"#{clean_code}"
    
    order_data = {
        "order_id": order_id,
        "clean_code": clean_code,
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "full_name": message.from_user.full_name,
        "item": data.get("item_name", "Premium"),
        "price_str": data.get("price_str", "160 грн"),
        "price_num": data.get("price_num", 160),
        "phone": phone
    }

    active_orders[clean_code] = order_data
    user_orders[message.from_user.id] = order_data
    await state.update_data(current_order_code=clean_code, order_data=order_data)

    text = (
        "💳 Оплата заказа\n"
        f"Заказ: {order_id}\n"
        f"Товар: {data.get('item_name')}\n"
        f"Номер: {phone}\n"
        f"Стоимость: {data.get('price_str')}\n"
        "Банк: A-Bank\n"
        f"Карта: {CARD_REQUISITES}\n\n"
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
    code = data.get("current_order_code")
    if code in active_orders:
        del active_orders[code]
    if call.from_user.id in user_orders:
        del user_orders[call.from_user.id]

    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_to_main")]])
    await call.message.edit_text("❌ Заказ отменён.", reply_markup=kb)

@router.callback_query(F.data == "send_receipt")
async def request_receipt(call: CallbackQuery, state: FSMContext):
    await state.set_state(OrderFSM.waiting_for_receipt)
    await call.message.answer("📸 Пожалуйста, отправьте фото чека об оплате:")

# Универсальный обработчик отправки чека (работает с любым состоянием FSM и просто при отправке фото)
@router.message(F.photo)
async def process_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_data = data.get("order_data")
    clean_code = data.get("current_order_code")

    # Поиск заказа в глобальном хранилище, если в FSM пусто
    if not order_data:
        order_data = user_orders.get(message.from_user.id)
        if order_data:
            clean_code = order_data.get("clean_code")

    if not order_data:
        await message.answer("⚠️ Активный заказ не найден. Пожалуйста, оформите заказ заново через /start.")
        await state.clear()
        return

    order_id = order_data["order_id"]

    text = (
        "✅ Чек отправлен!\n"
        f"Заказ: {order_id}\n"
        "⏳ Оплата находится на проверке.\n"
        "После подтверждения оплаты ваш заказ будет передан в обработку."
    )
    await message.answer(text)

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить и выдать", callback_data=f"app_{clean_code}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{clean_code}")
            ]
        ]
    )
    
    user_username = f"@{message.from_user.username}" if message.from_user.username else "Без юзернейма"
    
    admin_text = (
        "🚨 НОВЫЙ ЧЕК НА ПРОВЕРКУ!\n\n"
        f"🧾 Заказ: {order_id}\n"
        f"👤 Пользователь: {message.from_user.full_name} ({user_username} | ID: {message.from_user.id})\n"
        f"📱 Товар: {order_data['item']}\n"
        f"📞 Телефон: {order_data['phone']}\n"
        f"💸 Сумма: {order_data['price_str']}"
    )
    
    try:
        await bot.send_photo(
            chat_id=ADMIN_ID,
            photo=message.photo[-1].file_id,
            caption=admin_text,
            reply_markup=admin_kb,
            parse_mode=None  # Отключение форматирования для гарантированной отправки
        )
        logging.info(f"Уведомление успешно отправлено админу {ADMIN_ID}")
    except Exception as e:
        logging.error(f"❌ Ошибка отправки фото админу ({ADMIN_ID}): {e}")
        # Запасная отправка текстом, если фото не прошло
        try:
            await bot.send_message(
                chat_id=ADMIN_ID, 
                text=f"⚠️ Получен новый чек, но фото не загрузилось из-за ошибки!\n\n{admin_text}",
                reply_markup=admin_kb,
                parse_mode=None
            )
        except Exception as ex:
            logging.error(f"❌ Критическая ошибка отправки сообщения админу: {ex}")

    await state.clear()

# ==================== ОДОБРЕНИЕ И ОТКЛОНЕНИЕ ====================
@router.callback_query(F.data.startswith("app_"))
async def admin_approve(call: CallbackQuery):
    global total_purchases, total_earned
    clean_code = call.data.split("_")[1]
    order_info = active_orders.get(clean_code)
    
    if not order_info:
        await call.answer("Заказ устарел или уже был обработан.", show_alert=True)
        return

    target_user_id = order_info["user_id"]
    order_id = order_info["order_id"]
    item = order_info["item"]
    price_str = order_info["price_str"]
    price_num = order_info.get("price_num", 0)
    phone = order_info["phone"]

    total_purchases += 1
    total_earned += price_num

    log_line = f"SUCCESS_ORDER: {order_id} | UserID: {target_user_id} | Phone: {phone} | Item: {item} | Price: {price_num}"
    asyncio.create_task(append_to_github(log_line))

    if clean_code in active_orders:
        del active_orders[clean_code]
    if target_user_id in user_orders:
        del user_orders[target_user_id]

    user_text = (
        "🎉 Оплата подтверждена!\n"
        f"Заказ: {order_id}\n"
        f"Товар: {item}\n"
        f"Стоимость: {price_str}\n"
        "🔄 Заказ передан в обработку.\n"
        "⏳ Ожидайте выполнения заказа."
    )
    try:
        await bot.send_message(chat_id=target_user_id, text=user_text)
    except Exception:
        pass

    duration_text = "1 месяц" if "1 месяц" in item else "1 год"
    channel_text = (
        "💎 Premium успешно выдан!\n"
        f"Номер заказа: {order_id}\n"
        f"Premium: {duration_text}\n"
        f"Стоимость: {price_str}\n"
        "✅ Заказ успешно выполнен!"
    )
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=channel_text)
    except Exception as e:
        logging.error(f"Ошибка публикации в канал: {e}")

    await call.message.edit_caption(caption=call.message.caption + "\n\n✅ ОДОБРЕНО И ВЫДАНО", reply_markup=None)
    await call.answer("Заказ одобрен!")

@router.callback_query(F.data.startswith("rej_"))
async def admin_reject(call: CallbackQuery):
    clean_code = call.data.split("_")[1]
    order_info = active_orders.get(clean_code)

    if order_info:
        target_user_id = order_info["user_id"]
        order_id = order_info["order_id"]
        try:
            await bot.send_message(chat_id=target_user_id, text=f"❌ Ваш заказ {order_id} был отменён администратором.")
        except Exception:
            pass
        if clean_code in active_orders:
            del active_orders[clean_code]
        if target_user_id in user_orders:
            del user_orders[target_user_id]

    await call.message.edit_caption(caption=call.message.caption + "\n\n❌ ОТКЛОНЕНО", reply_markup=None)
    await call.answer("Заказ отклонён.")

# ==================== ЗАПУСК ====================
async def main():
    logging.basicConfig(level=logging.INFO)
    
    await load_data_from_github()
    asyncio.create_task(keep_alive())
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
