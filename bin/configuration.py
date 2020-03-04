"""
This will basically just streamline the configuration and cleanup the main code a bit
"""

from __future__ import absolute_import
from __future__ import print_function
__author__ = 'Adam Benson - AdamBenson.vfx@gmail.com'
__version__ = '0.5.0'

import six.moves.configparser
import sys
import os


def get_configuration():
    '''
    TODO: Eventually set this up to allow a shotgun page override of CFG file values.
            i.e. Variables on Shotgun that override the settings below if they exist.
    :return:
    '''
    sys_path = sys.path
    config_file = 'tardis_config.cfg'
    try:
        print('Finding configuration file...')
        config_path = [f for f in sys_path if os.path.isfile(f + '/' + config_file)][0] + '/' + config_file
        config_path = config_path.replace('\\', '/')
        print('Configuration found!')
    except IndexError as e:
        raise e

    # Create the configuration connection
    configuration = six.moves.configparser.ConfigParser()
    print('Reading the configuration file...')
    configuration.read(config_path)

    config = {}

    # Parse out the configuration to local variables

    # Shotgun
    config['sg_url'] = configuration.get('Shotgun', 'sg_url')
    config['sg_key'] = configuration.get('Shotgun', 'sg_key')
    config['sg_name'] = configuration.get('Shotgun', 'sg_name')
    config['admin_proj_id'] = configuration.get('Shotgun', 'admin_proj_id')
    config['admin_task_id'] = configuration.get('Shotgun', 'admin_task_id')
    config['overhead_tasks'] = configuration.get('Shotgun', 'overhead_tasks')
    config['paid_time_off'] = configuration.get('Shotgun', 'paid_time_off')
    config['unpaid_time_off'] = configuration.get('Shotgun', 'unpaid_time_off')
    config['lunch'] = configuration.get('Shotgun', 'lunch')
    config['break'] = configuration.get('Shotgun', 'Break')
    config['ot_approved_proj'] = configuration.get('Shotgun', 'ot_approved_proj')
    config['ot_approved_entity'] = configuration.get('Shotgun', 'ot_approved_entity')
    config['permissions'] = configuration.get('Shotgun', 'permissions').split(',')
    config['development'] = configuration.get('Shotgun', 'development')

    # Time Lord
    config['regular_days'] = configuration.get('Time Lord', 'regular_days').split(',')
    config['weekend_days'] = configuration.get('Time Lord', 'weekend_days').split(',')
    config['early_start'] = configuration.get('Time Lord', 'early_start')
    config['early_end'] = configuration.get('Time Lord', 'early_end')
    config['regular_start'] = configuration.get('Time Lord', 'regular_start')
    config['regular_end'] = configuration.get('Time Lord', 'regular_end')
    config['approx_lunch_start'] = configuration.get('Time Lord', 'approx_lunch_start')
    config['approx_lunch_end'] = configuration.get('Time Lord', 'approx_lunch_end')
    config['ot_type'] = configuration.get('Time Lord', 'ot_type')
    config['ot_hours'] = configuration.get('Time Lord', 'ot_hours')
    config['dt_hours'] = configuration.get('Time Lord', 'dt_hours')
    config['ot_alert_mins'] = configuration.get('Time Lord', 'ot_alert_mins')
    config['timer'] = configuration.get('Time Lord', 'timer')
    config['lunch_minutes'] = configuration.get('Time Lord', 'lunch_minutes')

    # Slack
    config['admins'] = configuration.get('Slack', 'admins')
    config['coords'] = configuration.get('Slack', 'coordinators')
    config['maintenance'] = configuration.get('Slack', 'maintenance')
    config['slack_entity'] = configuration.get('Slack', 'slack_entity')
    config['slack_id'] = configuration.get('Slack', 'slack_field_id')

    # Logging
    config['debug_logging'] = configuration.get('Logging', 'debugging')
    config['log_days'] = configuration.get('Logging', 'log_days')
    config['log_interval'] = configuration.get('Logging', 'log_interval')

    return config

