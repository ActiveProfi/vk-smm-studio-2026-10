"""Точка входа веб-приложения."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from webapp import create_app

app = create_app()

if __name__ == "__main__":
    # host=0.0.0.0 — доступ с других устройств в сети; для локальной работы достаточно 127.0.0.1
    # use_reloader=False: авто-перезагрузчик убивает фоновые потоки генерации визуала
    # (задачи зависают навсегда со статусом running).
    app.run(host="127.0.0.1", port=5050, debug=True, use_reloader=False)
