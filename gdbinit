# vi: set tabstop=4 shiftwidth=4 expandtab:
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

# Load python utilities
python import adbparams
python import feninit, tracebt, fastload, adblog


# Uncomment to change feninit behavior

#set adb-path /PATH/TO/SDK/platform-tools/adb
#set adb-device DEVICE-SERIAL

# feninit.default.objdir will be used as object directory if specified
# otherwise, feninit.default.srcroot will be scanned for directories
#   named 'mozilla-central', 'mozilla-aurora', etc.
# if feninit.default.srcroot is not specified,
#   current user directory is scanned

#python feninit.default.objdir = '~/mozilla/central/objdir-android'
#python feninit.default.srcroot = '~/mozilla'

# if feninit.default.no_launch is True,
#   the application will not be launched on the device (useful for B2G)

#python feninit.default.no_launch = True

# set feninit.default.gdbserver_port to use a specific port for
#   connecting to gdbserver, instead of a random port

#python feninit.default.gdbserver_port = 5039

# set feninit.default.jdwp_port to use a specific port for
#   connecting to jdwp, instead of a port based on the process id

#python feninit.default.jdwp_port = 5040

# set feninit.default.env to set environment variables for
#   debugging Fennec; only applicable when specifically using the
#   "Debug Fennec with env vars and args" option

#python feninit.default.env = 'FOO=bar BAR="foo bar"'

# set feninit.default.args to set arguments for debugging
#   Fennec; only applicable when specifically using the
#   "Debug Fennec with env vars and args" option

#python feninit.default.args = '--arg1 foo --arg2 bar'

# set feninit.default.cpp_env to set environment variables for
#   debugging compiled-code unit tests

#python feninit.default.cpp_env = 'FOO=bar BAR="foo bar"'

# set feninit.default.mochi_env to set environmental variables for
#   Fennec when debugging content Mochitests

#python feninit.default.mochi_env = 'FOO=bar BAR="foo bar"'

# set feninit.default.mochi_args to pass additional arguments to the
#   remote Mochitest harness; for a list of possible arguments, run
#   `python $objdir/_tests/testing/mochitest/runtestsremote.py --help`

#python feninit.default.mochi_args = '--arg1=foo --arg2=bar'

# set feninit.default.mochi_xre to set the default XRE path when
#   launching remote Mochitests

#python feninit.default.mochi_xre = '~/android-gdb/xre/bin'

# set feninit.default.mochi_harness to set the fallback path of the
#   remote Mochitest harness ('runtestsremote.py')

#python feninit.default.mochi_harness = '~/android-gdb/xre/mochitest'

# set feninit.default.mochi_xre_url to set the path under ftp.mozilla.org
#   to fetch XRE for running remote Mochitests; default is latest Aurora;
#   not applicable if feninit.default.mochi_xre is set

#python feninit.default.mochi_xre_url = '/pub/mozilla.org/firefox/nightly/latest-mozilla-aurora'

# set feninit.default.mochi_xre_update to set the interval in days
#   before updating local XRE from feninit.default.mochi_xre_url;
#   not applicable if feninit.default.mochi_xre is set

#python feninit.default.mochi_xre_update = 28


# Disable logcat redirection
#set adb-log-redirect off

# Set logcat color scheme
#set adb-log-color [order|priority|thread]


# Add a command for dumping Java stack traces
define dump-java-stack
    call dvmDumpAllThreads(true)
end

# Add a command for dumping JNI reference tables
define dump-jni-refs
    call dvmDumpJniReferenceTables()
end

# Add a command for dumping the gecko profiler's pseudo-stack.
# This sometimes provides useful information if gdb can't generate
# a backtrace.
define dump-pseudo-stack
    call mozilla_sampler_print_location()
end

feninit
fastload quick

