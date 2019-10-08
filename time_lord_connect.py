"""
The Time Lord Connect is a service that will utilize the Time Lord tools to update time sheets without interfering with
the Internal Auto Publisher.
The intent is that the IAP can send signals to this utility and update and create timesheet entries.
"""

from datetime import datetime
from datetime import timedelta
from dateutil import parser

import shotgun_api3 as sgapi
import logging

# Importing the Time Lord engine libraries
from bin import configuration
from bin import shotgun_collect
from bin import time_continuum
from bin import companions


class time_lord(object):
    def __init__(self, user=None, context=None):
        # Get the configuration file
        self.config = configuration.get_configuration()

        # Connect to Shotgun
        self.sg = sgapi.Shotgun(self.config['sg_url'], self.config['sg_name'], self.config['sg_key'])

        # Setup User information and Time Continuum
        self.people = companions.companions(self.sg)
        self.tl_time = time_continuum.continuum(self.sg)

        # Set the User from the drag-n-drop
        self.user = self.people.get_user_from_username(username=user)
        self.last_timesheet = None

        self.run_timesheet(context=context)

    def run_timesheet(self, context=None):
        # Collect the last timesheet
        self.last_timesheet = self.tl_time.get_last_timesheet(user=self.user)

        # Start testing the Timesheets.
        if not self.last_timesheet or self.last_timesheet['sg_task_end']:
            # No Timesheet exists, or the user is clocked out.
            self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=datetime.now())
        elif self.last_timesheet and not self.last_timesheet['sg_task_end']:
            # Get the last start time.
            last_start_dt = self.last_timesheet['sg_task_start']
            last_start = parser.parse('%s %s' % (last_start_dt.date(), last_start_dt.time()))

            # Test to make sure that the last timesheet was clocked out on the correct day.
            ts_from_today = self.tl_time.aint_today(date=last_start_dt.date())
            wrong_date_datetime_end = None
            wrong_date_datetime_start = None
            if ts_from_today:
                print 'Last timesheet ain\'t from today: %s' % ts_from_today
                eod = self.config['regular_end']
                end_of_day = parser.parse(eod).time()
                print 'endofday: %s' % end_of_day
                sod = self.config['regular_start']
                if last_start_dt.time() < end_of_day:
                    end_time = end_of_day
                else:
                    end_time = last_start_dt.time() + timedelta(minute=1)
                end_date = last_start_dt.date()
                wrong_date_datetime_end = parser.parse('%s %s' % (end_date, end_time))
                wrong_date_datetime_start = parser.parse('%s %s' % (datetime.now().date(), sod))

            # Create a short delayed entry from the last start
            pseudo_end = last_start + timedelta(seconds=1)
            last_task_id = str(self.last_timesheet['entity']['id'])
            current_task_id = str(context['Task']['id'])
            if current_task_id != last_task_id:
                print 'Retroactive clock-out of previous timesheet...'
                if wrong_date_datetime_end:
                    self.tl_time.clock_out_time_sheet(timesheet=self.last_timesheet, clock_out=wrong_date_datetime_end)
                    print 'Creating new retroactive timesheet block...'
                    ts_block = self.tl_time.create_new_timesheet(user=self.user, context=context,
                                                                 start_time=wrong_date_datetime_start,
                                                                 entry='Drag-n-Drop')
                else:
                    self.tl_time.clock_out_time_sheet(timesheet=self.last_timesheet, clock_out=pseudo_end)
                    print 'Creating new retroactive timesheet block...'
                    ts_block = self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=pseudo_end,
                                                                 entry='Drag-n-Drop')
                self.tl_time.clock_out_time_sheet(timesheet=ts_block, clock_out=datetime.now())
                print 'Creating New Current timesheet...'
                self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=datetime.now(),
                                                  entry='Drag-n-Drop')
                print 'New Timesheet created for %s' % self.user['name']
            elif current_task_id == last_task_id:
                if wrong_date_datetime_end:
                    print 'Creating retroactive timsheet block...'
                    self.tl_time.clock_out_time_sheet(timesheet=self.last_timesheet, clock_out=wrong_date_datetime_end)
                else:
                    print 'Creating retroactive timsheet block...'
                    self.tl_time.clock_out_time_sheet(timesheet=self.last_timesheet, clock_out=datetime.now())
                print 'Creating new timesheet...'
                self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=datetime.now(),
                                                  entry='Drag-n-Drop')
                print 'New Timesheet Created for %s' % self.user['name']




