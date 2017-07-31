from collections import OrderedDict
import json
import socket
import logging

from .utils import remove_dict_key_recursive, replace_dict_values_recursive

logger = logging.getLogger("sysd")


onu_nodes = ('onu-list', 'onu-policies', 'onu-profiles')

# Filtering of sensitive params for non-admin users
SENSITIVE_PARAMS = ('passphrase', 'password', 'pre-shared-secret', 'key')
SENSITIVE_PARAM_PLACEHOLDER = '*********'


class SysdSocket(object):
    def __init__(self, eom="\n"):
        self.eom = eom
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.setblocking(True)
        self.connected = False

    def connect(self):
        if not self.connected:
            self._socket.connect("/tmp/ubnt.socket.sysd")
            self.connected = True

    def close(self):
        self._socket.close()
        self.connected = False

    def write(self, data, send_eom=True):
        logger.debug("writing to socket: %s%s",
                     data, self.eom if send_eom else "")
        self._socket.send(data)
        if send_eom:
            self._socket.send(self.eom)

    def read(self):
        result = ""
        expected_length = None

        while True:
            buf = self._socket.recv(2048)
            if expected_length is None:
                expected_length, buf = buf.split("\n", 1)
                expected_length = int(expected_length)
            result += buf
            logger.debug("received from socket: %s", buf)

            if len(result) >= expected_length:
                break

        return result


def data_preprocess(data):
    data = replace_dict_values_recursive(data, None, "''")
    # __FORCE_ASSOC has some strange meaning in the frontend and it should be
    # filtered out of the data sent to the socket. This quirk thus has to be
    # implemented also here, because otherwise some edit operations would fail.
    # This hack can be removed if we're able to find out what's the meaning of
    # this __FORCE_ASSOC and what could it be replaced with.
    remove_dict_key_recursive(data, "__FORCE_ASSOC")

    for op in ('GET', 'SET', 'DELETE'):
        if op in data.keys():
            # Look if operation contains nodes for ONU configuration
            for node in onu_nodes:
                if node in data[op]:
                    # Move them to *_ONUCFG operation
                    onu_op = op + '_ONUCFG'
                    data.setdefault(onu_op, {})
                    data[onu_op][node] = data[op][node]
                    del data[op][node]

                    # Empty operations can cause errors, if we emptied the
                    # operation array, remove it and move to the next operation
                    if not data[op]:
                        del data[op]
                        break
    return data


def remove_sensitive_params(data):
    """Remove sensitive params from `data`."""
    for key, value in data.items():
        if any(x in key for x in SENSITIVE_PARAMS):
            data[key] = None \
                if isinstance(value, dict) \
                else SENSITIVE_PARAM_PLACEHOLDER
        elif isinstance(value, dict):
            remove_sensitive_params(value)

    return data


def data_postprocess(data, remove_sensitive):
    data = replace_dict_values_recursive(data, "''", None)

    if remove_sensitive:
        data = remove_sensitive_params(data)

    for op in ('GET', 'SET', 'DELETE'):
        onu_op = op + '_ONUCFG'
        if onu_op in data.keys():
            data.setdefault(op, {})
            data[op].update(data[onu_op])
            del data[onu_op]
    return data


def request(data, session_id=None, remove_sensitive=False):
    sock = SysdSocket()
    sock.connect()
    if session_id:
        data['SESSION_ID'] = session_id

    content = json.dumps(data_preprocess(data))
    sock.write(str(len(content)) + '\n' + content, False)
    response = sock.read()
    sock.close()

    if response:
        response = data_postprocess(
            json.loads(response, object_pairs_hook=OrderedDict),
            remove_sensitive=remove_sensitive
        )
        response.setdefault("success", True)
        return response
    else:
        return dict(success=False)
