import functools
import json

from bottle import request

from .. import sysd


def dispatch_request(**operations):
    """
    Check ACL and send a request to the sysd socket.
    """
    session = request.environ['beaker.session']
    remove_sensitive = session.get('level') != "admin"
    return sysd.request(operations, session.id,
                        remove_sensitive=remove_sensitive)


def get_post_content():
    """
    Get POST content from the request.

    Returns parsed JSON if the frontend posted raw JSON data in the POST body,
    request.POST (FormsDict) otherwise.
    """
    body = request.body.read(1)
    if body and body[0] == "{":
        # Probably a raw JSON for the socket
        try:
            return json.loads(request.body.read())
        except ValueError:
            pass  # just fall through
    return request.POST


def api_command(original_func=None):
    """
    Decorator for easier usage of dispatch_request. To dispatch data to sysd
    socket, simply create function that returns data to be dispatched as
    a dict and decorate it with @api_command.
    """
    def decorate(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return dispatch_request(**func(*args, **kwargs))
        return wrapper

    return decorate(original_func)


class APIError(ValueError):
    """
    Exception raised when invalid API operation has been performed.
    """
    def __repr__(self):
        """Return only message for nicer JSON errors."""
        return self.message if self.message else APIError.__repr__(self)
