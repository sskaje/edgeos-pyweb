import subprocess
import logging

from bottle import request, template

default_context = {}

logger = logging.getLogger("custom-ipset")


class IPSet:
    ALL = "VPN_SRC_ZONE"
    CDN = "SRC_DYNAMIC"
    HIJACK = "HIJACK_443"

    def getname(self, name):
        map = {
            "all": self.ALL,
            "cdn": self.CDN,
            "hijack": self.HIJACK
        }

        if name in map:
            return map[name]
        else:
            return name

    def __init__(self, ipset_bin):
        self.ipset_bin = ipset_bin

    def get(self, groupname):
        # return subprocess.check_output([self.ipset_bin, 'list', groupname])
        ps = subprocess.Popen([self.ipset_bin, 'list', self.getname(groupname)], stdout=subprocess.PIPE)
        output = subprocess.check_output(('grep', '-Ev', '^(Revision|Header|Size|Reference)'), stdin=ps.stdout)
        ps.wait()
        return output

    def add(self, groupname, ip):
        try:
            return subprocess.check_output([self.ipset_bin, 'add', self.getname(groupname), ip],
                                           stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as exc:
            return exc.output
        except:
            return ""

    def delete(self, groupname, ip):
        try:
            return subprocess.check_output([self.ipset_bin, 'del', self.getname(groupname), ip],
                                           stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as exc:
            return exc.output
        except:
            return ""


ipset = IPSet("/config/app/bin/ipset")


def register_urls(app, prefix):
    # "remove" must be registered before generic get_wizard route
    app.get(prefix + "/ipset/", callback=ipset_index)
    app.post(prefix + "/ipset/delete.json", callback=ipset_delete)
    app.post(prefix + "/ipset/add.json", callback=ipset_add)
    app.post(prefix + "/ipset/get.json", callback=ipset_get)

    global default_context
    default_context = {
        'model': app.config['device.model'],
        'body_class': app.config['device.config']['class'],
        'model_name': app.config['device.config']['name'],
        'authenticated': False,
        'default_config_wizard': False,
        'username': None,
        'level': None,
        'features': None
    }


def client_ip():
    return request.environ.get('REMOTE_ADDR')


def ipset_index():
    logger.info("access: index")

    context = default_context
    context['client_ip'] = client_ip()
    context['ipset'] = {
        "all": ipset.get(ipset.ALL),
        "cdn": ipset.get(ipset.CDN),
        "hijack": ipset.get(ipset.HIJACK)
    }

    return template("custom/ipset", **context)


def ipset_add():
    groupname = request.POST.get("groupname", "")
    ip = request.POST.get("ip", client_ip())

    output = ipset.add(groupname, ip)
    return {"output": output}


def ipset_delete():
    groupname = request.POST.get("groupname", "")
    ip = request.POST.get("ip", client_ip())

    output = ipset.delete(groupname, ip)
    return {"output": output}


def ipset_get():
    groupname = request.POST.get("groupname", None)
    output = ipset.get(groupname)
    return {"output": output}
