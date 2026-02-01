"""Управление инвентарем пользователя."""

import os
import time
from typing import Any, Dict, List
import requests
from config import (
    BASE_URL,
    REQUEST_TIMEOUT,
    DEFAULT_DELAY,
    OUTPUT_DIR,
    INVENTORY_FILE,
    PARSED_INVENTORY_FILE
)
from utils import load_json, save_json
from logger import get_logger


logger = get_logger("inventory")


class InventoryManager:
    """Менеджер для работы с инвентарем."""
    
    def __init__(self, output_dir: str = OUTPUT_DIR):
        """
        Инициализация менеджера инвентаря.
        
        Args:
            output_dir: Директория для хранения файлов
        """
        self.output_dir = output_dir
        self.inventory_path = os.path.join(output_dir, INVENTORY_FILE)
        self.parsed_inventory_path = os.path.join(output_dir, PARSED_INVENTORY_FILE)
    
    def load_inventory(self) -> List[Dict[str, Any]]:
        """
        Загружает инвентарь из файла.
        
        Returns:
            Список карт инвентаря
        """
        return load_json(self.inventory_path, default=[])
    
    def save_inventory(self, inventory: List[Dict[str, Any]]) -> bool:
        """
        Сохраняет инвентарь в файл.
        
        Args:
            inventory: Список карт для сохранения
        
        Returns:
            True если успешно
        """
        return save_json(self.inventory_path, inventory)
    
    def load_parsed_inventory(self) -> Dict[str, Dict[str, Any]]:
        """
        Загружает пропарсенный инвентарь из файла.
        
        Returns:
            Словарь с пропарсенными картами {card_id: card_data}
        """
        return load_json(self.parsed_inventory_path, default={})
    
    def save_parsed_inventory(
        self,
        parsed_inventory: Dict[str, Dict[str, Any]]
    ) -> bool:
        """
        Сохраняет пропарсенный инвентарь в файл.
        
        Args:
            parsed_inventory: Словарь с пропарсенными картами
        
        Returns:
            True если успешно
        """
        return save_json(self.parsed_inventory_path, parsed_inventory)
    
    def remove_card(self, card: Dict[str, Any]) -> bool:
        """
        Удаляет карту из инвентаря.
        
        Args:
            card: Карта для удаления
        
        Returns:
            True если успешно
        """
        inventory = self.load_inventory()
        
        try:
            inventory.remove(card)
            return self.save_inventory(inventory)
        except ValueError:
            return False
    
    def sync_inventories(self) -> bool:
        """
        Синхронизирует обычный и пропарсенный инвентарь при запуске.
        
        Выполняет следующие операции:
        1. Загружает новый инвентарь с сервера и обновляет inventory.json
        2. Удаляет из inventory.json карты которые уже есть в parsed_inventory.json
        3. Удаляет из parsed_inventory.json карты которых нет в новом inventory.json
        
        Returns:
            True если успешно
        """
        logger.info("🔄 Синхронизация инвентаря с пропарсенными данными...")
        
        # Загружаем оба файла
        inventory = self.load_inventory()
        parsed_inventory = self.load_parsed_inventory()
        
        if not inventory:
            logger.info("Инвентарь пустой, синхронизация не требуется")
            return True
        
        if not parsed_inventory:
            logger.info("Пропарсенный инвентарь пустой, синхронизация не требуется")
            return True
        
        # Создаем набор instance_id из обычного инвентаря для быстрого поиска
        inventory_instance_ids = set()
        for card in inventory:
            instance_id = card.get('id')
            if instance_id:
                inventory_instance_ids.add(str(instance_id))
        
        # Создаем набор instance_id из пропарсенного инвентаря
        parsed_instance_ids = set()
        for card_id_str, card_data in list(parsed_inventory.items()):
            instance_id = card_data.get('instance_id')
            if instance_id:
                parsed_instance_ids.add(str(instance_id))
        
        # 1. Удаляем из inventory.json карты которые есть в parsed_inventory.json
        initial_inventory_count = len(inventory)
        inventory = [
            card for card in inventory
            if str(card.get('id', '')) not in parsed_instance_ids
        ]
        removed_from_inventory = initial_inventory_count - len(inventory)
        
        # 2. Удаляем из parsed_inventory.json карты которых нет в inventory.json
        initial_parsed_count = len(parsed_inventory)
        parsed_inventory = {
            card_id_str: card_data
            for card_id_str, card_data in parsed_inventory.items()
            if str(card_data.get('instance_id', '')) in inventory_instance_ids
        }
        removed_from_parsed = initial_parsed_count - len(parsed_inventory)
        
        # Сохраняем обновленные файлы
        save_success = True
        if removed_from_inventory > 0:
            if self.save_inventory(inventory):
                logger.info(f"✅ Удалено {removed_from_inventory} карт из inventory.json (уже пропарсены)")
            else:
                logger.error("❌ Ошибка сохранения обновленного inventory.json")
                save_success = False
        else:
            logger.info("Нет дубликатов в inventory.json")
        
        if removed_from_parsed > 0:
            if self.save_parsed_inventory(parsed_inventory):
                logger.info(f"✅ Удалено {removed_from_parsed} карт из parsed_inventory.json (больше нет в инвентаре)")
            else:
                logger.error("❌ Ошибка сохранения обновленного parsed_inventory.json")
                save_success = False
        else:
            logger.info("Нет лишних карт в parsed_inventory.json")
        
        logger.info(f"📊 Итого: inventory.json={len(inventory)}, parsed_inventory.json={len(parsed_inventory)}")
        return save_success


def fetch_user_cards(
    session: requests.Session,
    user_id: str,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Загружает карточки пользователя с заданным смещением.
    
    Args:
        session: Сессия requests
        user_id: ID пользователя
        offset: Смещение для пагинации
    
    Returns:
        Список карт или пустой список при ошибке
    """
    url = f"{BASE_URL}/trades/{user_id}/availableCardsLoad"
    
    headers = {
        "Referer": f"{BASE_URL}/trades/{user_id}",
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    
    try:
        response = session.post(
            url,
            headers=headers,
            data={"offset": offset},
            timeout=REQUEST_TIMEOUT
        )
        
        if response.status_code != 200:
            return []
        
        data = response.json()
        return data.get("cards", [])
        
    except (requests.RequestException, ValueError):
        return []


def get_user_inventory(
    session: requests.Session,
    user_id: str,
    page_size: int = 60
) -> List[Dict[str, Any]]:
    """
    Получает все карточки пользователя.
    
    Args:
        session: Сессия requests
        user_id: ID пользователя
        page_size: Размер страницы (по умолчанию API возвращает 60)
    
    Returns:
        Список всех карт пользователя
    """
    all_cards = []
    offset = 0
    
    while True:
        cards = fetch_user_cards(session, user_id, offset)
        
        if not cards:
            break
        
        all_cards.extend(cards)
        offset += len(cards)
        
        # Если получили меньше, чем размер страницы - это последняя страница
        if len(cards) < page_size:
            break
        
        time.sleep(DEFAULT_DELAY)
    
    return all_cards