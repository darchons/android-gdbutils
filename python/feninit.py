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

import gdb, adb, readinput, os, sys

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
        adb.setDevice()

        while not devs:
            try:
                print 'ADB: waiting for device... (Ctrl+C to stop)'
                adb.waitForDevice()
            except gdb.GdbError, KeyboardInterrupt:
                raise gdb.GdbError(' ADB: no device')
            devs = adb.getDevices()

        if hasattr(self, 'device'):
            dev = self.device
            if not dev in devs:
                print 'feninit.default.device (%s) is not connected' % dev
        if len(devs) == 1:
            dev = devs[0]
        while not dev in devs:
            print 'Found multiple devices:'
            for i in range(len(devs)):
                print '%d. %s' % (i + 1, devs[i])
            dev = readinput.call('Choose device: ', '-l', str(devs))
            if dev.isdigit() and int(dev) > 0 and int(dev) <= len(devs):
                dev = devs[int(dev) - 1]
            elif len(dev) > 0:
                matchDev = filter(lambda x:
                        x.lower().startswith(dev.lower()), devs)
                if len(matchDev) == 1:
                    dev = matchDev[0]
        print 'Using device %s' % dev
        adb.setDevice(dev)
        self.device = dev

    def _chooseObjdir(self):
        # identify objdir
        def scanSrcDir(objdirs, path):
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
        objdir = ''
        objdirs = []
        scanSrcDir(objdirs, '~/mozilla-central')
        scanSrcDir(objdirs, '~/central')
        scanSrcDir(objdirs, '~/mozilla-aurora')
        scanSrcDir(objdirs, '~/aurora')
        scanSrcDir(objdirs, '~/mozilla-beta')
        scanSrcDir(objdirs, '~/beta')
        scanSrcDir(objdirs, '~/mozilla-release')
        scanSrcDir(objdirs, '~/release')
        objdirs.sort()

        if hasattr(self, 'objdir'):
            objdir = self.objdir
            if not objdir in objdirs:
                print 'feninit.default.objdir (%s) is not found' % objdir
        if len(objdirs) == 1:
            objdir = objdirs[0]
        while not objdir in objdirs:
            if objdirs:
                print 'Found multiple object directories:'
                for i in range(len(objdirs)):
                    print '%d. %s' % (i + 1, objdirs[i])
                print 'Choose object directory from above or enter alternative'
                objdir = readinput.call(': ', '-d')
            else:
                print 'No object directory found.'
                objdir = readinput.call('objdir: ', '-d')
            if objdir.isdigit() and int(objdir) > 0 and \
                    int(objdir) <= len(objdirs):
                objdir = objdirs[int(objdir) - 1]
            elif len(objdir) > 0:
                objdir = os.path.abspath(os.path.expanduser(objdir))
                matchObjdir = filter(lambda x:
                        x.startswith(objdir), objdirs)
                if len(matchObjdir) == 0:
                    scanSrcDir(objdirs, objdir)
                elif len(matchObjdir) == 1:
                    objdir = matchObjdir[0]
        print 'Using object directory: %s' % objdir
        self.objdir = objdir

    def _pullLibsAndSetPaths(self):
        DEFAULT_LIBS = ['lib/libdl.so', 'lib/libc.so', 'lib/libm.so',
                'lib/libstdc++.so', 'lib/liblog.so', 'lib/libz.so',
                'lib/libGLESv2.so', 'bin/linker', 'bin/app_process']
        if not hasattr(self, 'device') or not self.device or \
                not hasattr(self, 'device') or not self.objdir:
            return
        datadir = str(gdb.parameter('data-directory'))
        libdir = os.path.abspath(os.path.join(datadir,
                os.pardir + os.sep + 'lib' + os.sep + self.device))
        sys.stdout.write('Pulling libraries to %s... ' % libdir)
        sys.stdout.flush()
        for lib in DEFAULT_LIBS:
            try:
                dstpath = os.path.join(libdir, lib)
                if not os.path.exists(dstpath):
                    adb.pull('/system/' + lib, dstpath)
            except gdb.GdbError:
                sys.stdout.write('\n cannot pull %s... ' % lib)
        print 'Done'
        gdb.execute('set solib-absolute-prefix ' + libdir, False, True)
        print 'Set solib-absolute-prefix to "%s"' % libdir

        objlibdir = 

    def _setSymbolsDir(self):
        pass

    def invoke(self, argument, from_tty):
        self._chooseDevice()
        self._chooseObjdir()
        self._pullLibsAndSetPaths()
        # push gdbserver
        # forward port
        # am start
        # attach gdbserver
        self.dont_repeat()

default = FenInit()

