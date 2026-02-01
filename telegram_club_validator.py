"""Модуль для проверки членства пользователя в клубе и Telegram группе."""

import re
import requests
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from config import BASE_URL, REQUEST_TIMEOUT, TELEGRAM_CHAT_ID
from logger import get_logger

logger = get_logger("club_validator")


class ClubValidator:
    """Валидатор для проверки членства в клубе и Telegram группе."""
    
    def __init__(
        self,
        session,
        bot_token: str,
        required_club_slug: str,
        telegram_chat_id: str,
        proxy_manager=None
    ):
        """
        Args:
            session: requests.Session для MangaBuff (с прокси)
            bot_token: Токен Telegram бота
            required_club_slug: Slug клуба (например, 'klub-taro-2')
            telegram_chat_id: ID Telegram группы
            proxy_manager: Менеджер прокси (только для MangaBuff)
        """
        self.session = session  # 🔧 Используется только для MangaBuff
        self.bot_token = bot_token
        self.required_club_slug = required_club_slug
        self.telegram_chat_id = telegram_chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        
        # 🔧 ИСПРАВЛЕНО: НЕ используем прокси для Telegram API
        self.proxies = None
        logger.info("Club validator: прокси только для MangaBuff, Telegram API без прокси")
    
    def extract_club_slug_from_boost_url(self, boost_url: str) -> Optional[str]:
        """
        Извлекает slug клуба из boost URL.
        
        Args:
            boost_url: URL буста (например, 'https://mangabuff.ru/clubs/klub-taro-2/boost')
        
        Returns:
            Slug клуба или None
        """
        # Паттерн: /clubs/{slug}/boost
        match = re.search(r'/clubs/([^/]+)/boost', boost_url)
        if match:
            slug = match.group(1)
            logger.debug(f"Извлечен slug клуба: {slug}")
            return slug
        
        logger.warning(f"Не удалось извлечь slug из URL: {boost_url}")
        return None
    
    def get_user_club_slug(self, user_id: str) -> Optional[str]:
        """
        Парсит профиль пользователя и извлекает slug его клуба.
        
        Args:
            user_id: ID пользователя MangaBuff
        
        Returns:
            Slug клуба пользователя или None
        """
        url = f"{BASE_URL}/users/{user_id}"
        
        try:
            logger.debug(f"Загрузка профиля пользователя {user_id}...")
            # 🔧 ИСПОЛЬЗУЕМ SESSION (с прокси для MangaBuff)
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                logger.warning(f"Ошибка загрузки профиля: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Ищем ссылку на клуб в профиле
            # <a href="/clubs/klub-taro-2" class="club-top-list__name">
            club_link = soup.select_one('.club-top-list__name[href*="/clubs/"]')
            
            if not club_link:
                logger.info(f"Пользователь {user_id} не состоит ни в одном клубе")
                return None
            
            href = club_link.get('href', '')
            
            # Извлекаем slug из href
            match = re.search(r'/clubs/([^/]+)', href)
            if match:
                slug = match.group(1)
                club_name = club_link.get_text(strip=True)
                logger.debug(f"Пользователь состоит в клубе: {club_name} ({slug})")
                return slug
            
            logger.warning(f"Не удалось извлечь slug из href: {href}")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка парсинга клуба пользователя {user_id}: {e}")
            return None
    
    def check_club_membership(self, user_id: str) -> Tuple[bool, str]:
        """
        Проверяет состоит ли пользователь в нужном клубе.
        
        Args:
            user_id: ID пользователя MangaBuff
        
        Returns:
            (успех, сообщение)
        """
        logger.info(f"🔍 Проверка членства в клубе для пользователя {user_id}")
        
        user_club_slug = self.get_user_club_slug(user_id)
        
        if not user_club_slug:
            return False, (
                "❌ <b>Вы не состоите ни в одном клубе!</b>\n\n"
                "Для регистрации в боте нужно вступить в клуб:\n"
                f"🔗 <a href='{BASE_URL}/clubs/{self.required_club_slug}'>"
                f"Перейти в клуб</a>"
            )
        
        if user_club_slug != self.required_club_slug:
            return False, (
                f"❌ <b>Вы состоите в другом клубе!</b>\n\n"
                f"Ваш клуб: {user_club_slug}\n"
                f"Нужный клуб: {self.required_club_slug}\n\n"
                "Для регистрации в боте нужно вступить в клуб:\n"
                f"🔗 <a href='{BASE_URL}/clubs/{self.required_club_slug}'>"
                f"Перейти в клуб</a>"
            )
        
        logger.info(f"✅ Пользователь {user_id} состоит в правильном клубе: {self.required_club_slug}")
        return True, "Пользователь в нужном клубе"
    
    def check_telegram_membership(self, telegram_id: int) -> Tuple[bool, str]:
        """
        Проверяет подписан ли пользователь на Telegram группу.
        
        Args:
            telegram_id: ID пользователя в Telegram
        
        Returns:
            (успех, сообщение)
        """
        logger.info(f"🔍 Проверка подписки на Telegram группу для {telegram_id}")
        
        try:
            url = f"{self.api_url}/getChatMember"
            params = {
                "chat_id": self.telegram_chat_id,
                "user_id": telegram_id
            }
            
            # 🔧 БЕЗ ПРОКСИ для Telegram API
            response = requests.get(
                url,
                params=params,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.warning(f"Ошибка API getChatMember: {response.status_code}")
                # Не блокируем регистрацию при ошибке API
                return True, "Не удалось проверить подписку (пропускаем)"
            
            data = response.json()
            
            if not data.get('ok'):
                logger.warning(f"API вернуло ok=false")
                return True, "Не удалось проверить подписку (пропускаем)"
            
            result = data.get('result', {})
            status = result.get('status', '')
            
            logger.debug(f"Статус пользователя в группе: {status}")
            
            # Статусы членства: creator, administrator, member
            # НЕ состоит: left, kicked
            if status in ['creator', 'administrator', 'member']:
                logger.info(f"✅ Пользователь {telegram_id} состоит в группе (статус: {status})")
                return True, "Пользователь в группе"
            
            # Если не состоит или покинул
            return False, (
                "❌ <b>Вы не подписаны на Telegram группу!</b>\n\n"
                "Для регистрации в боте нужно вступить в клуб:\n"
                f"🔗 <a href='{BASE_URL}/clubs/{self.required_club_slug}'>"
            )
            
        except Exception as e:
            logger.error(f"Ошибка проверки Telegram подписки: {e}")
            # Не блокируем при ошибке
            return True, "Ошибка проверки подписки (пропускаем)"
    
    def _get_chat_username(self) -> str:
        """
        Получает username группы через getChat API.
        
        Returns:
            Username группы или chat_id
        """
        try:
            url = f"{self.api_url}/getChat"
            params = {"chat_id": self.telegram_chat_id}
            
            # 🔧 БЕЗ ПРОКСИ
            response = requests.get(
                url,
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    result = data.get('result', {})
                    username = result.get('username')
                    if username:
                        return username
            
            # Если не удалось получить username
            return self.telegram_chat_id
            
        except Exception as e:
            logger.debug(f"Не удалось получить chat username: {e}")
            return self.telegram_chat_id
    
    def validate_user_registration(
        self,
        telegram_id: int,
        mangabuff_user_id: str
    ) -> Tuple[bool, str]:
        """
        Полная проверка пользователя перед регистрацией.
        
        Args:
            telegram_id: ID пользователя в Telegram
            mangabuff_user_id: ID пользователя MangaBuff
        
        Returns:
            (успех, сообщение для пользователя)
        """
        logger.info(f"🔐 Валидация регистрации: TG {telegram_id} → MB {mangabuff_user_id}")
        
        # 1. Проверка клуба MangaBuff
        club_ok, club_message = self.check_club_membership(mangabuff_user_id)
        
        if not club_ok:
            logger.warning(f"❌ Проверка клуба не пройдена: {mangabuff_user_id}")
            return False, club_message
        
        # 2. Проверка Telegram группы
        telegram_ok, telegram_message = self.check_telegram_membership(telegram_id)
        
        if not telegram_ok:
            logger.warning(f"❌ Проверка Telegram группы не пройдена: {telegram_id}")
            return False, telegram_message
        
        logger.info(f"✅ Валидация пройдена для TG {telegram_id} → MB {mangabuff_user_id}")
        return True, "Проверки пройдены успешно"


def create_club_validator(
    session,
    bot_token: str,
    boost_url: str,
    telegram_chat_id: str,
    proxy_manager=None
) -> Optional[ClubValidator]:
    """
    Создает валидатор с автоматическим извлечением slug клуба из boost_url.
    
    Args:
        session: requests.Session (с прокси для MangaBuff)
        bot_token: Telegram bot token
        boost_url: URL страницы буста (например, 'https://mangabuff.ru/clubs/klub-taro-2/boost')
        telegram_chat_id: ID Telegram группы
        proxy_manager: Менеджер прокси (только для MangaBuff)
    
    Returns:
        ClubValidator или None при ошибке
    """
    # Извлекаем slug из boost_url
    match = re.search(r'/clubs/([^/]+)/boost', boost_url)
    
    if not match:
        logger.error(f"Не удалось извлечь slug клуба из boost_url: {boost_url}")
        return None
    
    club_slug = match.group(1)
    logger.info(f"Создан валидатор для клуба: {club_slug}")
    
    return ClubValidator(
        session=session,
        bot_token=bot_token,
        required_club_slug=club_slug,
        telegram_chat_id=telegram_chat_id,
        proxy_manager=proxy_manager
    )