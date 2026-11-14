"""Базовый интерфейс сессии."""


class SessionHandler:
    key = ""
    title = ""
    platforms = ("pc",)

    def can_start(self, login, roles):
        """Может ли пользователь открыть эту сессию."""
        return False

    def start(self, cur, login, payload):
        """Инициализация сессии. Сохранить состояние в БД."""
        pass

    def get_state(self, cur, login):
        """Текущее состояние (dict) для клиента."""
        return {}

    def handle_action(self, cur, login, action_id, value, settings):
        """Обработка действия.

        Возвращает dict:
          {"ok": True, "message": "...", "finished": bool}
          или {"ok": False, "error": "..."}.
        """
        raise NotImplementedError

    def get_view(self, cur, login, settings, caps):
        """ViewNode-документ для клиента (dict)."""
        return []

    def close(self, cur, login, force=False):
        """Закрыть сессию.

        При force=False — сессия может отказать в закрытии, если
        остались открытые ресурсы (тара, грузоместо).
        Возвращает {"ok": True} | {"ok": False, "error": "..."}.
        При force=True — закрыть принудительно (для logout).
        """
        return {"ok": True}