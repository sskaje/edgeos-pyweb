#!/usr/bin/env python
import logging
import os


LOG_DIR = "/var/www/logs"
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "gui.log"),
    level=logging.DEBUG
)


if __name__ == "__main__":
    from edgeos_gui.__main__ import main
    main()
