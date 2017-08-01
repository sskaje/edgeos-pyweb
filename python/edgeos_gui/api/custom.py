import importlib
import logging
import os

import bottle
import sys

from .. import custom

logger = logging.getLogger("custom_api")


class CustomError(Exception):
    pass


def register_custom(app, prefix):
    """
    Register custom apis

    :param app:
    :param prefix:
    :return:
    """

    try:
        loaded_modules = custom.loaded_modules
    except:
        loaded_modules = []

    module_load_count = 0

    for module_name in loaded_modules:
        try:
            module = importlib.import_module("edgeos_gui.custom." + module_name)

            if hasattr(module, 'register_urls'):
                module.register_urls(app, prefix)
                module_load_count += 1
            else:
                raise CustomError("no method register_urls found")

        except Exception as err:
            logger.error("Error loading custom module '%s': %s", module_name, err)

            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error("Error: %s %s:%d", exc_type, fname, exc_tb.tb_lineno)

    # register template path if at least one custom api registered
    if module_load_count:
        bottle.TEMPLATE_PATH.append(os.path.join(app.config['custom.dir'], "templates"))
