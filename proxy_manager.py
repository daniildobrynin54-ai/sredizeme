"""Менеджер прокси для requests с поддержкой SOCKS5 и автообновлением IP."""

import os
import re
import requests
from typing import Optional, Dict
from urllib.parse import urlparse, quote

from config import PROXY_ENABLED, PROXY_URL

class ProxyManager:
    """Менеджер для настройки SOCKS5/HTTP прокси с автообновлением IP."""
    
    def __init__(self, proxy_url: Optional[str] = None, auto_update_ip: bool = True):
        """
        Инициализация менеджера прокси.
        
        Args:
            proxy_url: URL прокси (различные форматы)
            auto_update_ip: Автоматически обновлять IP при инициализации
        """
        self.raw_proxy_str = proxy_url or PROXY_URL or os.getenv('PROXY_URL')
        self.proxy_url = self._normalize_proxy_url(self.raw_proxy_str)
        self.enabled = PROXY_ENABLED and bool(self.proxy_url)
        self.proxy_login = None
        self.proxy_password = None
        
        # Извлекаем логин/пароль для API
        if self.proxy_url:
            parsed = urlparse(self.proxy_url)
            self.proxy_login = parsed.username
            self.proxy_password = parsed.password
        
        # Автообновление IP
        if self.enabled and auto_update_ip and self.proxy_login:
            self._auto_update_ip()
    
    def _auto_update_ip(self) -> bool:
        """Автоматически обновляет IP через API proxy5.net."""
        try:
            # Получаем текущий IP (без прокси)
            response = requests.get("https://api.ipify.org?format=json", timeout=10)
            current_ip = response.json().get('ip')
            # Обновляем IP в прокси через API
            api_url = f"https://proxy5.net/api/getproxy?action=setip&login={self.proxy_login}"
            response = requests.get(api_url, timeout=10)
            
            if response.status_code == 200:
                import time
                time.sleep(5)
                return True
            else:
                return False
                
        except Exception as e:
            return False
    
    def _normalize_proxy_url(self, proxy_str: Optional[str]) -> Optional[str]:
        """
        Нормализует различные форматы прокси в стандартный URL.
        
        Поддерживаемые форматы:
        - socks5://user:pass@host:port
        - host:port@user:pass (автоматически добавит socks5://)
        - user:pass@host:port (автоматически добавит socks5://)
        - http://user:pass@host:port
        
        Args:
            proxy_str: Строка с прокси
            
        Returns:
            Нормализованный URL или None
        """
        if not proxy_str:
            return None
        
        proxy_str = proxy_str.strip()
        
        # Если уже в правильном формате
        if proxy_str.startswith(('http://', 'https://', 'socks5://', 'socks5h://')):
            # Проверяем что это реальный URL, а не что-то вроде "net-62-233-39-89.mcccx.com"
            try:
                parsed = urlparse(proxy_str)
                # Если схема есть, но хост выглядит подозрительно - игнорируем
                if parsed.scheme and not parsed.hostname:
                    return None
                return proxy_str
            except:
                return None
        
        # 🔧 ИСПРАВЛЕНО: Формат host:port@user:pass
        # Пример: 62.233.39.89:1080@PrsRUS1HZZ1GZ:LTWg4yWH
        match = re.match(r'^([\d\.]+):(\d+)@([^:@]+):([^:@]+)$', proxy_str)
        if match:
            host, port, user, password = match.groups()
            # Проверяем что host это действительно IP
            if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', host):
                password_encoded = quote(password, safe='')
                return f"socks5://{user}:{password_encoded}@{host}:{port}"
        
        # Формат: user:pass@host:port
        match = re.match(r'^([^:@]+):([^:@]+)@([\d\.]+):(\d+)$', proxy_str)
        if match:
            user, password, host, port = match.groups()
            # Проверяем что host это действительно IP
            if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', host):
                password_encoded = quote(password, safe='')
                return f"socks5://{user}:{password_encoded}@{host}:{port}"
        
        # Формат: host:port (без авторизации)
        match = re.match(r'^([\d\.]+):(\d+)$', proxy_str)
        if match:
            host, port = match.groups()
            if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', host):
                return f"socks5://{host}:{port}"
        return None
    
    def get_proxies(self) -> Optional[Dict[str, str]]:
        """
        Возвращает словарь прокси для requests.
        
        Returns:
            Словарь с прокси или None если прокси не используется
        """
        if not self.enabled or not self.proxy_url:
            return None
        
        try:
            parsed = urlparse(self.proxy_url)
            
            # Проверяем что URL корректный
            if not parsed.scheme or not parsed.hostname:
                return None
            
            # Для SOCKS5 нужна библиотека requests[socks]
            if parsed.scheme in ('socks5', 'socks5h'):
                return {
                    'http': self.proxy_url,
                    'https': self.proxy_url
                }
            # Для HTTP/HTTPS
            elif parsed.scheme in ('http', 'https'):
                return {
                    'http': self.proxy_url,
                    'https': self.proxy_url
                }
            else:
                return None
                
        except Exception as e:
            return None
    
    def is_enabled(self) -> bool:
        """Проверяет, включен ли прокси."""
        return self.enabled
    
    def get_info(self) -> str:
        """Возвращает информацию о прокси."""
        if not self.enabled:
            return "Proxy: Disabled"
        
        try:
            parsed = urlparse(self.proxy_url)
            
            if parsed.password:
                safe_url = f"{parsed.scheme}://{parsed.username}:***@{parsed.hostname}:{parsed.port}"
            else:
                safe_url = self.proxy_url
            
            return f"Proxy: {safe_url}"
        except:
            return f"Proxy: {self.proxy_url}"
    
    def test_connection(self) -> bool:
        """
        Тестирует подключение через прокси.
        
        Returns:
            True если прокси работает
        """
        if not self.enabled:
            return False
        
        proxies = self.get_proxies()
        
        if not proxies:
            return False
        
        try:
            # Тест 1: Проверка IP
            response = requests.get(
                "https://api.ipify.org?format=json",
                proxies=proxies,
                timeout=10
            )
            
            if response.status_code == 200:
                proxy_ip = response.json().get('ip')
            else:
                return False
            
            # Тест 2: Подключение к целевому сайту
            response = requests.get(
                "https://mangabuff.ru",
                proxies=proxies,
                timeout=10
            )
            
            if response.status_code == 200:
                return True
            else:
                return False
                
        except Exception as e:
            return False
    
    @staticmethod
    def parse_proxy_from_file(filepath: str) -> Optional[str]:
        """
        Загружает прокси из файла.
        
        Формат файла (первая строка):
        - socks5://user:pass@host:port
        - host:port@user:pass
        - user:pass@host:port
        
        Args:
            filepath: Путь к файлу с прокси
        
        Returns:
            URL прокси или None
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                line = f.readline().strip()
                if line:
                    return line
        except FileNotFoundError:
        except Exception as e:
        return None

def create_proxy_manager(
    proxy_url: Optional[str] = None,
    proxy_file: Optional[str] = None,
    auto_update_ip: bool = True,
    test_connection: bool = False
) -> ProxyManager:
    """
    Фабричная функция для создания ProxyManager.
    
    Args:
        proxy_url: URL прокси
        proxy_file: Путь к файлу с прокси
        auto_update_ip: Автоматически обновить IP
        test_connection: Тестировать подключение
    
    Returns:
        ProxyManager
    """
    # Приоритет: аргумент > файл > переменная окружения > config
    url = proxy_url
    
    if not url and proxy_file:
        url = ProxyManager.parse_proxy_from_file(proxy_file)
    
    manager = ProxyManager(url, auto_update_ip=auto_update_ip)
    
    if manager.is_enabled():
        print(f"[PROXY] {manager.get_info()}")
        
        # Тестируем подключение если нужно
        if test_connection:
            if manager.test_connection():
                print("[PROXY] ✅ Тест прокси пройден")
            else:
                print("[PROXY] ⚠️ Тест прокси не пройден (но продолжаем)")
    else:
        print("[PROXY] Proxy: Disabled")
    return manager