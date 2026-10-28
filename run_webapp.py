"""Точка входа веб-приложения."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from webapp import create_app

app = create_app()

if __name__ == "__main__":
    import os

    # Отладчик Flask по умолчанию выключен. Для локальной отладки: WEBAPP_DEBUG=1
    # use_reloader=False: авто-перезагрузчик убивает фоновые потоки генерации визуала.
    debug = (os.environ.get("WEBAPP_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on"}
    app.run(host="127.0.0.1", port=5050, debug=debug, use_reloader=False)
