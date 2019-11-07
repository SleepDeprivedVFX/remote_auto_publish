#!/usr/bin/env python

import logging
import SocketServer
import re
from datetime import datetime

print datetime.date(datetime.now())

LOG_FILE = 'C:/shotgun/remote_auto_publish/logs/server_test.log'
HOST, PORT = '0.0.0.0', 514
pattern = '/Jobs/\w+/publish/\w+/'

logging.basicConfig(level=logging.INFO, format='%(message)s', datefmt='', filename=LOG_FILE, filemode='a')


class SyslogUDPHandler(SocketServer.BaseRequestHandler):

    def handle(self):
        data = bytes.decode(self.request[0].strip())
        socket = self.request[1]
        data_list = data.split(',')

        # Raw Data List
        try:
            event = data_list[0]
            event = str(event.split(': ')[1])
        except IndexError:
            event = None
        try:
            path = data_list[1]
            path = path.split(': ')[1]
        except IndexError:
            path = None
        try:
            event_type = data_list[2]
            event_type = event_type.split(': ')[1]
        except IndexError:
            event_type = None
        try:
            file_size = data_list[3]
            file_size = file_size.split(': ')[1]
        except IndexError:
            file_size = None
        try:
            user = data_list[4]
            user = user.split(': ')[1]
            user = user.strip('ASC\\')
        except IndexError:
            user = None
        try:
            ip = data_list[5]
            ip = ip.split(': ')[1]
        except IndexError:
            ip = None

        if event == 'write' or event == 'move':
            if event_type == 'File':
                if path.startswith('/Jobs/'):
                    if re.findall(pattern, path):
                        print user, path, file_size, ip


if __name__ == "__main__":
    try:
        server = SocketServer.UDPServer((HOST, PORT), SyslogUDPHandler)
        server.serve_forever(poll_interval=0.5)
    except (IOError, SystemExit):
        raise
    except KeyboardInterrupt:
        print ("Crtl+C Pressed. Shutting down.")
