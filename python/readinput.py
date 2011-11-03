# vi: set tabstop=4 shiftwidth=4 expandtab:
# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Mozilla Corporation code.
#
# The Initial Developer of the Original Code is the Mozilla Corporation.
# Portions created by the Initial Developer are Copyright (C) 2011
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Jim Chen <jimnchen@gmail.com>
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

import readline, sys, os

readline.parse_and_bind('tab: complete')
readline.parse_and_bind('set bell-style none')
readline.set_completer()

if __name__ == '__main__': # not module

    from optparse import OptionParser

    def dirComplete(text, state):
        path = readline.get_line_buffer()
        basename = os.path.basename(path)
        dirname = os.path.dirname(path)
        abspath = os.path.abspath(os.path.expanduser(dirname))
        for d in os.listdir(abspath):
            if d.startswith(basename) and \
                    os.path.isdir(os.path.join(abspath, d)):
                if not state:
                    return d + os.sep
                state -= 1
        return None

    def listComplete(text, state):
        buf = readline.get_line_buffer().lower()
        results = [x for x in lst if x.lower().startswith(buf)] + [None]
        return results[state]

    parser = OptionParser()
    parser.add_option('-p', dest='p')
    parser.add_option('-l', dest='l')
    parser.add_option('-d', action='store_true', dest='d')
    (args, extras) = parser.parse_args()

    if hasattr(args, 'l') and args.l:
        lst = eval(args.l)
        readline.set_completer(listComplete)
    elif hasattr(args, 'd') and args.d:
        readline.set_completer_delims('\t\n/')
        readline.set_completer(dirComplete)

    sys.stderr.write(raw_input('' if not hasattr(args, 'p') else args.p))

else:

    import gdb, subprocess

    def call(prompt, *args):
        cmd = [sys.executable, os.path.join(gdb.PYTHONDIR, 'readinput.py'),
                '-p', prompt]
        cmd.extend(list(args))
        try:
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)
            out = proc.communicate()[1]
        except OSError, e:
            raise gdb.GdbError('cannot run readinput: ' + str(e))
        if proc.returncode != 0:
            raise gdb.GdbError('readinput returned exit code ' +
                                str(proc.returncode))
        return out

