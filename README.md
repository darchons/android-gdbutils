GDB python scripts to facilitate debugging under Android

tracebt
-------
tracebt is a stack unwinder for ARM that uses the general algorithm at http://www.mcternan.me.uk/ArmStackUnwinding

It is potentially useful for unwinding stack inside functions without symbols (i.e. system libraries, JIT code, etc.)

