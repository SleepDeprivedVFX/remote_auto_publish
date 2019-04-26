import os
from datetime import datetime
import sys

def datetime_to_float(d):
    epoch = datetime.utcfromtimestamp(0)
    total_seconds = (d - epoch).total_seconds()
    return total_seconds

num = datetime_to_float(datetime.now())
print num
