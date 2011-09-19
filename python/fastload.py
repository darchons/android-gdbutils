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

import gdb, threading, os, sys, adb, feninit

class FastLoad():
    '''Load librariess intelligently'''

    def __init__(self):
        self._loader = FastLoad.Loader()
        self._loader.solibs = None
        gdb.events.cont.connect(self.cont_handler)
        gdb.events.stop.connect(self.stop_handler)
        def loadLibList():
            if not self._loader.solibs:
                self._loader.solibs = \
                        gdb.execute('info sharedlibrary', False, True)
        gdb.post_event(loadLibList)

    class Loader(threading.Thread):
        def run(self):
            PARALLEL_LIMIT = 5

            libdir = feninit.default.libdir
            objdir = feninit.default.objdir \
                    if hasattr(feninit.default, 'objdir') else None
            buckets = [[] for x in range(PARALLEL_LIMIT)]

            self.paths = set()
            if objdir:
                self.paths.add(os.path.join(objdir, 'dist', 'bin'))

            for lib in (x.split()[-1] for x in self.solibs.splitlines()
                    if '.so' in x and len(x.split()) == 2):
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
                self.paths.add(os.path.dirname(dst))
                bucket = min(buckets, key=lambda x: len(x))
                bucket.append((src, dst))

            # let it loose!
            def makePullLibs(bucket):
                def doPullLibs():
                    for fromto in bucket:
                        try:
                            if self.continuing:
                                sys.__stderr__.write(
                                        'Background-loading %s.\n' % fromto[0])
                            adb.pull(fromto[0], fromto[1])
                        except gdb.GdbError:
                            pass
                return doPullLibs
            threads = [threading.Thread(target=makePullLibs(x))
                    for x in buckets]
            for thread in threads:
                thread.daemon = True
                thread.start()
            for thread in threads:
                thread.join()
            print 'All libraries pulled from device. Continuing.'

    def cont_handler(self, event):
        if not isinstance(event, gdb.ContinueEvent):
            return
        # load modules
        self._loader.continuing = True
        self._loader.daemon = True
        self._loader.start()

    def stop_handler(self, event):
        if self._loader.isAlive():
            self._loader.continuing = False
            sys.stdout.write('Waiting for libraries from device... ')
            sys.stdout.flush()
            self._loader.join()
            print 'Done'
        # set paths
        sys.stdout.write('Loading symbols... ')
        sys.stdout.flush()
        libdir = feninit.default.libdir
        gdb.execute('set sysroot ' + libdir, False, True)
        gdb.execute('set solib-search-path ' +
                os.pathsep.join(self._loader.paths), False, True)
        # load all symbols
        gdb.execute('sharedlibrary', False, True)
        print 'Done'

default = FastLoad()

# don't load libs automatically
gdb.execute('set auto-solib-add off', False, True)

