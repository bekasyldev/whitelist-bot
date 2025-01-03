import os
from dotenv import load_dotenv
import re
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from translations import TRANSLATIONS
from excel_service import ExcelService
import signal
import asyncio
import sys

# Load environment variables
load_dotenv()

# Простая настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
START, LANGUAGE_SELECT, WALLET_TYPE, USER_WALLET, REFERRER_WALLET, ADMIN_MENU, VALIDATE_USER = range(7)

# Get environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

class WalletBot:
    def __init__(self, token, admin_id):
        global ADMIN_ID
        self.token = token
        self.users_data = []
        ADMIN_ID = admin_id
        self.application = None
        self.excel_service = ExcelService()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Starts the conversation."""
        context.user_data.clear()

        if update.effective_user.id == ADMIN_ID:
            if not os.path.exists('data/excel_link.txt'):
                await update.message.reply_text(
                    "👋 Привет, администратор!\n\n"
                    "❗️ Для начала работы необходимо:\n"
                    "Установить ссылку на Excel файл командой:\n"
                    "/setlink <ссылка на Excel>\n\n"
                    "❗️ Требования к файлу Excel:\n"
                    "- Колонки:\n"
                    "  • Телеграмм ID\n"
                    "  • Имя пользователя\n"
                    "  • Пользовательский кошелек\n"
                    "  • Кошелек реферера\n"
                    "  • Статус"
                )
                return ConversationHandler.END

            context.user_data['language'] = 'ru'
            keyboard = [
                ['Валидация пользователя']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "Панель администратора\n\n"
                "🔗 Текущая ссылка на файл: /getlink",
                reply_markup=reply_markup
            )
            return ADMIN_MENU

        # Check if admin has set up the file
        if not os.path.exists('data/excel_link.txt'):
            await update.message.reply_text(
                "⚠️ Бот находится в процессе настройки.\n"
                "Пожалуйста, попробуйте позже."
            )
            return ConversationHandler.END

        keyboard = [
            ['English 🇬🇧', '中文 🇨🇳'],
            ['Indonesia 🇮🇩', 'Filipino 🇵🇭'],
            ['Tiếng Việt 🇻🇳', 'Русский 🇷🇺']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "Please select your language\n"
            "请选择您的语言\n"
            "Pilih bahasa Anda\n"
            "Piliin ang iyong wika\n"
            "Vui lòng chọn ngôn ngữ của bạn\n"
            "Пожалуйста, выберите язык",
            reply_markup=reply_markup
        )
        return LANGUAGE_SELECT

    async def select_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles language selection."""
        text = update.message.text

        # Маппинг текста кнопок на коды языков
        language_map = {
            'English 🇬🇧': 'en',
            '中文 🇨🇳': 'zh',
            'Indonesia 🇮🇩': 'id',
            'Filipino 🇵🇭': 'ph',
            'Tiếng Việt 🇻🇳': 'vi',
            'Русский 🇷🇺': 'ru'
        }

        language = language_map.get(text)
        if not language:
            await update.message.reply_text("Please select a language using the buttons")
            return LANGUAGE_SELECT

        # Сохраняем выбранный язык
        context.user_data['language'] = language

        # Показываем приветственное сообщение на выбранном языке
        keyboard = [['Start']]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

        await update.message.reply_text(
            TRANSLATIONS[language]['welcome'],
            reply_markup=reply_markup
        )
        return START

    async def user_start_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Begins the user registration process."""
        language = context.user_data.get('language', 'en')
        try:
            # Уведомление администратора о новом пользователе (всегда на русском)
            if self.application and ADMIN_ID:
                try:
                    await self.application.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"🆕 Новый пользователь начал регистрацию: @{update.effective_user.username or 'без username'}"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin: {e}")
                    pass

            # Use translated button text
            keyboard = [[TRANSLATIONS[language]['evm_wallet']]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                TRANSLATIONS[language]['select_wallet'],
                reply_markup=reply_markup
            )
            return WALLET_TYPE

        except Exception as e:
            logger.error(f"Error in user_start_registration: {e}")
            await update.message.reply_text(TRANSLATIONS[language]['error_try_again'])
            return ConversationHandler.END

    async def select_wallet_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles wallet type selection."""
        language = context.user_data.get('language', 'en')
        wallet_type = update.message.text

        # Check against translated button text
        if wallet_type != TRANSLATIONS[language]['evm_wallet']:
            await update.message.reply_text(TRANSLATIONS[language]['select_wallet_error'])
            return WALLET_TYPE

        # Store the wallet type
        context.user_data['wallet_type'] = 'EVM'

        # Show instructions in selected language without back button
        await update.message.reply_text(
            TRANSLATIONS[language]['enter_wallet']
        )
        return USER_WALLET

    async def collect_user_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collects and validates the user's wallet address."""
        language = context.user_data.get('language', 'en')
        try:
            user_wallet = update.message.text.strip()

            # Validate EVM wallet format
            if not self.is_valid_eth_address(user_wallet):
                await update.message.reply_text(
                    TRANSLATIONS[language]['invalid_wallet']
                )
                return USER_WALLET

            # Store the wallet in context
            context.user_data['user_wallet'] = user_wallet

            # Ask for referrer wallet without validation requirements
            await update.message.reply_text(
                TRANSLATIONS[language]['enter_referral']
            )
            return REFERRER_WALLET

        except Exception as e:
            logger.error(f"Error in collect_user_wallet: {e}")
            await update.message.reply_text(TRANSLATIONS[language]['error_try_again'])
            return ConversationHandler.END

    async def admin_start_validation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Начинает процесс валидации ользователей."""
        try:
            await update.message.reply_text(
                "📝 Отправьте адреса кошельков для подтверждения (максимум 10)\n"
                "Каждый адрес с новой строки\n\n"
                "Пример:\n"
                "0x1aD2B053b8c6b1592cB645DEfadf105F34d8C6e1\n"
                "0x2bE4F48F9F0C8F7156705F5477a4F3943d6A2F12"
            )
            return VALIDATE_USER

        except Exception as e:
            logger.error(f"Error in admin_start_validation: {e}")
            await update.message.reply_text("Произошла ошибка. Попробуйте снова через /start")
            return ADMIN_MENU

    async def confirm_user_validation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Подтверждает валидацию списка кошельков."""
        try:
            # Разбиваем текст на отдельные адреса
            wallets = [w.strip() for w in update.message.text.split('\n') if w.strip()]
            
            if len(wallets) > 10:
                await update.message.reply_text(
                    "❌ Слишком много кошельков! Максимум 10 за раз.",
                    reply_markup=ReplyKeyboardMarkup([['Валидация пользователя']], resize_keyboard=True)
                )
                return ADMIN_MENU

            # Проверяем формат каждого кошелька
            invalid_wallets = [w for w in wallets if not self.is_valid_eth_address(w)]
            if invalid_wallets:
                await update.message.reply_text(
                    "❌ Неверный формат следующих кошельков:\n" + 
                    "\n".join(invalid_wallets),
                    reply_markup=ReplyKeyboardMarkup([['Валидация пользователя']], resize_keyboard=True)
                )
                return ADMIN_MENU

            # Обрабатываем каждый кошелек
            results = {
                'success': [],
                'already_validated': [],
                'not_found': [],
                'failed': []
            }

            for wallet in wallets:
                result = await self.excel_service.update_wallet_status_by_address(wallet, 'Подтвержден')
                
                if isinstance(result, dict) and result.get('success'):
                    try:
                        # Отправляем уведомление пользователю
                        user_language = await self.excel_service.get_user_language(result['user_id']) or 'en'
                        await self.application.bot.send_message(
                            chat_id=result['user_id'],
                            text=TRANSLATIONS[user_language]['validation_success']
                        )
                        results['success'].append(f"{wallet} (ID: {result['user_id']})")
                    except Exception as e:
                        logger.error(f"Failed to send message to {result['user_id']}: {e}")
                        results['failed'].append(wallet)
                elif result == 'already_validated':
                    results['already_validated'].append(wallet)
                elif result == 'not_found':
                    results['not_found'].append(wallet)
                else:
                    results['failed'].append(wallet)

            # Формируем отчет
            report = "📊 Результаты валидации:\n\n"
            
            if results['success']:
                report += "✅ Успешно подтверждены:\n"
                report += "\n".join(results['success']) + "\n\n"
            
            if results['already_validated']:
                report += "ℹ️ Уже подтверждены:\n"
                report += "\n".join(results['already_validated']) + "\n\n"
            
            if results['not_found']:
                report += "❓ Не найдены:\n"
                report += "\n".join(results['not_found']) + "\n\n"
            
            if results['failed']:
                report += "❌ Ошибка при обработке:\n"
                report += "\n".join(results['failed'])

            await update.message.reply_text(
                report,
                reply_markup=ReplyKeyboardMarkup([['Валидация пользователя']], resize_keyboard=True)
            )

            return ADMIN_MENU

        except Exception as e:
            logger.error(f"Error in confirm_user_validation: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при обработке запроса",
                reply_markup=ReplyKeyboardMarkup([['Валидация пользователя']], resize_keyboard=True)
            )
            return ADMIN_MENU

    def is_valid_eth_address(self, address: str) -> bool:
        """Validates Ethereum address format."""
        # Check if address matches the format: 0x followed by 40 hex characters
        pattern = r'^0x[a-fA-F0-9]{40}$'
        return bool(re.match(pattern, address))

    async def save_user_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Saves the user data to Excel file."""
        language = context.user_data.get('language', 'en')
        try:
            # Handle /start command
            if update.message.text == '/start':
                return await self.start(update, context)

            referrer_wallet = update.message.text.strip()
            user_wallet = context.user_data.get('user_wallet')

            # Validate referrer wallet format - KEEPING THIS VALIDATION
            if not self.is_valid_eth_address(referrer_wallet):
                await update.message.reply_text(
                    TRANSLATIONS[language]['invalid_wallet']
                )
                return REFERRER_WALLET

            # Check if referrer wallet is same as user wallet
            if referrer_wallet.lower() == user_wallet.lower():
                await update.message.reply_text(
                    TRANSLATIONS[language]['same_wallet']
                )
                return REFERRER_WALLET

            # Use excel service to save data
            user_data = {
                'Телеграмм ID': update.effective_user.id,
                'Имя пользователя': update.effective_user.username,
                'Пользовательский кошелек': user_wallet,
                'Кошелек реферера': referrer_wallet,
                'Статус': None
            }

            result = self.excel_service.save_user_data(user_data)
            
            if result == 'success':
                # Remove keyboard only after successful registration
                await update.message.reply_text(
                    TRANSLATIONS[language]['registration_success'],
                    reply_markup=ReplyKeyboardRemove()
                )
                # Notify admin about new registration
                if self.application:
                    await self.application.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"✅ Новая регистрация!\n"
                             f"👤 Пользователь: @{update.effective_user.username or 'без username'}\n"
                             f"📱 ID: {update.effective_user.id}\n"
                             f"💼 Кошелек: {user_wallet}\n"
                             f"👥 Реферер: {referrer_wallet}"
                    )
                return ConversationHandler.END
            elif result == 'wallet_exists':
                await update.message.reply_text(
                    TRANSLATIONS[language]['wallet_exists'],
                    reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
            else:
                raise Exception("Failed to save data")

        except Exception as e:
            logger.error(f"Error in save_user_data: {e}")
            await update.message.reply_text(
                TRANSLATIONS[language]['error_try_again']
            )
            return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels and ends the conversation."""
        await update.message.reply_text(
            'Операция отменена.',
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    async def shutdown(self):
        """Cleanup before shutdown"""
        if self.application:
            await self.application.shutdown()

    def run(self):
        """Runs the bot."""
        try:
            application = Application.builder().token(self.token).build()
            self.application = application

            # Set up conversation handler
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler('start', self.start)],
                states={
                    LANGUAGE_SELECT: [
                        CommandHandler('start', self.start),
                        MessageHandler(
                            filters.Regex('^(English 🇬🇧|中文 🇨🇳|Indonesia 🇮🇩|Filipino 🇵🇭|Tiếng Việt 🇻🇳|Русский 🇷🇺)$'),
                            self.select_language
                        )
                    ],
                    START: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.user_start_registration)
                    ],
                    WALLET_TYPE: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.select_wallet_type)
                    ],
                    USER_WALLET: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.collect_user_wallet)
                    ],
                    REFERRER_WALLET: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.save_user_data)
                    ],
                    ADMIN_MENU: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.Regex('^Валидация пользователя$'), self.admin_start_validation),
                    ],
                    VALIDATE_USER: [
                        CommandHandler('start', self.start),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.confirm_user_validation)
                    ],
                },
                fallbacks=[CommandHandler('cancel', self.cancel)]
            )

            # Add handlers
            application.add_handler(conv_handler)
            application.add_handler(CommandHandler('setlink', self.set_excel_link))
            application.add_handler(CommandHandler('getlink', self.get_excel_link))

            # Start the bot
            application.run_polling(allowed_updates=Update.ALL_TYPES)

        except Exception as e:
            logger.error(f"Error in run method: {e}")
            if self.application:
                self.application.stop()

    async def restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Restarts the conversation."""
        context.user_data.clear()  # Clear user data
        return await self.start(update, context)  # Restart from beginning

    async def set_excel_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Saves the shared Excel file link"""
        if update.effective_user.id != ADMIN_ID:
            return

        try:
            # Extract link from command
            link = ' '.join(context.args)
            if not link:
                await update.message.reply_text("Использование: /setlink <ссылка>")
                return

            # Save link to file
            with open('data/excel_link.txt', 'w') as f:
                f.write(link)

            await update.message.reply_text(
                "✅ Ссылка сохранена!\n\n"
                "Теперь вы можете:\n"
                "1️⃣ Открыть файл по ссылке\n"
                "2️⃣ Просматривать изменения в реальном времени\n"
                "3️⃣ Редактировать данные\n\n"
                "Получить ссылку: /getlink"
            )
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")

    async def get_excel_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Sends the shared Excel file link"""
        if update.effective_user.id != ADMIN_ID:
            return

        try:
            if os.path.exists('data/excel_link.txt'):
                with open('data/excel_link.txt', 'r') as f:
                    link = f.read().strip()
                await update.message.reply_text(
                    f"🔗 Ссылка на файл Excel:\n{link}\n\n"
                    "Откройте ссылку для просмотра и редактирования данных."
                )
            else:
                await update.message.reply_text(
                    "❌ Ссылка еще не установлена.\n"
                    "Используйте /setlink <ссылка> для установки."
                )
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")

def signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown"""
    logger.info("Received shutdown signal, cleaning up...")
    if bot.application:
        asyncio.run(bot.shutdown())
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def main():
    bot = WalletBot(BOT_TOKEN, ADMIN_ID)
    bot.run()

if __name__ == '__main__':
    try:
        bot = WalletBot(BOT_TOKEN, ADMIN_ID)
        bot.run()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        if bot.application:
            asyncio.run(bot.shutdown())