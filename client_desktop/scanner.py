from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QApplication, QTextEdit, QComboBox
)
from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtGui import QShortcut, QKeySequence


# -----------------------------------------------------------------
# Нормализация раскладки: ЙЦУКЕН → QWERTY по позициям клавиш.
# Сканер шлёт латинские клавиши, ОС с русской раскладкой
# превращает их в кириллицу. Здесь переводим обратно.
# -----------------------------------------------------------------

_RU_TO_EN = {
    # строчные
    'й': 'q', 'ц': 'w', 'у': 'e', 'к': 'r', 'е': 't',
    'н': 'y', 'г': 'u', 'ш': 'i', 'щ': 'o', 'з': 'p',
    'х': '[', 'ъ': ']',
    'ф': 'a', 'ы': 's', 'в': 'd', 'а': 'f', 'п': 'g',
    'р': 'h', 'о': 'j', 'л': 'k', 'д': 'l', 'ж': ';',
    'э': "'", 'ё': '`',
    'я': 'z', 'ч': 'x', 'с': 'c', 'м': 'v', 'и': 'b',
    'т': 'n', 'ь': 'm', 'б': ',', 'ю': '.',
    # заглавные
    'Й': 'Q', 'Ц': 'W', 'У': 'E', 'К': 'R', 'Е': 'T',
    'Н': 'Y', 'Г': 'U', 'Ш': 'I', 'Щ': 'O', 'З': 'P',
    'Х': '{', 'Ъ': '}',
    'Ф': 'A', 'Ы': 'S', 'В': 'D', 'А': 'F', 'П': 'G',
    'Р': 'H', 'О': 'J', 'Л': 'K', 'Д': 'L', 'Ж': ':',
    'Э': '"', 'Ё': '~',
    'Я': 'Z', 'Ч': 'X', 'С': 'C', 'М': 'V', 'И': 'B',
    'Т': 'N', 'Ь': 'M', 'Б': '<', 'Ю': '>',
    # дополнительные
    '№': '#',
}


def _has_cyrillic(code: str) -> bool:
    for ch in code:
        if '\u0400' <= ch <= '\u04FF':
            return True
    return False


def normalize_scan(code: str) -> str:
    """Переводит кириллицу в латиницу по позициям клавиш."""
    if not code:
        return code
    has_cyr = _has_cyrillic(code)
    out = []
    for ch in code:
        if has_cyr and ch == '.':
            out.append('/')
        elif ch in _RU_TO_EN:
            out.append(_RU_TO_EN[ch])
        else:
            out.append(ch)
    return "".join(out)


class ScannerBridge(QObject):
    """Приёмник сканера HID.

    Сканер в режиме «клавиатура» пишет символы в текущий виджет
    с фокусом. Мы держим на главном окне невидимый QLineEdit и
    принудительно возвращаем ему фокус. Сканер пишет туда,
    накапливается в buffer, по Enter или таймауту 300 мс
    эмитится сигнал scanned(code).
    """

    scanned = Signal(str)

    def __init__(self, main_window, hidden_input):
        super().__init__(main_window)
        self.main_window = main_window
        self.hidden_input = hidden_input
        self._buffer = []

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._flush)

        self.hidden_input.textChanged.connect(self._on_text_changed)
        self.hidden_input.returnPressed.connect(self._on_return)

        # Автофокус: раз в 500 мс возвращаем фокус на hidden_input,
        # если пользователь не в диалоге и не в реальном поле ввода.
        self._focus_timer = QTimer(self)
        self._focus_timer.setInterval(500)
        self._focus_timer.timeout.connect(self._ensure_focus)
        self._focus_timer.start()

    # ---------- приём скана ----------

    def _on_text_changed(self, text):
        if not text:
            return
        self._buffer.append(text)
        self.hidden_input.blockSignals(True)
        self.hidden_input.clear()
        self.hidden_input.blockSignals(False)
        self._timer.start()

    def _on_return(self):
        self._flush()

    def _flush(self):
        self._timer.stop()
        raw = "".join(self._buffer).strip()
        self._buffer.clear()
        if not raw:
            return
        code = normalize_scan(raw)
        try:
            self.scanned.emit(code)
        except Exception as e:
            print("scanned emit:", e)

    # ---------- фокус ----------

    def _ensure_focus(self):
        # не трогаем, пока открыт модальный диалог
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isModal() and w.isVisible():
                return
        # не трогаем, если пользователь печатает в реальное поле
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QTextEdit, QComboBox)) \
                and fw is not self.hidden_input:
            return
        if fw is not self.hidden_input:
            try:
                self.hidden_input.setFocus(Qt.OtherFocusReason)
            except Exception:
                pass