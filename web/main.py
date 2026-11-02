"""The separate web service reuses the same event feed."""

import os
from http.server import ThreadingHTTPServer

import db
from bot.main import Handler


def main():
    with db.connect() as conn:
        db.init_schema(conn)
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
