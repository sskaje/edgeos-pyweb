import copy
from datetime import date
import json
import os
from urlparse import urljoin

import bottle
from bottle import HTTPResponse, redirect, request, template

from .api.edge import auth, partial
from .utils import csrf, ubnt, require_acl


def index():
    """
    Index view - show main page to authenticated users and login page to
    unauthenticated.
    """
    session = request.environ['beaker.session']

    app = bottle.default_app()

    # Merge features from config and auth response for JS app config
    # Do not modify the original value
    features = copy.copy(session.get("features", {}))
    features.update(app.config['device.config']['features'])

    context = {
        'error': session.get("error", None),
        'eula': ubnt.is_eula_pending(),
        'custom_logo': "ufiber" if app.config['device.model'] == "UF-OLT" else "",
        'username': session.get("username", None),
        'level': session.get("level", None),
        'authenticated': session.get("authenticated", False),
        'features': json.dumps(features),
        'model': app.config['device.model'],
        'body_class': app.config['device.config']['class'],
        'model_name': app.config['device.config']['name'],
        'ports': app.config['device.config']['features']['ports'],
        'poe': app.config['device.config']['features']['poe'],
        'switch': app.config['device.config']['features'].get("switch", {}),
        'default_config_wizard': app.config['device.config'].get('default_config_wizard',
                                                                 'Wizard/setup/Basic_Setup'),
        'gui_features': app.config['device.config'].get("gui_features", {}),
    }
    if not session.get('authenticated'):
        return template("views/login", **context)

    return template("views/main", **context)


def login():
    """
    Login view - check username and password, require accepting of EULA if it
    has not been accepted yet.
    """
    username = request.POST.get("username")
    password = request.POST.get("password")
    response = auth(username, password)
    success = response.get("success", "0") == "1"

    session = request.environ['beaker.session']
    if success:
        session['error'] = None
        eula_pending = ubnt.is_eula_pending()
        eula_accepted = request.POST.get("accept-eula") == "on"
        if eula_pending and not eula_accepted:
            session['error'] = "Please accept the Terms of Use"
        else:
            if eula_accepted:
                ubnt.accept_eula()
            session.regenerate_id()
            session['authenticated'] = True
            session['ip'] = request.environ.get("REMOTE_ADDR")
            session['username'] = username
            session['level'] = response.get("level")
            session['started'] = response.get("started")
            session['features'] = response.get("platform")
            session['model'] = response.get("platform", {}).get("model")
            # Redirect back to '/' and set session cookie
            res = bottle.response.copy(cls=HTTPResponse)
            res.status = 303
            res.body = ""
            res.set_header("Location", urljoin(request.url, "/"))
            res.set_cookie("X-CSRF-TOKEN", csrf.generate_csrf_token())
            res.set_cookie("PHPSESSID", session.id)  # TODO: PHPSESSID, srsly...
            raise res
    else:
        session['error'] = response.get("error", "Unexpected error during authentication")
    redirect("/")


def logout():
    """Logout view - delete user's session."""
    session = request.environ["beaker.session"]
    if "authenticated" in session:
        session.delete()
    redirect("/")


def cli():
    """CLI view - just render CLI template."""
    return template("views/cli")


def download_file(src_filename, attachment_filename, content_type, unlink=False):
    """
    Return HTTP response containing `src_filename` as attachment with
    name `attachment_filename` and specified `content_type`.
    """
    stats = os.stat(src_filename)
    headers = {
        'Content-Type': content_type,
        'Content-Disposition': 'attachment; filename="%s"' % attachment_filename,
        'Content-Length': stats.st_size
    }

    def read_file_chunks():
        """
        Read file by chunks, optionally unlink it after it has been served.
        """
        try:
            with open(src_filename, "rb") as f:
                while True:
                    data = f.read(16 * 1024)  # 16 kB chunks
                    if not data:
                        break
                    yield data
        finally:
            if unlink:
                os.unlink(src_filename)

    return HTTPResponse(read_file_chunks(), **headers)


@require_acl
def config():
    """
    Config view - serves the config tarball after it has been requested. Prior
    call of `api.edge.config_save` is required, as it creates the backup file
    and sets the `config_backup_file` session variable.
    """
    session = request.environ['beaker.session']
    config_backup_file = session.get('config_backup_file')
    if not config_backup_file:
        raise HTTPResponse("Config backup not found", status=404)

    response = partial(struct='{"system": null}')
    hostname = response.get("GET", {}).get("system", {}).get("host-name", "ubnt")
    filename = "edgeos_%s_%s.tar.gz" % (hostname, date.today().strftime("%Y%m%d"))

    return download_file(config_backup_file, filename, "application/gzip",
                         unlink=True)


@require_acl
def support_file():
    """
    Support file view - returns tarball with debug logs previously created by
    calling `api.edge.get_support_file` (which create a session variable,
    mechanism is same as for `config` view.
    """
    session = request.environ['beaker.session']
    support_filename = session.get('support_file')
    if not support_filename:
        raise HTTPResponse("Support file not found", status=404)

    response = partial(struct='{"system": null}')
    hostname = response.get("GET", {}).get("system", {}).get("host-name", "ubnt")
    filename = "edgeos-support_file-%s_%s.tar.gz"\
               % (hostname, date.today().strftime("%Y%m%d"))

    return download_file(support_filename, filename, "application/gzip",
                         unlink=True)
