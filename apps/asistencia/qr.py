"""
Generación de QR como SVG inline con segno (pure-python, sin dependencias).
"""
import io

import segno


def svg_qr(data: str, *, scale: int = 6, border: int = 2) -> str:
    """
    Devuelve el QR de `data` como string SVG listo para embeber en el HTML.

    `data` es típicamente la URL absoluta del endpoint de marcado de asistencia.
    """
    qr = segno.make(data, error="m")
    buff = io.BytesIO()
    qr.save(buff, kind="svg", scale=scale, border=4, xmldecl=False, svgns=True)
    return buff.getvalue().decode("utf-8")
