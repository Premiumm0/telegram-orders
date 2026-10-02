import asyncio
import random
import string
import logging
from github import Github
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
BOT_TOKEN = "8809744925:AAGdRh7yrbNC7YW0npY5iK43zsOgd283PQk"
ADMIN_ID = 7837011810  # Ваш числовой Telegram ID (узнать в @userinfobot)
CHANNEL_ID = "@Premium_Giive"  # Канал для публикаций

# Настройки GitHub
GITHUB_TOKEN = "ВАШ_GITHUB_PERSONAL_ACCESS_TOKEN"  # Токен с правами 'repo'
GITHUB_REPO_NAME = "Premiumm0/telegram-orders"     # Ваш репозиторий
GITHUB_FILE_PATH = "orders.txt"                    # Файл для сохранения заказов

CARD_REQUISITES = "4323347356530466 (A-Bank)"
# ===================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# Локальная база пользователей и заказов
users_db = {} 
orders_db = {}

# FSM Состояния
class OrderFSM(StatesGroup):
    waiting_for_phone = State()
    waiting_for_receipt = State()

def generate_order_id():
    chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"#Prem{chars}"

def save_order_to_github(order_id: str, user_id: int, item: str, price: str):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO_NAME)
        
        try:
            contents = repo.get_contents(GITHUB_FILE_PATH)
            current_data = contents.decoded_content.decode("utf-8")
            sha = contents.sha
        except Exception:
            current_data = ""
            sha = None

        new_entry = f"Заказ: {order_id} | UserID: {user_id} | Товар: {item} | Сумма: {price}\n"
        updated_data = current_data + new_entry

        if sha:
            repo.update_file(GITHUB_FILE_PATH, f"Добавлен заказ {order_id}", updated_data, sha)
        else:
            repo.create_file(GITHUB_FILE_PATH, f"Заказ {order_id}", updated_data)
        return True
    except Exception as e:
        logging.error(f"Ошибка сохранения на GitHub: {e}")
        return False

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
            [InlineKeyboardButton(text="◀️️ Назад", callback_data="back_to_tariffs")]
        ]
    )

def get_payment_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📸 Отправить чек", callback_data="send_receipt")],
            [InlineKeyboardButton(text="❌ Отменить заказ", callback_data="cancel_order")]
        ]
    )

# Хэндлеры
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    if user_id not in users_db:
        users_db[user_id] = {
            "name": message.from_user.first_name,
            "completed_orders": 0
        }
    
    text = (
        "👋 Добро пожаловать в магазин Telegram Premium!\n"
        "Здесь ты можешь быстро приобрести Premium на свой аккаунт.\n\n"
        "💎 Выберите действие:"
    )
    await message.answer(text, reply_markup=get_main_keyboard())

@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    user_id = message.from_user.id
    user_data = users_db.get(user_id, {"name": message.from_user.first_name, "completed_orders": 0})
    
    text = (
        "👤 Ваш профиль\n\n"
        f"🆔 ID: {user_id}\n\n"
        f"👤 Имя: {user_data['name']}\n\n"
        f"📦 Заказов: {user_data['completed_orders']}"
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
    await call.message.delete()
    await call.message.answer("💎 Выберите действие:", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("💎 Telegram Premium", reply_markup=get_tariff_keyboard())

@router.callback_query(F.data.in_({"buy_1_month", "buy_1_year"}))
async def select_tariff(call: CallbackQuery, state: FSMContext):
    if call.data == "buy_1_month":
        item_name = "Premium 1 месяц"
        price = "160 грн"
    else:
        item_name = "Premium 1 год"
        price = "1300 грн"

    await state.update_data(item_name=item_name, price=price)
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
        "item": data["item_name"],
        "price": data["price"],
        "phone": phone
    }

    text = (
        "💳 Оплата заказа\n"
        f"🧾 Заказ: {order_id}\n"
        f"📱 Товар: {data['item_name']}\n"
        f"📞 Номер: {phone}\n"
        f"💸 Стоимость: {data['price']}\n"
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
    price = data.get("price", "160 грн")

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
    
    admin_text = (
        "🔔 Новый чек на проверку!\n\n"
        f"🧾 Заказ: {order_id}\n"
        f"👤 Пользователь: {message.from_user.full_name} (ID: {message.from_user.id})\n"
        f"📱 Товар: {data['item_name']}\n"
        f"📞 Номер: {data['phone']}\n"
        f"💸 Сумма: {data['price']}"
    )
    
    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=admin_text,
        reply_markup=admin_kb
    )
    await state.clear()

@router.callback_query(F.data.startswith("approve_"))
async def admin_approve(call: CallbackQuery):
    order_id = call.data.split("_")[1]
    order_info = orders_db.get(order_id)
    
    if not order_info:
        await call.answer("Заказ не найден.", show_alert=True)
        return

    user_id = order_info["user_id"]
    item = order_info["item"]
    price = order_info["price"]

    # Сохраняем в GitHub
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, save_order_to_github, order_id, user_id, item, price)

    # Пополняем счётчик профиля
    if user_id in users_db:
        users_db[user_id]["completed_orders"] += 1

    # Уведомление пользователю
    user_text = (
        "🎉 Оплата подтверждена!\n"
        f"🧾 Заказ: {order_id}\n"
        f"📱 Товар: {item}\n"
        f"💰 Стоимость: {price}\n"
        "🔄 Заказ передан в обработку.\n"
        "⏳ Ожидайте выполнения заказа."
    )
    try:
        await bot.send_message(chat_id=user_id, text=user_text)
    except Exception:
        pass

    # Пост в канал
    duration_text = "1 месяц" if "1 месяц" in item else "1 год"
    channel_text = (
        "💎 Premium успешно выдан!\n"
        f"🧾 Номер заказа: {order_id}\n"
        f"💎 Premium: {duration_text}\n"
        f"💰 Стоимость: {price}\n"
        "✅ Заказ успешно выполнен!"
    )
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=channel_text)
    except Exception as e:
        logging.error(f"Ошибка канала: {e}")

    await call.message.edit_caption(caption=call.message.caption + "\n\n✅ **ОДОБРЕНО**")

@router.callback_query(F.data.startswith("reject_"))
async def admin_reject(call: CallbackQuery):
    order_id = call.data.split("_")[1]
    order_info = orders_db.get(order_id)
    
    if order_info:
        user_id = order_info["user_id"]
        try:
            await bot.send_message(chat_id=user_id, text=f"❌ Ваш заказ {order_id} был отменён администратором.")
        except Exception:
            pass

    await call.message.edit_caption(caption=call.message.caption + "\n\n❌ **ОТКЛОНЕНО**")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
