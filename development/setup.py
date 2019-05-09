# setup.py
from distutils.core import setup
import py2exe

setup(console=['test_dev.py'],
      options={
          'py2exe': {
              'packages': ['logging', 'SocketServer', 're']
          }
      }
      )