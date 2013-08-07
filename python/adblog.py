# vi: set tabstop=4 shiftwidth=4 expandtab:
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import gdb, adb, feninit, threading, sys, os, cStringIO, collections

ADBLogEntry = collections.namedtuple('ADBLogEntry',
        ['date', 'time', 'pid', 'tid', 'priority', 'tag', 'text']);

def default_filter(entry):
    global log_width, log_colorfn
    if not hasattr(feninit.default, 'pid') or \
            entry.pid == feninit.default.pid:
        text = entry.text
        if log_width > 8 and len(text) + 5 > log_width:
            text = text[0: log_width - 8] + '...'
        return 'adb| \x1B[3' + str(log_colorfn(entry)) + 'm' + \
                text + '\x1B[39m\n'
    return None

def _getColorFn(color):
    PRIORITY_MAP = {'F': 1, 'E': 1, 'W': 3, 'I': 2, 'D': 6, 'V': 4}
    lastColor = [1]
    def orderColorFn(entry):
        lastColor[0] = lastColor[0] + 1 if lastColor[0] <= 5 else 2
        return lastColor[0]
    def priorityColorFn(entry):
        return PRIORITY_MAP[entry.priority] \
                if entry.priority in PRIORITY_MAP else 5
    def threadColorFn(entry):
        return (int(entry.tid, 0) % 5 + 2) if entry.tid else 5
    return priorityColorFn if color == 'priority' else \
            threadColorFn if color == 'thread' else orderColorFn

log_colorfn = None
log_filter = default_filter

class LogColor(gdb.Parameter):
    '''Set 'adb logcat' output coloring'''
    set_doc = 'Set "adb logcat" output color to be based on ' + \
            '"order", "priority", or "thread"'
    show_doc = 'Show current "adb logcat" output color scheme'

    def __init__(self):
        super(LogColor, self).__init__('adb-log-color',
                gdb.COMMAND_SUPPORT, gdb.PARAM_ENUM,
                ['order', 'priority', 'thread'])
        self.value = 'order'
        self.get_set_string()

    def get_set_string(self):
        self.value = self.value.lower()
        return 'Color "adb logcat" output based on ' + self.value

    def get_show_string(self, svalue):
        return 'Currently coloring "adb logcat" output based on ' + svalue

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

log_color = LogColor()
log_redirect = LogRedirect()

class ADBLog(threading.Thread):

    def _parseLog(self, logFile):
        wholeLog = ''
        while 'gecko' not in wholeLog and 'fennec' not in wholeLog:
            line = ''
            while not line.startswith('['):
                line = logFile.readline()
                if not line:
                    raise StopIteration()
            # line == '[ DAY TIME PID:TID PRIO/TAG ]'
            items = line.strip('[] \t\r\n').split()
            text = []
            while True:
                line = logFile.readline()
                if not line:
                    raise StopIteration()
                line = line.strip()
                if not line:
                    break
                text.append(line)
            wholeLog = ' '.join(items).lower() + ',' + ' '.join(text).lower()

        if len(items) < 5:
            pidtid = items[2].partition(':')
            priotag = items[3].partition('/')
        else:
            pidtid = [items[2].strip(':'), None, items[3]]
            priotag = items[4].partition('/')
        return ADBLogEntry(items[0], items[1],
                pidtid[0], pidtid[2],
                priotag[0], priotag[2], '\\\\'.join(text));

    def __init__(self):
        super(ADBLog, self).__init__(name='ADBLog')
        self.daemon = True

        logcatArgs = ['-v', 'long']

        logCount = 0
        dump = cStringIO.StringIO(adb.call(['logcat', '-d'] + logcatArgs))
        try:
            while True: # parse until the end of log
                self._parseLog(dump)
                logCount += 1
        except StopIteration:
            pass
        self.skipCount = logCount

        def adblogPreExec():
            os.setpgrp()
        self.logcat = adb.call(['logcat'] + logcatArgs,
                stdin=None, async=True, preexec_fn=adblogPreExec)

        self.running = False

    def run(self):
        try:
            global log_filter
            while self.logcat.poll() == None:
                entry = self._parseLog(self.logcat.stdout)
                if self.skipCount:
                    self.skipCount -= 1
                    continue
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
    global continuing
    continuing = True
    if not bool(gdb.parameter('adb-log-redirect')):
        exit_handler(event)
        continuing = True
        return
    global adblog, log_width, log_colorfn
    if not adblog:
        adb.chooseDevice()
        adblog = ADBLog()
        adblog.start()
    log_width = int(gdb.parameter('width'))
    log_colorfn = _getColorFn(str(gdb.parameter('adb-log-color')))
    adblog.running = True

def stop_handler(event):
    global continuing
    continuing = False
    global adblog
    if not adblog:
        return
    adblog.running = False

def exit_handler(event):
    global continuing
    continuing = False
    global adblog
    if not adblog:
        return
    adblog.running = False
    adblog.terminate()
    adblog = None

adblog = None
continuing = False
gdb.events.cont.connect(cont_handler)
gdb.events.stop.connect(stop_handler)
gdb.events.exited.connect(exit_handler)

