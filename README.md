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

---

## adblog

When enabled, "adb logcat" output is redirected to the gdb terminal when the program is running. When the program is stopped or exited, redirection stops as well. Any log entry during the stopped interval is skipped.

Currently, only Fennec log messages are redirected (i.e. messages with tags fennec or Gecko).

Logs are outputted with cyclic colors, to easily distinguish between identical logs.

#### Configuration

    gdb> set adb-log-redirect on|off

Enable or disable log redirection

#### Customization

Each log entry is passed to a log filter function, and output from the log filter function is written to the terminal. The log filter function has the form:

    def filter_name(entry):
        ...
        return output

    entry     namedtuple containing information about the log entry
              valid members are 'date', 'time', 'pid', 'tid',
              'priority', 'tag', and 'text'.
              See 'adb logcat -v long' for format of each field.
    output    string object that is written to the terminal

The default filter function has the name adblog.default_filter. To assign a different filter function set adblog.log_filter to the custom function. The custom function can optionally call adblog.default_filter to perform default processing.

