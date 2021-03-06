#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
import os
import os.path
from subprocess import Popen, PIPE, call
import re

DOCUMENTATION = '''
---
module: locale_gen
short_description: Creates or removes locales.
description:
     - Manages locales by editing /etc/locale.gen and invoking locale-gen.
version_added: "1.6"
author: "Augustus Kling (@AugustusKling)"
options:
    name:
        description:
             - Name and encoding of the locale, such as "en_GB.UTF-8".
        required: true
        default: null
        aliases: []
    state:
      description:
           - Whether the locale shall be present.
      required: false
      choices: ["present", "absent"]
      default: "present"
'''

EXAMPLES = '''
# Ensure a locale exists.
- locale_gen: name=de_CH.UTF-8 state=present
'''

LOCALE_NORMALIZATION = {
    ".utf8": ".UTF-8",
    ".eucjp": ".EUC-JP",
    ".iso885915": ".ISO-8859-15",
}

# ===========================================
# location module specific support methods.
#

def is_available(name, ubuntuMode):
    """Check if the given locale is available on the system. This is done by
    checking either :
    * if the locale is present in /etc/locales.gen
    * or if the locale is present in /usr/share/i18n/SUPPORTED"""
    if ubuntuMode:
        __regexp = '^(?P<locale>\S+_\S+) (?P<charset>\S+)\s*$'
        __locales_available = '/usr/share/i18n/SUPPORTED'
    else:
        __regexp = '^#{0,1}\s*(?P<locale>\S+_\S+) (?P<charset>\S+)\s*$'
        __locales_available = '/etc/locale.gen'

    re_compiled = re.compile(__regexp)
    fd = open(__locales_available, 'r')
    for line in fd:
        result = re_compiled.match(line)
        if result and result.group('locale') == name:
            return True
    fd.close()
    return False

def is_present(name):
    """Checks if the given locale is currently installed."""
    output = Popen(["locale", "-a"], stdout=PIPE).communicate()[0]
    return any(fix_case(name) == fix_case(line) for line in output.splitlines())

def fix_case(name):
    """locale -a might return the encoding in either lower or upper case.
    Passing through this function makes them uniform for comparisons."""
    for s, r in LOCALE_NORMALIZATION.iteritems():
        name = name.replace(s, r)
    return name

def replace_line(existing_line, new_line):
    """Replaces lines in /etc/locale.gen"""
    try:
        f = open("/etc/locale.gen", "r")
        lines = [line.replace(existing_line, new_line) for line in f]
    finally:
        f.close()
    try:
        f = open("/etc/locale.gen", "w")
        f.write("".join(lines))
    finally:
        f.close()

def set_locale(name, enabled=True):
    """ Sets the state of the locale. Defaults to enabled. """
    search_string = '#{0,1}\s*%s (?P<charset>.+)' % name
    if enabled:
        new_string = '%s \g<charset>' % (name)
    else:
        new_string = '# %s \g<charset>' % (name)
    try:
        f = open("/etc/locale.gen", "r")
        lines = [re.sub(search_string, new_string, line) for line in f]
    finally:
        f.close()
    try:
        f = open("/etc/locale.gen", "w")
        f.write("".join(lines))
    finally:
        f.close()

def apply_change(targetState, name):
    """Create or remove locale.

    Keyword arguments:
    targetState -- Desired state, either present or absent.
    name -- Name including encoding such as de_CH.UTF-8.
    """
    if targetState=="present":
        # Create locale.
        set_locale(name, enabled=True)
    else:
        # Delete locale.
        set_locale(name, enabled=False)
    
    localeGenExitValue = call("locale-gen")
    if localeGenExitValue!=0:
        raise EnvironmentError(localeGenExitValue, "locale.gen failed to execute, it returned "+str(localeGenExitValue))

def apply_change_ubuntu(targetState, name):
    """Create or remove locale.
    
    Keyword arguments:
    targetState -- Desired state, either present or absent.
    name -- Name including encoding such as de_CH.UTF-8.
    """
    if targetState=="present":
        # Create locale.
        # Ubuntu's patched locale-gen automatically adds the new locale to /var/lib/locales/supported.d/local
        localeGenExitValue = call(["locale-gen", name])
    else:
        # Delete locale involves discarding the locale from /var/lib/locales/supported.d/local and regenerating all locales.
        try:
            f = open("/var/lib/locales/supported.d/local", "r")
            content = f.readlines()
        finally:
            f.close()
        try:
            f = open("/var/lib/locales/supported.d/local", "w")
            for line in content:
                locale, charset = line.split(' ')
                if locale != name:
                    f.write(line)
        finally:
            f.close()
        # Purge locales and regenerate.
        # Please provide a patch if you know how to avoid regenerating the locales to keep!
        localeGenExitValue = call(["locale-gen", "--purge"])
    
    if localeGenExitValue!=0:
        raise EnvironmentError(localeGenExitValue, "locale.gen failed to execute, it returned "+str(localeGenExitValue))

# ==============================================================
# main

def main():

    module = AnsibleModule(
        argument_spec = dict(
            name = dict(required=True),
            state = dict(choices=['present','absent'], default='present'),
        ),
        supports_check_mode=True
    )

    name = module.params['name']
    state = module.params['state']

    if not os.path.exists("/etc/locale.gen"):
        if os.path.exists("/var/lib/locales/supported.d/"):
            # Ubuntu created its own system to manage locales.
            ubuntuMode = True
        else:
            module.fail_json(msg="/etc/locale.gen and /var/lib/locales/supported.d/local are missing. Is the package \"locales\" installed?")
    else:
        # We found the common way to manage locales.
        ubuntuMode = False

    if not is_available(name, ubuntuMode):
        module.fail_json(msg="The locales you've entered is not available "
                             "on your system.")

    if is_present(name):
        prev_state = "present"
    else:
        prev_state = "absent"
    changed = (prev_state!=state)
    
    if module.check_mode:
        module.exit_json(changed=changed)
    else:
        if changed:
            try:
                if ubuntuMode==False:
                    apply_change(state, name)
                else:
                    apply_change_ubuntu(state, name)
            except EnvironmentError, e:
                module.fail_json(msg=e.strerror, exitValue=e.errno)

        module.exit_json(name=name, changed=changed, msg="OK")

# import module snippets
from ansible.module_utils.basic import *

main()
