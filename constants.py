STEPS = [
    "product_name",
    "shipment_date",
    "estimated_arrival",
    "product_color",
    "total_amount",
    "warehouse",
    "size_amounts"
]

PROMPTS = {
    "product_name": "Название изделия:",
    "shipment_date": "Дата отправки (дд/мм/гггг):",
    "estimated_arrival": "Дата возможного прибытия (дд/мм/гггг):",
    "product_color": "Цвет изделия:",
    "total_amount": "Количество (шт):",
    "warehouse": "Склад:",
    "size_amounts": "Количество на каждый размер (S: 50 M: 25 L: 50):"
}

# Date validation regex
DATE_PATTERN = r'^(0[1-9]|[12][0-9]|3[01])[./](0[1-9]|1[012])[./](20\d\d)$'

# Size amounts regex
SIZE_PATTERN = r'^[sS]:?\s*(\d+)\s*[mM]:?\s*(\d+)\s*[lL]:?\s*(\d+)$'