import json
import logging
import tempfile

from bottle import default_app, request

from . import api_command, dispatch_request, get_post_content, APIError
from ..utils import get_parent_structure, require_acl

logger = logging.getLogger("edge_api")


def register_urls(app, prefix):
    # Authentication
    app.post(prefix + "/auth.json", callback=auth,
             csrf_exempt=True)
    # Config API
    app.get(prefix + "/get.json", callback=get)
    app.get(prefix + "/partial.json", callback=partial)
    app.get(prefix + "/data.json", callback=data)
    app.post(prefix + "/set.json", callback=set_)
    app.post(prefix + "/delete.json", callback=delete)
    app.post(prefix + "/batch.json", callback=batch)
    app.get(prefix + "/heartbeat.json", callback=heartbeat)
    # Misc device operations
    app.post(prefix + "/operation/get-support-file.json", callback=get_support_file)
    app.post(prefix + "/operation/<op>.json", callback=operation)
    # Config backup/restore
    app.get(prefix + "/config/save.json", callback=config_save)
    app.post(prefix + "/config/restore.json", callback=config_restore,
             csrf_token_in_query=True)
    # Device upgrade
    app.post(prefix + "/upgrade.json", callback=upgrade,
             csrf_token_in_query=True)
    # Wizard
    app.post(prefix + "/setup.json", callback=wizard_setup)
    app.post(prefix + "/feature.json", callback=wizard_feature)
    # Config tree
    app.get(prefix + "/getcfg.json", callback=getcfg)
    # ONUs
    app.post(prefix + "/onu/upgrade.json", callback=onu_upgrade)
    app.post(prefix + "/onu/reboot.json", callback=onu_reboot)


@require_acl(admin_only=False)
@api_command
def get():
    operations = {
        'GET': {
            'firewall': "",
            'interfaces': "",
            'service': "",
            'system': "",
            'vpn': "",
            'protocols': "",
            'traffic-control': "",
            'onu-list': "",
            'onu-profiles': "",
            'onu-policies': "",
        }
    }
    return operations


@require_acl
@api_command
def set_():
    operations = {
        'SET': get_post_content()
    }
    operations['GET'] = get_parent_structure(operations['SET'])
    return operations


@require_acl
@api_command
def delete():
    operations = {
        'DELETE': get_post_content()
    }
    operations['GET'] = get_parent_structure(operations['DELETE'])
    return operations


@require_acl
@api_command
def batch():
    operations = get_post_content()
    if not operations.get("GET"):
        operations['GET'] = get_parent_structure(operations.get("SET")) \
            if operations.get("SET") else {}
        if operations.get('DELETE'):
            operations['GET'].update(get_parent_structure(operations['DELETE']))
    return operations


@require_acl
@api_command
def partial(struct=None):
    return dict(GET=json.loads(struct or request.GET.get("struct", "{}")))


@require_acl
@api_command
def getcfg():
    return dict(GETCFG=request.GET.getall("node[]"))


@require_acl(authenticated_only=False, admin_only=False)
@api_command
def auth(username=None, password=None):
    username = username or request.POST.get("username", "")
    password = password or request.POST.get("password", "")
    return dict(AUTH=dict(username=username, password=password))


@require_acl(admin_only=False)
@api_command
def data():
    return dict(GETDATA=request.GET.get("data"))


@require_acl(admin_only=False)
def heartbeat():
    response = dispatch_request(PING=None)
    return dict(PING=bool(response['success']), SESSION=True)


@require_acl
@api_command
def operation(op):
    return dict(OPERATION=dict(op=op))


@require_acl
def get_support_file():
    response = dispatch_request(OPERATION=dict(op="get-support-file"))
    session = request.environ['beaker.session']
    session['support_file'] = response['OPERATION']['path']
    session.save()
    return response


@require_acl
def config_save():
    response = dispatch_request(CONFIG=dict(action="save"))
    session = request.environ['beaker.session']
    session['config_backup_file'] = response['CONFIG']['path']
    session.save()
    return response


@require_acl
def config_restore():
    try:
        qqfile = request.files.get("qqfile")
        if not qqfile:
            raise APIError("Missing file upload.")
        path = tempfile.mktemp()
        qqfile.save(path)
    finally:
        del request['_cgi.FieldStorage']
        request.body.close()

    response = dispatch_request(CONFIG=dict(action="restore", path=path))
    error = response.get('CONFIG', {}).get('error')
    if error:
        raise APIError(error)

    return response


@require_acl
def upgrade():
    app = default_app()
    try:
        app.config['apply_upload_patches'] = True
        app.config['delete_uploaded_tempfile'] = False
        qqfile = request.files.get("qqfile")
        if not qqfile:
            raise APIError("Missing file upload.")
        path = qqfile.file.name
    finally:
        del request['_cgi.FieldStorage']
        request.body.close()
        app.config['apply_upload_patches'] = False
        app.config['delete_uploaded_tempfile'] = True

    response = dispatch_request(UPGRADE=dict(path=path))
    error = response.get('UPGRADE', {}).get('error')
    if error:
        raise APIError(error)

    return response


@require_acl
@api_command
def wizard_setup():
    post_content = get_post_content()
    return dict(SETUP=post_content.get("data"))


def check_wizard_feature_admin_only(session):
    """
    Check if the called action should be performed as admin_only.
    
    Currently operator has only the "load" action allowed.
    """
    if session['level'] == "admin":
        return False
    else:
        post_content = get_post_content()
        if post_content.get('data', {}).get('action', "") == "load":
            return False
    return True


@require_acl(admin_only=check_wizard_feature_admin_only)
@api_command
def wizard_feature():
    post_content = get_post_content()
    return dict(FEATURE=post_content.get("data"))


@require_acl
@api_command
def onu_upgrade():
    post_content = get_post_content()
    onu_list = json.loads(post_content.get("onu_list", "[]"))

    try:
        qqfile = request.files.get("qqfile")
        if not qqfile:
            raise APIError("Missing file upload.")
        path = tempfile.mktemp()
        logger.info("Saving ONU upgrade image to %s", path)
        qqfile.save(path)
    finally:
        del request['_cgi.FieldStorage']
        request.body.close()

    return dict(UPGRADE_ONU=dict(path=path,
                                 onu_list=onu_list))


@require_acl
@api_command
def onu_reboot():
    return dict(REBOOT_ONU=dict(get_post_content()))
