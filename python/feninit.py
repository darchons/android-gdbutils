# vi: set tabstop=4 shiftwidth=4 expandtab:
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import gdb, adb, readinput, adblog, getxre
import os, sys, subprocess, threading, time, shlex, tempfile, pipes, shutil, re

class FenInit(gdb.Command):
    '''Initialize gdb for debugging Fennec on Android'''

    TASKS = (
        'Debug Fennec (default)',
        'Debug Fennec with env vars and args',
        'Debug using jdb',
        'Debug content Mochitest',
        'Debug compiled-code unit test',
        'Debug Fennec with pid'
    )
    (
        TASK_FENNEC,
        TASK_FENNEC_ENV,
        TASK_JAVA,
        TASK_MOCHITEST,
        TASK_CPP_TEST,
        TASK_ATTACH_PID,
    ) = tuple(range(len(TASKS)))

    def __init__(self):
        super(FenInit, self).__init__('feninit', gdb.COMMAND_SUPPORT)

    def complete(self, text, word):
        return gdb.COMPLETE_NONE

    def _chooseTask(self):
        if ('SSH_CONNECTION' in os.environ and
            os.environ['SSH_CONNECTION'] and
            'ANDROID_ADB_SERVER_PORT' in os.environ and
            os.environ['ANDROID_ADB_SERVER_PORT']):
            gdbserver_set = hasattr(self, 'gdbserver_port') and \
                            self.gdbserver_port
            jdwp_set = hasattr(self, 'jdwp_port') and self.jdwp_port
            if not gdbserver_set or not jdwp_set:
                print '\n********'
                print '* Pro-tip: you seem to be forwarding ADB through SSH'
                if not gdbserver_set:
                    print '* configure gdbserver_port in gdbinit.local to set the ' \
                          'forwarding port for gdb debugging'
                if not jdwp_set:
                    print '* configure jdwp_port in gdbinit.local to set the ' \
                          'forwarding port for jdb debugging'
                print '********'
        print '\nFennec GDB utilities'
        print '  (see utils/gdbinit and utils/gdbinit.local on how to configure settings)'
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

    def _isObjDir(self, abspath):
        return os.path.isdir(abspath) and \
            os.path.isfile(os.path.join(abspath, 'Makefile')) and \
            os.path.isdir(os.path.join(abspath, 'dist'))

    def _chooseObjdir(self):
        def scanSrcDir(objdirs, path):
            # look for 'obj*' directories, using 'dist' as a clue
            abspath = os.path.abspath(path)
            if abspath in objdirs or not os.path.isdir(abspath):
                return
            if self._isObjDir(abspath):
                objdirs.insert(0, abspath)
                return
            for d in os.listdir(abspath):
                if not d.startswith('obj'):
                    continue
                objdir = os.path.join(abspath, d)
                if objdir in objdirs:
                    continue
                if self._isObjDir(objdir):
                    objdirs.insert(0, objdir)

        objdir = '' # None means don't use an objdir
        objdirs = []
        # look for possible locations
        srcroot = os.path.expanduser(os.path.expandvars(
            self.srcroot if hasattr(self, 'srcroot') else '~'))
        for d in os.listdir(srcroot):
            scanSrcDir(objdirs, os.path.join(srcroot, d))
        objdirs.sort()

        # use saved setting if possible; also allows gdbinit to set objdir
        if hasattr(self, 'objdir'):
            if self.objdir:
                objdir = os.path.abspath(os.path.expanduser(
                        os.path.expandvars(self.objdir)))
                scanSrcDir(objdirs, objdir)
                if not any((s.startswith(objdir) for s in objdirs)):
                    print 'Preset object directory (%s) is invalid' % objdir
            else:
                # self.objdir specifically set to not use objdir
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

        searchPaths = [os.path.join(libdir, os.path.join(*d)) \
                for d in DEFAULT_SEARCH_PATHS]
        if self.objdir:
            searchPaths.append(os.path.join(self.objdir, 'dist', 'bin'))
            searchPaths.append(os.path.join(self.objdir, 'dist', 'lib'))
        gdb.execute('set solib-search-path ' +
                os.pathsep.join(searchPaths), False, True)
        print 'Updated solib-search-path.'

    def _extractApk(self, pkg, bindir, libdir):
        sys.stdout.write('Pulling apk for symbols... ')
        sys.stdout.flush()
        apk = self._getPackageApk(pkg)
        if not apk:
            print 'Could not find apk.'
            return

        def findSzip(path):
            try:
                with open(os.devnull, 'w') as devnull:
                    subprocess.call(path, stdout=devnull, stderr=devnull)
                return path
            except OSError:
                pass
            return None
        szip = findSzip(os.path.join(bindir, 'szip')) or \
               findSzip('szip')
        if not szip:
            print '*** Could not find szip tool ***'
            return

        import zipfile
        appdir = os.path.join(libdir, 'app', pkg)
        if os.path.isdir(appdir):
            shutil.rmtree(appdir, ignore_errors=True)
        apppath = os.path.join(appdir, 'app.apk')
        adb.pull(apk, apppath)
        print 'Done'

        sys.stdout.write('Extracting apk... ')
        sys.stdout.flush()
        apkzip = zipfile.ZipFile(apppath, 'r')
        try:
            if any(not os.path.realpath(os.path.join(appdir, f)).startswith(
                   os.path.realpath(appdir))
                   for f in apkzip.namelist()):
                # extracted file will be outside of the destination directory
                raise gdb.GdbError('Invalid apk file')
            apkzip.extractall(appdir)
        finally:
            apkzip.close()
        print 'Done'

        sys.stdout.write('Un-szipping solibs... ')
        sys.stdout.flush()
        dirs = [gdb.parameter('solib-search-path')]
        with open(os.devnull, 'w') as devnull:
            for root, dirnames, filenames in os.walk(appdir):
                for sofile in (fn for fn in filenames if fn.endswith('.so')):
                    subprocess.check_call([szip, '-d', os.path.join(root, sofile)],
                        stdout=devnull, stderr=devnull)
                    if root not in dirs:
                        dirs.append(root)
        print 'Done'

        gdb.execute('set solib-search-path ' + os.pathsep.join(dirs), False, True)
        print 'Updated solib-search-path'

    def _getPackageApk(self, pkg):
        devpkgs = adb.call(['shell', 'pm', 'list', 'packages', '-f'])
        if not devpkgs.strip():
            return None
        for devpkg in (l.strip() for l in devpkgs.splitlines()):
            if not devpkg:
                continue
            # devpkg has the format 'package:/data/app/pkg.apk=pkg'
            devpkg = devpkg.partition('=')
            if pkg != devpkg[2]:
                continue
            return devpkg[0].partition(':')[2]
        return ''

    def _verifyPackage(self, objdir, pkg):
        if not objdir or not pkg:
            return True
        # get base package name without any webapp part
        pkg = pkg.partition(':')[0]

        apkprefix = self._getAppName(objdir) + '-'
        apks = []
        distdir = os.path.join(objdir, 'dist')
        for f in os.listdir(distdir):
            if f.lower().startswith(apkprefix) and f.lower().endswith('.apk'):
                apks.append(os.path.join(distdir, f))
        if not apks:
            return True
        apks.sort(key=lambda f: os.path.getmtime(f))
        apk = apks[-1]

        while True:
            devapk = self._getPackageApk(pkg)

            if devapk is None:
                return True

            if devapk:
                devapkls = adb.call(['shell', 'ls', '-l', devapk])
                devapksize = [int(f, 0) for f in devapkls.split()
                        if f.isdigit() and int(f, 0) > 1024 * 1024]
                if not devapksize:
                    return True
                if devapksize[0] == os.path.getsize(apk):
                    return True

            if devapk:
                print 'Package %s does not seem to match file %s.' % \
                        (pkg, os.path.basename(apk))
            else:
                print 'Package %s does not seem to exist.' % pkg
            ans = None
            while not ans or (ans[0] != 'y' and ans[0] != 'Y' and
                              ans[0] != 'n' and ans[0] != 'N'):
                ans = readinput.call('Reinstall apk? [yes/no]: ',
                        '-l', str(['yes', 'no']))
            print
            if ans[0] == 'n' or ans[0] == 'N':
                return False
            sys.stdout.write('adb install -r... ')
            sys.stdout.flush()
            adbout = adb.call(['install', '-r', apk],
                    stderr=subprocess.PIPE).splitlines()
            adbout = [f for f in adbout if f.strip()]
            if not adbout:
                adbout = ['No output?!']
            print adbout[-1]
            if 'success' in adbout[-1].lower():
                continue

            ans = None
            while not ans or (ans[0] != 'y' and ans[0] != 'Y' and
                              ans[0] != 'n' and ans[0] != 'N'):
                ans = readinput.call('Uninstall then install? [yes/no]: ',
                        '-l', str(['yes', 'no']))
            print
            if ans[0] == 'n' or ans[0] == 'N':
                return False
            sys.stdout.write('adb uninstall...')
            sys.stdout.flush()
            adb.call(['uninstall', pkg],
                    stderr=subprocess.PIPE)
            sys.stdout.write('\nadb install... ');
            sys.stdout.flush()
            adbout = adb.call(['install', '-r', apk],
                    stderr=subprocess.PIPE).splitlines()
            adbout = [f for f in adbout if f.strip()]
            if not adbout:
                adbout = ['No output?!']
            print adbout[-1]

    def _getAppName(self, objdir):
        try:
            with open(os.path.join(objdir, 'config', 'autoconf.mk')) as acfile:
                for line in acfile:
                    line = line.partition('=')
                    if line[0].strip() != 'MOZ_APP_NAME' or not line[2]:
                        continue
                    return line[2].strip()
        except IOError:
            pass
        return 'fennec'

    def _isWebAppPackage(self, pkg):
        return ':' in pkg and '.WebApp' in pkg

    def _getPackageName(self, objdir, webapps=False):
        pkgs = None
        if objdir:
            appname = self._getAppName(objdir)
            acname = os.path.join(objdir, 'config', 'autoconf.mk')
            try:
                acfile = open(acname)
                for line in acfile:
                    if 'ANDROID_PACKAGE_NAME' not in line:
                        continue
                    pkgs = [line.partition('=')[2].strip()
                                .replace('$(MOZ_APP_NAME)', appname)]
                    if webapps:
                        webapppkg = ':' + pkgs[0] + '.WebApp'
                        pkgs.extend([re.split(r'[ \t/]', p.strip())[-1]
                            for p in self._getRunningProcs(None)
                            if webapppkg in p])
                    if len(pkgs) < 2:
                        acfile.close()
                        print 'Using package %s.' % pkgs[0]
                        return pkgs[0]
                acfile.close()
            except IOError:
                pass
        if not pkgs:
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
        return [x for x in ps if
                (not pkg or pkg in re.split(r'[ \t/]', x)) and
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

        try:
            # try twice
            for i in range(2):
                for p in pkgProcs:
                    adb.call(['shell', 'run-as', pkg, 'kill', '-9',
                              next(c for c in p.split() if c.isdigit())])
                time.sleep(2)
                pkgProcs = self._getRunningProcs(pkg)
                if not pkgProcs:
                    return
        except:
            pass

        pkgProcs = self._getRunningProcs(pkg)
        if not pkgProcs:
            return
        for p in pkgProcs:
            print p
        raise gdb.GdbError(
            'Could not kill running %s process.' % pkg)

    def _chooseEnvVars(self):
        print 'Enter environmental variables and arguments'
        print '    e.g. NSPR_LOG_MODULES=all:5 www.mozilla.org -profile <dir>'
        cmd = readinput.call(': ')
        env, cmd, args = self.parseCommand(cmd,
            self.env if hasattr(self, 'env') and self.env else None,
            self.args if hasattr(self, 'args') and self.args else None, False)
        return (self.quoteEnv(env), args)

    def _launch(self, pkg):
        sys.stdout.write('Launching %s... ' % pkg)
        sys.stdout.flush()
        # always launch in case the activity is not in foreground
        args = ['shell', 'am', 'start', '-n', pkg + '/.App', '-W']
        extraArgs = []
        kill = False
        if hasattr(self, '_env') and self._env:
            envcount = 0
            for envvar in self._env:
                extraArgs += ['--es', 'env' + str(envcount), envvar]
                envcount += 1
            kill = True
        if hasattr(self, '_args') and self._args:
            if not self._args[0].startswith('-'):
                # assume data URI
                extraArgs += ['-d', self._args.pop(0)]
            extraArgs += ['--es', 'args', ' '.join(
                [pipes.quote(s) for s in self._args])]
            kill = True
        if kill:
            # kill first if we have any env vars or args
            self._killRunningProcs(pkg)
        out = adb.call(args + extraArgs)
        self.amExtraArgs = extraArgs
        if 'error' in out.lower():
            print ''
            print out
            raise gdb.GdbError('Error while launching %s.' % pkg)

    def _linkJavaSources(self, srcdir, objdir):
        # top dir of symbolic links
        targetdir = os.path.join(objdir, 'mobile', 'android', 'base', 'jdb')
        if not os.path.isdir(targetdir):
            os.makedirs(targetdir)
        # list of already linked java files
        knownSources = []
        for dirpath, dirnames, filenames in os.walk(targetdir):
            knownSources += [os.path.normpath(os.path.join(dirpath,
                os.readlink(os.path.join(dirpath, filename))))
                for filename in filenames]
        # link to a single source file
        def linkSource(filename):
            target = None
            with open(filename, 'r') as f:
                for line in f:
                    sline = line.split(';')[0].strip().split()
                    if len(sline) != 2 or sline[0] != 'package':
                        continue
                    # create java-style source dirs
                    target = os.path.join(*([targetdir] + sline[1].split('.')))
                    if not os.path.isdir(target):
                        os.makedirs(target)
                    break
            if not target:
                return
            # create relative symbolic link
            linkname = os.path.join(target, os.path.basename(filename))
            linktarget = os.path.relpath(filename, target)
            if not os.path.exists(linkname):
                os.symlink(linktarget, linkname)
        def linkSourceDir(root):
            # skip 'classes' dir which contains only '.class' files
            objdirclasses = os.path.join(objdir,
                'mobile', 'android', 'base', 'classes')
            for dirpath, dirnames, filenames in os.walk(root):
                if dirpath.startswith(targetdir) or \
                    dirpath.startswith(objdirclasses):
                    continue
                for filename in filenames:
                    if not filename.endswith('.java'):
                        continue
                    filename = os.path.join(dirpath, filename)
                    if filename in knownSources:
                        return
                    linkSource(filename)

        linkSourceDir(os.path.join(srcdir, 'mobile', 'android', 'base'))
        linkSourceDir(os.path.join(objdir, 'mobile', 'android', 'base'))
        return targetdir

    def _attach(self, pkg, use_jdb):
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

        if not use_jdb and pidParent:
            # the parent is not being debugged, pick the parent
            pidAttach = pidParent
            sys.stdout.write('Attaching to pid %s... ' % pidAttach)
            sys.stdout.flush()
        elif use_jdb or (not pidChild and
                        not (hasattr(self, 'no_jdb') and self.no_jdb)):
            # ok, no child is available. assume the user wants to launch jdb
            linkdir = None
            objdir = self.objdir
            srcdir = self._getTopSrcDir(objdir)
            if objdir and srcdir:
                print 'Creating source path links...'
                linkdir = self._linkJavaSources(srcdir, objdir)
            print 'Starting jdb for pid %s... ' % pidChildParent
            with open(os.devnull,"w") as devnull:
                if subprocess.call(['which', 'jdb'], stdout=devnull) != 0:
                    print 'jdb not found. Please install jdb.'
                    return
            jdwp = adb.call(['jdwp']).splitlines()
            if pidChildParent not in jdwp:
                print ('%s process (%s) does not support jdwp.' %
                    (pkg, pidChildParent))
                return
            jdwp_port = str(self.jdwp_port if hasattr(self, 'jdwp_port')
                                           else (0x8000 | int(pidChildParent)))
            adb.forward('tcp:' + jdwp_port, 'jdwp:' + pidChildParent)
            sourcepath = []
            print
            jdb_args = ['jdb', '-attach', 'localhost:' + jdwp_port]
            if linkdir:
                jdb_args += ['-sourcepath', linkdir]
            subprocess.call(jdb_args)
            return
        elif not pidChild:
            # ok, no child is available. assume the user
            # wants to wait for child to start up
            pkgProcs = []
            print 'Waiting for child process...'
            while not any(pidChildParent in x and
                          CHILD_EXECUTABLE in x for x in pkgProcs):
                pkgProcs = self._getRunningProcs(pkg, waiting=True)
                time.sleep(1)
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

        print '\nReady. Use "continue" to resume execution.'

    def _attachPid(self, pkg, pid):
        path = os.path.join(self.libdir,
                'system', 'bin', 'app_process')

        self.pid = pid
        gdbserver_port = ':' + str(self.gdbserver_port
                if hasattr(self, 'gdbserver_port') else 0)
        self._attachGDBServer(
                pkg,
                path,
                ['--once', '--attach', gdbserver_port, pid])

        print '\nReady. Use "continue" to resume execution.'

    def _attachGDBServer(self, pkg, filePath, args,
                         skipShell = False, redirectOut = False):
        # get base package name without any webapp part
        pkg = pkg.partition(':')[0]

        # always push gdbserver in case there's an old version on the device
        gdbserverPath = '/data/local/tmp/gdbserver'
        adb.push(os.path.join(self.bindir, 'gdbserver'), gdbserverPath)
        adb.call(['shell', 'chmod', '755', gdbserverPath])

        # run this after fork() and before exec(gdbserver)
        # so 'adb shell gdbserver' doesn't get gdb's signals
        def gdbserverPreExec():
            os.setpgrp()

        def runGDBServer(args): # returns (proc, port, stdout)
            proc = adb.call(args, stderr=subprocess.PIPE, async=True,
                    preexec_fn=gdbserverPreExec)
            need_watchdog = True
            def watchdog():
                time.sleep(10)
                if need_watchdog and proc.poll() is None: # still running
                    proc.terminate()
            (threading.Thread(target=watchdog)).start()

            # we have to find the port used by gdbserver from stdout
            # while this complicates things a little, it allows us to
            # have multiple gdbservers running
            out = []
            line = ' '
            while line:
                line = proc.stdout.readline()
                words = line.split()
                out.append(line.rstrip())
                if 'gdbserver terminated by' in line:
                    break
                # kind of hacky, assume the port number comes after 'port'
                if 'port' not in words:
                    continue
                if words.index('port') + 1 == len(words):
                    continue
                port = words[words.index('port') + 1]
                if not port.isdigit():
                    continue
                need_watchdog = False
                return (proc, port, out)
            # not found, error?
            need_watchdog = False
            return (None, None, out)

        # can we run as root?
        gdbserverProc = None
        gdbserverRootOut = ''
        intentPid = None
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
            sys.stdout.write('using intent... ')
            sys.stdout.flush()
            self._killRunningProcs(pkg)
            adb.call(['logcat', '-c'])
            adb.call(['shell', 'am', 'start', '-W', '-n', pkg + '/.App',
                      '-a', 'org.mozilla.gecko.DEBUG',
                      '--es', 'gdbserver', ' '.join(args)] +
                      getattr(self, 'amExtraArgs', []))
            (gdbserverProc, port, gdbserverAmOut) = runGDBServer(
                    ['logcat', '-s', '-v', 'process', 'gdbserver:V'])
            if gdbserverAmOut:
                intentPid = gdbserverAmOut[0][2:7]
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
            print '"am start" output:'
            print ' ' + '\n '.join([s for s in gdbserverAmOut
                                    if s]).replace('\0', '')
            if any('not executable: magic' in s for s in gdbserverRootOut):
                print '\n********'
                print '* Your device platform is not supported by this GDB'
                print '* Use jimdb-x86 for x86 targets/devices'
                print '* Use jimdb-arm for ARM targets/devices'
                print '********\n'
            raise gdb.GdbError('failed to run gdbserver')

        self.port = port
        self.gdbserver = gdbserverProc

        # collect output from gdbserver in another thread
        def makeGdbserverWait(obj, proc):
            def gdbserverWait():
                if not intentPid and not redirectOut:
                    obj.gdbserverOut = proc.communicate()
                    return
                while proc.poll() == None:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    if intentPid and intentPid in line and \
                            'gdbserver terminated by' in line:
                        proc.terminate()
                        break
                    if adblog.continuing:
                        sys.__stderr__.write('\x1B[1mout> \x1B[22m' + line)
            return gdbserverWait
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

    # returns (env, cmd, args)
    def parseCommand(self, cmd, extra_env=None, extra_args=None, has_cmd=True):
        try:
            comps = shlex.split(cmd)
            # cpp_env is a user-defined variable
            # cppenv is an internal variable
            if extra_env:
                comps = shlex.split(extra_env) + comps
            if extra_args:
                comps += shlex.split(extra_args)
        except ValueError as e:
            print str(e)
            return ([], '', [])
        comps = [os.path.expandvars(s) for s in comps]
        for i in range(len(comps)):
            if '=' in comps[i]:
                continue
            if has_cmd:
                return (comps[0: i], comps[i], comps[(i+1):])
            return (comps[0: i], '', comps[i:])
        return (comps, '', [])

    def quoteEnv(self, env):
        def _quote(s):
            comps = s.partition('=')
            return comps[0] + '=' + pipes.quote(comps[-1])
        return [_quote(s) for s in env]

    def _chooseCpp(self):
        rootdir = os.path.join(self.objdir, 'dist', 'bin') \
                  if self.objdir else os.getcwd()
        cpppath = ''
        testpath = (os.environ['TEST_PATH']
            if 'TEST_PATH' in os.environ else None)
        while not os.path.isfile(cpppath):
            print 'Enter path of unit test ' \
                  '(use tab-completion to see possibilities)'
            if self.objdir:
                print '    path can be relative to $objdir/dist/bin or absolute'
            print '    environmental variables and arguments are supported'
            print '    e.g. FOO=bar TestFooBar arg1 arg2'
            if testpath:
                print 'Leave empty to use TEST_PATH (%s)' % testpath
            cpppath = readinput.call(': ', '-f', '-c', rootdir,
                           '--file-mode', '0o100',
                           '--file-mode-mask', '0o100')
            if not cpppath and testpath:
                cpppath = testpath
            cppenv, cpppath, cppargs = self.parseCommand(cpppath, self.cpp_env
                if hasattr(self, 'cpp_env') and self.cpp_env else None)
            cpppath = os.path.normpath(os.path.join(rootdir,
                                       os.path.expanduser(cpppath)))
            print ''
        self.cpppath = cpppath
        self.cppenv = self.quoteEnv(cppenv)
        self.cppargs = cppargs

    def _prepareCpp(self, pkg):
        if self._getRunningProcs(pkg):
            sys.stdout.write('Restarting %s... ' % pkg)
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
            f.write('\n'.join(lines))
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
        testpath = (os.environ['TEST_PATH']
            if 'TEST_PATH' in os.environ else None)
        while not os.path.isfile(mochipath) and \
              not os.path.isdir(mochipath):
            print 'Enter path of Mochitest (file or directory)'
            print '    use tab-completion to see possibilities'
            if topsrcdir:
                print '    path can be relative to the ' \
                      'source directory or absolute'
            print '    Fennec environment variables and ' \
                  'test harness arguments are supported'
            print '    e.g. NSPR_LOG_MODULES=all:5 test_foo_bar.html ' \
                  '--remote-webserver=0.0.0.0'
            if testpath:
                print 'Leave empty to use TEST_PATH (%s)' % testpath
            mochipath = readinput.call(': ', '-f', '-c', rootdir,
                           '--file-mode', '0o000',
                           '--file-mode-mask', '0o100')
            if not mochipath and testpath:
                mochipath = testpath
            mochienv, mochipath, mochiargs = self.parseCommand(mochipath,
                self.mochi_env if hasattr(self, 'mochi_env')
                    and self.mochi_env else None,
                self.mochi_args if hasattr(self, 'mochi_args')
                    and self.mochi_args else None)
            mochipath = os.path.normpath(os.path.join(rootdir,
                                         os.path.expanduser(mochipath)))
            print ''
        return (mochienv, mochipath, mochiargs)

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
            testargs = ['--setenv=' + s for s in self.quoteEnv(sutenv)]
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
                time.sleep(2)
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
            return outputWait
        outThd = threading.Thread(
                name = 'Mochitest',
                target = makeOutputWait(self, proc))
        outThd.daemon = True
        outThd.start()
        return proc

    def _choosePid(self):
        print 'Enter PID'
        return readinput.call(': ', '-d')

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
            pkg = self._getPackageName(objdir,
                webapps=(self._task in (self.TASK_FENNEC, self.TASK_JAVA)))
            self._verifyPackage(objdir, pkg)

            if not objdir and pkg:
                # extract apk to get symbols
                self._extractApk(pkg, self.bindir, self.libdir)

            if (self._task == self.TASK_FENNEC or
                self._task == self.TASK_FENNEC_ENV or
                self._task == self.TASK_JAVA):
                if self._task == self.TASK_FENNEC_ENV:
                    self._env, self._args = self._chooseEnvVars()
                else:
                    self._env, self._args = [], []
                no_launch = hasattr(self, 'no_launch') and self.no_launch
                if not no_launch and not self._isWebAppPackage(pkg):
                    self._launch(pkg)
                else:
                    sys.stdout.write('Attaching to %s... ' % pkg)
                    sys.stdout.flush()
                self._attach(pkg, self._task == self.TASK_JAVA)
            elif self._task == self.TASK_MOCHITEST:
                xredir = self._getXREDir(datadir)
                env, test, args = self._chooseMochitest(objdir)
                self._mochitest = self._launchMochitest(
                        pkg, objdir, xredir, env, test, args)
                self._attach(pkg, False)
            elif self._task == self.TASK_CPP_TEST:
                self._chooseCpp()
                self._prepareCpp(pkg)
                self._attachCpp(pkg)
            elif self._task == self.TASK_ATTACH_PID:
                pid = self._choosePid()
                self._attachPid(pkg, pid)

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

