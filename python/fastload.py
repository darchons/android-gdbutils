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

import gdb, threading, os, sys, subprocess, feninit

class FastLoad(gdb.Command):
    '''Pull libraries in background'''

    def __init__(self):
        super(FastLoad, self).__init__('fastload', gdb.COMMAND_SUPPORT)
        self._loader = None

    def complete(self, text, word):
        return gdb.COMPLETE_NONE

    def invoke(self, argument, from_tty):
        if self._loader:
            return
        libdir = feninit.default.libdir \
                if hasattr(feninit.default, 'libdir') else None
        if not libdir or os.path.exists(os.path.join(
                libdir, 'system', 'lib', 'libdvm.so')):
            return
        self._loader = FastLoad.Loader()
        self._loader.solibs = gdb.execute('info sharedlibrary', False, True)
        gdb.events.cont.connect(self.cont_handler)
        gdb.events.stop.connect(self.stop_handler)
        gdb.events.exited.connect(self.exit_handler)
        # load modules
        self._loader.continuing = False
        self._loader.adbcmd = str(gdb.parameter('adb-path'))
        self._loader.adbdev = str(gdb.parameter('adb-device'))
        self._loader.start()

    def cont_handler(self, event):
        if not isinstance(event, gdb.ContinueEvent):
            return
        self._loader.continuing = True

    def stop_handler(self, event):
        loader = self._loader
        self.exit_handler(event)
        # set paths and load all symbols
        if not loader.hasLibs:
            return
        sys.__stdout__.write('Loading symbols... ')
        sys.__stdout__.flush()
        gdb.execute('sharedlibrary', False, True)
        print 'Done'

    def exit_handler(self, event):
        gdb.events.cont.disconnect(self.cont_handler)
        gdb.events.stop.disconnect(self.stop_handler)
        gdb.events.exited.disconnect(self.exit_handler)
        if self._loader.isAlive():
            self._loader.continuing = False
            sys.__stdout__.write('Waiting for libraries from device... ')
            sys.__stdout__.flush()
            self._loader.join()
            print 'Done'
        self._loader = None

    class Loader(threading.Thread):
        def run(self):
            PARALLEL_LIMIT = 5

            libdir = feninit.default.libdir
            objdir = feninit.default.objdir \
                    if hasattr(feninit.default, 'objdir') else None
            buckets = [[] for x in range(PARALLEL_LIMIT)]

            for lib in (x.split()[-1] for x in self.solibs.splitlines()
                    if ('.so' in x or '/' in x) and len(x.split()) == 2):
                if objdir and os.path.exists(
                        os.path.join(objdir, 'dist', 'bin', lib)):
                    continue
                if '/' in lib:
                    src = lib
                    dst = os.path.join(libdir, lib.lstrip('/'))
                else:
                    src = '/system/lib/' + lib
                    dst = os.path.join(libdir, 'system', 'lib', lib)
                if os.path.exists(dst):
                    continue
                bucket = min(buckets, key=lambda x: len(x))
                bucket.append((src, dst))

            self.hasLibs = any(buckets)
            if not self.hasLibs:
                return

            # let it loose!
            def makePullLibs(bucket, fnull):
                def doPullLibs():
                    for fromto in bucket:
                        if self.continuing:
                            sys.__stderr__.write(
                                    'Background-loading %s.\n' % fromto[0])
                        cmd = [self.adbcmd]
                        cmd += ['-s', self.adbdev] if self.adbdev else []
                        cmd += ['pull', fromto[0], fromto[1]]
                        subprocess.Popen(cmd, stdout=fnull,
                                stderr=fnull).wait()
                return doPullLibs
            fnull = open(os.devnull, 'wb')
            threads = [threading.Thread(
                    target=makePullLibs(x, fnull)) for x in buckets]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            fnull.close()
            if self.continuing:
                sys.__stderr__.write(
                        'All libraries pulled from device. Continuing.\n')

default = FastLoad()
feninit.default.skipPull = True

