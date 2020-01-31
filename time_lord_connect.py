"""
The Time Lord Connect is a service that will utilize the Time Lord tools to update time sheets without interfering with
the Internal Auto Publisher.
The intent is that the IAP can send signals to this utility and update and create timesheet entries.
"""

__author__ = 'Adam Benson - AdamBenson.vfx@gmail.com'
__version__ = '0.4.11'

from datetime import datetime
from datetime import timedelta
from dateutil import parser

import shotgun_api3 as sgapi

# Importing the Time Lord engine libraries
from bin import configuration
from bin import time_continuum
from bin import companions


class time_lord(object):
    def __init__(self, user=None, context=None, log=None):
        # Setup logging system
        self.logger = log
        self.logger.info('Time Lord Connection Logger Started...')

        # Get the configuration file
        self.config = configuration.get_configuration()
        self.logger.debug('Configuration found and setup.')

        # Connect to Shotgun
        self.sg = sgapi.Shotgun(self.config['sg_url'], self.config['sg_name'], self.config['sg_key'])
        self.logger.debug('Shotgun connection made.')

        # Setup User information and Time Continuum
        self.people = companions.companions(self.sg)
        self.logger.debug('People database connected.')
        self.tl_time = time_continuum.continuum(self.sg)
        self.logger.debug('Time continuum connected.')

        # Set the User from the drag-n-drop
        self.user = self.people.get_user_from_username(username=user)
        self.logger.debug('User %s is setup' % user)
        self.latest_timesheet = None

        self.logger.info('Update Timesheets...')
        self.run_timesheet(context=context)

    def run_timesheet(self, context=None):
        # Collect the last timesheet
        self.logger.debug('Get the last timesheet.')
        self.latest_timesheet = self.tl_time.get_latest_timesheet(user=self.user)

        # Start testing the Timesheets.
        if not self.latest_timesheet or self.latest_timesheet['sg_task_end']:
            # No Timesheet exists, or the user is clocked out.
            self.logger.info('%s not clocked in, creating new timesheet.' % self.user['name'])
            new_ts = self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=datetime.now())
            self.logger.debug('New timesheet created: %s' % new_ts)
        elif self.latest_timesheet and not self.latest_timesheet['sg_task_end']:
            # Get the last start time.
            self.logger.debug('%s is clocked in. Getting start time...' % self.user['name'])
            last_start_dt = self.latest_timesheet['sg_task_start']
            last_start = parser.parse('%s %s' % (last_start_dt.date(), last_start_dt.time()))

            # Test to make sure that the last timesheet was clocked out on the correct day.
            self.logger.debug('Testing if the current timesheet is from today...')
            ts_from_today = self.tl_time.aint_today(date=last_start_dt.date())
            wrong_date_datetime_end = None
            wrong_date_datetime_start = None
            if ts_from_today:
                print 'Last timesheet ain\'t from today: %s' % ts_from_today
                self.logger.info('The last timesheet ain\'t from today.  Prepping to clock it out...')
                eod = self.config['regular_end']
                end_of_day = parser.parse(eod).time()
                sod = self.config['regular_start']
                self.logger.info('Creating old out time...')
                if last_start_dt.time() < end_of_day:
                    end_time = end_of_day
                else:
                    add_time = last_start_dt + timedelta(minutes=1)
                    end_time = add_time.time()

                end_date = last_start_dt.date()
                wrong_date_datetime_end = parser.parse('%s %s' % (end_date, end_time))
                wrong_date_datetime_start = parser.parse('%s %s' % (datetime.now().date(), sod))
                self.logger.info('New end date and time: %s' % wrong_date_datetime_end)

            # Create a short delayed entry from the last start
            self.logger.debug('Setup pseudo-end date for retroactive timesheets.')
            pseudo_end = last_start + timedelta(seconds=1)
            last_task_id = str(self.latest_timesheet['entity']['id'])
            current_task_id = str(context['Task']['id'])
            if current_task_id != last_task_id:
                print 'Retroactive clock-out of previous timesheet...'
                self.logger.info('Retroactive clock-out of previous timesheet...')
                if wrong_date_datetime_end:
                    self.tl_time.clock_out_time_sheet(timesheet=self.latest_timesheet,
                                                      clock_out=wrong_date_datetime_end,
                                                      comment='Retroactive Clockout of Previous Timesheet')
                    print 'Creating new retroactive timesheet block...'
                    self.logger.info('Creating new retroactive timesheet block...')
                    ts_block = self.tl_time.create_new_timesheet(user=self.user, context=context,
                                                                 start_time=wrong_date_datetime_start,
                                                                 entry='Drag-n-Drop')
                else:
                    self.tl_time.clock_out_time_sheet(timesheet=self.latest_timesheet, clock_out=pseudo_end,
                                                      comment='Clocking out last timesheet at %s' % pseudo_end)
                    print 'Creating new retroactive timesheet block...'
                    self.logger.info('Creating new retroactive timesheet block...')
                    ts_block = self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=pseudo_end,
                                                                 entry='Drag-n-Drop', comment='Drag-n-Drop Retroactive')
                self.tl_time.clock_out_time_sheet(timesheet=ts_block, clock_out=datetime.now(),
                                                  comment='Retroactive clock out at %s to close Drag-n-Drop block' %
                                                  datetime.now())
                print 'Creating New Current timesheet...'
                self.logger.info('Creating new current timesheet...')
                self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=datetime.now(),
                                                  entry='Drag-n-Drop', comment='Drag-n-Drop New')
                print 'New Timesheet created for %s' % self.user['name']
                self.logger.info('New Timesheet created for %s' % self.user['name'])
            elif current_task_id == last_task_id:
                self.logger.info('Same task detected.  Creating a timesheet block...')
                if wrong_date_datetime_end:
                    print 'Creating retroactive timsheet block...'
                    self.logger.info('Creating retroactive timsheet block...')
                    self.tl_time.clock_out_time_sheet(timesheet=self.latest_timesheet,
                                                      clock_out=wrong_date_datetime_end,
                                                      comment='Wrong Date - Clocking out for Retroactive Block')
                else:
                    print 'Creating retroactive timsheet block...'
                    self.logger.info('Creating retroactive timsheet block...')
                    self.tl_time.clock_out_time_sheet(timesheet=self.latest_timesheet, clock_out=datetime.now(),
                                                      comment='Clocking out for Retroactive Block')
                print 'Creating new timesheet...'
                self.logger.info('Creating new timesheet...')
                self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=datetime.now(),
                                                  entry='Drag-n-Drop', comment='Drag-n-Drop New')
                print 'New Timesheet Created for %s' % self.user['name']
                self.logger.info('New Timesheet Created for %s' % self.user['name'])




