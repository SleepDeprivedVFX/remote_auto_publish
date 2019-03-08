import os
from glob import glob
import re
import win32file
import win32con
import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import platform
import time
import logging
import logging.handlers
import shutil
import yaml
import psd_tools as psd
import shotgun_api3
from Queue import Queue
import threading

q = Queue()


# Windows Triggers
ACTIONS = {
    1: "Created",
    2: "Deleted",
    3: "Updated",
    4: "Renamed from something",
    5: "Renamed to something"
}
# Thanks to Claudio Grondi for the correct set of numbers
FILE_LIST_DIRECTORY = 0x0001

# Dropbox Folder
path_to_watch = "C:/Users/events/Dropbox/ASC_REMOTE"
hDir = win32file.CreateFile(
    path_to_watch,
    FILE_LIST_DIRECTORY,
    win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
    None,
    win32con.OPEN_EXISTING,
    win32con.FILE_FLAG_BACKUP_SEMANTICS,
    None
)


def process_file(filename):
    while True:
        thing = q.get()
        print thing
        q.task_done()


T = threading.Thread(name='shit', target=process_file)
T.setDaemon(True)
T.start()


class remoteAutoPublisher(win32serviceutil.ServiceFramework):
    _svc_name_ = "RemoteAutoPublisher"
    _svc_display_name_ = "Remote Auto Publisher"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED,
                              (self._svc_name_, ''))
        self.main()

    def main(self):
        while 1:
            results = win32file.ReadDirectoryChangesW(
                hDir,
                1024,
                True,
                win32con.FILE_NOTIFY_CHANGE_FILE_NAME |
                win32con.FILE_NOTIFY_CHANGE_DIR_NAME |
                win32con.FILE_NOTIFY_CHANGE_ATTRIBUTES |
                win32con.FILE_NOTIFY_CHANGE_SIZE |
                win32con.FILE_NOTIFY_CHANGE_LAST_WRITE |
                win32con.FILE_NOTIFY_CHANGE_SECURITY,
                None,
                None
            )
            for action, file in results:
                full_filename = os.path.join(path_to_watch, file)
                print full_filename, ACTIONS.get(action, "Unknown")
                # This is where my internal processes get triggered.
                # Needs a logger at the very least, although a window would be nice too.
                if action == 1:
                    if os.path.isfile(full_filename):
                        # logger.info('New file detected. %s' % full_filename)
                        copying = True
                        size2 = -1
                        while copying:
                            size = os.stat(full_filename).st_size
                            if size == size2:
                                time.sleep(2)
                                # process_file(full_filename)
                                q.put(full_filename)
                                copying = False
                            else:
                                size2 = os.stat(full_filename).st_size
                                time.sleep(2)


if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(remoteAutoPublisher)

