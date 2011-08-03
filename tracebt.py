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

import re, sys, logging
from logging import debug, info, warning, error, critical, exception

re_inst = re.compile(r'.+(0x[\da-f]+):\s+([\d\w_\.]+)\s+([^;]*);?')

logging.getLogger().setLevel(logging.WARNING)

class Frame:

    def __init__(self, pc, sp, is_thumb):
        self.pc = pc
        self.sp = sp
        self.is_thumb = is_thumb

    def printToGDB(self):
        gdb.execute('frame ' + hex(self.sp) + ' ' + hex(self.pc), False, False)

    def __str__(self):
        # adjust pc according to ARM/THUMB mode
        pc = self.pc & (~1) if self.is_thumb else self.pc & (~3)
        return 'frame at {0:#08x} with function {1} ({2:#08x}) in {3}'.format(
                self.sp, '??', pc, gdb.solib_name(pc))

    def _unwind(self):

        class Branch:
            def __init__(self, pc, is_cond):
                self.pc = pc
                self.is_cond = is_cond
                self.take = not is_cond
            def __cmp__(self, other):
                return self.pc - other if type(other) is int \
                    else self.pc - other.pc

        class AssemblyCache:
            BLOCK_SIZE = 0x80
            MAX_RANGES = 10
            class Range(tuple):
                def __new__(cls, start, end, is_thumb, insts):
                    return tuple.__new__(cls, (start, end, is_thumb, insts))
            def __init__(self, pc, is_thumb):
                self.pc = pc
                self.is_thumb = is_thumb
                self._ranges = [self._loadRange(pc, is_thumb)]
                self._curRange = self._ranges[0]
                self._curIndex = 0
            def __iter__(self):
                return self
            def _findRange(self, addr, is_thumb):
                return next((r for r in self._ranges if addr >= r[0]
                                and addr < r[1] and is_thumb == r[2]), None)
            def _loadRange(self, pc, is_thumb):
                # load instructions up until any cached range
                end = pc + BLOCK_SIZE
                cached = next((r for r in self._ranges if pc < r[0]
                                and end > r[1] and is_thumb == r[2]), None)
                if cached:
                    end = cached[0]
                # adjust pc according to ARM/THUMB mode
                pc = pc | 1 if is_thumb else pc & (~3)
                # disassemble a block of instructions at pc
                strInsts = gdb.execute('disassemble ' + hex(pc) + ', ' +
                            hex(end), False, True).lower().splitlines()
                insts = []
                # discard last instruction to avoid misdisassembly
                for strInst in strInsts[: -2]:
                    match = re_inst.match(strInst)
                    if not match:
                        continue
                    # update pc
                    ipc = int(match.group(1).strip(), 0)
                    # get mnemonic and strip width qualifier
                    mnemonic = match.group(2).strip()
                    mnemonic = mnemonic[:-2] \
                                if mnemonic.endswith(('.n', '.w')) \
                                else mnemonic
                    # get arguments and strip function name
                    args = match.group(3) + ' '
                    args = args[: args.find('<')].strip()
                    insts.append((ipc, mnemonic, args))
                if not insts
                    return None
                r = Range(insts[0][0], insts[-1][0], is_thumb, insts)
                self._ranges.append(r)
                if len(self._ranges > MAX_RANGES):
                    del self._ranges[0]
                return r
            def next(self):
                is_thumb = self._curRange[2]
                self._curIndex += 1
                if self._curIndex < len(self._curRange):
                    return self._curRange[self._curIndex] + (is_thumb,)
                # jump to next range based on current pc
                self.jump(self._curRange[1] + 4, is_thumb)
                self._curIndex = 0
                return self._curRange[0] + (is_thumb,)
            def jump(self, pc, is_thumb):
                self._curIndex = -1
                self._curRange = _findRange(pc, is_thumb)
                if not self._curRange:
                    self._curRange = _loadRange(pc, is_thumb)
                assert self._curRange, "cannot load instructions!"

        branchHistory = []
        assemblyCache = AssemblyCache(self.pc, self.is_thumb)
        sp = self.sp

        for pc, mnemonic, args, is_thumb in assemblyCache:

            # trace branch instructions
            def traceBranch(is_cond):
                info('branch (%s) to %s @ %x : %x', mnemonic, args, pc, sp)
                new_pc = int(args, 0)
                new_is_thumb = not is_thumb if mnemonic.startswith('bx') \
                                else is_thumb
                if pc not in branchHistory:
                    branchHistory.append(Branch(pc, is_cond))
                elif branchHistory[-1] == pc: # nowhere else to go
                    condid = next((i for i in
                                    reversed(range(len(branchHistory)))
                                    if not branchHistory[i].take), None)
                    assert condid >= 0, "infinite loop!"
                    del branchHistory[condid + 1 :]
                    branchHistory[condid].take = True
                return (branchHistory[branchHistory.index(pc)].take,
                        new_pc, new_is_thumb)

            # handle individual instructions
            if mnemonic == 'b' or mnemonic == 'bx' or \
                mnemonic == 'bal' or mnemonic == 'bxal':
                if args == 'lr':
                    # FIXME lr might not be valid
                    warning('frame (bx lr) @ %x : %x', pc, sp)
                    pc = int(gdb.parse_and_eval('(unsigned)$lr'))
                    return Frame(pc, sp, (pc & 1) != 0)
                (new_block, pc, is_thumb) = traceBranch(False)
                # always take unconditional branches
                assemblyCache.jump(pc, is_thumb)

            elif mnemonic == 'cbnz' or mnemonic == 'cbz' or \
                mnemonic.startswith('b') and mnemonic[1:].lstrip('bx') in \
                    ['eq', 'ne', 'cs', 'cc', 'hs', 'lo', 'mi', 'pl',
                     'vs', 'vc', 'hi', 'ls', 'ge', 'lt', 'gt', 'le']:
                if mnemonic.startswith('cb'):
                    args = args[args.find(',') + 1 :].lstrip()
                (new_block, pc, is_thumb) = traceBranch(True)
                if new_block:
                    assemblyCache.jump(pc, is_thumb)

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
                    info('frame (pop pc) @ %x : %x', pc, sp)
                    args = args[args.find('pc') :]
                    pc = int(gdb.parse_and_eval('*(unsigned*)' +
                            hex(sp - 4 * len(args.split(',')))))
                    return Frame(pc, sp, (pc & 1) != 0)

            elif mnemonic == 'add' and args.startswith('sp'):
                assert args.split(',')[1].find('r') < 0, \
                        'ADD with ' + args + ' (pc = ' + hex(pc) + ')'
                sp += int(args[args.find('#') + 1 :], 0)

            elif mnemonic == 'sub' and args.startswith('sp'):
                assert args.split(',')[1].find('r') < 0, \
                        'SUB with ' + args + ' (pc = ' + hex(pc) + ')'
                sp -= int(args[args.find('#') + 1 :], 0)

            elif args.startswith('pc') or (args.find('pc') < args.find('}')):
                warning('unknown instruction (%s %s) affected pc',
                        mnemonic, args)

            elif args.startswith('sp') or (args.find('sp') < args.find('}')):
                warning('unknown instruction (%s %s) affected sp',
                        mnemonic, args)

    def unwind(self):
        # don't let value of cpsr affect our results
        saved_cpsr = int(gdb.parse_and_eval('$cpsr'))
        gdb.execute('set $cpsr=' + hex(saved_cpsr & 0x00f003df))
        try:
            return self._unwind()
        finally:
            gdb.execute('set $cpsr=' + hex(saved_cpsr))

pc = int(gdb.parse_and_eval('(unsigned)$pc'))
sp = int(gdb.parse_and_eval('(unsigned)$sp'))
is_thumb = (gdb.parse_and_eval('$cpsr') & 0x20) != 0

f = Frame(pc, sp, is_thumb)
print '#0: ' + str(f)
for i in range(1, 10):
    f = f.unwind()
    print '#{0}: {1}'.format(i, str(f))

