"""Optional browser-test server with an isolated, disposable account database."""

import os
import sys
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        # Browser diagnostics should not retain submitted identity/return URLs.
        pass


def main():
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    os.environ["DJANGO_ENV"] = "development"
    os.environ["DJANGO_DEBUG"] = "true"
    os.environ["DJANGO_ALLOWED_HOSTS"] = "127.0.0.1"

    import django
    from django.conf import settings

    settings.DATABASES = {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": Path(sys.argv[1])}
    }
    settings.INTRINIO_API_KEY = ""
    django.setup()

    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application

    call_command("migrate", interactive=False, verbosity=0)
    application = StaticFilesHandler(get_wsgi_application())
    with make_server("127.0.0.1", 0, application, handler_class=QuietHandler) as server:
        print(server.server_port, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
