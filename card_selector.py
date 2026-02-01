"""Селектор карт для обмена с исключением уже отправленных."""

import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from config import (
    OUTPUT_DIR,
    MAX_CARD_SELECTION_ATTEMPTS,
    CACHE_VALIDITY_HOURS,
    MAX_WANTERS_FOR_TRADE
)
from inventory import InventoryManager
from parsers import count_wants
from utils import extract_card_data, is_cache_valid
from logger import get_logger


logger = get_logger("card_selector")
MAX_WANTERS_ALLOWED = MAX_WANTERS_FOR_TRADE


class CardSelector:
    """Селектор для подбора оптимальных карт для обмена."""
    
    def __init__(
        self,
        session,
        output_dir: str = OUTPUT_DIR,
        locked_cards: Optional[Set[int]] = None,
        used_cards: Optional[Set[int]] = None  # 🔧 НОВОЕ: История использованных карт
    ):
        self.session = session
        self.inventory_manager = InventoryManager(output_dir)
        self.locked_cards = locked_cards or set()
        self.used_cards = used_cards or set()  # 🔧 НОВОЕ
    
    def is_card_available(self, instance_id: int) -> bool:
        """Проверяет, доступна ли карта (не заблокирована и не использована)."""
        if instance_id in self.locked_cards:
            logger.debug(f"Карта {instance_id} заблокирована")
            return False
        
        # 🔧 НОВОЕ: Проверка на уже использованные карты
        if instance_id in self.used_cards:
            logger.debug(f"Карта {instance_id} уже использовалась")
            return False
        
        return True
    
    def mark_card_used(self, instance_id: int) -> None:
        """🔧 НОВОЕ: Помечает карту как использованную."""
        self.used_cards.add(instance_id)
        logger.debug(f"Карта {instance_id} помечена как использованная")
    
    def reset_used_cards(self) -> None:
        """🔧 НОВОЕ: Сбрасывает список использованных карт."""
        count = len(self.used_cards)
        self.used_cards.clear()
        logger.debug(f"Сброшено {count} использованных карт")
    
    def parse_and_cache_card(
        self,
        card: Dict[str, Any],
        parsed_inventory: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Парсит карту и сохраняет в кэш."""
        card_data = extract_card_data(card)
        
        if not card_data:
            return None
        
        instance_id = card_data["instance_id"]
        if not self.is_card_available(instance_id):
            return None
        
        card_id_str = str(card_data["card_id"])
        
        if card_id_str in parsed_inventory:
            cached = parsed_inventory[card_id_str]
            if is_cache_valid(cached.get("cached_at", ""), CACHE_VALIDITY_HOURS):
                cached["instance_id"] = instance_id
                return cached
        
        wanters_count = count_wants(
            self.session,
            card_id_str,
            force_accurate=False
        )
        
        if wanters_count < 0:
            return None
        
        if wanters_count > MAX_WANTERS_ALLOWED:
            return None
        
        parsed_card = {
            "card_id": card_data["card_id"],
            "name": card_data["name"],
            "rank": card_data["rank"],
            "wanters_count": wanters_count,
            "timestamp": time.time(),
            "cached_at": datetime.now().isoformat(),
            "instance_id": instance_id
        }
        
        parsed_inventory[card_id_str] = parsed_card
        self.inventory_manager.save_parsed_inventory(parsed_inventory)
        
        return parsed_card
    
    def filter_cards_by_rank(
        self,
        inventory: List[Dict[str, Any]],
        target_rank: str
    ) -> List[Dict[str, Any]]:
        """Фильтрует карты по рангу."""
        filtered = []
        
        for card in inventory:
            card_data = extract_card_data(card)
            if card_data and card_data["rank"] == target_rank:
                if self.is_card_available(card_data["instance_id"]):
                    filtered.append(card)
        
        return filtered
    
    def select_from_unparsed(
        self,
        available_cards: List[Dict[str, Any]],
        target_wanters: int,
        parsed_inventory: Dict[str, Dict[str, Any]],
        max_attempts: int = MAX_CARD_SELECTION_ATTEMPTS
    ) -> Optional[Dict[str, Any]]:
        """Выбирает карту из непропарсенного инвентаря."""
        attempts = 0
        random.shuffle(available_cards)
        
        while available_cards and attempts < max_attempts:
            attempts += 1
            random_card = available_cards.pop(0)
            self.inventory_manager.remove_card(random_card)
            
            parsed_card = self.parse_and_cache_card(random_card, parsed_inventory)
            
            if not parsed_card:
                continue
            
            if parsed_card["wanters_count"] < target_wanters:
                return parsed_card
        
        print(f"   Продолжаем парсить все непропарсенные карты...")
        
        while available_cards:
            random_card = available_cards.pop(0)
            self.inventory_manager.remove_card(random_card)
            
            parsed_card = self.parse_and_cache_card(random_card, parsed_inventory)
            
            if parsed_card and parsed_card["wanters_count"] < target_wanters:
                return parsed_card
        
        return None
    
    def select_from_parsed(
        self,
        parsed_inventory: Dict[str, Dict[str, Any]],
        target_rank: str,
        target_wanters: int,
        exclude_instances: Optional[Set[int]] = None  # 🔧 НОВОЕ
    ) -> Optional[Dict[str, Any]]:
        """
        🔧 УЛУЧШЕНО: Выбирает карту из пропарсенного инвентаря с исключением.
        
        Args:
            exclude_instances: Множество instance_id которые нужно исключить
        """
        exclude_instances = exclude_instances or set()
        
        suitable_less = []
        suitable_equal = []
        suitable_closest = []
        
        for card_data in parsed_inventory.values():
            if card_data["rank"] != target_rank:
                continue
            
            instance_id = card_data.get("instance_id", 0)
            
            # 🔧 НОВОЕ: Проверка на исключение
            if instance_id in exclude_instances:
                continue
            
            if not self.is_card_available(instance_id):
                continue
            
            wanters = card_data["wanters_count"]
            if wanters > MAX_WANTERS_ALLOWED:
                continue
            
            if wanters < target_wanters:
                suitable_less.append(card_data)
            elif wanters == target_wanters:
                suitable_equal.append(card_data)
            else:
                suitable_closest.append(card_data)
        
        if suitable_less:
            return random.choice(suitable_less)
        
        if suitable_equal:
            return random.choice(suitable_equal)
        
        if suitable_closest:
            suitable_closest.sort(key=lambda x: x["wanters_count"])
            return suitable_closest[0]
        
        return None
    
    def select_best_card(
        self,
        target_rank: str,
        target_wanters: int,
        exclude_instances: Optional[Set[int]] = None  # 🔧 НОВОЕ
    ) -> Optional[Dict[str, Any]]:
        """
        🔧 УЛУЧШЕНО: Выбирает лучшую карту с исключением определенных instance_id.
        """
        inventory = self.inventory_manager.load_inventory()
        parsed_inventory = self.inventory_manager.load_parsed_inventory()
        
        if not inventory and not parsed_inventory:
            print("   ⚠️  Инвентарь пуст!")
            return None
        
        available_cards = self.filter_cards_by_rank(inventory, target_rank)
        
        print(f"   Доступно непропарсенных карт ранга {target_rank}: {len(available_cards)}")
        
        if available_cards:
            selected_card = self.select_from_unparsed(
                available_cards,
                target_wanters,
                parsed_inventory
            )
            
            if selected_card:
                print(f"   ✅ Выбрана непропарсенная карта: {selected_card['name']} ({selected_card['wanters_count']} желающих)")
                return selected_card
            else:
                print(f"   ⚠️  Не найдено подходящих непропарсенных карт")
        
        print(f"   Ищем в пропарсенном инвентаре...")
        selected_card = self.select_from_parsed(
            parsed_inventory,
            target_rank,
            target_wanters,
            exclude_instances  # 🔧 НОВОЕ
        )
        
        if selected_card:
            wanters = selected_card['wanters_count']
            if wanters < target_wanters:
                print(f"   ✅ Выбрана пропарсенная карта (меньше): {selected_card['name']} ({wanters} < {target_wanters})")
            elif wanters == target_wanters:
                print(f"   ✅ Выбрана пропарсенная карта (равно): {selected_card['name']} ({wanters} = {target_wanters})")
            else:
                print(f"   ✅ Выбрана пропарсенная карта (ближайшая): {selected_card['name']} ({wanters} vs {target_wanters})")
            return selected_card
        
        print(f"   ❌ Не найдено подходящих карт ранга {target_rank}")
        return None


def select_trade_card(
    session,
    boost_card: Dict[str, Any],
    output_dir: str = OUTPUT_DIR,
    trade_manager=None,
    exclude_instances: Optional[Set[int]] = None  # 🔧 НОВОЕ
) -> Optional[Dict[str, Any]]:
    """
    🔧 УЛУЧШЕНО: Главная функция для выбора карты с исключением.
    
    Args:
        exclude_instances: Множество instance_id которые нужно исключить из выбора
    """
    target_rank = boost_card.get("rank", "")
    target_wanters = boost_card.get("wanters_count", 0)
    
    if not target_rank:
        return None
    
    locked_cards = set()
    if trade_manager:
        locked_cards = trade_manager.locked_cards
    
    selector = CardSelector(session, output_dir, locked_cards)
    return selector.select_best_card(target_rank, target_wanters, exclude_instances)