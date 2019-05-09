import SocketServer
import logging

LOG_FILE = 'C:/shotgun/remote_auto_publish/logs/server_test.log'
HOST, PORT = '0.0.0.0', 514

logging.basicConfig(level=logging.INFO, format='%(message)s', datefmt='', filename=LOG_FILE, filemode='a')

test = SocketServer.BaseRequestHandler


def thing(obj):
    return obj

shit = thing(test)
shit.handle(test)
