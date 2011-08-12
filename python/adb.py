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

import gdb, subprocess, readinput

returncode = 0

def call(args, **kw):
    cmd = [str(gdb.parameter('adb-path'))]
    dev = str(gdb.parameter('adb-device'))
    if dev:
        cmd.extend(['-s', dev])
    cmd.extend(args)
    async = False
    if 'async' in kw:
        async = kw['async']
        del kw['async']
    if 'stdin' not in kw:
        kw['stdin'] = subprocess.PIPE
    if 'stdout' not in kw:
        kw['stdout'] = subprocess.PIPE
    try:
        adb = subprocess.Popen(cmd, **kw)
        if async:
            return adb
        out = adb.communicate()[0]
        returncode = adb.returncode
    except OSError as e:
        raise gdb.GdbError('cannot run adb: ' + str(e))
    if adb.returncode != 0:
        raise gdb.GdbError('adb returned exit code ' + str(adb.returncode))
    return out

def getDevices():
    devs = []
    for sdev in call(['devices']).splitlines():
        devparts = sdev.partition('\t')
        if devparts[2] != 'device':
            continue
        devs.append(devparts[0].strip())
    return devs

def waitForDevice():
    call(['wait-for-device'])

def chooseDevice():
    # identify device
    devs = getDevices()

    # wait for a device if no device is found
    while not devs:
        try:
            print 'ADB: waiting for device... (Ctrl+C to stop)'
            waitForDevice()
        except gdb.GdbError, KeyboardInterrupt:
            raise gdb.GdbError(' ADB: no device')
        devs = getDevices()

    # use saved setting if possible; also allows gdbinit to set device
    dev = str(gdb.parameter('adb-device'))
    if dev and dev not in devs:
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
    if str(gdb.parameter('adb-device')) != dev:
        gdb.execute('set adb-device ' + dev)
    return dev

def pull(src, dest):
    params = ['pull']
    if isinstance(src, list):
        params.extend(src)
    else:
        params.append(str(src))
    params.append(dest)
    call(params, stderr=subprocess.PIPE)

def push(src, dest):
    params = ['push']
    if isinstance(src, list):
        params.extend(src)
    else:
        params.append(str(src))
    params.append(dest)
    call(params, stderr=subprocess.PIPE)

def pathExists(path):
    # adb shell doesn't seem to return error codes
    out = call(['shell', 'ls "' + path + '"; echo $?'],
            stderr=subprocess.PIPE)
    return int(out.splitlines()[-1]) == 0

def forward(from_port, to_port):
    call(['forward', from_port, to_port])

