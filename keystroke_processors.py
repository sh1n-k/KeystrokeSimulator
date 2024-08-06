import ntpath
import sys
import platform

if platform.system() == "Windows":
    import win32api
    import win32gui
    import win32process
elif platform.system() == "Darwin":
    import AppKit


def get_processes_macos():
    workspace = AppKit.NSWorkspace.sharedWorkspace()
    app_list = workspace.runningApplications()

    return [
        (app.localizedName(), app.processIdentifier(), None)
        for app in app_list
        if app.activationPolicy() == 0
    ]


def get_processes_windows():
    processes = {}
    window_names = {}

    def enum_window_callback(hwnd, lparam):
        if win32gui.IsWindowVisible(hwnd):
            tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid not in processes:
                process_handle = win32api.OpenProcess(0x1000, False, pid)
                process_name = win32process.GetModuleFileNameEx(process_handle, 0)
                processes[pid] = process_name
                window_name = win32gui.GetWindowText(hwnd)
                window_names[pid] = [window_name]
                win32api.CloseHandle(process_handle)
            else:
                window_name = win32gui.GetWindowText(hwnd)
                if window_name not in window_names[pid]:
                    window_names[pid].append(window_name)
        return True

    win32gui.EnumWindows(enum_window_callback, None)

    return [
        (ntpath.basename(processes[pid]).split(".")[0], pid, window_names[pid])
        for pid in processes
    ]


class ProcessCollector:
    @staticmethod
    def get():
        return (
            get_processes_macos()
            if sys.platform == "darwin"
            else get_processes_windows()
        )
