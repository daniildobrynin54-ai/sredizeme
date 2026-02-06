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

MAX_WANTERS_ALLOWED = MAX_WANTERS_FOR_TRADE

# 🔧 НОВОЕ: Порог нормализации для карт с малым количеством желающих
LOW_WANTERS_THRESHOLD = 5  # Карты с 0-5 желающих считаются равными

def normalize_wanters(wanters_count: int) -> int:
    """
    Нормализует количество желающих для карт с малым спросом.
    
    Карты с 0-5 желающих приравниваются к 0 для целей сравнения.
    Это позволяет использовать карты с 1-5 желающих вместо карт с 0 желающих.
    
    Args:
        wanters_count: Реальное количество желающих
    
    Returns:
        Нормализованное значение (0 если <= 5, иначе исходное значение)
    """
    if wanters_count <= LOW_WANTERS_THRESHOLD:
        return 0
    return wanters_count

class CardSelector:
    """Селектор для подбора оптимальных карт для обмена."""
    
    def __init__(
        self,
        session,
        output_dir: str = OUTPUT_DIR,
        locked_cards: Optional[Set[int]] = None,
        used_cards: Optional[Set[int]] = None
    ):
        self.session = session
        self.inventory_manager = InventoryManager(output_dir)
        self.locked_cards = locked_cards or set()
        self.used_cards = used_cards or set()
    
    def is_card_available(self, instance_id: int) -> bool:
        """Проверяет, доступна ли карта (не заблокирована и не использована)."""
        if instance_id in self.locked_cards:
            return False
        
        if instance_id in self.used_cards:
            return False
        
        return True
    
    def mark_card_used(self, instance_id: int) -> None:
        """Помечает карту как использованную."""
        self.used_cards.add(instance_id)
    
    def reset_used_cards(self) -> None:
        """Сбрасывает список использованных карт."""
        count = len(self.used_cards)
        self.used_cards.clear()
    
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
        """Выбирает карту из непропарсенного инвентаря с нормализацией 0-5 желающих."""
        attempts = 0
        random.shuffle(available_cards)
        
        # Нормализуем target
        normalized_target = normalize_wanters(target_wanters)
        
        while available_cards and attempts < max_attempts:
            attempts += 1
            random_card = available_cards.pop(0)
            self.inventory_manager.remove_card(random_card)
            
            parsed_card = self.parse_and_cache_card(random_card, parsed_inventory)
            
            if not parsed_card:
                continue
            
            # Нормализуем количество желающих для сравнения
            normalized_wanters = normalize_wanters(parsed_card["wanters_count"])
            
            # 🔧 ИЗМЕНЕНО: >= вместо <
            if normalized_wanters >= normalized_target:
                return parsed_card
        
        print(f"   Продолжаем парсить все непропарсенные карты...")
        
        while available_cards:
            random_card = available_cards.pop(0)
            self.inventory_manager.remove_card(random_card)
            
            parsed_card = self.parse_and_cache_card(random_card, parsed_inventory)
            
            if parsed_card:
                normalized_wanters = normalize_wanters(parsed_card["wanters_count"])
                # 🔧 ИЗМЕНЕНО: >= вместо <
                if normalized_wanters >= normalized_target:
                    return parsed_card
        
        return None
    
    def select_from_parsed(
        self,
        parsed_inventory: Dict[str, Dict[str, Any]],
        target_rank: str,
        target_wanters: int,
        exclude_instances: Optional[Set[int]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Выбирает карту из пропарсенного инвентаря с исключением.
        
        🔧 ИСПРАВЛЕНО: Новая логика приоритетов с нормализацией 0-5 желающих.
        
        Приоритет выбора:
        1. wanters >= target (больше или равно)
        2. Ближайшее меньшее значение
        
        Нормализация: Карты с 0-5 желающих считаются равными (как 0).
        Например, если target=0, то карты с 1,2,3,4,5 желающих тоже подходят.
        
        Args:
            exclude_instances: Множество instance_id которые нужно исключить
        """
        exclude_instances = exclude_instances or set()
        
        # Нормализуем target для сравнения
        normalized_target = normalize_wanters(target_wanters)
        
        suitable_greater_equal = []  # >= target (приоритет 1)
        suitable_less = []           # < target (приоритет 2)
        
        for card_data in parsed_inventory.values():
            if card_data["rank"] != target_rank:
                continue
            
            instance_id = card_data.get("instance_id", 0)
            
            if instance_id in exclude_instances:
                continue
            
            if not self.is_card_available(instance_id):
                continue
            
            wanters = card_data["wanters_count"]
            if wanters > MAX_WANTERS_ALLOWED:
                continue
            
            # Нормализуем количество желающих для сравнения
            normalized_wanters = normalize_wanters(wanters)
            
            # 🔧 ИСПРАВЛЕНО: Упрощенная логика - только 2 приоритета
            if normalized_wanters >= normalized_target:
                suitable_greater_equal.append(card_data)
            else:  # normalized_wanters < normalized_target
                suitable_less.append(card_data)
        
        # Приоритет 1 - карты с >= желающих (после нормализации)
        if suitable_greater_equal:
            return random.choice(suitable_greater_equal)
        
        # Приоритет 2 - карты с меньшим количеством (ближайшие к target)
        if suitable_less:
            # Сортируем по убыванию - берем ближайшее к target
            suitable_less.sort(key=lambda x: normalize_wanters(x["wanters_count"]), reverse=True)
            return suitable_less[0]
        
        return None
    
    def select_best_card(
        self,
        target_rank: str,
        target_wanters: int,
        exclude_instances: Optional[Set[int]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Выбирает лучшую карту с исключением определенных instance_id.
        """
        inventory = self.inventory_manager.load_inventory()
        parsed_inventory = self.inventory_manager.load_parsed_inventory()
        
        if not inventory and not parsed_inventory:
            print("   ⚠️  Инвентарь пуст!")
            return None
        
        available_cards = self.filter_cards_by_rank(inventory, target_rank)
        
        print(f"   Доступно непропарсенных карт ранга {target_rank}: {len(available_cards)}")
        
        # Показываем информацию о нормализации если target <= 5
        if target_wanters <= LOW_WANTERS_THRESHOLD:
            print(f"   ℹ️  Target {target_wanters} <= {LOW_WANTERS_THRESHOLD}: карты с 0-{LOW_WANTERS_THRESHOLD} желающих равнозначны")
        
        if available_cards:
            selected_card = self.select_from_unparsed(
                available_cards,
                target_wanters,
                parsed_inventory
            )
            
            if selected_card:
                wanters = selected_card['wanters_count']
                normalized_wanters = normalize_wanters(wanters)
                normalized_target = normalize_wanters(target_wanters)
                
                # 🔧 ИСПРАВЛЕНО: Обновленные сообщения с учетом нормализации
                if normalized_wanters >= normalized_target:
                    if wanters <= LOW_WANTERS_THRESHOLD and target_wanters <= LOW_WANTERS_THRESHOLD:
                        print(f"   ✅ Выбрана непропарсенная карта: {selected_card['name']} ({wanters} желающих, нормализовано до 0)")
                    else:
                        print(f"   ✅ Выбрана непропарсенная карта (больше/равно): {selected_card['name']} ({wanters} >= {target_wanters})")
                else:
                    print(f"   ✅ Выбрана непропарсенная карта (меньше): {selected_card['name']} ({wanters} < {target_wanters})")
                return selected_card
            else:
                print(f"   ⚠️  Не найдено подходящих непропарсенных карт")
        
        print(f"   Ищем в пропарсенном инвентаре...")
        selected_card = self.select_from_parsed(
            parsed_inventory,
            target_rank,
            target_wanters,
            exclude_instances
        )
        
        if selected_card:
            wanters = selected_card['wanters_count']
            normalized_wanters = normalize_wanters(wanters)
            normalized_target = normalize_wanters(target_wanters)
            
            # 🔧 ИСПРАВЛЕНО: Обновленные сообщения с учетом нормализации
            if normalized_wanters >= normalized_target:
                if wanters <= LOW_WANTERS_THRESHOLD and target_wanters <= LOW_WANTERS_THRESHOLD:
                    print(f"   ✅ Выбрана пропарсенная карта: {selected_card['name']} ({wanters} желающих, нормализовано до 0)")
                else:
                    print(f"   ✅ Выбрана пропарсенная карта (больше/равно): {selected_card['name']} ({wanters} >= {target_wanters})")
            else:
                print(f"   ✅ Выбрана пропарсенная карта (меньше): {selected_card['name']} ({wanters} < {target_wanters})")
            return selected_card
        
        print(f"   ❌ Не найдено подходящих карт ранга {target_rank}")
        return None

def select_trade_card(
    session,
    boost_card: Dict[str, Any],
    output_dir: str = OUTPUT_DIR,
    trade_manager=None,
    exclude_instances: Optional[Set[int]] = None
) -> Optional[Dict[str, Any]]:
    """
    Главная функция для выбора карты с исключением.
    
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