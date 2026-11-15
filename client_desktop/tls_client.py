"""TLS-хелперы для ПК-терминала.

Pinning по fingerprint: клиент хранит PEM сертификата в
config.json и использует его как CA (verify=path). Если
сервер перевыпустил сертификат — при следующем скане QR
fingerprint в QR не совпадёт с сохранённым, TOFU повторится.
"""

import base64
import hashlib
import os
import socket
import ssl


def _certs_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, ".certs")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        return None
    return path


def _url_key(url):
    h = hashlib.sha256((url or "").encode("utf-8")).hexdigest()
    return h[:16]


def cert_file_path(url):
    d = _certs_dir()
    if d is None:
        return None
    return os.path.join(d, f"{_url_key(url)}.pem")


def write_cert_file(url, pem):
    p = cert_file_path(url)
    if not p:
        return None
    try:
        with open(p, "w", encoding="ascii") as f:
            f.write(pem)
        return p
    except Exception:
        return None


def remove_cert_file(url):
    p = cert_file_path(url)
    if p and os.path.isfile(p):
        try:
            os.remove(p)
        except Exception:
            pass


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def fingerprint_of_pem(pem: str) -> str:
    if not pem:
        raise ValueError("empty pem")
    pem_str = pem if isinstance(pem, str) else pem.decode("ascii")
    der = ssl.PEM_cert_to_DER_cert(pem_str)
    return _b64url_nopad(hashlib.sha256(der).digest())


def fetch_peer_cert(host, port, timeout=5):
    """Возвращает PEM сертификата с сервера БЕЗ валидации.

    Используется только при TOFU: сверить sha256 с fp из QR.
    Никакие данные через это соединение не передаются.
    """
    old = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        return ssl.get_server_certificate((host, int(port)))
    finally:
        try:
            socket.setdefaulttimeout(old)
        except Exception:
            pass


def split_host_port(url):
    """https://host:port[/path] → (host, port). port по умолчанию 8765."""
    s = (url or "").strip()
    for scheme in ("https://", "http://"):
        if s.startswith(scheme):
            s = s[len(scheme):]
            break
    s = s.split("/", 1)[0]
    if ":" in s:
        host, p = s.rsplit(":", 1)
        try:
            port = int(p)
        except ValueError:
            port = 8765
    else:
        host, port = s, 8765
    return host, port