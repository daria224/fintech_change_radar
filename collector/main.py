import sys

import db
from radar_core.collect import collect


def main():
    with db.connect() as conn:
        db.init_schema(conn)
        collect(conn, historical="--history" in sys.argv)


if __name__ == "__main__":
    main()
