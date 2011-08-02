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

import re
from logging import debug, info, warning, error, critical, exception

re_inst = re.compile(r'.+(0x[\da-f]+):\s+([\d\w_\.]+)\s+([^;]*);?')

def tracebt ():

    def doReport (pc, sp, is_thumb):
        gdb.execute('frame ' + hex(sp) + ' ' + hex(pc), False, False)

    def doTrace (pc, sp, is_thumb):
        BLOCK_SIZE = 0x80
        branchList = []

        def doTraceBlock (pc, sp, is_thumb):
            debug('start block @ %x : %x', pc, sp)
            condBranchSkipped = 0

            # adjust pc according to ARM/THUMB mode
            pc = pc | 1 if is_thumb else pc & (~3)
            # disassemble a block of instructions at pc
            insts = gdb.execute('disassemble ' + hex(pc) +
                                ',' + hex(pc + BLOCK_SIZE),
                                False, True).lower().splitlines()
            for inst in insts[: -2]: # avoid misdisassembly at the end
                match = re_inst.match(inst)
                if not match:
                    continue
                # update pc
                pc = int(match.group(1).strip(), 0)

                # get mnemonic and strip width qualifier
                mnemonic = match.group(2).strip()
                mnemonic = mnemonic[:-2] \
                            if mnemonic.endswith(('.n', '.w')) \
                            else mnemonic
                # get arguments and strip function name
                args = match.group(3) + ' '
                args = args[: args.find('<')].strip()

                # trace certain instructions
                def doTraceBranch (pc, sp, is_thumb, mnemonic, args):
                    if args == 'lr':
                        # FIXME lr might not be valid
                        warning('bx lr @ %x : %x', pc, sp)
                        pc = int(gdb.parse_and_eval('(unsigned)$lr'))
                        doReport(pc, sp, (pc & 1) != 0)
                        return (pc, sp, (pc & 1) != 0)
                    info('b addr @ %x : %x', pc, sp)
                    pc = int(args, 0)
                    branchList.append((pc, condBranchSkipped))
                    return (pc, sp, is_thumb
                        if mnemonic.startswith('bx') else not is_thumb)

                if mnemonic == 'b' or mnemonic == 'bx' or \
                    mnemonic == 'bal' or mnemonic == 'bxal':
                    print 'skipped condB: ' + str(condBranchSkipped)
                    condBranchSkipped = 0
                    return doTraceBranch(pc, sp, is_thumb, mnemonic, args)

                elif mnemonic.startswith('b') and mnemonic.lstrip('bx') in \
                    ['eq', 'ne', 'cs', 'cc', 'hs', 'lo', 'mi', 'pl',
                     'vs', 'vc', 'hi', 'ls', 'ge', 'lt', 'gt', 'le']:
                    condBranchSkipped += 1

                elif mnemonic == 'vpush':
                    sp -= 8 * len(args[args.find('{') :].split(','))

                elif mnemonic == 'push' or \
                    (mnemonic.startswith('stmd') and args.startswith('sp!')):
                    sp -= 4 * len(args[args.find('{') :].split(','))

                elif mnemonic == 'vpop':
                    sp += 8 * len(args[args.find('{') :].split(','))

                elif mnemonic == 'pop' or \
                    (mnemonic.startswith('ldmi') and args.startswith('sp!')):
                    sp += 4 * len(args[args.find('{') :].split(','))
                    if args.find('pc') > 0:
                        info('pop pc @ %x : %x', pc, sp)
                        args = args[args.find('pc') :]
                        pc = int(gdb.parse_and_eval('*(unsigned*)' +
                                hex(sp - 4 * len(args.split(',')))))
                        doReport(pc, sp, (pc & 1) != 0)
                        return (pc, sp, (pc & 1) != 0)

                elif mnemonic == 'add' and args.startswith('sp'):
                    assert args.split(',')[1].find('r') < 0, \
                            'ADD with ' + args + ' (pc = ' + hex(pc) + ')'
                    sp += int(args[args.find('#') + 1 :], 0)

                elif mnemonic == 'sub' and args.startswith('sp'):
                    assert args.split(',')[1].find('r') < 0, \
                            'SUB with ' + args + ' (pc = ' + hex(pc) + ')'
                    sp -= int(args[args.find('#') + 1 :], 0)

            debug('end blocki @ %x : %x', pc, sp)
            return (pc, sp, is_thumb)

        # don't let value of cpsr affect our results
        saved_cpsr = int(gdb.parse_and_eval('$cpsr'))
        gdb.execute('set $cpsr=' +
                    hex(saved_cpsr & 0x03df), False, True)

        try:
            for i in range(0x10):
                (pc, sp, is_thumb) = doTraceBlock(pc, sp, is_thumb)
        finally:
            gdb.execute('set $cpsr=' + hex(saved_cpsr), False, True)

    pc = int(gdb.parse_and_eval('(unsigned)$pc'))
    sp = int(gdb.parse_and_eval('(unsigned)$sp'))
    is_thumb = (gdb.parse_and_eval('$cpsr') & 0x20) != 0
    doTrace(pc, sp, is_thumb)

tracebt()

