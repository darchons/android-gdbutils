# vi: set tabstop=4 shiftwidth=4 expandtab:
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

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
        raise gdb.GdbError('adb returned exit code ' + str(adb.returncode) +
                           ' for arguments ' + str(args))
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

