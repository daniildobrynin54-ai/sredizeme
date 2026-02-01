"""Модуль авторизации с поддержкой прокси."""

from typing import Optional
import requests
from bs4 import BeautifulSoup

from config import BASE_URL, USER_AGENT, REQUEST_TIMEOUT
from rate_limiter import RateLimitedSession
from proxy_manager import ProxyManager
from logger import get_logger

logger = get_logger("auth")


class AuthenticationError(Exception):
    """Ошибка аутентификации."""
    pass


def get_csrf_token(session: requests.Session) -> Optional[str]:
    """Получает CSRF токен со страницы логина."""
    try:
        logger.debug("Запрос CSRF токена")
        response = session.get(f"{BASE_URL}/login", timeout=REQUEST_TIMEOUT)
        
        if response.status_code != 200:
            logger.error(f"Ошибка получения страницы логина: статус {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Пробуем найти токен в meta теге
        token_meta = soup.select_one('meta[name="csrf-token"]')
        if token_meta:
            token = token_meta.get("content", "").strip()
            if token:
                logger.debug("CSRF токен найден в meta теге")
                return token
        
        # Пробуем найти токен в input поле
        token_input = soup.find("input", {"name": "_token"})
        if token_input:
            token = token_input.get("value", "").strip()
            if token:
                logger.debug("CSRF токен найден в input поле")
                return token
        
        logger.warning("CSRF токен не найден на странице")
        return None
        
    except requests.RequestException as e:
        logger.error(f"Ошибка при получении CSRF токена: {e}")
        return None


def create_session(proxy_manager: Optional[ProxyManager] = None) -> requests.Session:
    """
    Создает настроенную сессию requests с прокси.
    
    Args:
        proxy_manager: Менеджер прокси
    
    Returns:
        Настроенная сессия с rate limiting
    """
    logger.debug("Создание новой сессии")
    session = requests.Session()
    
    # Настраиваем прокси
    if proxy_manager and proxy_manager.is_enabled():
        proxies = proxy_manager.get_proxies()
        if proxies:
            session.proxies.update(proxies)
            proxy_info = proxy_manager.get_info()
            print(f"🔗 Используется прокси: {proxy_info}")
            logger.info(f"Прокси настроен: {proxy_info}")
    
    # Настраиваем заголовки
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.8",
    })
    logger.debug("Заголовки сессии настроены")
    
    # Оборачиваем в RateLimitedSession
    logger.debug("Создание RateLimitedSession")
    return RateLimitedSession(session)


def login(
    email: str,
    password: str,
    proxy_manager: Optional[ProxyManager] = None
) -> Optional[RateLimitedSession]:
    """
    Выполняет вход в аккаунт.
    
    Args:
        email: Email пользователя
        password: Пароль
        proxy_manager: Менеджер прокси
    
    Returns:
        Авторизованная сессия или None при ошибке
    
    Raises:
        AuthenticationError: При ошибке аутентификации
    """
    logger.info(f"Попытка входа для email: {email[:3]}***{email[-10:]}" if len(email) > 13 else "***")
    session = create_session(proxy_manager)
    
    csrf_token = get_csrf_token(session)
    if not csrf_token:
        print("⚠️  Не удалось получить CSRF токен")
        logger.error("Не удалось получить CSRF токен")
        return None
    
    logger.debug("CSRF токен получен успешно")
    
    headers = {
        "Referer": f"{BASE_URL}/login",
        "Origin": BASE_URL,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRF-TOKEN": csrf_token,
    }
    
    data = {
        "email": email,
        "password": password,
        "_token": csrf_token
    }
    
    try:
        logger.debug("Отправка запроса авторизации")
        response = session.post(
            f"{BASE_URL}/login",
            data=data,
            headers=headers,
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT
        )
        
        logger.debug(f"Ответ сервера: статус {response.status_code}")
        
        # Проверяем успешность входа по наличию cookie сессии
        if "mangabuff_session" not in session.cookies:
            print("⚠️  Авторизация не удалась: нет cookie сессии")
            logger.error("Авторизация не удалась: cookie сессии отсутствует")
            return None
        
        # Обновляем заголовки для последующих запросов
        session.headers.update({
            "X-CSRF-TOKEN": csrf_token,
            "X-Requested-With": "XMLHttpRequest"
        })
        
        logger.info("Авторизация успешна")
        return session
        
    except requests.RequestException as e:
        print(f"⚠️  Ошибка при авторизации: {e}")
        logger.exception(f"Ошибка при авторизации: {e}")
        return None


def is_authenticated(session: requests.Session) -> bool:
    """
    Проверяет, авторизована ли сессия.
    
    Args:
        session: Сессия для проверки
    
    Returns:
        True если сессия авторизована
    """
    # Для RateLimitedSession нужно обращаться к _session
    result = False
    if isinstance(session, RateLimitedSession):
        result = "mangabuff_session" in session._session.cookies
    else:
        result = "mangabuff_session" in session.cookies
    
    logger.debug(f"Проверка авторизации: {'авторизована' if result else 'не авторизована'}")
    return result