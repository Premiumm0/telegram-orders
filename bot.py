import os
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= КОНФИГУРАЦИЯ =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8661283656"))  # Ваш Telegram ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# Счётчики и база в памяти
all_users = set()
total_purchases = 0
total_earned = 0
user_purchases_count = {}  # Личные заказы пользователей
active_orders = {}         # Текущие заказы

# ================= FSM (СОСТОЯНИЯ) =================
class OrderState(StatesGroup):
    waiting_for_phone = State()
    waiting_for_receipt = State()

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================
async def keep_alive():
    """Авто-пинг раз в 15 минут, чтобы Render не спал и Telegram не банил"""
    while True:
        await asyncio.sleep(900)  # 15 минут (безопасный интервал)
        try:
            async with aiohttp.ClientSession() as session:
                # Вставьте ссылку на ваш Render сервис, если используете Webhook/Keep-Alive
                pass
        except Exception:
            pass

# ================= ОБРАБОТЧИКИ КОМАНД =================
@router.message(CommandStart())
async def cmd_start(message: Message):
    # Ограничение: доступ только пользователям с @username
    if not message.from_user.username:
        await message.answer("⚠️ Для использования бота укажите @username в настройках Telegram профиля.")
        return

    all_users.add(message.from_user.id)
    
    text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Добро пожаловать в наш магазин. Выберите нужный раздел в меню ниже:"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Оформить подписку", callback_dict="buy")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")]
    ])
    
    await message.answer(text, reply_markup=keyboard)

@router.callback_query(F.data == "profile")
async def show_profile(call: CallbackQuery):
    user_id = call.from_user.id
    username_str = f"@{call.from_user.username}" if call.from_user.username else "Отсутствует"

    if user_id == ADMIN_ID:
        text = (
            "<b>👤 Профиль Администратора</b>\n\n"
            f"<b>🆔 ID:</b> <code>{user_id}</code>\n"
            f"<b>🏷 Юзернейм:</b> {username_str}\n\n"
            "<b>📊 Статистика магазина:</b>\n"
            f"👥 Пользователей: {len(all_users)}\n"
            f"💎 Продано: {total_purchases}\n"
            f"💰 Заработано: {total_earned} грн"
        )
    else:
        my_orders = user_purchases_count.get(user_id, 0)
        text = (
            "<b>👤 Ваш профиль</b>\n\n"
            f"<b>🆔 ID:</b> <code>{user_id}</code>\n"
            f"<b>👤 Имя:</b> {call.from_user.first_name}\n"
            f"<b>🏷 Юзернейм:</b> {username_str}\n"
            f"<b>📦 Заказов:</b> {my_orders}"
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="start_menu")]
    ])
    
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(F.data == "start_menu")
async def back_to_start(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Оформить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")]
    ])
    await call.message.edit_text("Главное меню:", reply_markup=keyboard)

# ================= ОФОРМЛЕНИЕ ЗАКАЗА =================
@router.callback_query(F.data == "buy")
async def start_buy(call: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.waiting_for_phone)
    await call.message.answer("📱 Введите номер телефона или логин для оформления:")

@router.message(OrderState.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await state.set_state(OrderState.waiting_for_receipt)

    import uuid
    order_id = str(uuid.uuid4())[:8].upper()
    await state.update_data(order_id=order_id)

    # Безопасный текст с HTML-цитатами (blockquote)[cite: 2]
    text = (
        "<b>👛 Оплата переводом на карту</b>\n\n"
        f"<blockquote>Заказ: #{order_id}\n"
        "Товар: Telegram Premium\n"
        "К оплате: 150 грн</blockquote>\n\n"
        "<b>💳 Реквизиты для перевода</b>\n\n"
        "<blockquote>• Банк: A-Bank\n"
        "• Номер карты: 4323345042778606</blockquote>\n\n"
        "<b>🤖 Что нужно сделать</b>\n\n"
        "<blockquote>1. Переведите точную сумму на карту выше\n"
        "2. Отправьте скриншот чека в этот чат</blockquote>"
    )

    await message.answer(text, parse_mode="HTML")

@router.message(OrderState.waiting_for_receipt, F.photo)
async def process_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    phone = data.get("phone")
    user_id = message.from_user.id
    photo_id = message.photo[-1].file_id

    # Сохраняем в активные заказы
    active_orders[order_id] = {
        "user_id": user_id,
        "phone": phone,
        "price": 150
    }

    # Отправляем уведомление админу без лишних форматирований
    admin_text = (
        f"📥 Новый заказ #{order_id}\n\n"
        f"👤 Покупатель: @{message.from_user.username} ({user_id})\n"
        f"📱 Данные: {phone}\n"
        f"💰 Сумма: 150 грн"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{order_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{order_id}")
        ]
    ])

    await bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=admin_text, reply_markup=keyboard)
    await message.answer("⏳ Ваш чек отправлен на проверку администратору. Ожидайте выдачи!")
    await state.clear()

# ================= ДЕЙСТВИЯ АДМИНИСТРАТОРА =================
@router.callback_query(F.data.startswith("approve_"))
async def approve_order(call: CallbackQuery):
    global total_purchases, total_earned
    order_id = call.data.split("_")[1]

    if order_id not in active_orders:
        await call.answer("Заказ не найден или уже обработан", show_alert=True)
        return

    order = active_orders.pop(order_id)
    target_user_id = order["user_id"]
    price = order["price"]

    # Обновляем статистику
    total_purchases += 1
    total_earned += price
    user_purchases_count[target_user_id] = user_purchases_count.get(target_user_id, 0) + 1

    # Уведомляем клиента
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=f"🎉 Ваш заказ #{order_id} успешно выполнен! Подписка Premium активирована."
        )
    except Exception:
        pass

    await call.message.edit_caption(caption=f"{call.message.caption}\n\n✅ **ОДОБРЕНО**")

@router.callback_query(F.data.startswith("reject_"))
async def reject_order(call: CallbackQuery):
    order_id = call.data.split("_")[1]

    if order_id not in active_orders:
        await call.answer("Заказ не найден или уже обработан", show_alert=True)
        return

    order = active_orders.pop(order_id)
    target_user_id = order["user_id"]

    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=f"❌ Ваш заказ #{order_id} отклонен. Проверьте правильность отправленного чека."
        )
    except Exception:
        pass

    await call.message.edit_caption(caption=f"{call.message.caption}\n\n❌ **ОТКЛОНЕНО**")

# ================= ЗАПУСК БОТА =================
async def main():
    asyncio.create_task(keep_alive())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
