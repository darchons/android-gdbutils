# vi: set tabstop=4 shiftwidth=4 expandtab:
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import gdb, readinput
import os, subprocess, time

class Updater(gdb.Command):
    '''Update gdb/gdbutils'''

    def __init__(self):
        super(Updater, self).__init__('update-gdbutils', gdb.COMMAND_SUPPORT)

    def complete(self, text, word):
        return gdb.COMPLETE_NONE

    def _callGit(self, args, **kw):
        cmd = ['git', '--work-tree=' + self.worktree,
                '--git-dir=' + self.gitdir]
        cmd.extend(args)
        if 'stdin' not in kw:
            kw['stdin'] = subprocess.PIPE
        if 'stdout' not in kw:
            kw['stdout'] = subprocess.PIPE
        return_error = False
        if 'return_error' in kw:
            return_error = kw['return_error']
            del kw['return_error']
        try:
            adb = subprocess.Popen(cmd, **kw)
            out = adb.communicate()[0]
        except OSError as e:
            raise gdb.GdbError('cannot run git: ' + str(e))
        if not return_error and adb.returncode != 0:
            raise gdb.GdbError('git returned exit code ' + str(adb.returncode))
        if return_error:
            return adb.returncode, out
        return out

    def _checkUpdate(self):
        print
        dirty = bool(self._callGit(['diff', '--shortstat']).strip())
        if dirty:
            self._callGit(['stash', 'save'])
        revbefore = self._callGit(['rev-parse', 'HEAD']).strip()
        self._callGit(['pull'], stdout=None)
        revafter = self._callGit(['rev-parse', 'HEAD']).strip()
        if dirty:
            code, gitout = self._callGit(['stash', 'pop'], return_error=True)
            if code or 'CONFLICT' in gitout:
                print gitout.strip()
                print '\nPlease resolve git conflict and restart gdb.'
                gdb.execute('quit')
                return
        if revbefore == revafter:
            return
        print '\nUpdated successfully. Please restart gdb.'
        gdb.execute('quit')

    def invoke(self, argument, from_tty):
        self.dont_repeat()

        interval = (self.update_interval
                if hasattr(self, 'update_interval') else 90)
        if not interval:
            return

        self.worktree = os.path.abspath(
                os.path.join(gdb.PYTHONDIR, os.path.pardir))
        self.gitdir = os.path.join(self.worktree, '.git')
        if not os.path.isdir(self.gitdir):
            return

        marker = os.path.join(self.worktree, '.update')
        def touchUpdate():
            with open(marker, 'a'):
                os.utime(marker, None)

        if not os.path.isfile(marker):
            touchUpdate()
            return

        elapsed = time.time() - os.path.getmtime(marker)
        if elapsed >= interval * 24 * 60 * 60:
            ans = ''
            while not ans or (ans[0] != 'y' and ans[0] != 'Y' and
                              ans[0] != 'n' and ans[0] != 'N'):
                print
                ans = readinput.call(
                    'Last checked for update %d days ago; '
                    'check now? [yes/no]: ' %
                    (elapsed / 60 / 60 / 24),
                    '-l', str(['yes', 'no']))
            if ans[0] == 'y' or ans[0] == 'Y':
                self._checkUpdate()
            # update timestamp regardless of choice above
            touchUpdate()

default = Updater()

