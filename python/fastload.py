# vi: set tabstop=4 shiftwidth=4 expandtab:
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import gdb, threading, os, sys, subprocess, feninit, adb

class FastLoad(gdb.Command):
    '''Pull libraries in background'''

    def __init__(self):
        super(FastLoad, self).__init__('fastload', gdb.COMMAND_SUPPORT)
        self._loader = None

    def complete(self, text, word):
        return gdb.COMPLETE_NONE

    def invoke(self, argument, from_tty):
        if self._loader:
            print 'Already running.'
            return
        libdir = feninit.default.libdir \
                if hasattr(feninit.default, 'libdir') else None
        if not libdir:
            return
        force = True
        idfile = os.path.join(libdir, '.id')
        devid = adb.call(['shell', 'cat', '/proc/version',
                          '/system/build.prop'])[0:2048].strip()
        try:
            with open(idfile, 'r') as libid:
                if libid.read(2048) == devid:
                    force = False
                    if argument == 'quick':
                        return
        except IOError:
            pass
        self._loader = FastLoad.Loader()
        self._loader.solibs = gdb.execute('info sharedlibrary', False, True)
        self._loader.force = force
        self._loader.idfile = idfile
        self._loader.devid = devid
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
        if not self._loader:
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
                    if ('.so' in x or '/' in x) and len(x.split()) >= 2):
                if os.path.exists(lib): # symbol already loaded
                    if not self.force or not lib.startswith(libdir):
                        continue
                    if os.path.join('system', 'lib') in lib or \
                       os.path.join('system', 'vendor', 'lib') in lib:
                        # turn to a relative path
                        lib = lib.split(os.path.sep)[-1]
                    else:
                        # turn to an absolute path
                        lib = '/' + '/'.join(lib[len(libdir):]
                                       .lstrip(os.path.sep)
                                       .split(os.path.sep))
                if objdir and os.path.exists(
                        os.path.join(objdir, 'dist', 'bin', lib)):
                    continue
                if '/' in lib:
                    src = lib
                    dst = os.path.join(libdir, os.path.sep.join(
                                       lib.lstrip('/').split('/')))
                    if not self.force and os.path.exists(dst):
                        continue
                    bucket = min(buckets, key=lambda x: len(x))
                    bucket.append((src, dst))
                    continue
                for srclibdir in ['', 'drm/', 'hw/', 'egl/']:
                    src = '/system/lib/' + srclibdir + lib
                    dst = os.path.join(libdir, 'system', 'lib', lib)
                    if not self.force and os.path.exists(dst):
                        continue
                    bucket = min(buckets, key=lambda x: len(x))
                    bucket.append((src, dst))
                for srclibdir in ['', 'drm/', 'egl/', 'hw/']:
                    src = '/system/vendor/lib/' + srclibdir + lib
                    dst = os.path.join(libdir, 'system', 'vendor', 'lib', lib)
                    if not self.force and os.path.exists(dst):
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
                        try:
                            os.makedirs(os.path.dirname(fromto[1]))
                        except:
                            pass

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
            if hasattr(self, 'idfile'):
                try:
                    with open(self.idfile, 'w') as libid:
                        libid.write(self.devid)
                except IOError:
                    pass
            if self.continuing:
                sys.__stderr__.write(
                        'All libraries pulled from device. Continuing.\n')

default = FastLoad()
feninit.default.skipPull = True

