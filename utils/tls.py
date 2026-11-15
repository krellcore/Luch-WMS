"""TLS/HTTPS для «Луча».

Схема: самоподписанный сертификат на склад + pinning через
QR-код (`WMS://ip:port#fp=<base64url(sha256(der))>`).

Сертификат лежит в `warehouses/<name>/tls/`:
    cert.pem         — публичный сертификат
    key.pem          — приватный ключ (0600)
    fingerprint.txt  — base64url(sha256(der)) для QR

Клиент при первом скане QR:
  1. Берёт fp из фрагмента `#fp=...`.
  2. Забирает сертификат сервера через `ssl.get_server_certificate`.
  3. Сверяет sha256(der) с fp. Если не совпало — отказ.
  4. Сохраняет cert.pem локально и использует его как CA
     для всех последующих запросов.
"""

import base64
import datetime
import hashlib
import os
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


CERT_VALID_DAYS = 3650   # 10 лет
MIN_TLS_VERSION = ssl.TLSVersion.TLSv1_2


def tls_dir(warehouse_dir):
    return os.path.join(warehouse_dir, "tls")


def cert_path(warehouse_dir):
    return os.path.join(tls_dir(warehouse_dir), "cert.pem")


def key_path(warehouse_dir):
    return os.path.join(tls_dir(warehouse_dir), "key.pem")


def fp_path(warehouse_dir):
    return os.path.join(tls_dir(warehouse_dir), "fingerprint.txt")


def has_cert(warehouse_dir):
    if not warehouse_dir:
        return False
    return (os.path.isfile(cert_path(warehouse_dir))
            and os.path.isfile(key_path(warehouse_dir)))


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def fingerprint_of_pem(pem: str) -> str:
    """base64url(sha256(der)) — то, что попадает в `#fp=...`."""
    if not pem:
        raise ValueError("empty pem")
    pem_str = pem if isinstance(pem, str) else pem.decode("ascii")
    der = ssl.PEM_cert_to_DER_cert(pem_str)
    return _b64url_nopad(hashlib.sha256(der).digest())


def cert_fingerprint(warehouse_dir):
    """Читает fp из файла или считает из cert.pem.

    Возвращает base64url(sha256(der)) или None.
    """
    p = cert_path(warehouse_dir)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "rb") as f:
            pem = f.read()
        return fingerprint_of_pem(pem)
    except Exception:
        return None


def _collect_local_ips():
    """Все текущие IPv4 сервера (без 127.0.0.1 — он добавляется
    отдельно, без link-local и 0.*)."""
    ips = set()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        try:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass
    return sorted(
        ip for ip in ips
        if ip and not ip.startswith("169.254.")
        and not ip.startswith("0.")
        and ip != "127.0.0.1"
    )


def generate_cert(warehouse_dir, extra_ips=None):
    """Генерирует самоподписанный сертификат на 10 лет.

    SAN: localhost, 127.0.0.1, все текущие IPv4 сервера
    (+ extra_ips, если переданы). После смены IP сервера
    сертификат нужно перевыпустить — иначе hostname-check
    на клиенте не пройдёт.
    """
    os.makedirs(tls_dir(warehouse_dir), exist_ok=True)

    ips = ["127.0.0.1"] + _collect_local_ips()
    if extra_ips:
        ips.extend(extra_ips)
    # уникализировать, сохранив порядок
    seen = set()
    ips = [ip for ip in ips if ip and not (ip in seen or seen.add(ip))]

    san_list = [x509.DNSName("localhost")]
    for ip in ips:
        try:
            import ipaddress
            san_list.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except Exception:
            pass

    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "luch.local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Luch WMS"),
    ])

    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(
            now + datetime.timedelta(days=CERT_VALID_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False)
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True)
        .sign(key, hashes.SHA256())
    )

    with open(key_path(warehouse_dir), "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    try:
        os.chmod(key_path(warehouse_dir), 0o600)
    except Exception:
        pass

    with open(cert_path(warehouse_dir), "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    fp = cert_fingerprint(warehouse_dir)
    with open(fp_path(warehouse_dir), "w", encoding="utf-8") as f:
        f.write(fp or "")

    return fp


def make_server_context(warehouse_dir):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(
        certfile=cert_path(warehouse_dir),
        keyfile=key_path(warehouse_dir),
    )
    try:
        ctx.minimum_version = MIN_TLS_VERSION
    except Exception:
        pass
    return ctx


def make_client_context(cert_file):
    """Контекст для клиента: доверяет ТОЛЬКО указанному
    сертификату (не системным CA). Это и есть pinning.

    Hostname-check включён. SAN сертификата должен содержать
    IP/hostname, к которому идёт подключение.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cafile=cert_file)
    try:
        ctx.minimum_version = MIN_TLS_VERSION
    except Exception:
        pass
    return ctx


def fetch_peer_cert(host, port, timeout=5):
    """Возвращает PEM-сертификат с сервера БЕЗ валидации.

    Используется только для TOFU: клиент сверяет
    fingerprint_of_pem(этот_pem) с fp из QR. Никакие
    данные через это соединение не передаются.
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