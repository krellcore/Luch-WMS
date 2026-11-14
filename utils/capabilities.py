"""Согласование возможностей клиентов."""

from view_protocol import (
    NODE_TYPES, ACTION_TYPES, FEATURE_NAMES, PROTOCOL_VERSION,
)
from mgmt_protocol import MGMT_WIDGETS


SUPPORTED_PROTOCOL_MAJOR = 1


class ClientCapabilities:
    def __init__(self, protocol=None, widgets=None, actions=None,
                 features=None, device=""):
        self.protocol = protocol or PROTOCOL_VERSION
        self.widgets = set(widgets) if widgets else set(NODE_TYPES)
        self.actions = set(actions) if actions else set(ACTION_TYPES)
        self.features = set(features) if features else set()
        self.device = device or ""

    def is_pc(self):
        return self.device == "pc"

    def supports(self, name):
        if name in NODE_TYPES:
            return name in self.widgets
        if name in ACTION_TYPES:
            return name in self.actions
        if name in FEATURE_NAMES:
            return name in self.features
        return False

    def to_dict(self):
        return {
            "protocol": self.protocol,
            "widgets": sorted(self.widgets),
            "actions": sorted(self.actions),
            "features": sorted(self.features),
            "device": self.device,
        }

    @staticmethod
    def from_dict(d):
        if not isinstance(d, dict):
            return ClientCapabilities()
        return ClientCapabilities(
            protocol=d.get("protocol"),
            widgets=d.get("widgets"),
            actions=d.get("actions"),
            features=d.get("features"),
            device=d.get("device") or "",
        )


class CapabilityRegistry:
    def __init__(self):
        self._by_login = {}

    def set(self, login, caps):
        if not login:
            return
        self._by_login[login] = caps

    def get(self, login):
        if not login:
            return ClientCapabilities()
        return self._by_login.get(login) or ClientCapabilities()

    def drop(self, login):
        self._by_login.pop(login, None)

    def drop_all(self):
        self._by_login.clear()

    def stats(self):
        return {login: caps.to_dict()
                for login, caps in self._by_login.items()}


def is_protocol_supported(protocol_str):
    if not protocol_str:
        return False
    try:
        major = int(str(protocol_str).split(".")[0])
    except Exception:
        return False
    return major == SUPPORTED_PROTOCOL_MAJOR


# ==================================================================
# Профиль «mgmt» (клиент управления)
# ==================================================================

def mgmt_capabilities(protocol="1.0", widgets=None):
    """Возможности клиента управления. По умолчанию — все
    mgmt-узлы. Клиент может прислать урезанный widgets."""
    return ClientCapabilities(
        protocol=protocol,
        widgets=widgets if widgets is not None else MGMT_WIDGETS,
        actions=["tap", "input_submit", "upload", "download"],
        features=["sidebar", "table_double_click", "file_upload",
                  "file_download"],
        device="mgmt",
    )


registry = CapabilityRegistry()