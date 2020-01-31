"""
This will basically just streamline the configuration and cleanup the main code a bit
"""

__author__ = 'Adam Benson - AdamBenson.vfx@gmail.com'
__version__ = '0.4.11'

import ConfigParser
import sys
import os


def get_configuration():
    sys_path = sys.path
    config_file = 'tardis_config.cfg'
    try:
        print 'Finding configuration file...'
        config_path = [f for f in sys_path if os.path.isfile(f + '/' + config_file)][0] + '/' + config_file
        config_path = config_path.replace('\\', '/')
        print 'Configuration found!'
    except IndexError, e:
        raise e

    # Create the configuration connection
    configuration = ConfigParser.ConfigParser()
    print 'Reading the configuration file...'
    configuration.read(config_path)

    config = {}
    # Parse out the configuration to local variables
    # Shotgun
    config['sg_url'] = configuration.get('Shotgun', 'sg_url')
    config['sg_key'] = configuration.get('Shotgun', 'sg_key')
    config['sg_name'] = configuration.get('Shotgun', 'sg_name')
    config['admin_proj_id'] = configuration.get('Shotgun', 'admin_proj_id')
    config['overhead_tasks'] = configuration.get('Shotgun', 'overhead_tasks')
    config['paid_time_off'] = configuration.get('Shotgun', 'paid_time_off')
    config['unpaid_time_off'] = configuration.get('Shotgun', 'unpaid_time_off')
    config['lunch'] = configuration.get('Shotgun', 'lunch')
    config['break'] = configuration.get('Shotgun', 'Break')

    # Time Lord
    config['regular_days'] = configuration.get('Time Lord', 'regular_days').split(',')
    config['weekend_days'] = configuration.get('Time Lord', 'weekend_days').split(',')
    config['regular_start'] = configuration.get('Time Lord', 'regular_start')
    config['regular_end'] = configuration.get('Time Lord', 'regular_end')
    config['approx_lunch_start'] = configuration.get('Time Lord', 'approx_lunch_start')
    config['approx_lunch_end'] = configuration.get('Time Lord', 'approx_lunch_end')
    config['ot_type'] = configuration.get('Time Lord', 'ot_type')
    config['ot_hours'] = configuration.get('Time Lord', 'ot_hours')
    config['dt_hours'] = configuration.get('Time Lord', 'dt_hours')
    config['timer'] = configuration.get('Time Lord', 'timer')
    config['lunch_minutes'] = configuration.get('Time Lord', 'lunch_minutes')

    # Logging
    config['debug_logging'] = configuration.get('Logging', 'debugging')

    return config

