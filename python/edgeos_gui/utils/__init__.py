from cgi import FieldStorage
import functools
import json
import logging
import tempfile
from traceback import format_exc

import bottle
from bottle import _e, default_app, request, tob


logger = logging.getLogger("utils")


class NamedFileFieldStorage(FieldStorage):
    """
    Field storage which uses NamedTemporaryFile if application's config
    has "apply_upload_patches" option enabled. Also performs few more
    quirks to workaround problems with uploading on devices with small tmpfs.
    """
    def __init__(self, *args, **kwargs):
        app = default_app()
        self.apply_patches = app.config.get('apply_upload_patches', False)
        FieldStorage.__init__(self, *args, **kwargs)

    def __del__(self):
        if not self.apply_patches:
            return
        # Close file so it can be unlinked
        try:
            self.file.close()
        except AttributeError:
            pass

    def make_file(self, binary=None):
        """
        Create file for writing. If Bottle app's apply_upload_patches
        is enabled, it creates a named temporary file with delete flag disabled.
        """
        if not self.apply_patches:
            return FieldStorage.make_file(self, binary)
        logger.debug("NamedFileFieldStorage - applying upload patch.")
        return tempfile.NamedTemporaryFile("w+b", delete=False)


class ErrorMiddleware(object):
    """
    Middleware which returns caught exceptions as JSON with
    {"success": false, "errors": ["exception_repr"]}
    if the request was a XHR. Otherwise renders the error using
    the standard bottle error template.
    
    The exception is logged using Python `logging`.
    """
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        try:
            return self.app(environ, start_response)
        except Exception:
            logging\
                .getLogger("error_middleware")\
                .exception("Uncaught exception during request")
            environ['wsgi.errors'].write(format_exc())
            is_xhr = environ.get('HTTP_X_REQUESTED_WITH', '').lower() == "xmlhttprequest"
            is_qquploader = environ \
                .get('bottle.request.files', {}) \
                .get('qqfile') is not None
            if is_xhr or is_qquploader:
                # Return JSON with list of errors to XHR
                headers = [('Content-Type', 'application/json')]
                start_response('500 INTERNAL SERVER ERROR', headers)
                return [tob(json.dumps({'success': False,
                                       'errors': [repr(_e())]}))]

            # Use nice bottle style formatting for normal request
            headers = [('Content-Type', 'text/html; charset=UTF-8')]
            start_response('500 INTERNAL SERVER ERROR', headers)
            return [tob(bottle.template(
                bottle.ERROR_PAGE_TEMPLATE,
                e=bottle.HTTPError(500, "Internal Server Error", _e(), format_exc())
            ))]


def dict_map_recursive(func, dictionary):
    """
    Method for recursively applying `func` to all key/value pairs of the
    `dictionary`. `func` is supposed to change the values of the dictionary
    on some condition.

    `func` takes three parameters:
      - `key` - name of the currently examined key
      - `value` - value of the current key
      - `dictionary` - dictionary at the current depth

    Modifies the dictionary in-place, without creating a copy, returns
    the modified instance.
    """
    for key, value in dictionary.items():
        if isinstance(value, dict):
            dict_map_recursive(func, value)
        else:
            func(key, value, dictionary)
    return dictionary


def replace_dict_values_recursive(dictionary, old, new):
    """
    Walk through a dictionary and replace all occurrences of `old` value by
    the `new` value.
    
    Does not create a new copy of dictionary, the first argument of the
    function is mutated.
    """
    def func(key, value, current_dictionary):
        if value == old:
            current_dictionary[key] = new

    return dict_map_recursive(func, dictionary)


def remove_dict_key_recursive(dictionary, key):
    """
    Walk through a dictionary and remove all items with key of value `key`.

    Does not create a new copy of dictionary, the first argument of the
    function is mutated.
    """
    def func(current_key, _, current_dictionary):
        if current_key == key:
            del current_dictionary[current_key]

    return dict_map_recursive(func, dictionary)


def get_parent_structure(dictionary, context=None):
    """
    Get "parent structure" of a dictionary.
    
    Structure of the resulting dictionary is same as of the original one but
    only those key-value pairs are kept that have a dictionary instance as
    value.
    """
    context = context or dictionary
    res = {}
    for k, v in context.iteritems():
        if isinstance(v, dict):
            if v:
                res[k] = get_parent_structure(dictionary, context[k])
            else:
                # Do not recurse into empty dict
                res[k] = v
    return res


def check_acl(authenticated_only=True, admin_only=True):
    """
    Return True if user identified by the current session has rights to
    perform an action restricted to authenticated users (if authenticated_only
    is True) or to admin users only (if admin_only is True).
    """
    session = request.environ['beaker.session']
    authenticated = session.get("authenticated", False)
    user_level = session.get("level", "operator")

    if callable(admin_only):
        admin_only = admin_only(session)

    if (authenticated_only and not authenticated) or (admin_only and not user_level == "admin"):
        return False

    return True


def require_acl(original_func=None, authenticated_only=True, admin_only=True):
    """
    Decorator for views which require authentication or admin rights, 
    uses check_acl() to check the rights.
    
    Raises HTTP 403 if authentication fails.
    """
    def decorate(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not check_acl(authenticated_only, admin_only):
                if admin_only:
                    msg = "Only administrator can perform this action."
                else:
                    msg = "You must be authenticated to perform this action."
                if bottle.request.is_xhr:
                    msg = json.dumps({'success': False,
                                      'errors': [msg]})
                raise bottle.HTTPError(403, msg)
            return func(*args, **kwargs)
        return wrapper

    if original_func:
        return decorate(original_func)

    return decorate


def absolute_url(path, scheme=None):
    """
    Return absolute URL with scheme and netloc.

    If scheme is specified, it is replaced in the reconstructed URL.
    """
    parts = bottle.request.urlparts
    scheme = scheme or parts.scheme
    url = scheme + '://' + parts.hostname
    if parts.port:
        url += ':' + str(parts.port)
    return url + path


def api_url(path):
    """Get absolute URL for an API endpoint."""
    return absolute_url("/api") + path
