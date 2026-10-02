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

# Гарантируем, что ADMIN_ID — целое число (int)
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7837011810"))

CHANNEL_ID = "@Premium_Giive"
GITHUB_REPO_NAME = "Premiumm0/telegram-orders"
GITHUB_ORDERS_PATH = "orders.txt"
CARD_REQUISITES = "4323347356530466 (A-Bank)"
PING_URL = "https://telegram-orders-yvf0.onrender.com/"
# ===================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# Оперативная память исключительно для активных незавершенных заказов
active_orders = {}

# ==================== ЗАПИСЬ ЗАКАЗОВ В GITHUB ====================
def _sync_append_order_to_github(order_text):
    try:
        if not GITHUB_TOKEN:
            return
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO_NAME)
        try:
            contents = repo.get_contents(GITHUB_ORDERS_PATH)
            old_content = contents.decoded_content.decode("utf-8")
            new_content = old_content + "\n" + order_text
            repo.update_file(GITHUB_ORDERS_PATH, "Новый заказ", new_content, contents.sha)
        except Exception:
            repo.create_file(GITHUB_ORDERS_PATH, "Инициализация заказов", order_text)
    except Exception as e:
        logging.error(f"Ошибка сохранения заказа в GitHub: {e}")

async def append_order_to_github(order_text):
    await asyncio.to_thread(_sync_append_order_to_github, order_text)

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
            # Админа пропускаем без условий
            if user.id == ADMIN_ID:
                return await handler(event, data)

            # Обычным пользователям нужен username
            if not user.username:
                error_text = (
                    "⚠️ **У вас не установлен Юзернейм (@username)!**\n\n"
                    "Чтобы сделать заказ, добавьте имя пользователя (@username) в настройках Telegram, "
                    "затем отправьте `/start`."
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

# ==================== FSM СOСТОЯНИЯ ====================
class OrderFSM(StatesGroup):
    waiting_for_phone = State()
    waiting_for_receipt = State()

def generate_order_id():
    chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"#Prem{chars}"

async def keep_alive():
    """Фоновый пинг"""
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
    text = (
        "👋 Добро пожаловать в магазин Telegram Premium!\n"
        "Выберите интересующий пункт ниже:"
    )
    await message.answer(text, reply_markup=get_main_keyboard())

@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    if message.from_user.id == ADMIN_ID:
        admin_text = (
            "👑 **Панель Владельца**\n\n"
            f"👤 **Админ:** {message.from_user.first_name}\n"
            f"🆔 **ID:** `{message.from_user.id}`\n\n"
            "✅ Бот работает в автономном режиме. Все заявки и чеки поступают вам в ЛС прямо сюда!"
        )
        await message.answer(admin_text, parse_mode="Markdown")
        return

    username_str = f"@{message.from_user.username}" if message.from_user.username else "Отсутствует"
    text = (
        "👤 Ваш профиль:\n\n"
        f"🆔 ID: `{message.from_user.id}`\n"
        f"👤 Имя: {message.from_user.first_name}\n"
        f"🏷 Юзернейм: {username_str}"
    )
    await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "📞 Поддержка")
async def show_support(message: Message):
    await message.answer("📞 По вопросам покупки обращайтесь напрямую к администратору.")

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
        price_num = 160
        price_str = "160 грн"
    else:
        item_name = "Premium 1 год"
        price_num = 1300
        price_str = "1300 грн"

    await state.update_data(item_name=item_name, price_str=price_str, price_num=price_num)
    await state.set_state(OrderFSM.waiting_for_phone)

    text = (
        "📱 **Введите номер телефона**\n\n"
        "Укажите номер, к которому привязан ваш аккаунт Telegram.\n"
        "Например: `+380XXXXXXXXX`"
    )
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())

@router.message(OrderFSM.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    data = await state.get_data()
    order_id = generate_order_id()
    
    await state.update_data(phone=phone, order_id=order_id)
    
    active_orders[order_id] = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "full_name": message.from_user.full_name,
        "item": data["item_name"],
        "price_str": data["price_str"],
        "price_num": data["price_num"],
        "phone": phone
    }

    # МГНОВЕННОЕ УВЕДОМЛЕНИЕ ВЛАДЕЛЬЦУ О НАЧАЛЕ ОФОРМЛЕНИЯ
    try:
        user_mention = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"📥 **Новая заявка на покупку!**\n\n"
                f"🧾 Заказ: `{order_id}`\n"
                f"👤 Клиент: {message.from_user.full_name} ({user_mention})\n"
                f"📱 Товар: {data['item_name']}\n"
                f"📞 Телефон: `{phone}`\n"
                f"💰 Сумма: {data['price_str']}\n\n"
                f"⏳ Ожидаем чек от клиента..."
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Не удалось отправить уведомление админу: {e}")

    text = (
        "💳 **Реквизиты для оплаты**\n\n"
        f"🧾 Заказ: `{order_id}`\n"
        f"📱 Товар: {data['item_name']}\n"
        f"📞 Номер: `{phone}`\n"
        f"💸 Сумма: **{data['price_str']}**\n\n"
        f"🏦 Банк: **MonoBank**\n"
        f"💳 Карта: `{CARD_REQUISITES}`\n\n"
        "📸 Переведите деньги и нажмите **«Отправить чек»** ниже."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_payment_keyboard())

@router.callback_query(F.data == "cancel_order")
async def cancel_order(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id", "#Prem000000")
    
    if order_id in active_orders:
        del active_orders[order_id]

    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_to_main")]])
    await call.message.edit_text(f"❌ Заказ `{order_id}` отменён.", parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data == "send_receipt")
async def request_receipt(call: CallbackQuery, state: FSMContext):
    await state.set_state(OrderFSM.waiting_for_receipt)
    await call.message.answer("📸 Отправьте фото или скриншот чека в чат:")

@router.message(OrderFSM.waiting_for_receipt, F.photo)
async def process_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    
    await message.answer("✅ Чек получен! Передано администратору на проверку. Ожидайте выдачи.")

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить и выдать", callback_data=f"approve_{order_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{order_id}")
            ]
        ]
    )
    
    user_username = f"@{message.from_user.username}" if message.from_user.username else "Без юзернейма"
    
    admin_text = (
        "🚨 **НОВЫЙ ЧЕК НА ПРОВЕРКУ!**\n\n"
        f"🧾 **Заказ:** `{order_id}`\n"
        f"👤 **Пользователь:** {message.from_user.full_name} ({user_username} | ID: `{message.from_user.id}`)\n"
        f"📱 **Товар:** {data.get('item_name')}\n"
        f"📞 **Телефон:** `{data.get('phone')}`\n"
        f"💸 **Сумма:** {data.get('price_str')}"
    )
    
    # Отправляем фото чека ВЛАДЕЛЬЦУ
    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=admin_text,
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )
    await state.clear()

# ==================== ОДОБРЕНИЕИ И ОТКЛОНЕНИЕ ВЛАДЕЛЬЦЕМ ====================
@router.callback_query(F.data.startswith("approve_"))
async def admin_approve(call: CallbackQuery):
    order_id = call.data.split("_")[1]
    order_info = active_orders.get(order_id)
    
    if not order_info:
        await call.answer("Заказ устарел или уже был обработан.", show_alert=True)
        return

    user_id = order_info["user_id"]
    item = order_info["item"]
    price_str = order_info["price_str"]
    phone = order_info["phone"]

    # Запись удачного заказа в GitHub
    order_log_line = f"Заказ: {order_id} | UserID: {user_id} | Phone: {phone} | Item: {item} | Price: {price_str}"
    asyncio.create_task(append_order_to_github(order_log_line))

    # Удаление из памяти
    del active_orders[order_id]

    user_text = (
        "🎉 **Оплата подтверждена!**\n\n"
        f"🧾 Заказ: `{order_id}`\n"
        f"📱 Товар: {item}\n"
        "⏳ Выдача Premium запущена. С вами скоро свяжутся!"
    )
    try:
        await bot.send_message(chat_id=user_id, text=user_text, parse_mode="Markdown")
    except Exception:
        pass

    # Публикация успешной покупки в канале
    duration_text = "1 месяц" if "1 месяц" in item else "1 год"
    channel_text = (
        "💎 **Telegram Premium успешно выдан!**\n\n"
        f"🧾 Номер заказа: `{order_id}`\n"
        f"💎 Срок: {duration_text}\n"
        f"💰 Стоимость: {price_str}\n"
        "✅ Заказ выполнен!"
    )
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=channel_text, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Ошибка публикации в канал: {e}")

    await call.message.edit_caption(caption=call.message.caption + "\n\n✅ **ОДОБРЕНО И ВЫДАНО**", reply_markup=None)
    await call.answer("Заказ одобрен!")

@router.callback_query(F.data.startswith("reject_"))
async def admin_reject(call: CallbackQuery):
    order_id = call.data.split("_")[1]
    order_info = active_orders.get(order_id)

    if order_info:
        user_id = order_info["user_id"]
        try:
            await bot.send_message(chat_id=user_id, text=f"❌ Ваш заказ `{order_id}` был отклонен администратором.", parse_mode="Markdown")
        except Exception:
            pass
        del active_orders[order_id]

    await call.message.edit_caption(caption=call.message.caption + "\n\n❌ **ОТКЛОНЕНО**", reply_markup=None)
    await call.answer("Заказ отклонен.")

# ==================== ЗАПУСК ====================
async def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.create_task(keep_alive())
    
    # Удаляем сомнительные предыдущие апдейты при запуске
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
