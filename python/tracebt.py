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

import gdb, re, logging, os
from logging import debug, info, warning, error, critical, exception

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
        try:
            block = gdb.block_for_pc(pc)
        except RuntimeError:
            block = None
        if block and block.is_valid() and block.function:
            func = block.function.print_name
        else:
            func = gdb.execute('info symbol ' + hex(pc), True, True).strip()
            if func.startswith('No symbol'):
                func = '??'
        for sep in ['(', '+', 'in section']:
            if sep in func:
                func = func[: func.find(sep)].strip()
                break
        lib = gdb.solib_name(pc)
        lib = os.path.basename(lib) if lib else '??'
        return 'frame {0:#08x} in function {1} ({2:#08x}) from {3}'.format(
                self.sp, func, pc, lib)

    def __cmp__(self, other):
        if self.pc != other.pc:
            return self.pc - other.pc
        if self.sp != other.sp:
            return self.sp - other.sp
        if self.is_thumb == other.is_thumb:
            return 0
        return id(self) - id(other)

    def __hash__(self):
        return self.pc ^ self.sp ^ (-1 if self.is_thumb else 0)

    def _unwind(self):

        class Branch:
            def __init__(self, pc, is_cond):
                self.pc = pc
                self.is_cond = is_cond
                self.take = not is_cond
                self.tryTake = False
            def __cmp__(self, other):
                return self.pc - other if type(other) is int \
                                        else self.pc - other.pc
            def __hash__(self):
                return self.pc
            def __str__(self):
                return hex(self.pc) + '[' + \
                    ('c' if self.is_cond else '') + \
                    ('t' if self.take else '') + \
                    ('T' if self.tryTake else '') + ']'

        class AssemblyCache:
            RE_INSTRUCTION = re.compile(
                r'.+(0x[\da-f]+).*:\s+([\d\w_\.]+)\s+([^;]*);?')
            BLOCK_SIZE = 0x80
            MAX_RANGES = 10
            class Range(tuple):
                def __new__(cls, start, end, is_thumb, insts):
                    return tuple.__new__(cls, (start, end, is_thumb, insts))
            def __init__(self, pc, is_thumb):
                self._ranges = []
                self.jump(pc, is_thumb)
            def __iter__(self):
                return self
            def __str__(self):
                inst = self._curRange[3][self._curIndex]
                return hex(inst[0]) + ': ' + inst[1] + ' ' + inst[2]
            def _findRange(self, addr, is_thumb):
                return next((r for r in self._ranges if addr >= r[0]
                                and addr < r[1] and is_thumb == r[2]), None)
            def _loadRange(self, pc, is_thumb):
                # load instructions up until any cached range
                end = pc + self.BLOCK_SIZE
                cached = next((r for r in self._ranges if pc < r[0]
                                and end >= r[1] and is_thumb == r[2]), None)
                if cached:
                    end = cached[0] + 8 # account for last instruction
                # adjust pc according to ARM/THUMB mode
                pc = pc | 1 if is_thumb else pc & (~3)
                # disassemble a block of instructions at pc
                strInsts = gdb.execute('disassemble ' + hex(pc) + ', ' +
                            hex(end), False, True).lower().splitlines()
                insts = []
                # discard last instruction to avoid misdisassembly
                for strInst in strInsts[: -2]:
                    match = self.RE_INSTRUCTION.match(strInst)
                    if not match:
                        continue
                    # update pc
                    ipc = int(match.group(1).strip(), 0) & ~1
                    # don't go past end because another range might cover it
                    if ipc > end:
                        break
                    # get mnemonic and strip width qualifier
                    mnemonic = match.group(2).strip()
                    mnemonic = mnemonic[:-2] \
                                if mnemonic.endswith(('.n', '.w')) \
                                else mnemonic
                    # get arguments and strip function name
                    args = match.group(3) + ' '
                    args = args[: args.find('<')].strip()
                    insts.append((ipc, mnemonic, args))
                if not insts:
                    return None
                r = AssemblyCache.Range(insts[0][0], insts[-1][0],
                                        is_thumb, insts)
                self._ranges.append(r)
                if len(self._ranges) > self.MAX_RANGES:
                    del self._ranges[0]
                return r
            def next(self):
                is_thumb = self._curRange[2]
                self._curIndex += 1
                if self._curIndex < len(self._curRange[3]):
                    return self._curRange[3][self._curIndex] + (is_thumb,)
                # jump to end pc should automatically switch to next range
                self.jump(self._curRange[1], is_thumb)
                self._curIndex = 0
                return self._curRange[3][0] + (is_thumb,)
            def jump(self, pc, is_thumb):
                self._curRange = self._findRange(pc, is_thumb)
                if not self._curRange:
                    self._curRange = self._loadRange(pc, is_thumb)
                assert self._curRange, "cannot load instructions!"
                self._curIndex = next((i for i in range(len(self._curRange[3]))
                                    if self._curRange[3][i][0] > pc), -1) - 2
                assert self._curIndex >= -1, "instruction at " + \
                                                hex(pc) + " not in range!"

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
                elif branchHistory[-1].tryTake:
                    branchHistory[-1].tryTake = False
                elif branchHistory[-1] == pc: # nowhere else to go
                    condid = next((i for i in
                                    reversed(range(len(branchHistory)))
                                    if not branchHistory[i].take), -1)
                    assert condid >= 0, "infinite loop!"
                    del branchHistory[condid + 1 :]
                    branchHistory[condid].take = True
                    branchHistory[condid].tryTake = True
                    return (True, new_pc, new_is_thumb)
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
                elif args.startswith('r'):
                    warning('skipped unconditional branch (%s %s) @ %x : %x',
                            mnemonic, args, pc, sp)
                    continue
                (new_block, pc, is_thumb) = traceBranch(False)
                # always take unconditional branches
                assemblyCache.jump(pc, is_thumb)

            elif mnemonic == 'cbnz' or mnemonic == 'cbz' or \
                mnemonic.startswith('b') and mnemonic[1:].lstrip('bx') in \
                    ['eq', 'ne', 'cs', 'cc', 'hs', 'lo', 'mi', 'pl',
                     'vs', 'vc', 'hi', 'ls', 'ge', 'lt', 'gt', 'le']:
                if mnemonic.startswith('cb'):
                    args = args[args.find(',') + 1 :].lstrip()
                if args == 'lr':
                    warning('skipped conditional bx lr @ %x : %x', pc, sp)
                    continue
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
                (mnemonic.startswith('ldmi') and args.startswith('sp!')) or \
                (mnemonic.startswith('pop') and args.find('pc') >= 0):
                sp += 4 * len(args[args.find('{') :].split(','))
                if args.find('pc') > 0:
                    info('frame (pop pc) @ %x : %x', pc, sp)
                    args = args[args.find('pc') :]
                    pc = int(gdb.parse_and_eval('*(unsigned*)' +
                            hex(sp - 4 * len(args.split(',')))))
                    return Frame(pc, sp, (pc & 1) != 0)

            elif mnemonic == 'add' and args.startswith('sp'):
                assert args.split(',')[1].find('r') < 0, \
                        'unhandled add: ' + args + ' (pc = ' + hex(pc) + ')'
                sp += int(args[args.find('#') + 1 :], 0)

            elif mnemonic == 'sub' and args.startswith('sp'):
                assert args.split(',')[1].find('r') < 0, \
                        'unhandled sub: ' + args + ' (pc = ' + hex(pc) + ')'
                sp -= int(args[args.find('#') + 1 :], 0)

            elif args.startswith('pc') or ((args.find('pc') > args.find('{'))
                                    and (args.find('pc') < args.find('}'))):
                warning('unknown instruction at %s (%s %s) affected pc',
                        hex(pc), mnemonic, args)

            elif args.startswith('sp') or ((args.find('sp') > args.find('{'))
                                    and (args.find('sp') < args.find('}'))):
                warning('unknown instruction at %s (%s %s) affected sp',
                        hex(pc), mnemonic, args)

            elif mnemonic.startswith('pop') or mnemonic.startswith('push'):
                warning('conditional instruction at %s (%s %s) affected sp',
                        hex(pc), mnemonic, args)

    def unwind(self):
        # don't let value of cpsr affect our results
        saved_cpsr = int(gdb.parse_and_eval('$cpsr'))
        gdb.execute('set $cpsr=' + hex(saved_cpsr & 0x00f003df))
        try:
            return self._unwind()
        finally:
            gdb.execute('set $cpsr=' + hex(saved_cpsr))

class TraceBT(gdb.Command):
    '''Unwind stack by tracing instructions'''

    def __init__(self):
        super(TraceBT, self).__init__('tracebt', gdb.COMMAND_STACK)

    def complete(self, text, word):
        return gdb.COMPLETE_NONE

    def invoke(self, argument, from_tty):
        ARG_NAMES = ['pc', 'sp', 'is_thumb']

        self.dont_repeat()
        vals = [None for i in ARG_NAMES] # pc, sp, is_thumb
        try:
            args = gdb.string_to_argv(argument)
            if len(args) > len(ARG_NAMES):
                raise gdb.GdbError('Too many arguments!')

            for i in range(len(args)):
                arg = args[i].partition('=')
                if not arg[1]:
                    vals[i] = gdb.parse_and_eval(arg[0])
                elif arg[0] in ARG_NAMES:
                    vals[ARG_NAMES.index(arg[0])] = gdb.parse_and_eval(arg[2])
                else:
                    raise gdb.GdbError('invalid argument name')

            if vals[0] and not vals[2]:
                #infer thumb state
                vals[2] = (vals[0] & 1) != 0

            pc = int(vals[0] if vals[0] else \
                    gdb.parse_and_eval('(unsigned)$pc'))
            sp = int(vals[1] if vals[1] else \
                    gdb.parse_and_eval('(unsigned)$sp'))
            is_thumb = bool(vals[0] if vals[0] else \
                    (gdb.parse_and_eval('$cpsr') & 0x20) != 0)
        except gdb.GdbError:
            raise
        except (ValueError, gdb.error) as e:
            raise gdb.GdbError('cannot parse argument: ' + str(e))

        try:
            fid = 0
            f = Frame(0, 0, False)
            newf = Frame(pc, sp, is_thumb)
            while newf != f:
                print '#{0}: {1}'.format(fid, str(newf))
                f = newf
                newf = f.unwind()
                fid += 1
        except KeyboardInterrupt:
            raise gdb.GdbError("interrupted")
        print 'no more reachable frames'

default = TraceBT()
