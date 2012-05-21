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
# if feninit.default.no_launch is True,
#   the application will not be launched on the device (useful for B2G)

#python feninit.default.objdir = '~/mozilla/central/objdir-android'
#python feninit.default.srcroot = '~/mozilla'
#python feninit.default.no_launch = True


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

feninit
fastload quick

