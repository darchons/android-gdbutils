GDB python scripts to facilitate debugging under Android

---

## tracebt

tracebt is a stack unwinder for ARM that uses the general algorithm at <http://www.mcternan.me.uk/ArmStackUnwinding>. It implements conditional branch history tracking for deterministic branching behavior.

It can be useful for unwinding stack when GDB does not have enough debug information for regular 'backtrace' command to work, e.g. inside system libraries, JIT code, etc.

#### Usage

    gdb> tracebt [pc] [sp] [is_thumb]

      pc        starting program counter (prefix with 0x for hex)
      sp        starting stack pointer (prefix with 0x for hex)
      is_thumb  starting Thumb state (inferred from pc if omitted)

Find backtrace, and print out the stack pointer, program counter, function, and library of each frame. Backtracing stops when Ctrl+C is pressed, no more frames are available, or (for now at least) an error occurs. If pc or sp is not specified, the current respective register value is used.

pc and sp arguments are useful when the program is stopped inside a function prologue, for which tracebt does not provide support. In this case, the pc and sp values inside the function body can be calculated and used for backtracing. The arguments are also useful when the program is not running; i.e. the pc and sp registers are not available.

---

## feninit

feninit is a tool to initialize the GDB environment for debugging Fennec on an Android phone. It requires minimal input from the user, and automates all of the background tasks to get Fennec and GDB to debug-ready states. It supports multiple devices, multiple object directories, parent/child processes, and non-root debugging supported by Android 2.3 or higher.

#### Configuration

gdbinit file can be used to configure default options and path to adb. See gdbinit for examples.

#### Usage

    gdb> feninit

Initialize Fennec for Android debugging environment in GDB, in the following order:

* Choosing target device if applicable
* Choosing target object directory if applicable
* Downloading system libraries and binaries
* Setting symbol search paths
* Launching Fennec
* Uploading and launching gdbserver
* Attaching gdbserver to appropriate parent or child process
* Connecting to gdbserver
