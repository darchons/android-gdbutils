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

import gdb, adb, readinput, adblog, getxre
import os, sys, subprocess, threading, time, shlex, tempfile, pipes, shutil, re

class FenInit(gdb.Command):
    '''Initialize gdb for debugging Fennec on Android'''

    TASKS = (
        'Debug Fennec (default)',
        'Debug content Mochitest',
        'Debug compiled-code unit test'
    )
    (
        TASK_FENNEC,
        TASK_MOCHITEST,
        TASK_CPP_TEST
    ) = (
        0,
        1,
        2
    )

    def __init__(self):
        super(FenInit, self).__init__('feninit', gdb.COMMAND_SUPPORT)

    def complete(self, text, word):
        return gdb.COMPLETE_NONE

    def _chooseTask(self):
        print '\nFennec GDB utilities'
        print ' (edit utils/gdbinit file to change preferences)'
        for i in range(len(self.TASKS)):
            print '%d. %s' % (i + 1, self.TASKS[i])
        task = 0
        while task < 1 or task > len(self.TASKS):
            task = readinput.call('Enter option from above: ', '-l',
                                  str(list(self.TASKS)))
            if not task:
                task = 1
                break
            if task.isdigit():
                task = int(task)
                continue
            matchTask = filter(lambda x: x.lower().startswith(task.lower()),
                               self.TASKS)
            if len(matchTask) == 1:
                task = self.TASKS.index(matchTask[0]) + 1
        print ''
        return task - 1

    def _chooseDevice(self):
        dev = adb.chooseDevice()
        print 'Using device %s' % dev
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
        srcroot = self.srcroot if hasattr(self, 'srcroot') else '~'
        scanSrcDir(objdirs, os.path.join(srcroot, 'mozilla-central'))
        scanSrcDir(objdirs, os.path.join(srcroot, 'central'))
        scanSrcDir(objdirs, os.path.join(srcroot, 'mozilla-aurora'))
        scanSrcDir(objdirs, os.path.join(srcroot, 'aurora'))
        scanSrcDir(objdirs, os.path.join(srcroot, 'mozilla-beta'))
        scanSrcDir(objdirs, os.path.join(srcroot, 'beta'))
        scanSrcDir(objdirs, os.path.join(srcroot, 'mozilla-release'))
        scanSrcDir(objdirs, os.path.join(srcroot, 'release'))
        objdirs.sort()

        # use saved setting if possible; also allows gdbinit to set objdir
        if hasattr(self, 'objdir'):
            objdir = self.objdir
            if objdir:
                scanSrcDir(objdirs, objdir)
            else:
                objdir = None
                objdirs.append(objdir)
        # let user choose even if only one objdir found,
        # because the user might want to not use an objdir
        while objdir not in objdirs:
            print 'Choices for object directory to use:'
            print '0. Do not use object directory'
            for i in range(len(objdirs)):
                print '%d. %s' % (i + 1, objdirs[i])
            print 'Enter number from above or enter alternate path'
            objdir = readinput.call(': ', '-d')
            print ''
            if not objdir:
                continue
            if objdir.isdigit() and int(objdir) >= 0 and \
                    int(objdir) <= len(objdirs):
                if int(objdir) == 0:
                    objdir = None
                else:
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
        DEFAULT_FILE = 'system/bin/app_process'
        # libraries/binaries to pull from device
        DEFAULT_LIBS = ['system/lib/libdl.so', 'system/lib/libc.so',
                'system/lib/libm.so', 'system/lib/libstdc++.so',
                'system/lib/liblog.so', 'system/lib/libz.so',
                'system/lib/libGLESv2.so', 'system/bin/linker']
        # search path for above libraries/binaries
        DEFAULT_SEARCH_PATHS = [['system', 'lib'],
                                ['system', 'vendor', 'lib'],
                                ['system', 'bin']]

        datadir = str(gdb.parameter('data-directory'))
        libdir = os.path.abspath(
                os.path.join(datadir, os.pardir, 'lib', self.device))
        self.datadir = datadir
        self.libdir = libdir
        self.bindir = os.path.abspath(
                os.path.join(datadir, os.pardir, 'bin'))

        # always pull the executable file
        dstpath = os.path.join(libdir, DEFAULT_FILE.replace('/', os.sep))
        if not os.path.exists(dstpath):
            adb.pull('/' + DEFAULT_FILE, dstpath)

        # only pull libs and set paths if automatically loading symbols
        if hasattr(self, 'skipPull') and not self.skipPull:
            sys.stdout.write('Pulling libraries to %s... ' % libdir)
            sys.stdout.flush()
            for lib in DEFAULT_LIBS:
                try:
                    dstpath = os.path.join(libdir, lib.replace('/', os.sep))
                    if not os.path.exists(dstpath):
                        adb.pull('/' + lib, dstpath)
                except gdb.GdbError:
                    sys.stdout.write('\n cannot pull %s... ' % lib)
                    sys.stdout.flush()
            print 'Done'

        gdb.execute('set sysroot ' + libdir, False, True)
        print 'Set sysroot to "%s".' % libdir

        searchPaths = [os.path.join(libdir, os.path.sep.join(d)) \
                for d in DEFAULT_SEARCH_PATHS]
        if self.objdir:
            searchPaths.append(os.path.join(self.objdir, 'dist', 'bin'))
            searchPaths.append(os.path.join(self.objdir, 'dist', 'lib'))
        gdb.execute('set solib-search-path ' +
                os.pathsep.join(searchPaths), False, True)
        print 'Updated solib-search-path.'

    def _getPackageName(self, objdir):
        if objdir:
            acname = os.path.join(objdir, 'config', 'autoconf.mk')
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
            except IOError:
                pass
        pkgs = [x.partition(':')[-1] for x in \
            adb.call(['shell', 'pm', 'list', 'packages']).splitlines() \
            if ':org.mozilla.' in x]
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
        print ''
        return pkg

    def _getRunningProcs(self, pkg, waiting=False):
        ps = adb.call(['shell', 'ps']).splitlines()
        return [x for x in ps if pkg in re.split(r'[ \t/]', x) and
                (not waiting or 'S' in x.split() or 'T' in x.split())]

    def _killRunningProcs(self, pkg):
        pkgProcs = self._getRunningProcs(pkg)
        if not pkgProcs:
            return

        adb.call(['shell', 'am', 'force-stop', pkg])
        time.sleep(3)
        pkgProcs = self._getRunningProcs(pkg)
        if not pkgProcs:
            return

        for p in pkgProcs:
            adb.call(['run-as', pkg, 'kill', '-9',
                      next(c for c in p.split() if c.isdigit())])
        time.sleep(2)
        pkgProcs = self._getRunningProcs(pkg)
        if not pkgProcs:
            return

        for p in pkgProcs:
            print p
        raise gdb.GdbError(
            'Could not kill running %s process.' % pkg)

    def _launch(self, pkg):
        # name of child binary
        CHILD_EXECUTABLE = 'plugin-container'

        # get parent/child processes
        pkgProcs = self._getRunningProcs(pkg)

        if all([CHILD_EXECUTABLE in x for x in pkgProcs]):
            # launch
            sys.stdout.write('Launching %s... ' % pkg)
            sys.stdout.flush()
            out = adb.call(['shell', 'am', 'start', '-n', pkg + '/.App'])
            if 'error' in out.lower():
                print ''
                print out
                raise gdb.GdbError('Error while launching %s.' % pkg)
            # sleep for 1s to allow time to launch
            time.sleep(1)

    def _attach(self, pkg):
        # name of child binary
        CHILD_EXECUTABLE = 'plugin-container'
        # 'file' command argument for parent process
        PARENT_FILE_PATH = os.path.join(self.libdir,
                'system', 'bin', 'app_process')
        # 'file' command argument for child process
        if self.objdir:
            CHILD_FILE_PATH = os.path.join(self.objdir,
                    'dist', 'bin', CHILD_EXECUTABLE)
            if not os.path.exists(CHILD_FILE_PATH):
                CHILD_FILE_PATH = os.path.join(self.objdir,
                        'dist', 'bin', 'lib', 'libplugin-container.so')
        else:
            CHILD_FILE_PATH = None

        # get parent/child processes that are waiting ('S' state)
        pkgProcs = self._getRunningProcs(pkg, waiting=True)

        # wait for parent launch to complete
        while all([CHILD_EXECUTABLE in x for x in pkgProcs]):
            pkgProcs = self._getRunningProcs(pkg, waiting=True)
        print 'Done'

        # get parent/child(ren) pid's
        pidParent = next((next((col for col in x.split() if col.isdigit()))
                for x in pkgProcs if CHILD_EXECUTABLE not in x))
        pidChild = [next((col for col in x.split() if col.isdigit()))
                for x in pkgProcs if CHILD_EXECUTABLE in x]
        pidChildParent = pidParent

        # see if any gdbserver instance is running, and discard
        # the debuggee from our list because it's already taken
        ps = adb.call(['shell', 'ps']).splitlines()
        for proc in [x.split() for x in ps if 'gdbserver' in x]:
            # get the program being debugged by examining gdbserver cmdline
            cmdline = adb.call(['shell', 'cat',
                    '/proc/' + next((col for col in proc if col.isdigit())) +
                    '/cmdline']).split('\0')
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
            pkgProcs = []
            print 'Waiting for child process...'
            while not any(pidChildParent in x and
                          CHILD_EXECUTABLE in x for x in pkgProcs):
                pkgProcs = self._getRunningProcs(pkg, waiting=True)
            pidChild = [next((col for col in x.split() if col.isdigit()))
                        for x in pkgProcs]

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
            sys.stdout.write('\nAttaching... ')
            sys.stdout.flush()
        self.pid = pidAttach

        gdbserver_port = ':' + str(self.gdbserver_port
                if hasattr(self, 'gdbserver_port') else 0)
        self._attachGDBServer(
                pkg,
                (PARENT_FILE_PATH if pidParent else CHILD_FILE_PATH),
                ['--once', '--attach', gdbserver_port, pidAttach])

        if pidParent:
            print '\nRun another gdb session to debug child process.'
        print '\nReady. Use "continue" to resume execution.'

    def _attachGDBServer(self, pkg, filePath, args,
                         skipShell = False, redirectOut = False):
        # always push gdbserver in case there's an old version on the device
        gdbserverPath = '/data/local/tmp/gdbserver'
        adb.push(os.path.join(self.bindir, 'gdbserver'), gdbserverPath)

        # run this after fork() and before exec(gdbserver)
        # so 'adb shell gdbserver' doesn't get gdb's signals
        def gdbserverPreExec():
            os.setpgrp()

        def runGDBServer(args): # returns (proc, port, stdout)
            proc = adb.call(args, stderr=subprocess.PIPE, async=True,
                    preexec_fn=gdbserverPreExec)
            # we have to find the port used by gdbserver from stdout
            # while this complicates things a little, it allows us to
            # have multiple gdbservers running
            out = []
            line = ' '
            while line:
                line = proc.stdout.readline()
                words = line.split()
                out.append(line.rstrip())
                # kind of hacky, assume the port number comes after 'port'
                if 'port' not in words:
                    continue
                if words.index('port') + 1 == len(words):
                    continue
                port = words[words.index('port') + 1]
                if not port.isdigit():
                    continue
                return (proc, port, None)
            # not found, error?
            return (None, None, out)

        # can we run as root?
        gdbserverProc = None
        gdbserverRootOut = ''
        if not skipShell:
            gdbserverArgs = ['shell', gdbserverPath]
            gdbserverArgs.extend(args)
            (gdbserverProc, port, gdbserverRootOut) = runGDBServer(gdbserverArgs)
        if not gdbserverProc:
            sys.stdout.write('as non-root... ')
            sys.stdout.flush()
            gdbserverArgs = ['shell', 'run-as', pkg, gdbserverPath]
            gdbserverArgs.extend(args)
            (gdbserverProc, port, gdbserverRunAsOut) = \
                    runGDBServer(gdbserverArgs)
        if not gdbserverProc:
            sys.stdout.write('as root... ')
            sys.stdout.flush()
            gdbserverArgs = [gdbserverPath]
            gdbserverArgs.extend(args)
            adb.call(['shell', 'echo', '#!/system/bin/sh\n' +
                    ' '.join(gdbserverArgs), '>', gdbserverPath + '.run'])
            adb.call(['shell', 'chmod', '755', gdbserverPath + '.run'])
            (gdbserverProc, port, gdbserverSuOut) = runGDBServer(
                    ['shell', 'su', '-c', gdbserverPath + '.run'])
        if not gdbserverProc:
            print ''
            if gdbserverRootOut:
                print '"gdbserver" output:'
                print ' ' + '\n '.join([s for s in gdbserverRootOut
                                        if s]).replace('\0', '')
            print '"run-as" output:'
            print ' ' + '\n '.join([s for s in gdbserverRunAsOut
                                    if s]).replace('\0', '')
            print '"su -c" output:'
            print ' ' + '\n '.join([s for s in gdbserverSuOut
                                    if s]).replace('\0', '')
            raise gdb.GdbError('failed to run gdbserver')

        self.port = port
        self.gdbserver = gdbserverProc

        # collect output from gdbserver in another thread
        def makeGdbserverWait(obj, proc):
            def gdbserverWait():
                if not redirectOut:
                    obj.gdbserverOut = proc.communicate()
                    return
                while proc.poll() == None:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    if adblog.continuing:
                        sys.__stderr__.write('\x1B[1mout> \x1B[22m' + line)
            return gdbserverWait;
        gdbserverThd = threading.Thread(
                name = 'GDBServer',
                target = makeGdbserverWait(self, gdbserverProc))
        gdbserverThd.daemon = True
        gdbserverThd.start()

        # forward the port that gdbserver gave us
        adb.forward('tcp:' + port, 'tcp:' + port)
        print 'Done'

        sys.stdout.write('Setting up remote debugging... ')
        sys.stdout.flush()
        # load the right file
        gdb.execute('file ' + filePath, False, True)
        gdb.execute('target remote :' + port, False, True)
        print 'Done'

    def _chooseCpp(self):
        rootdir = os.path.join(self.objdir, 'dist', 'bin') \
                  if self.objdir else os.getcwd()
        cpppath = ''
        def parseCpp(cmd):
            try:
                comps = shlex.split(cmd)
                # cpp_env is a user-defined variable
                # cppenv is an internal variable
                if hasattr(self, 'cpp_env'):
                    envcomps = shlex.split(self.cpp_env)
                    envcomps.extend(comps)
                    comps = envcomps
            except ValueError as e:
                print str(e)
                return ([], '', [])
            for i in range(len(comps)):
                if '=' in comps[i]:
                    continue
                return (comps[0: i], comps[i], comps[(i+1):])
            return (comps, '', [])
        while not os.path.isfile(cpppath):
            print 'Enter path of unit test ' \
                  '(use tab-completion to see possibilities)'
            if self.objdir:
                print '    path can be relative to $objdir/dist/bin or absolute'
            print '    environmental variables and arguments are supported'
            print '    e.g. FOO=bar TestFooBar arg1 arg2'
            cpppath = readinput.call(': ', '-f', '-c', rootdir,
                           '--file-mode', '0o100',
                           '--file-mode-mask', '0o100')
            cppenv, cpppath, cppargs = parseCpp(cpppath)
            cpppath = os.path.normpath(os.path.join(rootdir,
                                       os.path.expanduser(cpppath)))
            print ''
        self.cpppath = cpppath
        self.cppenv = [s.partition('=')[0] + '=' +
                       pipes.quote(s.partition('=')[-1])
                       for s in cppenv]
        self.cppargs = cppargs

    def _prepareCpp(self, pkg):
        if self._getRunningProcs(pkg):
            sys.stdout.write('Restarting %s... ' % pkg);
            sys.stdout.flush()
            # wait for fennec to stop
            self._killRunningProcs(pkg)
        else:
            # launch
            sys.stdout.write('Launching %s... ' % pkg)
            sys.stdout.flush()
        out = adb.call(['shell', 'am', 'start', '-n', pkg + '/.App',
                '--es', 'env0', 'MOZ_LINKER_EXTRACT=1'])
        if 'error' in out.lower():
            print '\n' + out
            raise gdb.GdbError('Error while launching %s.' % pkg)
        else:
            pkgProcs = None
            while not pkgProcs:
                pkgProcs = self._getRunningProcs(pkg, waiting=True)
            # sleep for 2s to allow time to launch
            time.sleep(2)
            print 'Done'

    def _attachCpp(self, pkg):
        cppPath = '/data/local/tmp/' + os.path.basename(self.cpppath)
        cppEnv = self.cppenv
        cppArgs = self.cppargs
        wrapperPath = '/data/local/tmp/cpptest.run'
        libPath = '/data/data/' + pkg + '/lib'
        cachePath = '/data/data/' + pkg + '/cache'
        profilePath = '/data/data/' + pkg + '/files/mozilla'

        sys.stdout.write('Attaching to test... ')
        sys.stdout.flush()
        adb.push(self.cpppath, cppPath)
        with tempfile.NamedTemporaryFile(delete = False) as f:
            lines = ['#!/system/bin/sh']
            lines.extend(['export ' + s for s in cppEnv])
            lines.append('export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:' +
                         libPath + ':' + cachePath)
            lines.append('exec $@')
            f.writelines('\n'.join(lines))
            tmpname = f.name
        adb.push(tmpname, wrapperPath)
        adb.call(['shell', 'chmod', '755', wrapperPath])
        os.remove(tmpname)

        skipShell = False
        if 'mozilla' not in adb.call(['shell', 'ls', profilePath]):
            skipShell = True

        gdbserver_port = ':' + str(self.gdbserver_port
                if hasattr(self, 'gdbserver_port') else 0)
        gdbserver_args = ['--once', '--wrapper', 'sh', wrapperPath, '--',
                          gdbserver_port, cppPath]
        gdbserver_args.extend(cppArgs)
        self._attachGDBServer(pkg, self.cpppath, gdbserver_args,
                              skipShell, True)

        print '\nReady. Use "continue" to start execution.'

    def _getTopSrcDir(self, objdir):
        if objdir:
            mkname = os.path.join(objdir, 'Makefile')
            try:
                mkfile = open(mkname)
                for line in mkfile:
                    if 'topsrcdir' not in line:
                        continue
                    mkfile.close()
                    topsrcdir = line.partition('=')[2].strip()
                    return topsrcdir
                mkfile.close()
            except IOError:
                pass
            topsrcdir = os.path.join(objdir, '..')
            if os.path.isfile(os.path.join(topsrcdir, 'client.mk')):
                return topsrcdir
        return None

    # returns (env, test, args)
    def _chooseMochitest(self, objdir):
        topsrcdir = self._getTopSrcDir(objdir)
        rootdir = topsrcdir if topsrcdir else os.getcwd()
        mochipath = ''
        def parseMochitest(cmd):
            cmd = os.path.expandvars(cmd)
            try:
                comps = shlex.split(cmd)
                # mochi_env is a user-defined variable
                if hasattr(self, 'mochi_env') and self.mochi_env:
                    envcomps = shlex.split(os.path.expandvars(self.mochi_env))
                    envcomps.extend(comps)
                    comps = envcomps
            except ValueError as e:
                print str(e)
                return ([], '', [])
            for i in range(len(comps)):
                if '=' in comps[i]:
                    continue
                return (comps[0: i], comps[i], comps[(i+1):])
            return (comps, '', [])
        while not os.path.isfile(mochipath) and \
              not os.path.isdir(mochipath):
            print 'Enter path of Mochitest (file or directory; ' \
                  'use tab-completion to see possibilities)'
            if topsrcdir:
                print '    path can be relative to the ' \
                      'source directory or absolute'
            print '    Fennec environment variables and ' \
                  'test harness arguments are supported'
            print '    e.g. NSPR_LOG_MODULES=all:5 test_foo_bar.html ' \
                  '--remote-webserver=0.0.0.0'
            mochipath = readinput.call(': ', '-f', '-c', rootdir,
                           '--file-mode', '0o000',
                           '--file-mode-mask', '0o100')
            mochienv, mochipath, mochiargs = parseMochitest(mochipath)
            mochipath = os.path.normpath(os.path.join(rootdir,
                                         os.path.expanduser(mochipath)))
            print ''
        if hasattr(self, 'mochi_args') and self.mochi_args:
            argscomps = shlex.split(os.path.expandvars(self.mochi_args))
            argscomps.extend(mochiargs)
            mochiargs = argscomps
        return ([s.partition('=')[0] + '=' +
                 pipes.quote(s.partition('=')[-1])
                 for s in mochienv], mochipath, mochiargs)

    def _getXREDir(self, datadir):
        def checkXREDir(xredir):
            if os.path.isfile(os.path.join(xredir, 'bin', 'xpcshell')):
                return os.path.join(xredir, 'bin')
            if os.path.isfile(os.path.join(xredir, 'xpcshell')):
                return xredir
            if os.path.isfile(xredir):
                return os.path.dirname(xredir)
            return None

        if hasattr(self, 'mochi_xre') and self.mochi_xre:
            xredir = checkXREDir(os.path.expandvars(
                                 os.path.expanduser(self.mochi_xre)))
            if xredir:
                return os.path.abspath(xredir)
            print 'mochi_xre directory does not contain xpcshell'

        xredatadir = os.path.abspath(
                     os.path.join(datadir, os.path.pardir, 'xre'))
        xreupdate = os.path.join(xredatadir, '.update')
        def touchUpdate():
            with open(xreupdate, 'a'):
                os.utime(xreupdate, None)

        xredir = checkXREDir(xredatadir)
        if xredir:
            if not os.path.isfile(xreupdate):
                touchUpdate()
            else:
                interval = (self.mochi_xre_update
                        if hasattr(self, 'mochi_xre_update') else 28)
                if time.time() - os.path.getmtime(xreupdate) >= \
                        interval * 24 * 60 * 60:
                    ans = ''
                    while not ans or (ans[0] != 'y' and ans[0] != 'Y' and
                                      ans[0] != 'n' and ans[0] != 'N'):
                        ans = readinput.call(
                            'Last checked for XRE update %d days ago; '
                            'update now? [yes/no]: ' %
                            ((time.time() - os.path.getmtime(xreupdate))
                                / 60 / 60 / 24),
                            '-l', str(['yes', 'no']))
                    print ''
                    if ans[0] == 'y' or ans[0] == 'Y':
                        shutil.rmtree(xredatadir, ignore_errors=True)
                        getxre.call(xredatadir, self.mochi_xre_url
                                    if hasattr(self, 'mochi_xre_url')
                                    else None)
                    # update timestamp regardless of choice above
                    touchUpdate()
        while not xredir:
            print 'Enter path of XRE directory containing xpcshell,'
            print ' or leave blank to download from ftp.mozilla.org (~100MB)'
            xredir = readinput.call(': ', '-d')
            print ''
            if not xredir:
                getxre.call(xredatadir, self.mochi_xre_url
                                        if hasattr(self, 'mochi_xre_url')
                                        else None)
                touchUpdate()
                xredir = xredatadir
            xredir = checkXREDir(xredir)
        return os.path.abspath(xredir)

    def _launchMochitest(self, pkg, objdir, xredir, sutenv, test, args):
        env = dict(os.environ)
        adbpath = str(gdb.parameter('adb-path'))
        if os.path.dirname(adbpath):
            # Mochitest harness only uses 'adb' to invoke adb
            env['PATH'] = ((env['PATH'] + os.path.pathsep)
                          if 'PATH' in env else '') + os.path.dirname(adbpath)
        dev = str(gdb.parameter('adb-device'))
        if dev:
            env['ANDROID_SERIAL'] = dev
        topsrcdir = self._getTopSrcDir(objdir)

        if objdir and os.path.isfile(os.path.join(objdir, 'Makefile')) and \
                      os.path.isdir(os.path.join(objdir, '_tests')):
            # use `make mochitest-remote`
            exe = ['make', '-C', objdir, 'mochitest-remote']
            env['DM_TRANS'] = 'adb'
            if pkg:
                env['TEST_PACKAGE_NAME'] = pkg
            env['MOZ_HOST_BIN'] = xredir
            if not topsrcdir:
                topsrcdir = os.path.join(objdir, os.path.pardir)
            env['TEST_PATH'] = os.path.relpath(test, topsrcdir)
            testargs = ['--setenv=' + s for s in sutenv]
            testargs.extend([pipes.quote(s) for s in args])
            env['EXTRA_TEST_ARGS'] = ' '.join(testargs)
        else:
            # use `python runtestsremote.py`
            script = 'runtestsremote.py'
            def checkHarness(harness):
                while not os.path.isfile(os.path.join(harness, script)):
                    harness = os.path.normpath(
                              os.path.join(harness, os.path.pardir))
                    if os.path.ismount(harness):
                        return None
                return os.path.normpath(harness)
            harness = checkHarness(test)
            if not harness:
                harness = checkHarness(os.path.join(xredir, os.path.pardir,
                                                    'mochitest'))
            if not harness and hasattr(self, 'mochi_harness') \
                           and self.mochi_harness:
                harness = checkHarness(self.mochi_harness)
            while not harness:
                harness = readinput.call('Enter "' + script + '" path: ', '-f')
            if not topsrcdir:
                testsdir = os.path.sep + 'tests' + os.path.sep
                testsidx = test.rfind(testsdir)
                if testsidx >= 0:
                    topsrcdir = test[0: testsidx + len(testsdir)]
                else:
                    topsrcdir = os.path.join(harness, 'tests')
            exe = [sys.executable, os.path.join(harness, script),
                   '--autorun', '--close-when-done', '--deviceIP=',
                   '--console-level=INFO', '--file-level=INFO',
                   '--dm_trans=adb', '--app=' + pkg, '--xre-path=' + xredir,
                   '--test-path=' + os.path.relpath(test, topsrcdir)]
            exe.extend(['--setenv=' + s for s in sutenv])
            exe.extend(args)

        # run this before exec() so child doesn't get gdb's signals
        print 'Launching Mochitest... '

        # first kill off any running instance
        self._killRunningProcs(pkg)

        def exePreExec():
            os.setpgrp()
        proc = subprocess.Popen(exe, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                preexec_fn=exePreExec, env=env)

        line = proc.stdout.readline()
        while line and proc.poll() == None:
            print '\x1B[1mout> \x1B[22m' + line.strip()
            if 'INFO' in line and 'application pid' in line.lower():
                # test launched
                break
            line = proc.stdout.readline()

        if not line or proc.poll():
            raise gdb.GdbError('Test harness exited '
                               'without launching Fennec.')

        # collect further output in another thread
        def makeOutputWait(obj, proc):
            def outputWait():
                while proc.poll() == None:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    if 'INFO' in line and \
                        ('TEST-PASS' in line or 'TEST-KNOWN-FAIL' in line):
                        # don't log passing tests
                        continue
                    if line.startswith('----') and '/dev/log' in line:
                        # start of log dump
                        proc.communicate()
                        break
                    if adblog.continuing:
                        sys.__stderr__.write('\x1B[1mout> \x1B[22m' + line)
            return outputWait;
        outThd = threading.Thread(
                name = 'Mochitest',
                target = makeOutputWait(self, proc))
        outThd.daemon = True
        outThd.start()
        return proc

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
            if hasattr(self, '_mochitest') and self._mochitest:
                if self._mochitest.poll() is None:
                    print 'Already in remote Mochitest mode.'
                    return
                delattr(self, '_mochitest')
            self._task = self._chooseTask()
            self._chooseDevice()
            self._chooseObjdir()
            self._pullLibsAndSetPaths()
            
            datadir = str(gdb.parameter('data-directory'))
            objdir = self.objdir
            pkg = self._getPackageName(objdir)
            if self._task == self.TASK_FENNEC:
                no_launch = hasattr(self, 'no_launch') and self.no_launch
                if not no_launch:
                    self._launch(pkg)
                self._attach(pkg)
            elif self._task == self.TASK_MOCHITEST:
                xredir = self._getXREDir(datadir)
                env, test, args = self._chooseMochitest(objdir)
                self._mochitest = self._launchMochitest(
                        pkg, objdir, xredir, env, test, args)
                self._attach(pkg)
            elif self._task == self.TASK_CPP_TEST:
                self._chooseCpp()
                self._prepareCpp(pkg)
                self._attachCpp(pkg)

            self.dont_repeat()
        except:
            # if there is an error, a gdbserver might be left hanging
            if hasattr(self, 'gdbserver') and self.gdbserver:
                if self.gdbserver.poll() is None:
                    self.gdbserver.terminate()
                    print 'Terminated gdbserver.'
                delattr(self, 'gdbserver')
            if hasattr(self, '_mochitest') and self._mochitest:
                if self._mochitest.poll() is None:
                    self._mochitest.terminate()
                    print 'Terminated Mochitest.'
                delattr(self, '_mochitest')
            raise
        finally:
            gdb.execute('set height ' + str(saved_height), False, False)

default = FenInit()

