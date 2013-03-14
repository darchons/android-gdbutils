# vi: set tabstop=4 shiftwidth=4 expandtab:
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import gdb

class ADBPath(gdb.Parameter):
    '''When set, use the specified path when launching ADB instead of "adb"'''
    set_doc = 'Set path of Android ADB tool'
    show_doc = 'Show path of Android ADB tool'

    def __init__(self):
        super(ADBPath, self).__init__('adb-path',
                gdb.COMMAND_SUPPORT, gdb.PARAM_OPTIONAL_FILENAME)
        self.value = None
        self.get_set_string()

    def get_set_string(self):
        self.value = self.value.strip() if self.value else 'adb'
        return 'New Android ADB tool is "' + self.value + '"'

    def get_show_string(self, svalue):
        return 'Android ADB tool is "' + svalue + '"'

path = ADBPath()

class ADBDevice(gdb.Parameter):
    '''When set, use the specified device when launching ADB'''
    set_doc = 'Set device used by ADB'
    show_doc = 'Show device used by ADB'

    def __init__(self):
        super(ADBDevice, self).__init__('adb-device',
                gdb.COMMAND_SUPPORT, gdb.PARAM_STRING)
        self.value = None

    def get_set_string(self):
        self.value = self.value if self.value else ''
        return 'New ADB device is "' + self.value + '"'

    def get_show_string(self, svalue):
        return 'ADB device is "' + svalue + '"'

device = ADBDevice()

