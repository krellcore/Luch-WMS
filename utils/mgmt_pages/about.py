"""«О программе» — серверная сборка view."""

import os
import base64
import platform

from mgmt_protocol import (
    mgmt_page, heading, text, card, spacer, group,
    mgmt_html, mgmt_image, make_mgmt_document, mgmt_header
)
from mgmt_view_builder import build_sidebar
from i18n import tr, current_locale


APP_VERSION = "1.1.0"


_TABLE_STYLE = (
    'width="100%" cellpadding="20" cellspacing="0" '
    'style="background-color: white; border: 1px solid #dcdcdc; '
    'border-radius: 6px;"'
)

_TITLE_STYLE = (
    'style="color: #1e3a5f; margin-top: 0;"'
)

_P_STYLE = 'style="color: #2c3e50;"'


_LICENSE_HTML_RU = f"""
<table {_TABLE_STYLE}>
<tr><td>
<h2 {_TITLE_STYLE}>Лицензионное соглашение (MIT License)</h2>
<p {_P_STYLE}><b>Copyright (c) 2026 Krellcore</b></p>

<p {_P_STYLE}>Данное программное обеспечение («Луч», LUCH WMS) предоставляется бесплатно для распространения, использования, изменения и включения в другие проекты.</p>

<p {_P_STYLE}>Настоящим разрешается любым лицам, получающим копию данного программного обеспечения и сопутствующих файлов документации, свободно использовать Программное обеспечение без ограничений, включая, но не ограничиваясь, правами на использование, копирование, изменение, слияние, публикацию, распространение, сублицензирование и/или продажу копий Программного обеспечения, при соблюдении следующих условий:</p>

<p {_P_STYLE}><b>Условие указания авторства:</b> Вышеуказанное уведомление об авторских правах (Krellcore) и данное разрешение должны быть включены во все копии или существенные части Программного обеспечения.</p>

<p {_P_STYLE}><b>Отказ от ответственности:</b> ПРОГРАММНОЕ ОБЕСПЕЧЕНИЕ ПРЕДОСТАВЛЯЕТСЯ «КАК ЕСТЬ», БЕЗ КАКИХ-ЛИБО ГАРАНТИЙ, ЯВНЫХ ИЛИ ПОДРАЗУМЕВАЕМЫХ. АВТОР НЕ НЕСЕТ ОТВЕТСТВЕННОСТИ ЗА ЛЮБОЙ УЩЕРБ, ВОЗНИКШИЙ В РЕЗУЛЬТАТЕ ИСПОЛЬЗОВАНИЯ ДАННОГО ПРОГРАММНОГО ОБЕСПЕЧЕНИЯ.</p>
</td></tr>
</table>
"""


_LICENSE_HTML_EN = f"""
<table {_TABLE_STYLE}>
<tr><td>
<h2 {_TITLE_STYLE}>License Agreement (MIT License)</h2>
<p {_P_STYLE}><b>Copyright (c) 2026 Krellcore</b></p>

<p {_P_STYLE}>This software («Luch», LUCH WMS) is provided free of charge for distribution, use, modification, and inclusion in other projects.</p>

<p {_P_STYLE}>Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, subject to the following conditions:</p>

<p {_P_STYLE}><b>Attribution condition:</b> The above copyright notice (Krellcore) and this permission notice shall be included in all copies or substantial portions of the Software.</p>

<p {_P_STYLE}><b>Disclaimer:</b> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. THE AUTHOR SHALL NOT BE LIABLE FOR ANY DAMAGES ARISING FROM THE USE OF THIS SOFTWARE.</p>
</td></tr>
</table>
"""


def _license_html():
    if current_locale() == "en":
        return _LICENSE_HTML_EN
    return _LICENSE_HTML_RU


def _logo_src():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    path = os.path.join(root, "logo_horizontal.png")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return "data:image/png;base64," + \
            base64.b64encode(raw).decode("ascii")
    except Exception:
        return None


def build_view(login, role, context):
    title = tr("about.title", "О программе")
    children = [mgmt_header(title)]

    logo = _logo_src()
    pyver = platform.python_version()

    info_children = [
        text(tr("about.product",
                "<b>Луч (LUCH WMS)</b> — "
                "система управления складом.")),
        text(tr("about.version",
                "Версия: {version}", version=APP_VERSION)),
        text(tr("about.author_label",
                "<b>Автор и правообладатель:</b> {author}",
                author=tr("about.author", "Krellcore"))),
        text(tr("about.environment",
                "Среда: Python {pyver}, PySide6",
                pyver=pyver)),
    ]

    if logo:
        centered_info = group([
            group([], orientation="vertical", stretch=True),
            group(info_children, orientation="vertical", spacing=4),
            group([], orientation="vertical", stretch=True),
        ], orientation="vertical", stretch=True)

        header = group([
            mgmt_image(logo, width=300),
            centered_info,
        ], orientation="horizontal", spacing=20)
    else:
        header = group(info_children, orientation="vertical", spacing=4)
    children.append(header)

    children.append(spacer(20))
    children.append(text(
        tr("about.license_section",
           "Лицензия и правовая информация:"),
        bold=True, size=12))
    children.append(spacer(10))

    children.append(mgmt_html(_license_html(), height=400))

    page = mgmt_page("about", title, children)
    return make_mgmt_document(
        page, sidebar=build_sidebar(role), extra={"role": role})


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    return {"ok": False,
            "error": tr("about.static_page",
                        "«О программе» — статическая страница.")}