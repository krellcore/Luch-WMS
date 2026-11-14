from io import BytesIO
from PySide6.QtCore import Qt, QBuffer, QIODevice
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QFont


def make_barcode_pixmap(data, target_width=380, target_height=100):
    if not data:
        return None
    try:
        import barcode
        from barcode.writer import ImageWriter
    except ImportError:
        return None
    try:
        CODE128 = barcode.get_barcode_class("code128")
        buf = BytesIO()
        CODE128(str(data), writer=ImageWriter()).write(buf, options={
            "module_width": 0.25, "module_height": 8.0,
            "write_text": False, "quiet_zone": 3.0,
        })
        pix = QPixmap()
        if not pix.loadFromData(buf.getvalue()):
            return None
        return pix.scaled(target_width, target_height,
                          Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        return None


def make_qr_pixmap(data, size=200):
    if not data:
        return None
    try:
        import qrcode
    except ImportError:
        return None
    try:
        qr = qrcode.QRCode(version=None,
                           error_correction=qrcode.constants.ERROR_CORRECT_M,
                           box_size=10, border=2)
        qr.add_data(str(data))
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        pix = QPixmap()
        if not pix.loadFromData(buf.getvalue()):
            return None
        return pix.scaled(size, size, Qt.KeepAspectRatio,
                          Qt.SmoothTransformation)
    except Exception:
        return None


def make_label_image(title, subtitle, code, width=700, height=380):
    img = QImage(width, height, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    pen = p.pen()
    pen.setColor(QColor("#2c3e50"))
    pen.setWidth(3)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(4, 4, width - 8, height - 8)

    p.setPen(QColor("#e67e22"))
    # Используем дефолтный системный шрифт вместо хардкода "Arial"
    # во избежание проблем с рендерингом кириллицы в headless.
    f = QFont()
    f.setPointSize(26)
    f.setBold(True)
    p.setFont(f)
    p.drawText(0, 20, width, 50, Qt.AlignCenter, title)

    p.setPen(QColor("#2c3e50"))
    f = QFont()
    f.setPointSize(18)
    p.setFont(f)
    p.drawText(0, 80, width, 40, Qt.AlignCenter, subtitle)

    # ШК центрируется по горизонтали независимо от итоговой ширины
    bc = make_barcode_pixmap(code, width - 80, 140)
    if bc:
        bc_x = (width - bc.width()) // 2
        bc_y = 140
        p.drawPixmap(bc_x, bc_y, bc)

    p.setPen(QColor("#2c3e50"))
    f = QFont()
    f.setPointSize(16)
    f.setBold(True)
    p.setFont(f)
    p.drawText(0, height - 50, width, 40, Qt.AlignCenter, code)
    p.end()

    qb = QBuffer()
    qb.open(QIODevice.WriteOnly)
    img.save(qb, "PNG")
    data = bytes(qb.data())
    qb.close()
    return data