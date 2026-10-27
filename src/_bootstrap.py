"""Arranque común: fuerza UTF-8 y parchea SSL para Windows.

Importar este módulo antes que cualquier otro del proyecto:

    import src._bootstrap  # noqa: F401

Resuelve dos problemas exclusivos de Windows:

1. **Encoding.** La consola usa cp1252 por defecto y cualquier emoji en un
   `print` lanza `UnicodeEncodeError`. Forzamos UTF-8 en stdin/stdout/stderr y
   activamos `PYTHONUTF8`.

2. **Certificados.** En entornos corporativos con inspección TLS (Zscaler), el
   bundle de la empresa no está en `certifi`. `common.py` ya apunta al bundle
   del sistema, pero `urllib` lo ignora si el proceso no define `SSL_CERT_FILE`.
   Acá se rellena con el almacén de Windows si el archivo existe.
"""

import io
import os
import sys


def _force_utf8() -> None:
    """Reconfigura los flujos estándar a UTF-8 (idempotente)."""
    os.environ.setdefault("PYTHONUTF8", "1")
    for name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Flujo redirigido a algo que no soporta reconfiguración.
            try:
                setattr(sys, name, io.TextIOWrapper(
                    stream.buffer, encoding="utf-8", errors="replace"
                ))
            except Exception:
                pass


def _windows_ca_bundle() -> None:
    if not sys.platform.startswith("win"):
        return
    if os.environ.get("SSL_CERT_FILE"):
        return
    candidates = [
        r"C:\Program Files\Git\mingw64\etc\ssl\certs\ca-bundle.crt",
        r"C:\Program Files\Git\usr\ssl\certs\ca-bundle.crt",
        os.path.join(sys.prefix, "ssl", "cacert.pem"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            os.environ["SSL_CERT_FILE"] = path
            return


_force_utf8()
_windows_ca_bundle()
