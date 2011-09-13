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

import gdb, adb, feninit, threading, sys, os, cStringIO, collections

ADBLogEntry = collections.namedtuple('ADBLogEntry',
        ['date', 'time', 'pid', 'tid', 'priority', 'tag', 'text']);

def default_filter(entry):
    global log_width, log_color
    if not hasattr(feninit.default, 'pid') or \
            entry.pid == feninit.default.pid:
        log_color = log_color + 1 if log_color <= 5 else 2
        text = entry.text
        if log_width > 8 and len(text) + 5 > log_width:
            text = text[0: log_width - 8] + '...'
        return 'adb| \x1B[3' + str(log_color) + 'm' + text + '\x1B[39m\n'
    return None

log_color = 1
log_filter = default_filter;

class LogRedirect(gdb.Parameter):
    '''Set whether to redirect 'adb logcat' to gdb when program is running'''
    set_doc = 'Enable or disable redirecting "adb logcat"'
    show_doc = 'Show current "adb logcat" redirection setting'

    def __init__(self):
        super(LogRedirect, self).__init__('adb-log-redirect',
                gdb.COMMAND_SUPPORT, gdb.PARAM_BOOLEAN)
        self.value = True
        self.get_set_string()

    def get_set_string(self):
        return 'Set to ' + ('' if self.value else 'not ') + \
                'redirect "adb logcat" output'

    def get_show_string(self, svalue):
        return 'Currently ' + ('' if self.value else 'not ') + \
                'redirecting "adb logcat" output'

log_redirect = LogRedirect()

class ADBLog(threading.Thread):

    def _parseLog(self, logFile):
        line = ''
        while not line.startswith('['):
            line = logFile.next()
        # line == '[ DAY TIME PID:TID PRIO/TAG ]'
        items = line.strip('[] \t\r\n').split()
        text = []
        line = logFile.next().strip()
        while line:
            text.append(line)
            line = logFile.next().strip()
        pidtid = items[2].partition(':')
        priotag = items[3].partition('/')
        return ADBLogEntry(items[0], items[1],
                pidtid[0], pidtid[2],
                priotag[0], priotag[2], '\n'.join(text));

    def __init__(self):
        super(ADBLog, self).__init__()
        logcatArgs = ['-v', 'long',
                'Gecko:V', 'GeckoApp:V', 'GeckoAppJava:V',
                'GeckoSurfaceView:V', 'GeckoChildLoad:V', 'GeckoFonts:V',
                'GeckoMapFile:V', 'GeckoLibLoad:V', 'fennec:V', '*:S']

        logCount = 0
        dump = cStringIO.StringIO(adb.call(['logcat', '-d'] + logcatArgs))
        try:
            while True: # parse until the end of log
                self._parseLog(dump)
                logCount += 1
        except StopIteration:
            pass

        def adblogPreExec():
            os.setpgrp()
        self.logcat = adb.call(['logcat'] + logcatArgs,
                async=True, preexec_fn=adblogPreExec)
        while logCount:
            self._parseLog(self.logcat.stdout)
            logCount -= 1

        self.running = False

    def run(self):
        try:
            global log_filter
            while self.logcat.poll() == None:
                entry = self._parseLog(self.logcat.stdout)
                if not self.running:
                    continue
                log = log_filter(entry)
                if not log:
                    continue
                sys.__stderr__.write(log)
        except StopIteration:
            pass

    def terminate(self):
        self.logcat.terminate();

def cont_handler(event):
    if not isinstance(event, gdb.ContinueEvent):
        return
    if not bool(gdb.parameter('adb-log-redirect')):
        exit_handler(event)
        return
    global adblog, log_width
    if not adblog:
        adb.chooseDevice()
        adblog = ADBLog()
        adblog.start()
    log_width = int(gdb.parameter('width'))
    adblog.running = True

def stop_handler(event):
    global adblog
    if not adblog:
        return
    adblog.running = False

def exit_handler(event):
    global adblog
    if not adblog:
        return
    adblog.running = False
    adblog.terminate()
    adblog = None

adblog = None
gdb.events.cont.connect(cont_handler)
gdb.events.stop.connect(stop_handler)
gdb.events.exited.connect(exit_handler)

