"""Ponto de entrada do DDoSLab."""

from __future__ import annotations

import logging
import sys

from ddoslab import create_app

app = create_app()


if __name__ == "__main__":
    # Garante acentos corretos também no terminal do Windows.
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            try:
                fluxo.reconfigure(encoding="utf-8")
            except OSError:
                pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    print("DDoSLab disponível em http://127.0.0.1:5000")
    print("Pressione Ctrl+C para encerrar.")
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True,
        use_reloader=False,
    )
