# vi: set tabstop=4 shiftwidth=4 expandtab:
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import gdb, re, logging, os

class LogLimiter:
    def __init__(self):
        self.count = 0
    def filter(self, record):
        if record.levelno >= logging.WARNING:
            self.count += 1
            if self.count > 20:
                raise gdb.GdbError('Stopped: too many warnings.')
        return True
    def reset(self):
        self.count = 0

def _initLogger(log):
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s:%(message)s'))
    log.addHandler(handler)
    log.setLevel(logging.WARNING)
    log.addFilter(logLimiter)

log = logging.getLogger(__name__)
logLimiter = LogLimiter()
_initLogger(log)

class Frame:

    def __init__(self, pc, sp, is_thumb, regs = {}):
        self.pc = pc
        self.sp = sp
        self.is_thumb = is_thumb
        regs['pc'] = pc
        regs['sp'] = sp
        self.regs = regs

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
        regs = self.regs;
        regs['sp'] = savedSp = sp

        for pc, mnemonic, args, is_thumb in assemblyCache:

            # trace branch instructions
            def traceBranch(is_cond):
                log.info('branch (%s) to %s @ %x : %x', mnemonic, args, pc, sp)
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

            if savedSp == sp: # sp hasn't changed, regs['sp'] might have
                savedSp = sp = regs['sp']
            else: # sp has changed, update regs['sp']
                savedSp = regs['sp'] = sp

            # handle individual instructions
            if mnemonic == 'b' or mnemonic == 'bx' or \
                mnemonic == 'bal' or mnemonic == 'bxal':
                if args == 'lr':
                    # FIXME lr might not be valid
                    log.warning('frame (bx lr) @ %x : %x', pc, sp)
                    pc = regs['lr']
                    return Frame(pc, sp, (pc & 1) != 0, regs)
                elif args.startswith('r'):
                    log.warning(
                            'skipped unconditional branch (%s %s) @ %x : %x',
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
                    log.warning('skipped conditional bx lr @ %x : %x', pc, sp)
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
                for r in args.translate(None, '{ }').split(','):
                    regs[r] = int(gdb.parse_and_eval('*(unsigned*)' + hex(sp)))
                    sp += 4
                if args.find('pc') > 0:
                    log.info('frame (pop pc) @ %x : %x', pc, sp)
                    pc = regs['pc']
                    return Frame(pc, sp, (pc & 1) != 0, regs)

            elif mnemonic == 'add' or mnemonic.startswith('add.'):
                r = args.translate(None, ' ').split(',')
                if r[0] in regs:
                    if r[1] in regs:
                        if len(r) == 2:
                            regs[r[0]] += regs[r[1]]
                        elif r[2] in regs:
                            regs[r[0]] = regs[r[1]] + regs[r[2]]
                        elif r[2].startswith('#'):
                            regs[r[0]] = regs[r[1]] + int(r[2][1:], 0)
                        else:
                            log.warning('unhandled add: %s (pc = %s)',
                                        args, hex(pc))
                    elif r[1].startswith('#'):
                        regs[r[0]] += int(r[1][1:], 0)
                    else:
                        log.warning('unhandled add: %s (pc = %s)',
                                    args, hex(pc))
                else:
                    log.warning('unhandled add: %s (pc = %s)',
                                args, hex(pc))

            elif mnemonic == 'sub' or mnemonic.startswith('sub.'):
                r = args.translate(None, ' ').split(',')
                if r[0] in regs:
                    if r[1] in regs:
                        if len(r) == 2:
                            regs[r[0]] -= regs[r[1]]
                        elif r[2] in regs:
                            regs[r[0]] = regs[r[1]] - regs[r[2]]
                        elif r[2].startswith('#'):
                            regs[r[0]] = regs[r[1]] - int(r[2][1:], 0)
                        else:
                            log.warning('unhandled sub: %s (pc = %s)',
                                        args, hex(pc))
                    elif r[1].startswith('#'):
                        regs[r[0]] -= int(r[1][1:], 0)
                    else:
                        log.warning('unhandled sub: %s (pc = %s)',
                                    args, hex(pc))
                else:
                    log.warning('unhandled sub: %s (pc = %s)',
                                args, hex(pc))

            elif mnemonic == 'mov' or mnemonic.startswith('mov.'):
                r = args.translate(None, ' ').split(',')
                if r[0] in regs and r[1] in regs:
                    regs[r[0]] = regs[r[1]]
                elif r[0] in regs and r[1].startswith('#'):
                    regs[r[0]] = int(r[1][1:], 0)
                else:
                    log.warning('unhandled mov: %s (pc = %s)',
                                args, hex(pc))

            elif args.startswith('pc') or ((args.find('pc') > args.find('{'))
                                    and (args.find('pc') < args.find('}'))):
                log.warning('unknown instruction at %s (%s %s) affected pc',
                        hex(pc), mnemonic, args)

            elif args.startswith('sp') or ((args.find('sp') > args.find('{'))
                                    and (args.find('sp') < args.find('}'))):
                log.warning('unknown instruction at %s (%s %s) affected sp',
                        hex(pc), mnemonic, args)

            elif mnemonic.startswith('pop') or mnemonic.startswith('push'):
                log.warning('conditional instruction at %s (%s %s) affected sp',
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
            registers = gdb.execute('info registers', False, True).splitlines()
            regs = {s.split()[0]: int(s.split()[1], 0) for s in registers};
        except gdb.GdbError:
            raise
        except (ValueError, gdb.error) as e:
            raise gdb.GdbError('cannot parse argument: ' + str(e))

        try:
            fid = 0
            f = Frame(0, 0, False)
            newf = Frame(pc, sp, is_thumb, regs)
            while newf != f:
                print '#{0}: {1}'.format(fid, str(newf))
                f = newf
                newf = f.unwind()
                fid += 1
                logLimiter.reset()
        except KeyboardInterrupt:
            raise gdb.GdbError("interrupted")
        print 'no more reachable frames'

default = TraceBT()
