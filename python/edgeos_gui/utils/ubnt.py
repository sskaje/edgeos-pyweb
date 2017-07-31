import json
import os

COUNTERFEIT_FILE = "/etc/Error-A12"
EULA_FILE = "/root.dev/www/eula"
BUILD_ID_FILE = "/var/www/buildid"
DEVICE_MODEL_FILE = "/var/www/device_model"


def is_genuine():
    """Returns True if this is a genuine Ubiquiti device."""
    return not os.path.isfile(COUNTERFEIT_FILE)


def is_eula_pending():
    """Returns True if user has not accepted EULA yet."""
    return not os.path.isfile(EULA_FILE)


def accept_eula():
    """Mark EULA as accepted by "touching" of the EULA file."""
    with open(EULA_FILE, 'a'):
        os.utime(EULA_FILE, None)


def get_build_id():
    """Get build identifier for GUI assets."""
    with open(BUILD_ID_FILE, "r") as f:
        return f.read()


def get_device_model():
    """Get device model."""
    with open(DEVICE_MODEL_FILE, "r") as f:
        return f.read()


def load_device_config(filename, device_model):
    """Load device config from device description JSON file."""
    with open(filename, "r") as f:
        data = json.load(f)
        return data.get(device_model, data.get("unknown", {}))
