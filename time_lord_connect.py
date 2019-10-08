"""
The Time Lord Connect is a service that will utilize the Time Lord tools to update time sheets without interfering with
the Internal Auto Publisher.
The intent is that the IAP can send signals to this utility and update and create timesheet entries.
"""

from datetime import datetime
from datetime import timedelta
from dateutil import parser
from dateutil import relativedelta
import shotgun_api3 as sgapi
# Importing the Time Lord engine libraries
from bin import configuration
from bin import shotgun_collect
from bin import time_continuum
from bin import companions


class time_lord(object):
    def __init__(self, user=None, context=None):
        # Get the configuration file
        config = configuration.get_configuration()

        # Connect to Shotgun
        self.sg = sgapi.Shotgun(config['sg_url'], config['sg_name'], config['sg_key'])

        # Setup User information and Time Continuum
        self.people = companions.companions(self.sg)
        self.tl_time = time_continuum.continuum(self.sg)

        # Set the User from the drag-n-drop
        self.user = self.people.get_user_from_username(username=user)

        # Collect the last timesheet
        # TODO: Need to put in the Ain't today stuff for double checking the stuff especially from Macs
        self.last_timesheet = self.tl_time.get_last_timesheet(user=self.user)

        # Start testing the Timesheets.
        if not self.last_timesheet or self.last_timesheet['sg_task_end']:
            # No Timesheet exists, or the user is clocked out.
            self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=datetime.now())
        elif self.last_timesheet and not self.last_timesheet['sg_task_end']:
            # Get the last start time.
            last_start_dt = self.last_timesheet['sg_task_start']
            last_start = parser.parse('%s %s' % (last_start_dt.date(), last_start_dt.time()))
            # Create a short delayed entry from the last start
            pseudo_end = last_start + timedelta(seconds=30)
            last_task_id = str(self.last_timesheet['entity']['id'])
            current_task_id = str(context['Task']['id'])
            if current_task_id != last_task_id:
                print 'Retroactive clock-out of previous timesheet...'
                self.tl_time.clock_out_time_sheet(timesheet=self.last_timesheet, clock_out=pseudo_end)
                print 'Creating new retroactive timesheet block...'
                ts_block = self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=pseudo_end,
                                                             entry='Drag-n-Drop')
                self.tl_time.clock_out_time_sheet(timesheet=ts_block, clock_out=datetime.now())
                print 'Creating New Current timesheet...'
                self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=datetime.now(),
                                                  entry='Drag-n-Drop')
                print 'New Timesheet created for %s' % user
            elif current_task_id == last_task_id:
                print 'Creating retroactive timsheet block...'
                self.tl_time.clock_out_time_sheet(timesheet=self.last_timesheet, clock_out=datetime.now())
                print 'Creating new timesheet...'
                self.tl_time.create_new_timesheet(user=self.user, context=context, start_time=datetime.now(),
                                                  entry='Drag-n-Drop')
                print 'New Timesheet Created for %s' % user




