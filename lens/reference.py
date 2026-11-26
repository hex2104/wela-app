"""What event IDs mean, in plain words - the References tab and the meaning shown when an event ID is clicked.

One line per ID: [log, provider, id, title, meaning].
  log       s System, a Application, p Storport (with the drive logs read alongside it, e.g. Partition)
  provider  as the event names it, matched case-insensitively; "a|b" when several drivers log the same event
  id        an event ID, or "first-last" for a run of IDs that mean the same
Wording follows the providers' own message texts (Windows 11 manifests) for the events that have them.
A lens_config.json "references" list in the same shape adds IDs, or replaces a line with the same provider and id.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

_MINIPORT = ("The storage driver (stornvme for NVMe drives, storahci for SATA) logged {} about the drive. What happened is "
             "in its fields: MiniportEventDescription says it in words, MiniportEventId is the driver's own code and "
             "Parameter1-8 carry the details.")
_ROUTINE = "Routine information. No action needed."

REFERENCE = [
    # ---------------------------------------------------------------- System: boot, shutdown, sleep
    ["s", "Microsoft-Windows-Kernel-General", 12, "Windows started",
     "The operating system started: the first event of every boot, with the time Windows began loading."],
    ["s", "Microsoft-Windows-Kernel-General", 13, "Windows shutting down",
     "Logged at the end of a clean shutdown or restart. Missing before the next boot: that shutdown did not finish."],
    ["s", "Microsoft-Windows-Kernel-General", 1, "System time changed",
     "The clock was changed: by time sync (usually small), by a person or a program (named in the data), or at boot "
     "from the hardware clock. Big jumps make the times around it misleading."],
    ["s", "Microsoft-Windows-Kernel-General", 5, "Registry file recovered",
     "A registry file was found damaged and recovered; some settings may be lost. Often follows a hard shutdown or "
     "disk trouble."],
    ["s", "Microsoft-Windows-Kernel-General", 6, "Registry file not saved",
     "The registry could not write a registry file to disk. Points at disk or file system trouble."],
    ["s", "Microsoft-Windows-Kernel-General", 15, "Registry file reorganized", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-General", 16, "Registry history cleared", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-General", 18, "Started after a soft restart",
     "Windows restarted without going through the firmware (a soft restart). The data says whether it was recovering "
     "from a crash."],
    ["s", "Microsoft-Windows-Kernel-General", 24, "Time zone refreshed", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-Boot", 27, "Boot type",
     "How Windows started: 0 cold boot (a full start), 1 Fast Startup (hybrid boot, a saved kernel was resumed), "
     "2 resume from hibernate."],
    ["s", "Microsoft-Windows-Kernel-Boot", 20, "Last shutdown and boot status",
     "Whether the last shutdown and the last boot completed: LastShutdownGood or LastBootGood false means it did not."],
    ["s", "Microsoft-Windows-Kernel-Boot", 16, "Resume from hibernate failed",
     "Windows could not resume from hibernation and started afresh; what was open before is lost."],
    ["s", "Microsoft-Windows-Kernel-Boot", 29, "Fast Startup failed",
     "Fast Startup (hybrid boot) failed and Windows did a full boot instead."],
    ["s", "Microsoft-Windows-Kernel-Boot", 18, "Boot options counted", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-Boot", 25, "Boot menu policy", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-Boot", 30, "Firmware boot times", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-Boot", 32, "Boot manager waited",
     "How long the boot manager waited for the user (BitLocker PIN or the boot menu)."],
    ["s", "Microsoft-Windows-Kernel-Boot", 153, "Virtualization-based security", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-Boot", 238, "Firmware clock at boot", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-Power", 41, "Rebooted without a clean shutdown",
     "The PC started again without shutting down cleanly: it crashed, hung, lost power or was switched off with the "
     "power button. BugcheckCode not 0: a blue screen; PowerButtonTimestamp not 0: the power button was held; "
     "SleepInProgress not 0: it was going to sleep."],
    ["s", "Microsoft-Windows-Kernel-Power", 42, "Going to sleep",
     "The PC is entering sleep (TargetState 4) or hibernate (TargetState 5); Reason says what started it."],
    ["s", "Microsoft-Windows-Kernel-Power", 107, "Resumed from sleep", "The PC woke up from sleep or hibernate."],
    ["s", "Microsoft-Windows-Kernel-Power", 109, "Shutdown started by Windows",
     "The kernel power manager started a shutdown or restart: part of every clean shutdown, whoever asked for it."],
    ["s", "Microsoft-Windows-Kernel-Power", 105, "Power source changed",
     "The PC switched between mains power and battery (AcOnline in the data)."],
    ["s", "Microsoft-Windows-Kernel-Power", 172, "Network in standby",
     "Whether the network stayed connected during Modern Standby, and why. Routine."],
    ["s", "Microsoft-Windows-Kernel-Power", 187, "Program asked for sleep",
     "A program called Windows' sleep or hibernate function (SetSuspendState / SetSystemPowerState)."],
    ["s", "Microsoft-Windows-Kernel-Power", 506, "Entering Modern Standby",
     "Screen off, low-power connected standby; Reason says why."],
    ["s", "Microsoft-Windows-Kernel-Power", 507, "Leaving Modern Standby",
     "Woke from Modern Standby; the data says how long it slept and how much battery it used."],
    ["s", "Microsoft-Windows-Kernel-Power", 566, "Power session changed",
     "The power session moved to a new state, e.g. into or out of Modern Standby, or at boot. Routine."],
    ["s", "Microsoft-Windows-Kernel-Power", 86, "Shut down: too hot",
     "Windows shut down because a temperature sensor reached its critical limit. Check fans, vents and heat."],
    ["s", "Microsoft-Windows-Kernel-Power", 88, "Hibernated: too hot",
     "Windows hibernated because a temperature sensor reached its limit."],
    ["s", "Microsoft-Windows-Kernel-Power", 89, "Thermal zone listed", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-Power", 125, "Thermal zone listed", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-Power", 130, "Firmware sleep times", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-Power", 131, "Firmware resume times", _ROUTINE],
    ["s", "Microsoft-Windows-Kernel-Power", 137, "Firmware memory settings changed",
     "The firmware changed memory settings across sleep; this can slow resume. A firmware quirk, not a drive problem."],
    ["s", "Microsoft-Windows-Kernel-Power", 142, "Reset by the hardware watchdog",
     "The PC stopped responding and the hardware watchdog reset it: a hang, not a clean restart."],
    ["s", "Microsoft-Windows-Kernel-Power", 40, "Driver stopped a power change",
     "A driver (named in the data) stopped a sleep or shutdown transition."],
    ["s", "Microsoft-Windows-Kernel-Power", 521, "Battery count changed", _ROUTINE],
    ["s", "Microsoft-Windows-Power-Troubleshooter", 1, "Woke from sleep (report)",
     "The PC returned from a low-power state: when it went to sleep, when it woke, and what woke it (power button, lid, "
     "a USB device, a timer...)."],
    ["s", "User32", 1074, "Shutdown or restart requested",
     "A program or a person asked for a shutdown or restart. Names the process, the account it ran under, the reason "
     "code and the type (restart / power off)."],
    ["s", "User32", 1076, "Reason given for an unexpected shutdown",
     "Someone entered a reason for the last unexpected shutdown (Shutdown Event Tracker)."],
    ["s", "EventLog", 6005, "Event log started", "The Event Log service started: logged early in every boot."],
    ["s", "EventLog", 6006, "Event log stopped",
     "The Event Log service stopped: logged near the end of a clean shutdown or restart."],
    ["s", "EventLog", 6008, "Previous shutdown was unexpected",
     "Logged at boot when the last shutdown was not clean (power loss, crash, power button, hang). The data gives the "
     "time of the last sign of life."],
    ["s", "EventLog", 6009, "Windows version at boot", "Logged at every boot with the Windows version and build."],
    ["s", "EventLog", 6013, "System uptime",
     "A daily heartbeat with the seconds since boot: shows the PC was running at that time."],
    ["s", "Microsoft-Windows-Winlogon", 7001, "User signed in", "A user signed in."],
    ["s", "Microsoft-Windows-Winlogon", 7002, "User signed out",
     "A user signed out: logged at the start of a clean shutdown or restart."],
    ["s", "Microsoft-Windows-WER-SystemErrorReporting|BugCheck", 1001, "Blue screen (bugcheck)",
     "The PC restarted after a crash (blue screen). Names the stop code, e.g. 0x0000009f, and where the memory dump "
     "was saved."],
    ["s", "Microsoft-Windows-WER-SystemErrorReporting", 1018, "Crash dump deleted",
     "A crash dump was deleted because the disk had too little free space."],
    ["s", "Microsoft-Windows-Eventlog", 104, "Log cleared",
     "A log was cleared (named in the data): its events before this time are gone."],
    ["s", "Microsoft-Windows-Eventlog", 1102, "Security log cleared", "The Security (audit) log was cleared."],
    # ---------------------------------------------------------------- System: disk, file system, hardware
    ["s", "disk", 7, "Bad block",
     "The disk reported a bad block, a sector it cannot read. A sign of a failing drive: back up and check SMART."],
    ["s", "disk", 11, "Controller error",
     "An I/O to the disk failed at the controller or link: the drive, its slot or cable, or the controller."],
    ["s", "disk", 15, "Device not ready", "The disk was not ready for access: still starting, or not responding."],
    ["s", "disk", 51, "Paging I/O error",
     "An error while reading or writing the page file or a program's code. Often a warning sign of drive or "
     "connection trouble."],
    ["s", "disk", 52, "Predicted failure (SMART)",
     "The drive's own SMART monitoring predicts it will fail. Back up immediately."],
    ["s", "disk", 153, "I/O retried",
     "Windows had to retry an I/O to the disk: it timed out or failed once, then worked. A few are harmless; many in a "
     "row point at a slow or failing drive or link."],
    ["s", "disk", 154, "I/O failed (hardware error)", "An I/O to the disk failed because of a hardware error."],
    ["s", "disk", 157, "Disk surprise removed",
     "The disk disappeared without warning: unplugged, lost power or dropped off the bus."],
    ["s", "disk", 158, "Duplicate disk ID", "Two disks have the same identifiers (one is a clone). Not a hardware fault."],
    ["s", "stornvme|storahci|iaStorAC|iaStorA|iaStorVD", 129, "Reset to device",
     "The storage driver reset the drive after a request got no answer in time (usually 30-60 s). Repeated resets point "
     "at a drive, firmware or link problem."],
    ["s", "stornvme", 11, "Controller error (NVMe)", "The NVMe driver detected a controller error on the drive."],
    ["s", "storahci|iaStorAC|iaStorA|iaStorVD", 9, "Device did not respond",
     "The drive did not respond within the timeout period."],
    ["s", "Ntfs|Microsoft-Windows-Ntfs", 55, "File system corruption",
     "NTFS found damage in a volume's file system. Run chkdsk; repeated ones can come from a failing drive or from "
     "hard shutdowns."],
    ["s", "Microsoft-Windows-Ntfs", 98, "Volume check",
     "Logged as each volume mounts. As Information: healthy, no action needed. As a warning or error: the volume needs "
     "repair (chkdsk)."],
    ["s", "Microsoft-Windows-Ntfs", 140, "Journal not saved",
     "NTFS could not write its transaction log to the disk; data may be corrupted. Often follows the drive not "
     "responding or disappearing."],
    ["s", "Ntfs|Microsoft-Windows-Ntfs", 50, "Delayed write failed",
     "Windows could not save all the data for a file; data may be lost. Points at disk or connection trouble."],
    ["s", "Ntfs", 130, "File system repaired", "NTFS repaired the file system on the volume."],
    ["s", "Ntfs", 131, "File system cannot be repaired", "NTFS could not fix the volume's file system: run chkdsk."],
    ["s", "Microsoft-Windows-Ntfs", 150, "Bad clusters moved",
     "An I/O failed, so NTFS moved the data and marked those clusters bad. May mean a failing disk."],
    ["s", "Microsoft-Windows-Ntfs", 162, "Data read back differs",
     "Data read from the drive did not match what was written: a data integrity problem."],
    ["s", "Microsoft-Windows-Ntfs", 7, "Torn write in the file table",
     "NTFS found a file table record only partly written, e.g. cut off by a power loss."],
    ["s", "volmgr", 45, "Crash dump driver not loaded", "Windows could not load the driver it needs to save a crash dump."],
    ["s", "volmgr", 46, "Crash dump not set up", "Crash dump initialization failed: a crash would leave no dump."],
    ["s", "volmgr", 49, "Page file too small for dumps",
     "Crash dumps are not set up: no page file on the boot volume, or it is too small."],
    ["s", "volmgr", 161, "Crash dump not written",
     "A crash dump could not be written during a crash: the drive may not have been working at that moment."],
    ["s", "volmgr", 162, "Crash dump written", "A crash dump was saved."],
    ["s", "Microsoft-Windows-WHEA-Logger", 1, "Fatal hardware error",
     "A fatal hardware error; the record is in the event's data. The PC stops with a blue screen."],
    ["s", "Microsoft-Windows-WHEA-Logger", 16, "Fatal PCIe error",
     "A fatal error on a PCI Express link or port (the device and port are named)."],
    ["s", "Microsoft-Windows-WHEA-Logger", 17, "Corrected PCIe error",
     "A PCI Express link error that the hardware corrected. A few are harmless; many on the drive's port point at the "
     "link to the drive (slot, firmware, power saving)."],
    ["s", "Microsoft-Windows-WHEA-Logger", 18, "Fatal processor error",
     "A fatal error reported by the processor (machine check); the PC stops with a blue screen (0x124)."],
    ["s", "Microsoft-Windows-WHEA-Logger", 19, "Corrected processor error",
     "A processor error that the hardware corrected (machine check)."],
    ["s", "Microsoft-Windows-WHEA-Logger", 46, "Fatal memory error", "A fatal memory error."],
    ["s", "Microsoft-Windows-WHEA-Logger", 47, "Corrected memory error",
     "A memory error that the hardware corrected (ECC)."],
    # ---------------------------------------------------------------- System: services, drivers, updates
    ["s", "Service Control Manager", 7000, "Service failed to start", "A service could not start; the error is given."],
    ["s", "Service Control Manager", 7001, "Service dependency failed",
     "A service could not start because a service it depends on failed."],
    ["s", "Service Control Manager", 7009, "Service start timed out",
     "A service did not connect within the timeout (usually 30 s) while starting."],
    ["s", "Service Control Manager", 7011, "Service did not answer", "A service took too long to answer a request."],
    ["s", "Service Control Manager", 7022, "Service hung on start", "A service hung while starting."],
    ["s", "Service Control Manager", 7023, "Service stopped with an error", "A service stopped with the error given."],
    ["s", "Service Control Manager", 7024, "Service stopped with its own error",
     "A service stopped with an error code of its own."],
    ["s", "Service Control Manager", 7026, "Drivers did not load at boot",
     "Boot-start or system-start drivers failed to load (named in the event)."],
    ["s", "Service Control Manager", 7031, "Service crashed (recovery set)",
     "A service ended unexpectedly; Windows takes the recovery action named: restart the service, run a program, or "
     "restart the computer."],
    ["s", "Service Control Manager", 7034, "Service crashed", "A service ended unexpectedly."],
    ["s", "Service Control Manager", 7036, "Service started or stopped",
     "A service entered the running or stopped state. Very common and normal."],
    ["s", "Service Control Manager", 7040, "Service start type changed",
     "A service's start type was changed (e.g. automatic to manual)."],
    ["s", "Service Control Manager", 7042, "Service asked to stop", "A service was sent a stop request; the reason is given."],
    ["s", "Service Control Manager", 7043, "Service held up shutdown",
     "A service did not shut down properly after the pre-shutdown notice: it slowed or held up the shutdown."],
    ["s", "Service Control Manager", 7045, "Service installed", "A new service was installed."],
    ["s", "Display", 4101, "Display driver recovered",
     "The graphics driver stopped responding and Windows restarted it. Repeated ones can freeze the screen."],
    ["s", "Microsoft-Windows-Resource-Exhaustion-Detector", 2004, "Low on memory",
     "Windows found a low virtual-memory condition; the programs using the most are named."],
    ["s", "Microsoft-Windows-WindowsUpdateClient", 19, "Update installed", "Windows installed an update (named)."],
    ["s", "Microsoft-Windows-WindowsUpdateClient", 20, "Update failed", "An update failed to install; the error code is given."],
    ["s", "Microsoft-Windows-WindowsUpdateClient", 21, "Restart needed for updates",
     "Updates were installed and need a restart to finish."],
    ["s", "Microsoft-Windows-WindowsUpdateClient", 22, "Update restart scheduled",
     "The PC will restart within the minutes given to finish installing updates."],
    ["s", "Microsoft-Windows-WindowsUpdateClient", 43, "Update install started", "Windows started installing an update."],
    ["s", "Microsoft-Windows-WindowsUpdateClient", 44, "Update download started", "Windows Update started downloading an update."],
    ["s", "Microsoft-Windows-Servicing", 2, "Windows package installed",
     "A Windows package (update) changed to the state given, e.g. installed. Logged in the Setup log."],
    ["s", "Microsoft-Windows-Servicing", 4, "Package needs a restart",
     "A Windows package needs a restart before it can be installed. Logged in the Setup log."],
    ["s", "Microsoft-Windows-Kernel-PnP", 219, "Driver failed to load",
     "A device's driver failed to load at boot. Often harmless (a driver for a device that is not there)."],
    ["s", "Microsoft-Windows-Kernel-PnP", 225, "Program blocked device removal",
     "A program stopped a device from being removed or ejected."],
    ["s", "Microsoft-Windows-Kernel-Processor-Power", 37, "Processor speed limited",
     "The firmware limited the processor's speed (heat, power or battery saving)."],
    ["s", "Microsoft-Windows-Kernel-Processor-Power", 55, "Processor power features", _ROUTINE],
    ["s", "Microsoft-Windows-UserModePowerService", 12, "Power plan changed", "A program changed the active power plan."],
    ["s", "Microsoft-Windows-Time-Service", 35, "Time source set", "The time service is syncing with the time source named."],
    ["s", "Microsoft-Windows-Time-Service", 37, "Time data received", _ROUTINE],
    ["s", "Microsoft-Windows-Time-Service", 36, "Clock not synced",
     "The clock has not been synchronized for a while: no time source answered."],
    ["s", "Microsoft-Windows-Time-Service", 129, "Time source not found", "No domain time source was found; it tries again later."],
    ["s", "Microsoft-Windows-Time-Service", 134, "Time source not found", "The time source's name could not be looked up."],
    ["s", "Microsoft-Windows-DNS-Client", 1014, "Name lookup timed out",
     "A DNS lookup got no answer: no network or a slow DNS server. Common; not a PC fault."],
    ["s", "Microsoft-Windows-DistributedCOM", 10016, "DCOM permission", "A Windows component lacked a DCOM permission. Common and harmless."],
    ["s", "Microsoft-Windows-DistributedCOM", 10010, "DCOM server late", "A COM server did not register in time."],
    ["s", "Microsoft-Windows-DistributedCOM", 10005, "DCOM could not start a service", "DCOM could not start the service named."],
    ["s", "Microsoft-Windows-FilterManager", 6, "File system filter loaded", _ROUTINE],
    ["s", "Microsoft-Windows-DriverFrameworks-UserMode", 10110, "User-mode driver crashed",
     "A user-mode driver's host process ended; its devices may pause."],
    ["s", "Microsoft-Windows-DriverFrameworks-UserMode", 10111, "Device offline after a driver crash",
     "A device went offline because its user-mode driver crashed; Windows tries to restart it."],
    # ---------------------------------------------------------------- Application
    ["a", "Application Error", 1000, "App crashed",
     "A program crashed. Names the program, the module that failed and the exception code (0xc0000005 = access "
     "violation)."],
    ["a", "Application Error", 1005, "App closed: its file could not be read",
     "Windows could not read a program's file (network, disk or storage driver problem) and closed the program. Can "
     "point at the drive."],
    ["a", "Application Hang", 1002, "App hung", "A program stopped responding and was closed."],
    ["a", "Windows Error Reporting", 1001, "Error report",
     "Windows Error Reporting handled a problem. Event Name says what: APPCRASH (crash), AppHangB1 (hang), BlueScreen, "
     "LiveKernelEvent (a driver or hardware problem that did not crash the PC)..."],
    ["a", ".NET Runtime", 1026, ".NET app crashed", "A .NET program ended with an unhandled exception (named)."],
    ["a", "MsiInstaller", 1033, "Software installed", "Windows Installer installed a product (status 0 = success)."],
    ["a", "MsiInstaller", 1034, "Software removed", "Windows Installer removed a product."],
    ["a", "MsiInstaller", 1035, "Software reconfigured", "Windows Installer reconfigured a product."],
    ["a", "MsiInstaller", 1036, "Software update installed", "Windows Installer installed an update to a product."],
    ["a", "MsiInstaller", 1037, "Software update removed", "Windows Installer removed an update from a product."],
    ["a", "MsiInstaller", 1038, "Installer needs a restart", "Windows Installer needs a restart to finish."],
    ["a", "MsiInstaller", 1005, "Installer restarted the PC", "Windows Installer restarted the PC to finish an install."],
    ["a", "MsiInstaller", 1040, "Install started", "A Windows Installer transaction began."],
    ["a", "MsiInstaller", 1042, "Install ended", "A Windows Installer transaction ended."],
    ["a", "MsiInstaller", 11707, "Installation completed", "A product installed successfully."],
    ["a", "MsiInstaller", 11708, "Installation failed", "A product failed to install."],
    ["a", "MsiInstaller", 11724, "Removal completed", "A product was removed successfully."],
    ["a", "MsiInstaller", 11728, "Configuration completed", "A product was reconfigured successfully."],
    ["a", "Microsoft-Windows-RestartManager", 10000, "Restart Manager started",
     "An installer started a Restart Manager session to close programs that use its files."],
    ["a", "Microsoft-Windows-RestartManager", 10001, "Restart Manager ended", "The Restart Manager session ended."],
    ["a", "Microsoft-Windows-RestartManager", 10005, "Restart required", "Restart Manager found that a restart is needed."],
    ["a", "Microsoft-Windows-RestartManager", 10010, "App cannot be restarted",
     "A program that had to close cannot be restarted automatically."],
    ["a", "Microsoft-Windows-Winsrv", 10001, "App tried to stop shutdown", "A program tried to veto the shutdown (named)."],
    ["a", "Microsoft-Windows-Winsrv", 10002, "Hung app ended at shutdown", "A program was ended because it was hung."],
    ["a", "Microsoft-Windows-Security-SPP", 16384, "License service restart scheduled", _ROUTINE],
    ["a", "Microsoft-Windows-Security-SPP", 16394, "License migration done", _ROUTINE],
    ["a", "Microsoft-Windows-Security-SPP", 8198, "Activation failed", "Windows activation (slui.exe) failed; the error code is given."],
    ["a", "Winlogon|Microsoft-Windows-Winlogon", 6000, "Sign-in component not ready",
     "A Windows sign-in component was not ready for a notification. Common at boot; harmless."],
    ["a", "Winlogon|Microsoft-Windows-Winlogon", 6003, "Sign-in component not ready",
     "A Windows sign-in component was not ready for a critical notification. Common at boot; harmless."],
    ["a", "Microsoft-Windows-User Profiles Service", 1531, "User profile service started", _ROUTINE],
    ["a", "Microsoft-Windows-User Profiles Service", 1532, "User profile service stopped", _ROUTINE],
    ["a", "SecurityCenter", 15, "Antivirus status updated", _ROUTINE],
    ["a", "VSS", 8224, "Volume Shadow Copy idle stop", "The shadow copy service stopped after being idle. Normal."],
    ["a", "ESENT", 916, "Database engine notice", _ROUTINE],
    ["a", "Microsoft-Windows-Defrag|Defrag", 258, "Drive optimized",
     "Storage Optimizer finished: defragmentation on hard disks, TRIM ('retrim') on SSDs. Routine maintenance."],
    ["a", "LoadPerf", 1000, "Performance counters loaded", _ROUTINE],
    ["a", "LoadPerf", 1001, "Performance counters removed", _ROUTINE],
    ["a", "Microsoft-Windows-WMI", 10, "WMI event filter failed",
     "A WMI event filter could not be reactivated. Usually a leftover from removed software."],
    # ---------------------------------------------------------------- Storport (Storage-Storport Operational / Health)
    ["p", "Microsoft-Windows-StorPort", 500, "Request timed out",
     "An I/O to the drive took longer than its timeout and was cancelled; the drive is named. Repeated ones: the "
     "drive or its link is not responding, often followed by a reset (129)."],
    ["p", "Microsoft-Windows-StorPort", 501, "Bus reset", "Storport reset the storage bus of the adapter."],
    ["p", "Microsoft-Windows-StorPort", 502, "Drive marked unresponsive",
     "Storport marked the drive unresponsive; the reason is given."],
    ["p", "Microsoft-Windows-StorPort", 503, "Drive responsive again", "Storport marked the drive responsive again."],
    ["p", "Microsoft-Windows-StorPort", 504, "Error summary",
     "A periodic summary: errors and timeouts since the last one, and the last error's command (opcode), status and "
     "sense code. Zero errors is normal activity."],
    ["p", "Microsoft-Windows-StorPort", 505, "Performance summary",
     "A periodic summary of I/O counts and how long they took, by latency bucket, with bytes read and written. Normal "
     "activity; many I/Os in the slow buckets point at a slow drive."],
    ["p", "Microsoft-Windows-StorPort", 506, "QoS summary",
     "Requests slower than the threshold, and software and hardware timeouts, in the period."],
    ["p", "Microsoft-Windows-StorPort", 507, "Request stuck after reset",
     "The driver did not complete a request even after the drive was reset: a driver bug or a hung drive."],
    ["p", "Microsoft-Windows-StorPort", 508, "Request stuck after abort",
     "The driver did not complete a request even after it was aborted: a driver bug or a hung drive."],
    ["p", "Microsoft-Windows-StorPort", 509, "Abort timed out", "A request to abort an I/O timed out."],
    ["p", "Microsoft-Windows-StorPort", 510, "SMART statistics", "The drive's SMART statistics (Health log)."],
    ["p", "Microsoft-Windows-StorPort", 511, "ATA device statistics", "The drive's ATA statistics logs (Health log)."],
    ["p", "Microsoft-Windows-StorPort", 512, "NVMe health log",
     "The drive's NVMe health log: temperature, spare capacity, percentage used, media errors (Health log)."],
    ["p", "Microsoft-Windows-StorPort", 513, "Host memory buffer",
     "Host Memory Buffer allocation for a DRAM-less NVMe drive; a failure reason is given if it failed."],
    ["p", "Microsoft-Windows-StorPort", 514, "SMR out-of-order write", "An SMR drive got a write out of order."],
    ["p", "Microsoft-Windows-StorPort", "516-524", "Miniport event (error)", _MINIPORT.format("an error")],
    ["p", "Microsoft-Windows-StorPort", 534, "Miniport event (error)", _MINIPORT.format("an error")],
    ["p", "Microsoft-Windows-StorPort", "525-533", "Miniport event (warning)", _MINIPORT.format("a warning")],
    ["p", "Microsoft-Windows-StorPort", 535, "Drive may have failed", "The storage driver reports the drive potentially failed."],
    ["p", "Microsoft-Windows-StorPort", 536, "Drive failed, being removed",
     "The storage driver reports the drive failed and should be removed."],
    ["p", "Microsoft-Windows-StorPort", "537-542", "Miniport health event (error)", _MINIPORT.format("a health error")],
    ["p", "Microsoft-Windows-StorPort", "543-548", "Miniport health event (warning)", _MINIPORT.format("a health warning")],
    ["p", "Microsoft-Windows-StorPort", 549, "First I/O error in a period",
     "The first failed I/O in a reporting period: its command (opcode), SRB and SCSI status, sense code and latency."],
    ["p", "Microsoft-Windows-StorPort", 550, "Escalating reset",
     "Storport performed a hierarchical reset (unit, then target, then bus) to recover the drive."],
    ["p", "Microsoft-Windows-StorPort", 551, "Drive surprise removed", "The drive disappeared without warning."],
    ["p", "Microsoft-Windows-StorPort", 552, "Drive arrived", "The drive was detected: at boot or when reconnected."],
    ["p", "Microsoft-Windows-StorPort", 553, "Adapter rescanned", "The adapter was rescanned and changes were found."],
    ["p", "Microsoft-Windows-StorPort", 554, "Queued I/O over threshold",
     "Too many I/Os waiting for the drive: it is not keeping up."],
    ["p", "Microsoft-Windows-StorPort", 555, "Drive maintenance started", "Host-initiated maintenance time started for the drive."],
    ["p", "Microsoft-Windows-StorPort", 556, "Drive maintenance ended", "Host-initiated maintenance time ended for the drive."],
    ["p", "Microsoft-Windows-StorPort", 557, "Slow I/O", "An I/O took longer than the milliseconds given to complete."],
    ["p", "Microsoft-Windows-StorPort", 558, "Drive failed", "The storage driver reports the drive failed."],
    ["p", "Microsoft-Windows-StorPort", 559, "SMR drive not supported", "The driver does not support this SMR drive."],
    ["p", "Microsoft-Windows-StorPort", 560, "Live dump requested", "The storage driver asked for a live kernel dump of the drive's state."],
    ["p", "Microsoft-Windows-StorPort", 561, "Driver asked to reset the drive",
     "The storage driver requested a device reset; the reset type and how long it took are given."],
    ["p", "Microsoft-Windows-StorPort", 562, "Drive warning", "A warning about the drive (the code is given)."],
    ["p", "Microsoft-Windows-StorPort", 563, "I/O size summary", "A periodic summary of I/O sizes and latency. Normal activity."],
    ["p", "Microsoft-Windows-StorPort", 564, "Log page data", "A log page read from the drive (code and length given)."],
    ["p", "Microsoft-Windows-StorPort", 565, "SCSI diagnostic logs", "The drive's SCSI diagnostic logs (Health log)."],
    ["p", "Microsoft-Windows-StorPort", 567, "Miniport event (information)", _MINIPORT.format("information")],
    ["p", "Microsoft-Windows-StorPort", 568, "Miniport event (warning)", _MINIPORT.format("a warning")],
    ["p", "Microsoft-Windows-StorPort", "569-571", "Miniport health event", _MINIPORT.format("a health event")],
    ["p", "Microsoft-Windows-StorPort", 575, "Power-up retried",
     "Powering the drive up failed and is being retried: power management trouble."],
    ["p", "Microsoft-Windows-StorPort", 576, "Drive power-off setting", "The adapter's D3 (power-off) setting. Configuration."],
    ["p", "Microsoft-Windows-StorPort", "581-583", "Self-encrypting drive (TCG) problem",
     "A TCG (self-encrypting drive) command failed or is not supported."],
    ["p", "Microsoft-Windows-StorPort", 587, "NVMe error log", "Entries from the drive's own NVMe error log."],
    ["p", "Microsoft-Windows-StorPort", 588, "NVMe error recovery log", "The drive's NVMe error recovery log (Health log)."],
    ["p", "Microsoft-Windows-StorPort", 589, "Platform reset request failed",
     "A request to power-cycle the device (PLDR) failed."],
    ["p", "Microsoft-Windows-StorPort", 590, "Firmware activated", "New drive firmware was activated."],
    ["p", "Microsoft-Windows-StorPort", 591, "Plug and Play request failed", "A Plug and Play request to the adapter failed."],
    ["p", "Microsoft-Windows-StorPort", 592, "Adapter failed to start", "The storage adapter failed to start."],
    ["p", "Microsoft-Windows-StorPort", "1200-1208", "NVMe health event",
     "A health event from the NVMe controller, a namespace or the driver (error, warning or information)."],
    ["p", "Microsoft-Windows-StorPort", 1400, "NVMe adapter failed to start", "The NVMe adapter failed to start."],
    ["p", "Microsoft-Windows-StorPort", 1420, "NVMe queue request failed", "A request on an NVMe controller queue failed."],
    ["p", "Microsoft-Windows-StorPort", "1421-1429", "NVMe event",
     "An event from the NVMe controller, a namespace or the driver (information, warning or error)."],
    ["p", "Microsoft-Windows-StorPort", "1434-1436", "NVMe adapter event", "An event from the NVMe adapter."],
    ["p", "Microsoft-Windows-StorPort", 1437, "NVMe performance summary", "A periodic I/O latency summary. Normal activity."],
    ["p", "Microsoft-Windows-StorPort", 1438, "Slow NVMe I/O", "An I/O took longer than the milliseconds given."],
    ["p", "Microsoft-Windows-StorPort", 1, "Unit reset", "Storport reset a logical unit (the drive)."],
    ["p", "Microsoft-Windows-StorPort", 2, "Target reset", "Storport reset a target device."],
    ["p", "Microsoft-Windows-StorPort", 5, "Link down", "The link to the device went down."],
    ["p", "Microsoft-Windows-StorPort", 6, "Link up", "The link to the device came back up."],
    ["p", "Microsoft-Windows-Partition", 1006, "Disk inventory",
     "Logged when a disk arrives (at boot): model, serial, firmware, bus type, capacity and partition table. Its "
     "message says only: For internal use only."],
]


def _ids(eid) -> range:
    if isinstance(eid, str) and "-" in eid:
        a, b = eid.split("-", 1)
        return range(int(a), int(b) + 1)
    return range(int(eid), int(eid) + 1)


def table(cfg: dict = None) -> List[list]:
    """The reference with a team's additions from lens_config.json: theirs replace a line with the same provider and id."""
    extra = [list(r[:5]) for r in (cfg or {}).get("references") or [] if isinstance(r, (list, tuple)) and len(r) >= 5]
    mine = {(str(r[1]).lower(), str(r[2])) for r in extra}
    return [r for r in REFERENCE if (r[1].lower(), str(r[2])) not in mine] + extra


def titles(cfg: dict = None) -> Dict[Tuple[str, int], str]:
    """(provider lower-case, event ID) -> title, for every ID the reference covers."""
    out = {}
    for _, provs, eid, title, _ in table(cfg):
        for p in provs.lower().split("|"):
            for i in _ids(eid):
                out[(p, i)] = title
    return out


def uses(cfg: dict) -> Dict[Tuple[str, int], str]:
    """(provider lower-case, event ID) -> what LENS uses the event for, from the catalogue's rules."""
    out: Dict[Tuple[str, int], str] = {}

    def add(key, text):
        out[key] = f"{out[key]}; {text}" if key in out else text

    labels = {k: re.sub(r"\s*\([^()]*\)$", "", v) for k, v in cfg["signal_labels"].items()}
    for name, pairs in cfg["signals"].items():
        for prov, eid in pairs:
            add((prov.lower(), int(eid)), f"Power cycle evidence: {labels.get(name, name)}")
    for prov, eid, label, state, *info in cfg["storage_events"]:
        if eid != "*":
            add((prov.lower(), int(eid)), f"Drive event: {label} ({state})" +
                (f"; as Information: {info[0]} (normal activity)" if info else ""))
    for prov, eid, label, *_ in cfg.get("software_events", []):
        add((prov.lower(), int(eid)), f"App & update event: {label}")
    return out


def use_of(provider: str, eid: int, cfg: dict, known: Dict[Tuple[str, int], str] = None) -> str:
    """What LENS does with this event: its catalogue rule, or - for any other storage provider - a drive event at
    its level."""
    p = (provider or "").lower()
    u = (known if known is not None else uses(cfg)).get((p, int(eid)))
    if u:
        return u
    wild = {prov.lower() for prov, e, *_ in cfg["storage_events"] if e == "*"}
    if p in wild or any(h.lower() in p for h in cfg["storage_provider_hints"]):
        return "Drive event: its level sets the state (Information = normal activity)"
    return ""
