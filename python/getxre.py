# vi: set tabstop=4 shiftwidth=4 expandtab:
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys, os, subprocess

if __name__ == '__main__': # not module

    import ftplib, zipfile, platform, shutil
    from optparse import OptionParser

    parser = OptionParser()
    parser.add_option('-d', dest='d')
    parser.add_option('-u', dest='u')
    (args, extras) = parser.parse_args()

    if not hasattr(args, 'd') or not args.d:
        print 'missing required argument -d, the dst directory'
        exit(1)
    xredir = args.d
    if not os.path.isdir(xredir):
        os.makedirs(os.path.abspath(xredir))

    if platform.system() == 'Linux':
        binname = ('linux-x86_64.tar.bz2' if sys.maxsize > 2**32
                   else 'linux-i686.tar.bz2')
        testname = ('linux-x86_64.tests.zip' if sys.maxsize > 2**32
                    else 'linux-i686.tests.zip')
    elif platform.system() == 'Darwin':
        binname = 'mac.dmg'
        testname = 'mac.tests.zip'
    else:
        print 'Platform not supported.\n'
        exit(1)

    def download(src, dst):
        bn = os.path.basename(dst)
        with open(dst, 'wb') as f:
            size = [0, 0, ftp.size(src)]
            def write(s):
                f.write(s)
                size[0] += len(s)
                if size[1] > 0 and size[0] - size[1] < size[2] / 100:
                    return
                size[1] = size[0]
                sys.stdout.write('\rDownloading %s... %d%% ' %
                                 (bn, size[1] * 100 / size[2]))
                sys.stdout.flush()
            ftp.retrbinary('RETR ' + src, write)
        print '\rDownloading %s... Done' % bn

    server = 'ftp.mozilla.org'
    sys.stdout.write('Connecting to %s... ' % server)
    sys.stdout.flush()
    ftp = ftplib.FTP(server)
    try:
        ftp.login()
        files = ftp.nlst(args.u if hasattr(args, 'u') and args.u else
                         '/pub/mozilla.org/firefox/nightly/latest-mozilla-aurora')
        print 'Done'

        try:
            binsrc = next(f for f in files if binname in f)
        except StopIteration:
            print 'Cannot find binary archive %s.' % binname
            exit(1)
        bindst = os.path.join(xredir, binsrc.split('/')[-1])
        download(binsrc, bindst)
        try:
            testsrc = next(f for f in files if testname in f)
        except StopIteration:
            print 'Cannot find tests archive %s.' % testname
            exit(1)
        testdst = os.path.join(xredir, testsrc.split('/')[-1])
        download(testsrc, testdst)
    finally:
        ftp.quit()

    sys.stdout.write('Extracting %s... ' % os.path.basename(bindst))
    sys.stdout.flush()
    bindir = os.path.join(xredir, 'bin')
    if platform.system() == 'Linux':
        if not os.path.isdir(bindir):
            os.makedirs(os.path.abspath(bindir))
        subprocess.check_call(['tar', '--strip-components=1',
                               '-xjf', bindst, '-C', bindir])
    elif platform.system() == 'Darwin':
        out = subprocess.check_output(['hdiutil', 'attach',
                    '-nobrowse', bindst]).splitlines()
        try:
            out = next(l for l in out if '/dev/' in l and '/Volumes/' in l)
            out = out.split()
            volume = next(v for v in out if '/Volumes/' in v)
            dev = next(d for d in out if '/dev/' in d)
            for d in os.listdir(volume):
                if '.app' in d:
                    app = d
            shutil.copytree(os.path.join(volume, app, 'Contents', 'MacOS'),
                            bindir)
        finally:
            subprocess.check_output(['hdiutil', 'detach', dev])
    else:
        print 'Platform not supported.\n'
        exit(1)
    os.remove(bindst)
    print 'Done'
    sys.stdout.write('Extracting %s... ' % os.path.basename(testdst))
    sys.stdout.flush()
    testzip = zipfile.ZipFile(testdst, 'r')
    try:
        if any(not os.path.realpath(os.path.join(xredir, f)).startswith(
               os.path.realpath(xredir))
               for f in testzip.namelist()):
            # extracted file will be outside of the destination directory
            print 'Invalid zip file.\n'
            exit(1)
        testzip.extractall(xredir)
    finally:
        testzip.close()
    os.remove(testdst)
    print 'Done'
    for binary_name in ['certutil', 'pk12util', 'xpcshell', 'ssltunnel']:
        binary_path = os.path.join(xredir, 'bin', binary_name)
        if os.path.isfile(binary_path):
            os.chmod(binary_path, 0o755)
        else:
            raise Exception('Cannot find required binary %s' % (binary_path))
    print 'Downloaded XRE to ' + xredir

else:

    import gdb

    def call(xredir, url=None):
        cmd = [sys.executable, os.path.join(gdb.PYTHONDIR, 'getxre.py'),
                '-d', xredir]
        if url:
            cmd.extend(['-u', url])
        try:
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)
            out = proc.communicate()[1]
        except OSError, e:
            raise gdb.GdbError('cannot run getxre: ' + str(e))
        if proc.returncode != 0:
            raise gdb.GdbError('getxre returned exit code ' +
                                str(proc.returncode))
        return out

