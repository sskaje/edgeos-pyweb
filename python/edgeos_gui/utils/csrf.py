import binascii
import logging
import os

import bottle

logger = logging.getLogger("csrf")


def generate_csrf_token():
    """Generate 256-bits hexadecimal CSRF token using os.urandom()."""
    return binascii.b2a_hex(os.urandom(32))


class CSRFError(bottle.HTTPError):
    """Error/Response raised when validation of CSRF token fails."""
    def __init__(self):
        super(CSRFError, self).__init__(403, "Validation of CSRF token failed.")


class CSRFPlugin(object):
    """
    Plugin which applies CSRF protection using Double Submit Cookie method.
    
    CSRF protection is applied only to "unsafe" HTTP methods and can be
    explicitly disabled by settings `csrf_exempt` parameter of a Bottle
    route to `True`. It is also *disabled* for XMLHttpRequests if CSRF
    protection is not forced by setting `csrf_protect` option of route
    to `True`. Optionally the second CSRF token can be extracted from
    query params (instead of from extra header) if `csrf_token_in_query`
    is set to `True`.
    """
    name = "csrf"  # Bottle plugin name
    api = 2  # Bottle plugin API version
    safe_methods = ('GET', 'HEAD', 'OPTIONS', 'TRACE')

    def apply(self, callback, route):
        csrf_exempt = route.config.get("csrf_exempt", False)
        csrf_protect = route.config.get("csrf_protect", False)
        csrf_token_in_query = route.config.get("csrf_token_in_query", False)

        def wrapper(*args, **kwargs):
            # Apply CSRF protection always if csrf_protect is True
            if not csrf_protect:
                is_xhr = bottle.request.is_xhr
                is_safe = bottle.request.method in self.safe_methods
                # Do not apply CSRF protection if method is "safe"
                # or if the protection has been explicitly disabled
                # or if the request is a XMLHttpRequest
                if is_safe or csrf_exempt or is_xhr:
                    return callback(*args, **kwargs)

            csrf_cookie = bottle.request.get_cookie("X-CSRF-TOKEN")
            csrf_token = bottle.request.headers.get("X-CSRF-TOKEN")
            if csrf_token_in_query:
                csrf_token = csrf_token or bottle.request.query.get("X-CSRF-TOKEN")
            if not csrf_token or csrf_cookie != csrf_token:
                logging.error("CSRF token validation failed: %s != %s",
                              csrf_cookie, csrf_token)
                raise CSRFError()
            return callback(*args, **kwargs)
        return wrapper
