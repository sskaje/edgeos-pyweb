import argparse
import json
import logging
import os

from beaker.middleware import SessionMiddleware
import bottle

from .api import edge, wizard, custom
from . import views
from .utils import ubnt, csrf,\
    NamedFileFieldStorage, ErrorMiddleware,\
    api_url, absolute_url

logger = logging.getLogger("edgeos_gui")
BASE_DIR = os.path.dirname(__file__)


def init_app(debug=False, uncompressed_assets=False):
    """Initialize GUI's main app.

    Steps performed:
        * apply monkey-patches required for EdgeOS
        * read config from configuration files and other sources
          (device model, build id...)
        * set template defaults
        * register views
        * apply hooks
        * apply error handling middleware
        * apply session middleware
    ."""
    monkey_patch_beaker_container_serializer()
    monkey_patch_beaker_storage_depth()
    monkey_patch_cgi_fieldstorage()
    monkey_patch_bottle_tempfile()

    app = bottle.app()
    app.install(csrf.CSRFPlugin())

    bottle.TEMPLATE_PATH.append(os.path.join(BASE_DIR, "templates"))

    device_model = ubnt.get_device_model()
    device_config = ubnt.load_device_config(os.path.join(BASE_DIR, "data", "devices.json"),
                                            device_model)

    app.config['device.model'] = device_model
    app.config['device.config'] = device_config
    app.config['build_id'] = ubnt.get_build_id()
    app.config['debug'] = debug
    app.config['custom.dir'] = BASE_DIR + "/custom"

    defaults = {
        'compressed': not uncompressed_assets,
        'debug': app.config.get('debug'),
        'build': app.config.get('build_id'),
        'genuine': ubnt.is_genuine(),
        'device_model': device_model
    }
    bottle.SimpleTemplate.defaults.update(defaults)

    # Util functions for templates
    bottle.SimpleTemplate.defaults['api_url'] = api_url
    bottle.SimpleTemplate.defaults['absolute_url'] = absolute_url

    # HTML views
    app.post('/', callback=views.login, name='login', csrf_exempt=True)
    app.get('/', callback=views.index, name='index')
    app.get('/logout', callback=views.logout, name='logout')
    app.get('/cli/', callback=views.cli, name='cli')
    app.get('/files/config/', callback=views.config, name='config')
    app.get('/files/support-file/', callback=views.support_file, name='support_file')

    # API views
    api_prefix = "/api"
    edge.register_urls(app, api_prefix + "/edge")
    wizard.register_urls(app, api_prefix + "/wizard")

    custom.register_custom(app, "/custom")

    # Add bottle request hooks
    app.add_hook('after_request', apply_http_hardening_headers)

    # Use ErrorMiddleware to catch and report errors
    app.catchall = False
    app = ErrorMiddleware(app)

    session_options = {
        'session.type': 'file',
        'session.data_dir': '/var/run/beaker',
        'session.cookie_expires': True,
        'session.timeout': 1440,
        'session.auto': True,
        'session.httponly': True,
        'session.secure': True,
    }
    app = SessionMiddleware(app, session_options)

    return app


def apply_http_hardening_headers():
    # Clickjacking protection
    # can't use DENY - iframes are used in JS file uploader
    bottle.response.headers['X-Frame-Options'] = "SAMEORIGIN"
    # Disable content type sniffing
    bottle.response.headers['X-Content-Type-Options'] = "nosniff"
    # Enforce browsers' XSS filtering
    bottle.response.headers['X-XSS-Protection'] = "1; mode=block"


def monkey_patch_beaker_storage_depth():
    """
    Because ses-mon.cpp in ubnt-util must be notified about changes in sessions
    and it is hard to monitor the nested directory structure of the standard
    Beaker session layout, this method monkey-patches the encoded_path method
    to have default depth of 1, i.e. the session files will be directly in
    file_dir or lock_dir.
    """
    import beaker.util
    import functools
    beaker.util.encoded_path = functools.partial(beaker.util.encoded_path, depth=1)


def monkey_patch_beaker_container_serializer():
    """
    It is not possible to change the serializer which will be used in Beaker for
    serialization of sessions. Because legacy ses-mon.cpp is able to parse only
    PHP serialization format and it is not able to read Pickle, it is easiest
    to use monkey-patching to replace pickle module in runtime by phpserialize
    module.
    """
    import beaker.container
    import phpserialize
    beaker.container.cPickle = beaker.container.pickle = phpserialize


def monkey_patch_cgi_fieldstorage():
    """
    In order to be able to upload large files (i.e. device upgrade files with
    size ~100MiB) on devices with small tmpfs, we must apply a few workarounds
    to the standard file upload process. Normally when a file is uploaded,
    bottle create a temporary file containing stdin from the WSGI request.
    Then an instance of cgi.FieldStorage is created to extract multipart data
    from the tempfile. And finally, the file is copied when save() method on
    FileUpload (pointing to FieldStorage fileobj) is called. This means that
    when we upload 100 MiB file, we need around 300 MiB of space in tmpfs (if
    we wan't to save the file to tmpfs).
    """
    import cgi
    cgi.FieldStorage = NamedFileFieldStorage


def monkey_patch_bottle_tempfile():
    """
    This patch (along with monkey_patch_cgi_fieldstorage) is needed to make
    uploads of large files possible on devices with small tmpfs. See
    docstring of monkey_patch_cgi_fieldstorage for details.
    """
    from tempfile import TemporaryFile, NamedTemporaryFile

    def TemporaryFilePatched(*args, **kwargs):
        from bottle import default_app
        app = default_app()
        if app.config.get("apply_upload_patches", False):
            logger.debug("Applying upload patch - calling pre-upgrade-purge")
            purge_result = edge.operation("pre-upgrade-purge")
            if purge_result.get("OPERATION", {}).get("success", "0") != "1":
                logger.error("Failed to purge occupied space before upgrade: %s",
                             json.dumps(purge_result))
            logger.debug("Applying upload patches to bottle.TemporaryFile.")
            kwargs['dir'] = "/var/tmp"
            named_tempfile = NamedTemporaryFile(*args, **kwargs)
            return named_tempfile
        return TemporaryFile(*args, **kwargs)

    bottle.TemporaryFile = TemporaryFilePatched


def main():
    """
    Parse arguments, prepare main app and spin off a wsgiref or flup server.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("-H", "--host", default="0.0.0.0",
                        help="server hostname - applies only to wsgiref server")
    parser.add_argument("-p", "--port", type=int, default=8000,
                        help="server port - applies only to wsgiref server")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="enable debug mode")
    parser.add_argument("-u", "--uncompressed-assets", action="store_true",
                        help="use paths to uncompressed assets in templates")
    parser.add_argument("-s", "--server", default="flup",
                        help="server adapter to use")

    args = parser.parse_args()

    gui_app = init_app(args.debug, args.uncompressed_assets)

    # Drop log verbosity to WARNING if debugging is disabled
    logging.getLogger()\
        .setLevel(level=logging.DEBUG if args.debug else logging.WARNING)

    logger.debug("Starting with args: %s", args)

    if args.server == "wsgiref":
        bottle.run(app=gui_app, host=args.host, port=args.port, debug=args.debug)
    elif args.server == "flup":
        bottle.run(app=gui_app, server="flup", bindAddress=None, debug=args.debug)


if __name__ == "__main__":
    main()
