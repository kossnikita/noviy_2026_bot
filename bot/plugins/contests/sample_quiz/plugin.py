from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ChatType


class Plugin:
    name = "Викторина (демо)"
    slug = "quiz"

    def register_user(self, router: Router) -> None:
        @router.message(Command("quiz"), F.chat.type == ChatType.PRIVATE)
        async def cmd_quiz(message: Message):
            await message.answer(
                "Демо викторина: нажмите кнопку, чтобы начать!",
                reply_markup=self._start_kb(),
            )

        @router.callback_query(F.data == f"{self.slug}:start")
        async def start_quiz(cb: CallbackQuery):
            await cb.message.answer("Вопрос 1: Сколько будет 2+2?\nОтветьте цифрой.")
            await cb.answer()

        @router.message(F.text.regexp(r"^[0-9]+$"), F.chat.type == ChatType.PRIVATE)
        async def handle_answer(message: Message):
            if message.text.strip() == "4":
                await message.reply("Верно! Это просто демо.")
            else:
                await message.reply("Неверно, попробуйте ещё.")

    def register_admin(self, router: Router) -> None:
        @router.callback_query(F.data == f"{self.slug}:admin")
        async def admin_info(cb: CallbackQuery):
            await cb.message.answer("Админка викторины (демо): пока без настроек.")
            await cb.answer()

    def user_menu_button(self):
        return (self.name, f"{self.slug}:start")

    def admin_menu_button(self):
        return (f"Настройки: {self.name}", f"{self.slug}:admin")

    def _start_kb(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Начать", callback_data=f"{self.slug}:start"
                    )
                ]
            ]
        )
