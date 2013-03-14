# vi: set tabstop=4 shiftwidth=4 expandtab:
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys, os

if __name__ == '__main__': # not module

    import readline, shlex
    from optparse import OptionParser

    if 'libedit' in readline.__doc__:
        readline.parse_and_bind('bind ^I rl_complete')
    else:
        readline.parse_and_bind('tab: complete')
        readline.parse_and_bind('set bell-style none')
        readline.parse_and_bind('set completion-ignore-case on')
    readline.set_completer()

    def safeSplit(text):
        def trySplit(text, closing):
            try:
                if not closing:
                    return []
                return shlex.split(text + closing[0])
            except ValueError:
                return trySplit(text, closing[1:])
        return trySplit(text, ['', '"', "'"])

    PATH_DELIMS = [os.path.sep, '\t', ' ']
    DEFAULT_DELIMS = ['\t', ' ', '"', "'"]

    def getLine():
        buf = readline.get_line_buffer()
        idx = readline.get_endidx()
        if 'libedit' not in readline.__doc__:
            return '', buf[0: idx], ''
        prestart = max(buf.rfind(c, 0, idx) for c in DEFAULT_DELIMS) + 1
        preend = max(buf.rfind(c, 0, idx) for c in PATH_DELIMS) + 1
        poststart = min(buf.find(c, idx + 1) if buf.count(c, idx + 1)
                        else len(buf) - 1 for c in PATH_DELIMS) + 1
        postend = min(buf.find(c, idx + 1) if buf.count(c, idx + 1)
                      else len(buf) - 1 for c in DEFAULT_DELIMS) + 1
        return buf[prestart: preend], \
               buf[preend: poststart], \
               buf[poststart: postend]

    def dirComplete(text, state):
        pre, word, post = getLine()
        comps = safeSplit(pre + word)
        path = comps[-1] if comps else ''
        basename = os.path.basename(path)
        dirname = os.path.dirname(path)
        abspath = os.path.abspath(os.path.expanduser(dirname))
        for d in os.listdir(abspath):
            if 'libedit' not in readline.__doc__:
                if not d.lower().startswith(basename.lower()):
                    continue
            else:
                if not d.startswith(basename):
                    continue
            if d.startswith('.') and not basename.startswith('.'):
                continue
            if not os.path.isdir(os.path.join(abspath, d)):
                continue
            if not state:
                return pre + d + os.path.sep + post
            state -= 1
        return None

    def fileComplete(text, state):
        pre, word, post = getLine()
        comps = safeSplit(pre + word)
        path = comps[-1] if comps else ''
        basename = os.path.basename(path)
        dirname = os.path.dirname(path)
        abspath = os.path.abspath(os.path.expanduser(dirname))
        for f in os.listdir(abspath):
            if 'libedit' not in readline.__doc__:
                if not f.lower().startswith(basename.lower()):
                    continue
            else:
                if not f.startswith(basename):
                    continue
            if f.startswith('.') and not basename.startswith('.'):
                continue
            if os.path.isdir(os.path.join(abspath, f)):
                if not state:
                    return pre + f + os.path.sep + post
                state -= 1
            elif os.stat(os.path.join(abspath, f)).st_mode & fmm == fm:
                if not state:
                    return pre + f + post
                state -= 1
        return None

    def listComplete(text, state):
        buf = readline.get_line_buffer().lower()
        results = [x for x in lst if x.lower().startswith(buf)] + [None]
        return results[state]

    parser = OptionParser()
    parser.add_option('-p', dest='p')
    parser.add_option('-l', dest='l')
    parser.add_option('-d', action='store_true', dest='d')
    parser.add_option('-f', action='store_true', dest='f')
    parser.add_option('-c', dest='c')
    parser.add_option('--file-mode', dest='fm')
    parser.add_option('--file-mode-mask', dest='fmm')
    (args, extras) = parser.parse_args()

    if hasattr(args, 'l') and args.l:
        lst = eval(args.l)
        readline.set_completer_delims('')
        readline.set_completer(listComplete)
    elif hasattr(args, 'd') and args.d:
        if 'libedit' in readline.__doc__:
            readline.set_completer_delims(''.join(DEFAULT_DELIMS))
        else:
            readline.set_completer_delims(''.join(PATH_DELIMS))
        readline.set_completer(dirComplete)
    elif hasattr(args, 'f') and args.f:
        if 'libedit' in readline.__doc__:
            readline.set_completer_delims(''.join(DEFAULT_DELIMS))
        else:
            readline.set_completer_delims(''.join(PATH_DELIMS))
        readline.set_completer(fileComplete)
    curdir = None
    if hasattr(args, 'c') and args.c:
        os.chdir(os.path.abspath(os.path.expanduser(args.c)))
    fm = 0
    fmm = 0
    if hasattr(args, 'fm') and args.fm:
        fm = eval(args.fm)
        fmm = eval(args.fmm if hasattr(args, 'fmm') and args.fmm
                            else -1)

    out = raw_input('' if not hasattr(args, 'p') else args.p)
    relout = os.path.abspath(os.path.expanduser(out)) if out else ''
    if hasattr(args, 'd') and args.d and os.path.isdir(relout):
        out = relout
    elif hasattr(args, 'f') and args.f and os.path.isfile(relout):
        out = relout
    sys.stderr.write(out)

else:

    import gdb, subprocess

    def call(prompt, *args):
        cmd = [sys.executable, os.path.join(gdb.PYTHONDIR, 'readinput.py'),
                '-p', prompt]
        cmd.extend(list(args))
        try:
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)
            out = proc.communicate()[1]
        except OSError, e:
            raise gdb.GdbError('cannot run readinput: ' + str(e))
        if proc.returncode != 0:
            raise gdb.GdbError('readinput returned exit code ' +
                                str(proc.returncode))
        return out

