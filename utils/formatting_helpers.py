from models.user_data import user_data
from utils.google_sheets import  SIZE_COLS

STATE_WAREHOUSE  = "warehouse"
STATE_MODELS     = "models"            # list[{model_name, colors{color:[{bag_id, sizes{size:qty}}]}}]
STATE_SHIP_DATE  = "ship_date"
STATE_ETA_DATE   = "eta_date"
CURRENT_MODEL    = "current_model"

# ===================== Formatting Helpers ================================

def _format_bag_preview(color: str, current_bag: dict, bag_index: int, total_bags: int) -> str:
    """Format current bag preview with sizes"""
    sizes = current_bag.get('sizes', {})
    pairs = [f"{k}-{sizes[k]}" for k in SIZE_COLS if sizes.get(k, 0) > 0]
    body = " ".join(pairs) if pairs else "—"
    bag_id = current_bag.get('bag_id', f'пакет {bag_index + 1}')
    return f"Текущая расцветка: {color}\nПакет: {bag_id} ({bag_index + 1}/{total_bags})\nРазмеры: {body}\n\n"

def _format_confirmation(state: dict, factory_name: str) -> str:
    """Format confirmation message showing all data"""
    wh = state.get(STATE_WAREHOUSE, "—")
    ship = state.get(STATE_SHIP_DATE, "—")
    eta = state.get(STATE_ETA_DATE, "—")
    
    lines = [
        "Проверьте правильность данных:", 
        f"📋 Фабрика: {factory_name}",
        f"Склад: {wh}"
    ]
    total_all = 0
    total_bags = 0
    
    for item in state.get(STATE_MODELS, []):
        model = item.get("model_name", "—")
        colors = item.get("colors", {})
        lines.append(f"Модель: {model}")
        
        for color, bags in colors.items():
            lines.append(f"  Расцветка: {color}")
            for bag in bags:
                bag_id = bag.get('bag_id', '—')
                sizes = bag.get('sizes', {})
                qty = sum(int(v or 0) for v in sizes.values())
                total_all += qty
                total_bags += 1
                pairs = [f"{k}-{sizes.get(k,0)}" for k in SIZE_COLS if sizes.get(k,0) > 0]
                size_text = " ".join(pairs) if pairs else "—"
                lines.append(f"    {bag_id}: {size_text} (всего: {qty})")
        lines.append("")
    
    lines.append(f"📊 Общее количество: {total_all} шт")
    lines.append(f"📦 Общее количество пакетов: {total_bags}")
    lines.append(f"Дата отправки: {ship}")
    lines.append(f"Дата прибытия (примерное): {eta}")
    return "\n".join(lines)