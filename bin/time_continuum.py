"""
The Time Continuum utility will check to make sure that only one time sheet is active at a time, and that all previous
entries conform to excpected dates, times and over-time statuses.
For instance:
    User forgets to clock out on Friday.  Monday the user clocks in, but last week's entry is still open.
    User forgets to clock out the day before.  Chances are strong they're not still working from the day before.
This will handle the logic that makes sure days and weeks are sorted out, and that hours can be adjusted automatically,
or that appropriate pop ups can be issued reminding the user to update their time sheet.

This engine is going to handle the logic only.  Calls to users will be handled by other engines.
"""

from __future__ import absolute_import
from __future__ import print_function
from six.moves import range
__author__ = 'Adam Benson - AdamBenson.vfx@gmail.com'
__version__ = '0.4.14'

import datetime
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import sys
from dateutil import parser
from dateutil import relativedelta
import time
import inspect
import six.moves.cPickle as pickle
from . import configuration

config = configuration.get_configuration()


class continuum(object):
    def __init__(self, sg=None):
        self.logger = logging.getLogger('psychic_paper.continuum')
        self.logger.info('Continuum Activated!')
        self.sg = sg

        # Get the TLD Time Capsule File
        self.db_path = os.path.join(sys.path[0], 'db/time_capsule.tld')
        if not os.path.exists(self.db_path):
            os.makedirs(self.db_path)

        # Days of the week in an iteratable list
        self.weekdays = [
            'Monday',
            'Tuesday',
            'Wednesday',
            'Thursday',
            'Friday',
            'Saturday',
            'Sunday'
        ]

        # get time configurations
        self.double_time_mins = int(config['dt_hours']) * 60

    def get_time_capsule(self):
        """
        This will open and collect the current time capsule file.
        :return:
        """
        if os.path.exists(self.db_path):
            fh = open(self.db_path, 'rb')
            db_file = pickle.load(fh)
            fh.close()
            return db_file

    def save_time_capsule(self, data={}):
        """
        Saves the last EventLogEntry and TimeLog to the time_capsule, allowing for checks of existing timesheets
        and preventing the processing of events more than once.
        :param data: (dict): A collection of 2 values:
                   data =   {
                                'EventLogID': 123,
                                'TimeLogID': 456
                            }
        :return: None
        """
        if data:
            if os.path.exists(self.db_path):
                fh = open(self.db_path, 'wb')
                pickle.dump(data, fh)
                fh.close()

    def start_of_week(self):
        # Get the first day of the week
        week_start = datetime.datetime.today() - datetime.timedelta(days=datetime.datetime.today().isoweekday() % 7)
        week_start = week_start.replace(tzinfo=None)
        return week_start

    def time_from_last_week(self, start_time=None):
        '''
        Checks to see if the given start time is from last week or earlier
        :param start_time: a datetime value.
        :return:
        '''
        if start_time and start_time < self.start_of_week():
            return True
        return False

    def date_is_weekday(self, date=None):
        '''
        Check to see if the given date is a weekday
        :param date: (str) a string formatted date
        :return: (tuple) (True/False, "day" string) - True if a weekday, False if not. Name returned either way.
        '''
        if type(date) == datetime or datetime.datetime:
            date = str(date)
        weekday = parser.parse(date).weekday()
        day = self.weekdays[weekday]
        if weekday < 5:
            return True, day
        return False, day

    def aint_today(self, date=None):
        '''
        A check to see if the time card is from another day.  This should precede calls to date is weekday
        :param date: a date value
        :return: True or False
        '''
        if type(date) == datetime or datetime.datetime:
            date = str(date)
            self.logger.debug('Date converted: %s' % date)
        in_date = parser.parse(date).date()
        now_date = datetime.datetime.now().date()
        if in_date != now_date:
            return True
        return False

    def get_previous_work_day(self, date=None, regular_days=[]):
        '''
        This method will take a date and return the previous working day.
        :param date: A date to count back from
        :param regular_days: [list] A list of active days from the config file
        :return: previous_day: a date
        '''
        prev_day = None
        self.logger.info('Getting the previous work day...')
        if date:
            if type(date) == str:
                self.logger.debug('String type date detected.  Converting...')
                date = parser.parse(date)

            # subtract a day
            prev_day = date - relativedelta.relativedelta(days=1)
            self.logger.debug('prev_day: %s' % prev_day)

            is_last_week = self.time_from_last_week(start_time=prev_day)
            self.logger.debug('is last week? %s' % is_last_week)

            is_weekday = self.date_is_weekday(date=prev_day)
            is_wd = is_weekday[0]
            weekday = is_weekday[1]
            if is_wd:
                self.logger.debug('is_weekday: %s' % weekday)
                if weekday in regular_days:
                    self.logger.debug('Regular day %s' % weekday)
            else:
                self.logger.debug('NOT a weekday! %s' % weekday)
                tries = 0
                while weekday not in regular_days and tries < 5:
                    prev_day = prev_day - relativedelta.relativedelta(days=1)
                    is_weekday = self.date_is_weekday(date=prev_day)
                    weekday = is_weekday[1]
                    tries += 1
                self.logger.debug('Now the weekday is: %s' % weekday)
                self.logger.debug('And the new date is: %s' % prev_day)

        return prev_day

    def get_latest_timesheet(self, user=None):
        if user:
            self.logger.debug('Finding the last timesheet for %s' % user['name'])
            user_id = user['id']
            self.logger.debug('USER ID: %s' % user_id)

            # List all the timesheets for the user
            filters = [
                ['user', 'is', {'type': 'HumanUser', 'id': user_id}],
                ['sg_task_start', 'is_not', None]
            ]
            fields = [
                'user',
                'date',
                'sg_task_start',
                'sg_task_end',
                'project',
                'entity',
                'entity.Task.entity',
                'code',
                'sg_closed'
            ]
            try:
                latest_timesheet = self.sg.find_one('TimeLog', filters, fields, order=[{'field_name': 'sg_task_start',
                                                                                        'direction': 'desc'},
                                                                                       {'field_name': 'id',
                                                                                        'direction': 'desc'}])
                self.logger.debug('Timesheet found: %s' % latest_timesheet)
            except (AttributeError, Exception) as e:
                self.logger.error('Something unexpected happened while getting the last timesheet: %s' % e)
                latest_timesheet = None
            if latest_timesheet:
                print(('Latest: %s' % latest_timesheet))
                return latest_timesheet
            return {'sg_task_end': None, 'entity': None, 'project': None, 'date': '', 'sg_task_start': None}

    def assume_end_time(self, start_time=None, eod=None):
        self.logger.debug('Assuming an end time from the date and configuration...')
        if start_time:
            if type(eod) == str:
                self.logger.debug('Converting time to datetime type...')
                eod = parser.parse(eod).time()
            raw_date = datetime.datetime.date(start_time)
            new_datetime = datetime.datetime.combine(raw_date, eod)
            self.logger.debug('End date assumed: %s' % new_datetime)
            return new_datetime

    def get_previous_timesheet(self, user=None, start_time=None):
        if user:
            self.logger.debug('Finding the last timesheet for %s' % user['name'])
            user_id = user['id']
            self.logger.debug('USER ID: %s' % user_id)

            # List all the timesheets for the user
            filters = [
                ['user', 'is', {'type': 'HumanUser', 'id': user_id}],
                ['sg_task_start', 'less_than', start_time],
                {
                    "filter_operator": "any",
                    "filters": [
                        ['sg_task_start', 'in_calendar_day', 0],
                        ['sg_task_start', 'in_calendar_day', -1]
                    ]
                }
            ]
            fields = [
                'user',
                'date',
                'sg_task_start',
                'sg_task_end',
                'project',
                'entity',
                'entity.Task.entity',
                'code',
                'sg_closed'
            ]
            try:
                previous_timesheet = self.sg.find_one('TimeLog', filters, fields, order=[{'field_name': 'sg_task_start',
                                                                                        'direction': 'desc'},
                                                                                       {'field_name': 'id',
                                                                                        'direction': 'desc'}])
                self.logger.debug('Timesheet found: %s' % previous_timesheet)
            except (AttributeError, Exception) as e:
                self.logger.error('Something unexpected happened while getting the last timesheet: %s' % e)
                previous_timesheet = None
            if previous_timesheet:
                if previous_timesheet['sg_task_end']:
                    if previous_timesheet['sg_task_end'].date() == datetime.datetime.now().date():
                        return previous_timesheet
            return {'sg_task_end': None, 'entity': None, 'project': None, 'date': '', 'sg_task_start': None}

    def get_next_timesheet(self, user=None, start_time=None, tid=None):
        if user:
            self.logger.debug('Finding the last timesheet for %s' % user['name'])
            user_id = user['id']
            self.logger.debug('USER ID: %s' % user_id)

            # List all the timesheets for the user
            filters = [
                ['user', 'is', {'type': 'HumanUser', 'id': user_id}],
                ['sg_task_start', 'greater_than', start_time],
                ['duration', 'greater_than', 0.0]
            ]
            fields = [
                'user',
                'date',
                'sg_task_start',
                'sg_task_end',
                'project',
                'entity',
                'entity.Task.entity',
                'code',
                'sg_closed'
            ]
            try:
                previous_timesheet = self.sg.find_one('TimeLog', filters, fields, order=[{'field_name': 'sg_task_start',
                                                                                        'direction': 'asc'},
                                                                                       {'field_name': 'id',
                                                                                        'direction': 'asc'}])
                self.logger.debug('Timesheet found: %s' % previous_timesheet)
            except (AttributeError, Exception) as e:
                self.logger.error('Something unexpected happened while getting the last timesheet: %s' % e)
                previous_timesheet = None
            if previous_timesheet:
                return previous_timesheet
            return {'sg_task_end': None, 'entity': None, 'project': None, 'date': '', 'sg_task_start': None}

    def clock_out_time_sheet(self, timesheet=None, clock_out=None, auto=None, comment=None):
        start = timesheet['sg_task_start']
        start_time = start.time()
        start_date = start.date()
        clock_in = parser.parse('%s %s' % (start_date, start_time))
        diff = clock_out - clock_in

        total = (diff.total_seconds() / 60)
        if timesheet:
            self.logger.debug('Timesheet: %s' % timesheet)
            # Check to see if the timesheet has already been closed.
            try:
                if timesheet['sg_closed']:
                    # Find the next empty timesheet
                    filters = [
                        ['user', 'is', {'type': 'HumanUser', 'id': timesheet['user']['id']}],
                        ['sg_task_end', 'is', None],
                        ['id', 'is_not', timesheet['id']]
                    ]
                    fields = [
                        'user',
                        'date',
                        'sg_task_start',
                        'sg_task_end',
                        'project',
                        'entity',
                        'entity.Task.entity',
                        'code',
                        'sg_closed'
                    ]
                    empty_timesheets = self.sg.find('TimeLog', filters, fields,
                                                    order=[{'field_name': 'id', 'direction': 'desc'}])
                    if empty_timesheets:
                        for e_ts in empty_timesheets:
                            # figure out if the current timesheet
                            self.logger.debug('Empty_Timesheet: %s' % e_ts)
            except KeyError as e:
                self.logger.error('Couldn\'t find the key: %s' % e)
            data = {
                'sg_task_end': clock_out,
                'duration': total
            }
            if auto:
                data['sg_auto_clock_out'] = True
            try:
                update = self.sg.update('TimeLog', timesheet['id'], data)
                self.logger.info('Successfully clocked out. %s' % update)
                self.logger.info('Timesheet updated.')
            except Exception as e:
                self.logger.error('Failed to connect.  Trying again... %s' % e)
                update = self.clock_out_time_sheet(timesheet=timesheet, clock_out=clock_out)

            # Create Note
            project_id = int(timesheet['project']['id'])
            if auto:
                n_auto = ' automatically'
            else:
                n_auto = ''
            note = 'Clocked out%s at %s' % (n_auto, clock_out)
            if comment:
                note = note + ' with the comment: %s' % comment
            n_data = {
                'subject': 'Clock Out!',
                'content': note,
                'project': {'type': 'Project', 'id': project_id},
                'time_log_sg_history_time_logs': [
                    {'type': 'TimeLog', 'id': timesheet['id']}
                ]
            }
            try:
                self.sg.create('Note', n_data)
            except Exception as e:
                print(('Create Note Failed: %s' % e))
                self.logger.error('Could not create note: %s' % e)

            return update
        return None

    def create_new_timesheet(self, user=None, context=None, start_time=None, entry='User', tries=0, comment=None):
        """
        Creates a new timesheet.  Works with Stand alone, DCC and drag-n-drop publisher
        :param user: (dict) Contains the Shotgun User ID number
        :param context: (dict) A Shotgun Context Object. Can be built manually.
        :param start_time: (datetime) a date and time to start the clock, usually datetime.now()
        :param entry: (str) This tells the system where it camer from:
                                User = Standalone
                                DCC  = SG Integrated Software
                                Auto = Drag-n-Drop Publisher
        :return: New timesheet.
        """
        self.logger.debug('create_new:', inspect.stack()[0][3], inspect.stack()[1][3])
        if user and context:
            project_id = context['Project']['id']
            task_id = context['Task']['id']
            user_id = user['id']
            self.logger.debug(context)

            if start_time and type(start_time) == datetime or type(start_time) == datetime.datetime:
                task_start = start_time
            else:
                task_start = datetime.datetime.now()
            data = {
                'entity': {'type': 'Task', 'id': task_id},
                'sg_task_start': task_start,
                'user': {'type': 'HumanUser', 'id': user_id},
                'project': {'type': 'Project', 'id': project_id},
                'description': 'Time Lord %s Entry' % entry
            }
            try:
                timesheet = self.sg.create('TimeLog', data)
            except Exception as e:
                self.logger.debug('Something failed.  Trying again... %s' % e)
                timesheet = None
                time.sleep(2)
                test_clocked_in = self.is_user_clocked_in(user=user)
                if not test_clocked_in and tries <= 5:
                    tries += 1
                    timesheet = self.create_new_timesheet(user=user, context=context, start_time=start_time,
                                                          entry=entry, tries=tries)
                else:
                    self.logger.error('Failed to create timesheet!')

            if timesheet:
                self.logger.debug(timesheet)
                current_data = self.get_time_capsule()
                self.logger.debug(current_data)
                if type(current_data) == dict and 'EventLogID' in list(current_data.keys()):
                    event_id = current_data['EventLogID']
                else:
                    event_id = 0

                data = {
                    'EventLogID': event_id,
                    'TimeLogID': timesheet['id'],
                    'current': True
                }

                try:
                    self.save_time_capsule(data)
                    self.logger.info('Time Capsule saved!')
                except IOError as e:
                    self.logger.error('Failed to save the file.  Trying again in a few seconds... %s' % e)
                    time.sleep(2)
                    self.save_time_capsule(data)

                # Create Note
                note = 'Initial Timesheet Creation by %s at %s ' % (entry, start_time)
                if comment:
                    note = note + comment
                n_data = {
                    'subject': 'New Timesheet',
                    'content': note,
                    'project': {'type': 'Project', 'id': project_id},
                    'time_log_sg_history_time_logs': [
                        {'type': 'TimeLog', 'id': timesheet['id']}
                    ]
                }
                try:
                    self.sg.create('Note', n_data)
                except Exception as e:
                    print(('Create Note Failed: %s' % e))
                    self.logger.error('Could not create note: %s' % e)
            return timesheet

    def get_running_time(self, timesheet=None):
        '''
        Calculate the total running time since clocked in.
        :param timesheet: (dict) a timesheet from Shotgun
        :return: running_time: (str) a six digit string object
        '''
        running_time = {
            'rt': '000000',
            'h': '00',
            'm': '00',
            's': '00'
        }
        if timesheet:
            if 'user' in list(timesheet.keys()):
                user = timesheet['user']
            else:
                user = {'name': os.environ['USERNAME'], 'id': 0, 'sg_computer': os.environ['COMPUTERNAME']}
            try:
                if not timesheet['sg_task_end']:
                    start_datetime = timesheet['sg_task_start']
                    self.logger.debug('~' * 50)
                    self.logger.debug('start_datetime: %s' % start_datetime)
                    self.logger.debug('start_datetime TYPE: %s' % type(start_datetime))
                    if type(start_datetime) != datetime.datetime:
                        return running_time
                    start_date = start_datetime.date()
                    start_time = start_datetime.time()
                    start = parser.parse('%s %s' % (start_date, start_time))
                    current_date = datetime.datetime.now()
                    date_diff = current_date - start
                    split_time = str(date_diff).split(':')
                    try:
                        h = '%02d' % int(split_time[0])
                        m = '%02d' % int(split_time[1])
                        s = float(split_time[2])
                        s = '%02d' % int(s)
                    except ValueError as e:
                        if 'days,' in split_time[0]:
                            split_hours = split_time[0].split('days,')
                            d = int(split_hours[0])
                            d_to_h = d * 24
                            h = int(split_hours[1])
                            h = '%02d' % int(d_to_h + h)
                        elif 'day,' in split_time[0]:
                            split_hours = split_time[0].split('day,')
                            d = int(split_hours[0])
                            d_to_h = d * 24
                            h = int(split_hours[1])
                            h = '%02d' % int(d_to_h + h)
                        else:
                            self.logger.error('Can\'t parse the hours!')
                            error = '%s:\n%s | %s\n%s | %s' % (e, inspect.stack()[0][2], inspect.stack()[0][3],
                                                               inspect.stack()[1][2], inspect.stack()[1][3])
                            self.comm.send_error_alert(user=user, error=error)
                        m = '%02d' % int(split_time[1])
                        s = float(split_time[2])
                        s = '%02d' % int(s)
                    rt = h + m + s
                    running_time = {
                        'rt': rt,
                        'h': h,
                        'm': m,
                        's': s
                    }
            except (AttributeError, TypeError) as e:
                self.logger.error('Yeah, the shit hit the fan: %s' % e)
                error = '%s:\n%s | %s\n%s | %s' % (e, inspect.stack()[0][2], inspect.stack()[0][3],
                                                   inspect.stack()[1][2], inspect.stack()[1][3])
                self.comm.send_error_alert(user=user, error=error)
        return running_time

    def get_daily_total(self, user=None, lunch_id=None, break_id=None):
        '''
        This method will search all of the timesheets for a given user, for a given day, and total up the hours.
        :param user: (dict) The main user data
        :return: A total daily hours number
        '''
        total_duration = 0.0
        if user:
            filters = [
                ['user', 'is', {'type': 'HumanUser', 'id': user['id']}],
                {
                    "filter_operator": "any",
                    "filters": [
                        ['sg_task_start', 'in_calendar_day', 0],
                        ['sg_task_start', 'in_calendar_day', -1]
                    ]
                }
            ]
            if lunch_id:
                filters.append(
                    ['entity', 'is_not', {'type': 'Task', 'id': lunch_id}]
                )
            if break_id:
                filters.append(
                    ['entity', 'is_not', {'type': 'Task', 'id': break_id}]
                )
            fields = [
                'user',
                'duration',
                'sg_task_start',
                'sg_task_end',
                'sg_closed'
            ]
            try:
                # This will get time sheets from "today" and "yesterday" because Shotgun considers anything after 6PM to
                # be "yesterday".  Thus, the in_calendar_day query has to test for both, or not all records will be
                # acquired.  Then I can iterate through them to get dates from "today"
                timesheets = self.sg.find('TimeLog', filters, fields)
            except (AttributeError, Exception) as e:
                self.logger.error('Time sheet failed to acquire: %s' % e)
                timesheets = None
            if timesheets:
                for timesheet in timesheets:
                    if not self.aint_today(timesheet['sg_task_start']):
                        if timesheet['sg_task_end']:
                            end_datetime = timesheet['sg_task_end']
                            end_date = end_datetime.date()
                            end_time = end_datetime.time()
                            end = parser.parse('%s %s' % (end_date, end_time))
                        else:
                            end = datetime.datetime.now()
                        start_datetime = timesheet['sg_task_start']
                        start_date = start_datetime.date()
                        start_time = start_datetime.time()
                        start = parser.parse('%s %s' % (start_date, start_time))

                        diff = end - start
                        total_duration += ((diff.total_seconds() / 60.0) / 60)
        return total_duration

    def get_weekly_total(self, user=None, lunch_id=None, break_id=None):
        '''
        This method will find all the time sheets for a given user for the week and total them all up.
        :param user:
        :return:
        '''
        total_duration = 0.0
        if user:
            filters = [
                ['user', 'is', {'type': 'HumanUser', 'id': user['id']}],
                {
                    "filter_operator": "any",
                    "filters": [
                        ['sg_task_start', 'in_calendar_week', 0],
                        ['sg_task_start', 'in_calendar_week', -1]
                    ]
                }
            ]
            if lunch_id:
                filters.append(
                    ['entity', 'is_not', {'type': 'Task', 'id': lunch_id}]
                )
            if break_id:
                filters.append(
                    ['entity', 'is_not', {'type': 'Task', 'id': break_id}]
                )
            fields = [
                'user',
                'duration',
                'sg_task_start',
                'sg_task_end',
                'sg_closed'
            ]
            try:
                timesheets = self.sg.find('TimeLog', filters, fields)
            except (AttributeError, Exception) as e:
                self.logger.error('Failed to get the timesheet! %s' % e)
                timesheets = None
            if timesheets:
                for timesheet in timesheets:
                    this_date = timesheet['sg_task_start'].date()
                    if this_date > self.start_of_week().date():
                        if timesheet['sg_task_end']:
                            end_datetime = timesheet['sg_task_end']
                            end_date = end_datetime.date()
                            end_time = end_datetime.time()
                            end = parser.parse('%s %s' % (end_date, end_time))
                        else:
                            end = datetime.datetime.now()
                        start_datetime = timesheet['sg_task_start']
                        start_date = start_datetime.date()
                        start_time = start_datetime.time()
                        start = parser.parse('%s %s' % (start_date, start_time))

                        diff = end - start
                        total_duration += ((diff.total_seconds() / 60.0) / 60)
        return total_duration

    def get_todays_lunch(self, user=None, lunch_id=None, lunch_proj_id=None):
        if user and lunch_id:
            user_id = user['id']
            filters = [
                ['project', 'is', {'type': 'Project', 'id': lunch_proj_id}],
                ['user', 'is', {'type': 'HumanUser', 'id': user_id}],
                ['entity', 'is', {'type': 'Task', 'id': lunch_id}],
                {
                    "filter_operator": "any",
                    "filters": [
                        ['sg_task_start', 'in_calendar_day', 0],
                        ['sg_task_start', 'in_calendar_day', -1]
                    ]
                }
            ]
            fields = [
                'user',
                'date',
                'sg_task_start',
                'sg_task_end',
                'project',
                'entity',
                'entity.Task.entity',
                'duration',
                'sg_closed'
            ]
            try:
                get_lunch = self.sg.find('TimeLog', filters, fields)
            except AttributeError as e:
                self.logger.error('Get Lunch failed.  Trying again.')
                get_lunch = self.get_todays_lunch(user=user, lunch_id=lunch_id, lunch_proj_id=lunch_proj_id)
            if get_lunch:
                self.logger.debug('lunch_returns: %s' % get_lunch)
                today = datetime.datetime.now().date()
                for lunch in get_lunch:
                    start_date = lunch['sg_task_start'].date()
                    index = get_lunch.index(lunch)
                    if start_date != today:
                        get_lunch.pop(index)
                    if not get_lunch:
                        get_lunch = False
                return get_lunch
            else:
                self.logger.info('No lunch for you!')
                return False

    def create_lunch_break(self, user=None, lunch_id=None, task_id=None):
        if user:
            print('hello')

    def is_user_clocked_in(self, user=None):
        if user:
            self.logger.debug('Looking to see if %s is clocked in....' % user['name'])
            user_id = user['id']

            # List all the timesheets for the user
            filters = [
                ['user', 'is', {'type': 'HumanUser', 'id': user_id}]
            ]
            fields = [
                'user',
                'sg_task_start',
                'sg_task_end'
            ]
            try:
                clocked_in = self.sg.find_one('TimeLog', filters, fields, order=[{'field_name': 'sg_task_start',
                                                                                  'direction': 'desc'},
                                                                                 {'field_name': 'id',
                                                                                  'direction': 'desc'}])
            except Exception as e:
                self.logger.error('Could not check clocked in: %s' % e)
                clocked_in = None

            if clocked_in and clocked_in['sg_task_end']:
                return False
            return True

    def get_active_timesheets(self):
        # TODO: Might add some calendar day checks in here too
        filters = [
            ['sg_task_start', 'is_not', None],
            ['sg_task_end', 'is', None]
        ]
        fields = [
            'user',
            'sg_task_start',
            'sg_task_end',
            'project',
            'entity',
            'entity.Task.entity',
            'duration',
            'sg_closed'
        ]
        conn_attempts = 0
        timesheets = None
        while True:
            try:
                timesheets = self.sg.find('TimeLog', filters, fields)
            except Exception as e:
                if conn_attempts > 5:
                    self.logger.error('Failed to connect!')
                    break
                else:
                    self.logger.error('Bad connection.  Trying again...')
                    conn_attempts += 1
                    time.sleep(2)
            if timesheets:
                return timesheets
        return None

    def get_timesheet_by_id(self, tid=None):
        if tid:
            if type(tid) != int:
                tid = int(tid)
            filters = [
                ['id', 'is', tid]
            ]
            fields = [
                'user',
                'sg_task_start',
                'sg_task_end',
                'project',
                'entity',
                'entity.Task.entity',
                'duration',
                'sg_closed'
            ]
            conn_attempts = 0
            timesheet = None
            while True:
                try:
                    timesheet = self.sg.find_one('TimeLog', filters, fields)
                except Exception as e:
                    if conn_attempts > 5:
                        self.logger.error('Failed to connect!')
                        break
                    else:
                        self.logger.error('Bad connection.  Trying again...')
                        conn_attempts += 1
                        time.sleep(2)
                if timesheet:
                    return timesheet
        return None

    def get_all_timesheets_by_project(self, proj_id=None, users=None):
        timesheets = []
        if proj_id:
            filters = [
                ['project', 'is', {'type': 'Project', 'id': proj_id}],
                ['duration', 'greater_than', 0.0]
            ]
            if users:
                add_filters = []
                for user in users:
                    add_filters.append(['user', 'is', {'type': 'HumanUser', 'id': user['id']}])
                filter_ops = {
                    'filter_operator': 'any',
                    'filters': add_filters
                }
                filters.append(filter_ops)
            fields = [
                'user',
                'date',
                'sg_task_start',
                'sg_task_end',
                'project',
                'entity',
                'entity.Task.entity',
                'code',
                'sg_closed',
                'duration'
            ]
            try:
                timesheets = self.sg.find('TimeLog', filters, fields)
            except Exception as e:
                self.logger.error('Get all user timesheets by date failed.')
        return timesheets

    def timesheet_cleanup(self, user=None):
        """
        This method is designed to check for dead or accidental timesheets.  Time sheets that are not current, and
        which still have open ended records. i.e. More than one timesheet that hasn't been clocked out.
        It gets a collection of open ended timesheets for a user.
        If there is more than one record, then it double checks that the opened one is the most recent (might need to
        do that anyways)
        If there is more than one record, then a new collection gets all the timesheets surrounding the empty timesheet.
        It will check the next record's start time. If the start time is the same, either delete the duplicate record,
        or set its out time to the in time.
        If it aint_today, then it will check for EOD status, and clock it out at the EOD, or thereafter.
        :return: 'Cleaned' or 'Clean'
        """
        if user:
            filters = [
                ['user', 'is', {'type': 'HumanUser', 'id': user['id']}],
                {
                    "filter_operator": "any",
                    "filters": [
                        ['sg_task_start', 'is', None],
                        ['sg_task_end', 'is', None]
                    ]
                }
            ]
            fields = [
                'sg_task_start',
                'sg_task_end',
                'id',
                'user',
                'date',
                'sg_closed'
            ]
            try:
                empties = self.sg.find('TimeLog', filters, fields, order=[{'field_name': 'id', 'direction': 'desc'}])
            except Exception as e:
                self.logger.error('Couldn\'t get emtpies. Connection failure: %s' % e)
                # error = '%s:\n%s | %s\n%s | %s' % (e, inspect.stack()[0][2], inspect.stack()[0][3],
                #                                    inspect.stack()[1][2], inspect.stack()[1][3])
                # self.comm.send_error_alert(user=user, error=error)
                empties = None
            if empties:
                latest_timesheet = {'project': None}
                tries = 0
                while not latest_timesheet['project'] and tries < 10:
                    latest_timesheet = self.get_latest_timesheet(user=user)
                    tries += 1
                    time.sleep(5)
                if not latest_timesheet['project']:
                    return False
                latest_id = latest_timesheet['id']
                for empty in empties:
                    if empty['id'] != latest_id:
                        date = empty['date']
                        if type(date) != datetime or type(date) != datetime.datetime:
                            date = parser.parse(date).date()
                        sell_by_date = datetime.datetime.date(datetime.datetime.now()) - datetime.timedelta(days=30)
                        if date > sell_by_date:
                            if not empty['sg_task_start'] and not empty['sg_task_end']:
                                self.logger.debug('Total shitshow.  Ignore or delete.')
                            elif empty['sg_task_start'] and not empty['sg_task_end']:
                                next_ts = None
                                get_next_id = empty['id'] + 1
                                while not next_ts:
                                    try_next = self.get_timesheet_by_id(tid=get_next_id)
                                    if try_next and try_next['user']['id'] == user['id']:
                                        self.logger.debug('Found Next!')
                                        next_ts = try_next
                                        break
                                    get_next_id += 1
                                next_start = next_ts['sg_task_start']
                                self.logger.debug(type(next_start))
                                if type(next_start) != datetime.datetime:
                                    next_start = parser.parse(next_start)
                                if self.aint_today(next_start):
                                    self.logger.debug('Current timesheet is from previous day!')
                                    # Compare start time to EOD, if before: set EOD, else: set start time + 5 minutes.
                                else:
                                    data = {
                                        'sg_task_end': next_ts['sg_task_start'],
                                        'description': 'Time Lord Cleanup Processed'
                                    }
                                    tries = 0
                                    try:
                                        update = self.sg.update('TimeLog', empty['id'], data)

                                        # Create Note
                                        project_id = int(empty['project']['id'])
                                        note = 'Closed automatically at %s by the Cleanup Process for being an ' \
                                               'extraneous timesheet.'
                                        n_data = {
                                            'subject': 'Cleanup Process',
                                            'content': note,
                                            'project': {'type': 'Project', 'id': project_id},
                                            'time_log_sg_history_time_logs': [
                                                {'type': 'TimeLog', 'id': empty['id']}
                                            ]
                                        }
                                        try:
                                            self.sg.create('Note', n_data)
                                            self.logger.debug('Note created!')
                                        except Exception as e:
                                            print(('Create Note Failed: %s' % e))
                                            self.logger.error('Could not create note: %s' % e)
                                    except Exception as e:
                                        # FIXME: This does nothing!
                                        tries += 1
                                        self.logger.error('Cleanup process failed while updating... '
                                                          'Making another atempt: #%i' % tries)
                                        self.logger.error('Issue: %s' % e)
                                        if tries > 10:
                                            self.logger.error('Total Failure! %s' % e)
                                            return False
                                        update = None

                                    self.logger.debug('Updated: %s' % update)
                return empties

        return False

    def timesheet_consistency_cleanup(self, user=None, clock_out=False):
        end = datetime.datetime.now()
        start = (end - datetime.timedelta(days=1))
        filters = [
            ['user', 'is', {'type': 'HumanUser', 'id': user['id']}],
            {
                "filter_operator": "all",
                "filters": [
                    ['sg_task_start', 'greater_than', start],
                ]
            }
        ]
        if clock_out:
            filters.append(
                {
                    "filter_operator": "any",
                    "filters": [
                        ['sg_task_end', 'less_than', end],
                        ['sg_task_end', 'is', None]
                    ]
                }
            )
        else:
            filters.append(
                ['sg_task_end', 'less_than', end]
            )
        fields = [
            'user',
            'duration',
            'sg_task_start',
            'sg_task_end'
        ]
        try:
            get_timesheets = self.sg.find('TimeLog', filters, fields, order=[{'field_name': 'id', 'direction': 'desc'}])
        except Exception:
            self.logger.error(Exception)
            return False
        try:
            ordered_timesheets = sorted(get_timesheets, key=lambda x: (x['sg_task_start'], x['sg_task_end']),
                                        reverse=True)
        except TypeError as e:
            self.logger.warning('Missing data for sort.  Switching methods')
            ordered_timesheets = sorted(get_timesheets, key=lambda x: (x('sg_task_start'), x['id']), reverse=True)
        except Exception as e:
            self.logger.error('Could not order the timesheets!')
            error = '%s:\n%s | %s\n%s | %s' % (e, inspect.stack()[0][2], inspect.stack()[0][3],
                                               inspect.stack()[1][2], inspect.stack()[1][3])
            self.comm.send_error_alert(user=user, error=error)
            return False
        ts_count = len(ordered_timesheets)
        updates = []

        for ts in range(0, (ts_count - 1)):
            current_start = ordered_timesheets[ts]['sg_task_start']
            current_end = ordered_timesheets[ts]['sg_task_end']

            # Start Natural Anomalies checks. These include timesheets that span across days, negative times or
            # excesive hours
            # First check for timesheets whose start and end DATES don't match - spanning across days.
            if type(current_start) == datetime.datetime and type(current_end) == datetime.datetime:
                current_start_date = current_start.date()
                current_end_date = current_end.date()
                if current_start_date != current_end_date:
                    data = {
                        'sg_needs_approval': True
                    }
                    update = self.sg.update('TimeLog', ordered_timesheets[ts]['id'], data)
                    self.logger.debug('Update Needs Approval')
                    updates.append(update)

                    # Create Note
                    try:
                        project_id = int(ordered_timesheets[ts]['project']['id'])
                    except:
                        project_id = int(self.config['admin_proj_id'])
                    note = 'Marked "Needs Approval" for going into another day by the automatic consistency checker.'
                    n_data = {
                        'subject': 'Consistency Cleanup',
                        'content': note,
                        'project': {'type': 'Project', 'id': project_id},
                        'time_log_sg_history_time_logs': [
                            {'type': 'TimeLog', 'id': ordered_timesheets[ts]['id']}
                        ]
                    }
                    try:
                        self.sg.create('Note', n_data)
                    except Exception as e:
                        print(('Create Note Failed: %s' % e))
                        self.logger.error('Could not create note: %s' % e)

            # Next check for durations greater than double time hours, or durations having negative values.
            # I am currently skipping durations over 8 hours because it would get ridiculous. 12 hours seems fair here.
            duration = ordered_timesheets[ts]['duration']
            if duration > self.double_time_mins or duration < 0.0:
                data = {
                    'sg_needs_approval': True
                }
                update = self.sg.update('TimeLog', ordered_timesheets[ts]['id'], data)
                self.logger.debug('Update Needs Approval on Duration')
                updates.append(update)

                # Create Note
                try:
                    project_id = int(ordered_timesheets[ts]['project']['id'])
                except:
                    project_id = int(self.config['admin_proj_id'])
                note = 'Marked "Needs Approval" for excessive or negative time by the automatic consistency checker.'
                n_data = {
                    'subject': 'Consistency Cleanup',
                    'content': note,
                    'project': {'type': 'Project', 'id': project_id},
                    'time_log_sg_history_time_logs': [
                        {'type': 'TimeLog', 'id': ordered_timesheets[ts]['id']}
                    ]
                }
                try:
                    self.sg.create('Note', n_data)
                except Exception as e:
                    print(('Create Note Failed: %s' % e))
                    self.logger.error('Could not create note: %s' % e)

            # Check against previous time sheets
            if (ts + 1) > ts_count:
                # Break if the next record doesn't exist.
                break
            try:
                previous_start = ordered_timesheets[ts+1]['sg_task_start']
                previous_end = ordered_timesheets[ts+1]['sg_task_end']
                previous_id = int(ordered_timesheets[ts+1]['id'])
            except Exception as e:
                self.logger.debug('Timesheet consistency error: %s' % e)
                error = '%s:\n%s | %s\n%s | %s' % (e, inspect.stack()[0][2], inspect.stack()[0][3],
                                                   inspect.stack()[1][2], inspect.stack()[1][3])
                self.comm.send_error_alert(user=user, error=error)

                # Set Values to None
                previous_start = None
                previous_end = None
                previous_id = None

            if previous_end and current_start:
                if previous_end > current_start:
                    if ts == ts_count - 1:
                        previous_end = ordered_timesheets[ts-1]['sg_task_start']
                    else:
                        previous_end = current_start
                    data = {
                        'sg_task_end': previous_end,
                        'sg_closed': True
                    }
                    try:
                        update = self.sg.update('TimeLog', previous_id, data)
                        self.logger.debug('update output: %s' % update)
                        updates.append(update)

                        # Create Note
                        try:
                            project_id = int(ordered_timesheets[ts]['project']['id'])
                        except:
                            project_id = int(self.config['admin_proj_id'])
                        note = 'End time was adjusted automatically to %s by the Consistency Cleanup ' \
                               'Process' % previous_end
                        n_data = {
                            'subject': 'Consistency Cleanup',
                            'content': note,
                            'project': {'type': 'Project', 'id': project_id},
                            'time_log_sg_history_time_logs': [
                                {'type': 'TimeLog', 'id': ordered_timesheets[ts]['id']}
                            ]
                        }
                        try:
                            self.sg.create('Note', n_data)
                        except Exception as e:
                            print(('Create Note Failed: %s' % e))
                            self.logger.error('Could not create note: %s' % e)

                    except AttributeError as e:
                        self.logger.error('Failed to update the TimeLog.')
                        # NOTE: I could probably add a retry here.
                        error = '%s:\n%s | %s\n%s | %s' % (e, inspect.stack()[0][2], inspect.stack()[0][3],
                                                           inspect.stack()[1][2], inspect.stack()[1][3])
                        self.comm.send_error_alert(user=user, error=error)

        return updates

    def get_user_total_in_range(self, user=None, start=None, end=None, lunch_id=None, break_id=None):
        total_duration = 0.0
        if user and start and end:
            start = parser.parse(start)
            end = parser.parse(end)

            filters = [
                ['user', 'is', {'type': 'HumanUser', 'id': user}],
                {
                    "filter_operator": "all",
                    "filters": [
                        ['sg_task_start', 'greater_than', start],
                        ['sg_task_end', 'less_than', end]
                    ]
                },
                ['duration', 'greater_than', 0.0]
            ]
            if lunch_id:
                filters.append(
                    ['entity', 'is_not', {'type': 'Task', 'id': lunch_id}]
                )
            if break_id:
                filters.append(
                    ['entity', 'is_not', {'type': 'Task', 'id': break_id}]
                )
            fields = [
                'user',
                'duration',
                'sg_task_start',
                'sg_task_end'
            ]
            get_timesheets = self.sg.find('TimeLog', filters, fields, order=[{'field_name': 'id', 'direction': 'desc'}])
            if get_timesheets:
                for timesheet in get_timesheets:
                    total_duration += (float(timesheet['duration']) / 60.0)
        return total_duration

    def get_all_user_timesheets_by_date(self, user=None, date=None, order='desc'):
        if user and date:
            previous_date = date - datetime.timedelta(days=1)
            # print('previous date: %s' % previous_date)
            # print('date: %s' % date)
            next_date = date + datetime.timedelta(days=1)
            # print('next_date: %s' % next_date)
            user_id = user['id']

            filters = [
                ['user', 'is', {'type': 'HumanUser', 'id': user_id}],
                {
                    'filter_operator': 'all',
                    'filters': [
                        ['sg_task_start', 'greater_than', previous_date],
                        ['sg_task_start', 'less_than', next_date]
                    ]
                },
                ['duration', 'greater_than', 0.0]
            ]
            fields = [
                'user',
                'date',
                'sg_task_start',
                'sg_task_end',
                'project',
                'entity',
                'entity.Task.entity',
                'code',
                'sg_closed',
                'duration'
            ]

            try:
                timesheets = self.sg.find('TimeLog', filters, fields, order=[{'field_name': 'sg_task_start',
                                                                              'direction': order},
                                                                             {'field_name': 'id',
                                                                              'direction': order}])
                if timesheets:
                    for sheet in timesheets:
                        if str(date.date()) != str(sheet['sg_task_start'].date()):
                            index = timesheets.index(sheet)
                            timesheets.pop(index)
            except Exception as e:
                self.logger.error('Get all user timesheets by date failed.')
                timesheets = []
                # print self.get_latest_timesheet(user=user)
        return timesheets

    def get_all_timsheets_in_range(self, proj_id=None, start=None, end=None, all_time=False, order='desc'):
        timesheets = []
        if start and end:
            previous_start = start - datetime.timedelta(days=1)
            next_end = end + datetime.timedelta(days=1)

            filters = [
                ['duration', 'greater_than', 0.0]
            ]
            if not all_time:
                filters.append(
                    {
                        'filter_operator': 'all',
                        'filters': [
                            ['sg_task_start', 'greater_than', previous_start],
                            ['sg_task_end', 'less_than', next_end]
                        ]
                    }
                )
            if proj_id:
                filters.append(
                    ['project', 'is', {'type': 'Project', 'id': int(proj_id)}]
                )
            fields = [
                'user',
                'date',
                'sg_task_start',
                'sg_task_end',
                'project',
                'entity',
                'entity.Task.entity',
                'code',
                'sg_closed',
                'duration'
            ]
            try:
                timesheets = self.sg.find('TimeLog', filters, fields, order=[{'field_name': 'sg_task_start',
                                                                              'direction': order},
                                                                             {'field_name': 'id',
                                                                              'direction': order}])
                if timesheets:
                    for sheet in timesheets:
                        if type(sheet['sg_task_start']) == datetime.datetime:
                            if str(start.date()) != str(sheet['sg_task_start'].date()):
                                index = timesheets.index(sheet)
                                timesheets.pop(index)
            except Exception as e:
                print(('Shit the bed: %s' % e))
                self.logger.error('Cannot get all the timesheets! %s' % e)
                timesheets = []
        return timesheets

    def update_current_times(self, user=None, tid=None, start_time=None, end_time=None):
        update = None
        if user and tid and start_time:
            data = {
                'sg_task_start': start_time,
                'description': 'Updated by %s through Time Lord' % user['name']
            }
            if end_time:
                data['sg_task_end'] = end_time
            try:
                update = self.sg.update('TimeLog', tid, data)
                self.logger.debug('update start time output: %s' % update)
            except Exception as e:
                print(('Shit the bed: %s' % e))
                self.logger.error('Timesheet update failed: %s' % e)
            if update:
                self.timesheet_consistency_cleanup(user=user)
        return update

    def delete_timelog_by_id(self, tid=None):
        if tid:
            deleted = self.sg.delete('TimeLog', int(tid))
            return deleted

    def pretty_date_time(self, date_time=None):
        if date_time and type(date_time) == datetime.datetime:
            _date = date_time.date()
            _time = date_time.time()
            try:
                fmt_date = _date.strftime('%m/%d/%Y')
                fmt_time = _time.strftime('%I:%M %p')
                new_datetime = '%s %s' % (fmt_date, fmt_time)
                return new_datetime
            except Exception as e:
                self.logger.error('Can\'t convert datetime', e)
                return date_time


