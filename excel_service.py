import pandas as pd
import requests
from io import BytesIO
import logging
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import asyncio
from dotenv import load_dotenv

# Add this constant since it's used in the admin methods
ADMIN_MENU = 4  # Make sure this matches the state number in main.py

logger = logging.getLogger(__name__)

class ExcelService:
    def __init__(self):
        load_dotenv()  # Load environment variables from .env file
        # Use the SHEET_LINK environment variable directly
        self.sheet_link = os.getenv('SHEET_LINK')  # Get the link from the environment variable

        # Initialize Google credentials
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

        # Use environment variables for credentials files
        sheets_creds_file = 'key_shet.json'
        drive_creds_file = 'key_google_drive.json'

        try:
            self.drive_creds = ServiceAccountCredentials.from_json_keyfile_name(drive_creds_file, scope)
            self.sheets_creds = ServiceAccountCredentials.from_json_keyfile_name(sheets_creds_file, scope)
            self.drive_client = gspread.authorize(self.drive_creds)
            self.sheets_client = gspread.authorize(self.sheets_creds)
        except Exception as e:
            logger.error(f"Error initializing Google credentials: {e}")
            self.drive_client = None
            self.sheets_client = None

        self._sheet = None
        self._sheet_id = None

    def get_file_link(self):
        """Get the stored file link"""
        # Directly return the sheet link from the environment variable
        return self.sheet_link

    def save_user_data(self, user_data):
        """Save user data directly to online file"""
        try:
            file_link = self.get_file_link()
            if not file_link:
                raise Exception("No file link configured")

            # For Google Sheets
            if 'docs.google.com/spreadsheets' in file_link:
                # Extract sheet ID from link
                sheet_id = file_link.split('/d/')[1].split('/')[0]

                # Try both clients
                sheet = None
                try:
                    sheet = self.sheets_client.open_by_key(sheet_id).sheet1
                except Exception:
                    try:
                        sheet = self.drive_client.open_by_key(sheet_id).sheet1
                    except Exception as e:
                        logger.error(f"Could not access sheet: {e}")
                        return False

                try:
                    # Get all values
                    values = sheet.get_all_values()
                    
                    # Проверяем только существование кошелька
                    user_wallet = user_data['Пользовательский кошелек'].lower()
                    for row in values:
                        if len(row) > 2 and row[2].lower() == user_wallet:
                            logger.warning(f"Wallet {user_wallet} already exists")
                            return 'wallet_exists'

                    # Если кошелек не существует, добавляем новую строку
                    new_row = [
                        str(user_data['Телеграмм ID']),
                        str(user_data['Имя пользователя'] or ''),
                        user_data['Пользовательский кошелек'],
                        user_data['Кошелек реферера'],
                        user_data['Статус'] if user_data['Статус'] else ''
                    ]

                    sheet.append_row(new_row)
                    logger.info("Successfully added new row to sheet")
                    return 'success'

                except Exception as e:
                    logger.error(f"Error saving to Google Sheets: {e}")
                    return False

        except Exception as e:
            logger.error(f"Error saving user data: {e}")
            return False

    def _save_to_google_sheets(self, file_link, user_data):
        """Save data directly to Google Sheets"""
        try:
            # Extract sheet ID from link
            sheet_id = file_link.split('/d/')[1].split('/')[0]

            # Try both clients with error handling
            sheet = None
            last_error = None

            # Try sheets client
            try:
                sheet = self.sheets_client.open_by_key(sheet_id).sheet1
                logger.info("Successfully connected using sheets client")
            except Exception as e:
                logger.error(f"Failed to connect with sheets client: {e}")
                last_error = e

                # Try drive client
                try:
                    sheet = self.drive_client.open_by_key(sheet_id).sheet1
                    logger.info("Successfully connected using drive client")
                except Exception as e:
                    logger.error(f"Failed to connect with drive client: {e}")
                    last_error = e

            if not sheet:
                raise Exception(f"Could not access sheet with either client. Last error: {last_error}")

            # Only check if user wallet exists (not referrer)
            try:
                # Get the column with user wallets
                user_wallets = sheet.col_values(3)  # Assuming user wallet is in column 3
                # Remove header if exists
                if user_wallets and user_wallets[0] == 'Пользовательский кошелек':
                    user_wallets = user_wallets[1:]

                # Check if user wallet exists (case-insensitive)
                if any(wallet.lower() == user_data['Пользовательский кошелек'].lower()
                       for wallet in user_wallets):
                    logger.error("User wallet already exists")
                    return False
            except gspread.exceptions.CellNotFound:
                pass

            # Get current values to check column headers
            values = sheet.get_all_values()
            if not values:
                # Sheet is empty, add headers
                headers = [
                    'Телеграмм ID',
                    'Имя пользователя',
                    'Пользовательский кошелек',
                    'Кошелек реферера',
                    'Статус'
                ]
                sheet.append_row(headers)

            # Add new row
            new_row = [
                str(user_data['Телеграмм ID']),
                str(user_data['Имя пользователя'] or ''),
                user_data['Пользовательский кошелек'],
                user_data['Кошелек реферера'],
                user_data['Статус'] if user_data['Статус'] else ''
            ]

            sheet.append_row(new_row)
            logger.info("Successfully added new row to sheet")
            return True

        except Exception as e:
            logger.error(f"Error saving to Google Sheets: {e}")
            return False

    async def update_user_status(self, user_id, status):
        """Асинхронное обновление статуса"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._update_user_status_sync,
            user_id,
            status
        )

    def _update_user_status_sync(self, user_id, status):
        """Обновляет статус пользователя в Google Sheets."""
        try:
            file_link = self.get_file_link()
            if not file_link:
                logger.error("No file link configured")
                return None  # Changed to None for error case

            # Extract sheet ID from link
            sheet_id = file_link.split('/d/')[1].split('/')[0]

            # Try both clients
            sheet = None
            try:
                sheet = self.sheets_client.open_by_key(sheet_id).sheet1
            except Exception:
                try:
                    sheet = self.drive_client.open_by_key(sheet_id).sheet1
                except Exception as e:
                    logger.error(f"Could not access sheet: {e}")
                    return None  # Changed to None for error case

            # Find user row
            try:
                # Convert user_id to string for comparison
                str_user_id = str(user_id)

                # Get all values
                values = sheet.get_all_values()
                if not values:
                    return None  # Changed to None for error case

                # Find the row with matching user ID
                user_row = None
                for i, row in enumerate(values):
                    if row[0] == str_user_id:  # Assuming Telegram ID is in first column
                        # Check if already validated
                        if len(row) >= 5 and row[4] == 'Подтвержден':
                            return 'already_validated'  # New return value for already validated users
                        user_row = i + 1  # +1 because sheet rows are 1-based
                        break

                if user_row is None:
                    return 'not_found'  # New return value for users not found

                # Update status (assuming status is in column 5)
                sheet.update_cell(user_row, 5, status)
                return 'success'  # New return value for successful update

            except Exception as e:
                logger.error(f"Error finding/updating user: {e}")
                return None  # Changed to None for error case

        except Exception as e:
            logger.error(f"Error in update_user_status: {e}")
            return None  # Changed to None for error case

    def download_file(self, url):
        """Download file from Google Drive or OneDrive"""
        try:
            # Handle Google Drive links
            if 'drive.google.com' in url:
                file_id = self._get_google_file_id(url)
                download_url = f'https://drive.google.com/uc?export=download&id={file_id}'
            # Handle OneDrive links
            elif '1drv.ms' in url or 'onedrive.live.com' in url:
                download_url = url.replace('view.aspx', 'download.aspx')
            # Handle direct links
            else:
                download_url = url

            response = requests.get(download_url)
            response.raise_for_status()
            return BytesIO(response.content)
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            # Return empty file if download fails
            buffer = BytesIO()
            df = pd.DataFrame(columns=[
                'Телеграмм ID',
                'Имя пользователя',
                'Пользоватльский кошелек',
                'Кошелек реферера',
                'Статус'
            ])
            df.to_excel(buffer, index=False, engine='openpyxl')
            buffer.seek(0)
            return buffer

    def _get_google_file_id(self, url):
        """Extract file ID from Google Drive URL"""
        if '/file/d/' in url:
            return url.split('/file/d/')[1].split('/')[0]
        elif 'id=' in url:
            return url.split('id=')[1].split('&')[0]
        raise ValueError("Invalid Google Drive URL format")

    def _upload_to_service(self, df, link):
        """Upload file back to service"""
        try:
            # For Google Drive links
            if 'drive.google.com' in link:
                # For Google Sheets direct edit link
                if 'spreadsheets/d/' in link:
                    file_id = link.split('spreadsheets/d/')[1].split('/')[0]
                    edit_url = f'https://docs.google.com/spreadsheets/d/{file_id}/edit'
                    return True  # File will be edited directly in Google Sheets

                # For Google Drive view/share links
                elif 'file/d/' in link:
                    file_id = self._get_google_file_id(link)
                    view_url = f'https://drive.google.com/file/d/{file_id}/view'
                    return True  # File will be accessed via Google Drive

            # For OneDrive links
            elif '1drv.ms' in link or 'onedrive.live.com' in link:
                return True  # File will be edited directly in OneDrive

            # For direct links
            else:
                # Just verify the link is accessible
                response = requests.head(link)
                response.raise_for_status()
                return True

        except Exception as e:
            logger.error(f"Error uploading to service: {e}")
            return True  # Return True anyway to save locally

    async def check_user_exists(self, user_id):
        """Проверяет существование пользователя в таблице."""
        try:
            file_link = self.get_file_link()
            if not file_link:
                logger.error("No file link configured")
                return False

            # Extract sheet ID from link
            sheet_id = file_link.split('/d/')[1].split('/')[0]

            # Try both clients
            sheet = None
            try:
                sheet = self.sheets_client.open_by_key(sheet_id).sheet1
            except Exception:
                try:
                    sheet = self.drive_client.open_by_key(sheet_id).sheet1
                except Exception as e:
                    logger.error(f"Could not access sheet: {e}")
                    return False

            # Find user
            try:
                # Convert user_id to string for comparison
                str_user_id = str(user_id)
                
                # Get all values
                values = sheet.get_all_values()
                if not values:
                    return False

                # Check if user exists
                for row in values:
                    if row[0] == str_user_id:  # Assuming Telegram ID is in first column
                        return True
                
                return False

            except Exception as e:
                logger.error(f"Error checking user existence: {e}")
                return False

        except Exception as e:
            logger.error(f"Error in check_user_exists: {e}")
            return False

    async def get_user_language(self, user_id):
        """Получает язык пользователя из таблицы."""
        try:
            file_link = self.get_file_link()
            if not file_link:
                return None

            sheet_id = file_link.split('/d/')[1].split('/')[0]
            
            sheet = None
            try:
                sheet = self.sheets_client.open_by_key(sheet_id).sheet1
            except Exception:
                try:
                    sheet = self.drive_client.open_by_key(sheet_id).sheet1
                except Exception:
                    return None

            # Получаем все значения
            values = sheet.get_all_values()
            if not values:
                return None

            # Ищем пользователя
            str_user_id = str(user_id)
            for row in values:
                if row[0] == str_user_id:
                    # Возвращаем язык пользователя (если есть колонка с языком)
                    # Если нет колонки с языком, возвращаем None
                    return row[5] if len(row) > 5 else None

            return None

        except Exception as e:
            logger.error(f"Error getting user language: {e}")
            return None

    def get_current_sheet_id(self):
        """Получает ID текущей таблицы из сохраненной ссылки"""
        try:
            file_link = self.get_file_link()
            if not file_link:
                return None
            
            # Extract sheet ID from link
            if 'docs.google.com/spreadsheets' in file_link:
                return file_link.split('/d/')[1].split('/')[0]
            return None
            
        except Exception as e:
            logger.error(f"Error getting current sheet ID: {e}")
            return None

    async def get_sheet(self):
        """Переиспользование подключения к таблице"""
        if self._sheet and self._sheet_id == self.get_current_sheet_id():
            return self._sheet
            
        # Создаем новое подключение только если нужно
        try:
            sheet_id = self.get_current_sheet_id()
            if not sheet_id:
                return None
                
            self._sheet = self.sheets_client.open_by_key(sheet_id).sheet1
            self._sheet_id = sheet_id
            return self._sheet
        except Exception as e:
            logger.error(f"Error connecting to sheet: {e}")
            return None

    async def update_wallet_status_by_address(self, wallet_address, status):
        """Обновляет статус по адресу кошелька"""
        try:
            sheet = await self.get_sheet()
            if not sheet:
                return None

            # Получаем все данные
            values = sheet.get_all_values()
            if not values:
                return 'not_found'

            # Ищем кошелек (учитывая регистр)
            wallet_address = wallet_address.lower()
            for i, row in enumerate(values):
                if len(row) > 2 and row[2].lower() == wallet_address:
                    # Проверяем статус
                    if len(row) >= 5 and row[4] == 'Подтвержден':
                        return 'already_validated'
                    
                    # Обновляем статус
                    sheet.update_cell(i + 1, 5, status)
                    return {
                        'success': True,
                        'user_id': row[0],
                        'wallet': row[2]
                    }

            return 'not_found'

        except Exception as e:
            logger.error(f"Error updating wallet status by address: {e}")
            return None