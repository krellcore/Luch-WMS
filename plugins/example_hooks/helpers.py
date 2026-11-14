"""Пример вспомогательного модуля внутри папки плагина.

Импортируется из plugin.py как `from . import helpers`
(или `from .helpers import ...`). Ядро грузит папку как пакет
`luch_plugin_<name>`, поэтому относительные импорты работают.
"""


def is_special(barcode: str) -> bool:
    return (barcode or "").startswith("SPECIAL-")


def special_message(barcode: str) -> str:
    return f"Особый штрихкод {barcode} обработан"