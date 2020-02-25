"""
The companions are the human users who run along with our Time Lord.
"""

__author__ = 'Adam Benson - AdamBenson.vfx@gmail.com'
__version__ = '0.4.14'

import os
import sys
import platform
import logging

if platform.system() == 'Windows':
    env_user = 'USERNAME'
    computername = 'COMPUTERNAME'
else:
    env_user = 'USER'
    computername = 'HOSTNAME'


class companions(object):
    def __init__(self, sg=None):
        self.sg = sg
        self.logger = logging.getLogger('psychic_paper.companions')
        self.logger.info('Companions are onboard!')

    def get_user_from_computer(self):
        user = os.environ[env_user]
        # FIXME: This is a temp workaround for my laptop.
        if user == 'sleep':
            user = 'adamb'
        print user
        if user:
            filters = [
                ['login', 'is', user]
            ]
            fields = [
                'name',
                'email',
                'permission_rule_set',
                'sg_computer',
                'projects',
                'groups'
            ]
            find_user = self.sg.find_one('HumanUser', filters, fields)
            return find_user
        return False

    def get_user_from_username(self, username=None):
        if username:
            user = username
            if user:
                filters = [
                    ['login', 'is', user]
                ]
                fields = [
                    'name',
                    'email',
                    'permission_rule_set',
                    'sg_computer',
                    'projects',
                    'groups'
                ]
                find_user = self.sg.find_one('HumanUser', filters, fields)
                return find_user
            return False

