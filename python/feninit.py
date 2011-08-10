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

import gdb, adb, readinput, os, sys, subprocess, signal

class FenInit(gdb.Command):
    '''Initialize gdb for debugging Fennec on Android'''

    def __init__(self):
        super(FenInit, self).__init__('feninit', gdb.COMMAND_SUPPORT)

    def complete(self, text, word):
        return gdb.COMPLETE_NONE

    def _chooseDevice(self):
        # identify device
        dev = ''
        devs = adb.getDevices()

        # wait for a device if no device is found
        while not devs:
            try:
                print 'ADB: waiting for device... (Ctrl+C to stop)'
                adb.waitForDevice()
            except gdb.GdbError, KeyboardInterrupt:
                raise gdb.GdbError(' ADB: no device')
            devs = adb.getDevices()

        # use saved setting if possible; also allows gdbinit to set device
        if hasattr(self, 'device'):
            dev = self.device
            if dev not in devs:
                print 'feninit.default.device (%s) is not connected' % dev
        # use only device
        if len(devs) == 1:
            dev = devs[0]
        # otherwise, let user decide
        while not dev in devs:
            print 'Found multiple devices:'
            for i in range(len(devs)):
                print '%d. %s' % (i + 1, devs[i])
            dev = readinput.call('Choose device: ', '-l', str(devs))
            if dev.isdigit() and int(dev) > 0 and int(dev) <= len(devs):
                dev = devs[int(dev) - 1]
            elif len(dev) > 0:
                matchDev = filter(
                        lambda x: x.lower().startswith(dev.lower()), devs)
                # if only one match, use it
                if len(matchDev) == 1:
                    dev = matchDev[0]
        print 'Using device %s' % dev
        adb.setDevice(dev)
        self.device = dev

    def _chooseObjdir(self):
        def scanSrcDir(objdirs, path):
            # look for 'obj*' directories, using 'dist' as a clue
            abspath = os.path.abspath(os.path.expanduser(path))
            if not os.path.isdir(abspath):
                return
            if os.path.isdir(os.path.join(abspath, 'dist')):
                objdirs.append(abspath)
                return
            for d in os.listdir(abspath):
                if not d.startswith('obj'):
                    continue
                objdir = os.path.join(abspath, d)
                if os.path.isdir(objdir) and \
                        os.path.isdir(os.path.join(objdir, 'dist')):
                    objdirs.append(objdir)

        objdir = '' # None means don't use an objdir
        objdirs = []
        # look for possible locations
        scanSrcDir(objdirs, '~/mozilla-central')
        scanSrcDir(objdirs, '~/central')
        scanSrcDir(objdirs, '~/mozilla-aurora')
        scanSrcDir(objdirs, '~/aurora')
        scanSrcDir(objdirs, '~/mozilla-beta')
        scanSrcDir(objdirs, '~/beta')
        scanSrcDir(objdirs, '~/mozilla-release')
        scanSrcDir(objdirs, '~/release')
        objdirs.sort()

        # use saved setting if possible; also allows gdbinit to set objdir
        if hasattr(self, 'objdir'):
            objdir = self.objdir
            if objdir:
                scanSrcDir(objdirs, objdir)
                if objdir not in objdirs:
                    print 'feninit.default.objdir (%s) is not found' % objdir
            else:
                objdir = None
                objdirs.append(objdir)
        # let user choose even if only one objdir found,
        # because the user might want to not use an objdir
        while objdir not in objdirs:
            if objdirs:
                print 'Choices for object directory to use:'
                print '0. Do not use object directory'
                for i in range(len(objdirs)):
                    print '%d. %s' % (i + 1, objdirs[i])
                print 'Choose from above or enter alternative'
                objdir = readinput.call(': ', '-d')
                if not objdir:
                    continue
                elif objdir == '0':
                    objdir = None
                    break
            else:
                print 'No object directory found. Enter path or leave blank'
                objdir = readinput.call(': ', '-d')
                if not objdir:
                    objdir = None
                    break
            if objdir.isdigit() and int(objdir) > 0 and \
                    int(objdir) <= len(objdirs):
                objdir = objdirs[int(objdir) - 1]
                break
            objdir = os.path.abspath(os.path.expanduser(objdir))
            matchObjdir = filter(lambda x:
                    x.startswith(objdir), objdirs)
            if len(matchObjdir) == 0:
                # not on list, verify objdir first
                scanSrcDir(objdirs, objdir)
            elif len(matchObjdir) == 1:
                # only one match, good to go
                objdir = matchObjdir[0]
        print 'Using object directory: %s' % str(objdir)
        self.objdir = objdir

    def _pullLibsAndSetPaths(self):
        # libraries/binaries to pull from device
        DEFAULT_LIBS = ['lib/libdl.so', 'lib/libc.so', 'lib/libm.so',
                'lib/libstdc++.so', 'lib/liblog.so', 'lib/libz.so',
                'lib/libGLESv2.so', 'bin/linker', 'bin/app_process']
        # search path for above libraries/binaries
        DEFAULT_SEARCH_PATHS = ['lib', 'bin']

        datadir = str(gdb.parameter('data-directory'))
        libdir = os.path.abspath(
                os.path.join(datadir, os.pardir, 'lib', self.device))
        self.datadir = datadir
        self.libdir = libdir
        self.bindir = os.path.abspath(
                os.path.join(datadir, os.pardir, 'bin'))

        sys.stdout.write('Pulling libraries to %s... ' % libdir)
        sys.stdout.flush()
        for lib in DEFAULT_LIBS:
            try:
                dstpath = os.path.join(libdir, lib)
                if not os.path.exists(dstpath):
                    adb.pull('/system/' + lib, dstpath)
            except gdb.GdbError:
                sys.stdout.write('\n cannot pull %s... ' % lib)
                sys.stdout.flush()
        print 'Done'
        gdb.execute('set solib-absolute-prefix ' + libdir, False, True)
        print 'Set solib-absolute-prefix to "%s".' % libdir

        searchPaths = [os.path.join(libdir, d) for d in DEFAULT_SEARCH_PATHS]
        if self.objdir:
            searchPaths.append(os.path.join(self.objdir, 'dist', 'bin'))
            searchPaths.append(os.path.join(self.objdir, 'dist', 'lib'))
        gdb.execute('set solib-search-path ' +
                os.pathsep.join(searchPaths), False, True)
        print 'Updated solib-search-path.'

    def _getPackageName(self):
        if self.objdir:
            acname = os.path.join(self.objdir, 'config', 'autoconf.mk')
            try:
                acfile = open(acname)
                for line in acfile:
                    if 'ANDROID_PACKAGE_NAME' not in line:
                        continue
                    acfile.close()
                    pkg = line.partition('=')[2].strip()
                    print 'Using package %s.' % pkg
                    return pkg
                acfile.close()
            except OSError:
                pass
        pkgs = [x[:x.rindex('-')] for x in \
            adb.call(['shell', 'ls', '-1', '/data/app']).splitlines() \
            if x.startswith('org.mozilla.')]
        if pkgs:
            print 'Found package names:'
            for pkg in pkgs:
                print ' ' + pkg
        else:
            pkgs = ['org.mozilla.fennec_unofficial', 'org.mozilla.fennec',
                    'org.mozilla.aurora', 'org.mozilla.firefox']
        pkg = None
        while not pkg:
            pkg = readinput.call(
                'Use package (e.g. org.mozilla.fennec): ', '-l', str(pkgs))
        return pkg

    def _launchAndAttach(self):
        # name of child binary
        CHILD_EXECUTABLE = 'plugin-container'
        # 'file' command argument for parent process
        PARENT_FILE_PATH = os.path.join(self.libdir, 'bin', 'app_process')
        # 'file' command argument for child process
        if self.objdir:
            CHILD_FILE_PATH = os.path.join(self.objdir,
                    'dist', 'bin', CHILD_EXECUTABLE)
        else:
            CHILD_FILE_PATH = None

        # launch
        pkg = self._getPackageName()
        sys.stdout.write('Launching %s... ' % pkg)
        sys.stdout.flush()
        out = adb.call(['shell', 'am', 'start',
                '-a', 'org.mozilla.gecko.DEBUG', '-n', pkg + '/.App'])
        if 'error' in out.lower():
            print ''
            print out
            raise gdb.GdbError('Error while launching %s.' % pkg)

        # wait for launch to complete
        pkgProcs = None
        while not pkgProcs:
            ps = adb.call(['shell', 'ps']).splitlines()
            # get parent/child processes that are waiting ('S' state)
            pkgProcs = [x for x in ps if pkg in x and 'S' in x.split()]
        print 'Done'

        # get parent/child(ren) pid's
        pidParent = next((x.split()[1]
                for x in pkgProcs if CHILD_EXECUTABLE not in x))
        pidChild = [x.split()[1]
                for x in pkgProcs if CHILD_EXECUTABLE in x]
        pidChildParent = pidParent

        # see if any gdbserver instance is running, and discard
        # the debuggee from our list because it's already taken
        for proc in [x.split() for x in ps if 'gdbserver' in x]:
            # get the program being debugged by examine gdbserver cmdline
            cmdline = adb.call(['shell', 'cat',
                    '/proc/' + proc[1] + '/cmdline']).split('\0')
            if '--attach' not in cmdline:
                continue
            # this should be the pid
            pid = next((x for x in reversed(cmdline) if x.isdigit()))
            if pid == pidParent:
                pidParent = None
            elif pid in pidChild:
                pidChild.remove(pid)

        if pidParent:
            # the parent is not being debugged, pick the parent
            pidAttach = pidParent
            sys.stdout.write('Attaching to parent (pid %s)... ' % pidAttach)
            sys.stdout.flush()
        elif not pidChild:
            # ok, no child is available. assume the user
            # wants to wait for child to start up
            pkgProcs = None
            while not pkgProcs:
                print 'Waiting for child process...'
                ps = adb.call(['shell', 'ps']).splitlines()
                # check for 'S' state, for right parent, and for right child
                pkgProcs = [x for x in ps if 'S' in x and \
                        pidChildParent in x and CHILD_EXECUTABLE in x]
            pidChild = [x.split()[1] for x in pkgProcs]

        # if the parent was not picked, pick the right child
        if not pidParent and len(pidChild) == 1:
            # that is easy
            pidAttach = pidChild[0]
            sys.stdout.write('Attaching to child (pid %s)... ' % pidAttach)
            sys.stdout.flush()
        elif not pidParent:
            # should not happen for now, because we only use one child
            pidAttach = None
            while pidAttach not in pidChild:
                print 'WTF multiple child processes found:'
                for i in range(len(pidChild)):
                    print '%d. pid %s' % (i + 1, pidChild[i])
                pidAttach = readinput.call('Child pid: ', '-l', str(pidChild))
                if pidAttach.isdigit() and int(pidAttach) > 0 \
                        and int(pidAttach) <= len(pidChild):
                    pidAttach = pidChild[pidAttach]
            sys.stdout.write('Attaching... ')
            sys.stdout.flush()
        self.pid = pidAttach

        # push gdbserver if it's not there
        gdbserverPath = '/data/local/tmp/gdbserver'
        if not adb.pathExists(gdbserverPath):
            adb.push(os.path.join(self.bindir, 'gdbserver'), gdbserverPath)

        # run this after fork() and before exec(gdbserver)
        # so 'adb shell gdbserver' doesn't get gdb's signals
        def gdbserverPreExec():
            os.setpgrp()

        # can we run as root?
        if 'uid=0' in adb.call(['shell', 'id']):
            gdbserverProc = adb.call(['shell',
                    gdbserverPath, '--attach', ':0', pidAttach],
                    stderr=subprocess.PIPE, async=True,
                    preexec_fn=gdbserverPreExec)
        else:
            sys.stdout.write('as non-root... ')
            sys.stdout.flush()
            gdbserverProc = adb.call(['shell', 'run-as', pkg,
                    gdbserverPath, '--attach', ':0', pidAttach],
                    stderr=subprocess.PIPE, async=True,
                    preexec_fn=gdbserverPreExec)

        # we passed ':0' to gdbserver so it'll pick a port for us
        # but that means we have to find the port from stdout
        # while this complicates things a little, it allows us to
        # have multiple gdbservers running
        port = None
        while not port:
            if gdbserverProc.poll() is not None:
                print ''
                print gdbserverProc.stdout.read()
                raise gdb.GdbError('gdbserver exited unexpectedly')
            line = gdbserverProc.stdout.readline().split()
            # kind of hacky, assume the port number comes after 'port'
            if 'port' in line:
                port = line[line.index('port') + 1]

        self.port = port
        self.gdbserver = gdbserverProc

        # forward the port that gdbserver gave us
        adb.forward('tcp:' + port, 'tcp:' + port)
        print 'Done'

        sys.stdout.write('Setting up remote debugging... ')
        sys.stdout.flush()
        # load the right file
        gdb.execute('file ' + PARENT_FILE_PATH
                if pidParent else CHILD_FILE_PATH, False, True)
        gdb.execute('target remote :' + port, False, True)
        print 'Done\n'

        if pidParent:
            print 'Run another gdb session to debug child process.\n'
        print 'Ready. Use "continue" to resume execution.'

    def invoke(self, argument, from_tty):
        try:
            saved_height = gdb.parameter('height')
            saved_height = int(saved_height) if saved_height else 0
            gdb.execute('set height 0') # suppress pagination
            if hasattr(self, 'gdbserver') and self.gdbserver:
                if self.gdbserver.poll() is None:
                    print 'Already in remote debug mode.'
                    return
                delattr(self, 'gdbserver')
            self._chooseDevice()
            self._chooseObjdir()
            self._pullLibsAndSetPaths()
            self._launchAndAttach()
            self.dont_repeat()
        except:
            # if there is an error, a gdbserver might be left hanging
            if hasattr(self, 'gdbserver') and self.gdbserver:
                if self.gdbserver.poll() is None:
                    self.gdbserver.terminate()
                    print 'Terminated gdbserver.'
                delattr(self, 'gdbserver')
            raise
        finally:
            gdb.execute('set height ' + str(saved_height), False, True)

default = FenInit()

