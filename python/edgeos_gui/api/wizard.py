from glob import glob
import json
import tempfile
import os
import re
import shutil
import tarfile

from bottle import request

from . import APIError
from ..utils import require_acl

WIZARD_FILES = ('validator.json', 'wizard-run', 'wizard.html')
WIZARD_PATH_SETUP = "/var/www/wizard/setup"
WIZARD_PATH_FEATURE = "/var/www/wizard/feature"
WIZARD_BACKUP_FEATURE = "/config/wizard/feature"


def register_urls(app, prefix):
    # "remove" must be registered before generic get_wizard route
    app.get(prefix + "/remove/<key>.json", callback=remove)
    app.get(prefix + "/all.json", callback=all_)
    app.post(prefix + "/upload.json", callback=upload,
             csrf_exempt=True)  # ignore for file uploads
    app.post(prefix + "/create.json", callback=create,
             csrf_exempt=True)  # won't have any side-effects, file upload is needed
    app.get(prefix + "/<type_>/<key>.json", callback=get_wizard)


def create_wizard_dict(type_, item, custom=False):
    """Create a dictionary with info about a wizard."""
    return {
        'id': "%s-%s" % (type_, item),
        'key': item,
        'name': item.replace("_", " "),
        'type': type_,
        'custom': custom,
    }


def subdirectory_names(directory):
    """
    Iterate directory and yield names of its subdirectories,
    including hidden directories.
    """
    dir_paths = glob(directory.rstrip("/") + "/*/")
    # Also include hidden directories
    dir_paths.extend(glob(directory.rstrip("/") + "/.*/"))
    for path in dir_paths:
        yield os.path.basename(os.path.normpath(path))


def get_wizard_list(types):
    """
    Get list of dictionaries with wizard info for wizard types specified in
    `types` argument.
    
    Feature wizards in the "main" path are preferred to wizards in "backup"
    path. 
    """
    result = []
    for type_ in types:
        if type_ == "setup":
            for item in subdirectory_names(WIZARD_PATH_SETUP):
                result.append(create_wizard_dict(type_, item))
        elif type_ == "feature":
            existing = set()
            # Add feature wizards from main path
            for item in subdirectory_names(WIZARD_PATH_FEATURE):
                result.append(create_wizard_dict(type_, item))
                existing.add(item)
            # Add feature wizards from backup path
            # only if they've not been in main path
            for item in subdirectory_names(WIZARD_BACKUP_FEATURE):
                if item not in existing:
                    result.append(create_wizard_dict(type_, item, custom=True))
        else:
            raise APIError("Invalid wizard type.")
    return result


def get_wizard_data(type_, wizard):
    """
    Get wizard data - i.e. dictionary containing the HTML content
    and validator for the specified wizard.
    """
    if type_ == "setup":
        path = os.path.join(WIZARD_PATH_SETUP, wizard)
        if not os.path.isdir(path):
            raise APIError("Requested wizard does not exist.")
    elif type_ == "feature":
        # Check main path first, fall back to backup path
        path = os.path.join(WIZARD_PATH_FEATURE, wizard)
        if not os.path.isdir(path):
            path = os.path.join(WIZARD_BACKUP_FEATURE, wizard)
            if not os.path.isdir(path):
                raise APIError("Requested wizard does not exist.")
    else:
        raise APIError("Invalid wizard type.")

    wizard_file = os.path.join(path, "wizard.html")
    if not os.path.isfile(wizard_file):
        raise APIError("Wizard file does not exist.")

    with open(wizard_file, "r") as f:
        html = f.read()

    # Read validator JSON if it exists
    validator_file = os.path.join(path, "validator.json")
    validator = None
    if os.path.isfile(validator_file):
        with open(validator_file, "r") as f:
            validator = json.load(f)

    return {
        'html': html,
        'validator': validator,
    }


def move_wizard_files(src_dir, dest_dir):
    """Move wizard files from src_dir to dest_dir and adjust file mode."""
    os.mkdir(dest_dir, 0o775)
    for filename in WIZARD_FILES:
        dest_file = os.path.join(dest_dir, filename)
        shutil.move(os.path.join(src_dir, filename), dest_file)
        if filename == "wizard-run":
            os.chmod(dest_file, 0o755)
        else:
            os.chmod(dest_file, 0o644)


@require_acl(admin_only=False)
def get_wizard(type_, key):
    """View wrapping get_wizard_data method."""
    result = {'success': True}
    result.update(get_wizard_data(type_, key))
    return result


@require_acl(admin_only=False)
def all_():
    """View returning list of all available wizards."""
    return {'success': True,
            'wizards': get_wizard_list(['setup', 'feature'])}


@require_acl
def upload():
    """
    View for uploading wizard data.
    
    It uploads and unpacks the data to a temporary directory and
    saves the path to session so it can be checked in create() method.
    Returns JSON with path to the directory containing extracted files.
    """
    try:
        qqfile = request.files.get("qqfile")
        if not qqfile:
            raise APIError("Missing file upload.")

        path = tempfile.mktemp()
        qqfile.save(path)

        # Accept both .tar and .tar.gz
        try:
            f = tarfile.open(path, "r:gz")
        except tarfile.ReadError:
            f = tarfile.open(path, "r")

        names = sorted(f.getnames())
        if names != sorted(WIZARD_FILES):
            f.close()
            os.unlink(path)
            raise APIError("Invalid wizard package - it must contain "
                           "wizard.html, validator.json and wizard-run "
                           "but contains: %s" % ", ".join(names))

        session = request.environ['beaker.session']
        # Extract to a directory with "0" suffix
        extracted_path = path + "0"
        f.extractall(extracted_path)
        f.close()
        os.unlink(path)
        session['wizard_path'] = extracted_path
    finally:
        del request['_cgi.FieldStorage']
        request.body.close()

    return {'success': True,
            'path': extracted_path}


@require_acl
def create():
    """
    View which creates a new wizard from POSTed path and name.
    
    Files in "path" must have been uploaded previously using upload() method
    which sets "wizard_path" to session. If the wizard name is valid and files
    for the wizard exist, they are moved to WIZARD_BACKUP_FEATURE subdirectory
    and dictionary with info about the new wizard is returned.
    """
    # File must have been uploaded using upload() first
    path = request.POST.get("path")
    session = request.environ['beaker.session']
    if not path or path != session.get('wizard_path'):
        raise APIError("Invalid wizard upload.")

    # Replace spaces in name with underscore,
    # remove all except alphanumeric chars, underscore and dashes
    name = request.POST.get("name")
    name = name.replace(" ", "_")
    name = re.sub(r"[^a-zA-Z0-9_-]", "", name)
    if not name:
        raise APIError("Invalid wizard name.")

    # Only "feature" wizards can be uploaded now
    type_ = "feature"

    # Check for existence of main wizard, fail if exists
    if os.path.exists(os.path.join(WIZARD_PATH_FEATURE, name)):
        raise APIError("System defined wizard '%s' already exists" % name)

    # Check if wizard destination path is available,
    # remove it if it exists and is a directory
    dest_dir = os.path.join(WIZARD_BACKUP_FEATURE, name)
    if os.path.exists(dest_dir):
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir)
        else:
            raise APIError("Unable to upload wizard to '%s'" % dest_dir)

    # Move and adjust file mode
    move_wizard_files(path, dest_dir)

    return {'success': True,
            'wizard': create_wizard_dict(type_, name)}


@require_acl
def remove(key):
    """
    Remove complete directory with the wizard data.
    Returns name of the wizard on success.
    """
    path = os.path.join(WIZARD_BACKUP_FEATURE, key)
    if not os.path.isdir(path):
        raise APIError("No wizard to delete.")

    shutil.rmtree(path)
    return {'success': True,
            'wizard': key}
