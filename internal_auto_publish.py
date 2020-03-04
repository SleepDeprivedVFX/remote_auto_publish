"""
The Internal Auto Publisher (IAP) is a server listener that gets data from the server logs in order to better port
"""

from __future__ import absolute_import
from __future__ import print_function
import os
import sys
from glob import glob
import re
import time
import logging
import logging.handlers
import shutil
import yaml
import psd_tools as psd
import shotgun_api3
import queue
import threading
from datetime import datetime
import socketserver
import subprocess
import configparser
import requests
import json

import time_lord_connect as tlc

# __author__ = 'Adam Benson'
# __version__ = '1.0.1'

sys_path = sys.path
config_file = 'auto_publisher_config.cfg'
try:
    print('Finding configuration file...')
    config_path = [f for f in sys_path if os.path.isfile(f + '/' + config_file)][0] + '/' + config_file
    config_path = config_path.replace('\\', '/')
    print('Configuration found!')
except IndexError as e:
    raise e

configuration = configparser.ConfigParser()
print('Reading the configuration file...')
configuration.read(config_path)

cfg_sg_url = configuration.get('Shotgun', 'shotgun_url')
cfg_sg_key = configuration.get('Shotgun', 'shotgun_key')
cfg_sg_name = configuration.get('Shotgun', 'shotgun_name')

# Build Shotgun Connection
sg = shotgun_api3.Shotgun(cfg_sg_url, cfg_sg_name, cfg_sg_key)

# Server Logs Connections
HOST = configuration.get('IAP', 'host')
PORT = int(configuration.get('IAP', 'port'))

# Watch Folder Filters
publish_path_to_watch = configuration.get('Publisher', 'publish_path')
ref_path_to_watch = configuration.get('Referencer', 'reference_path')
publish_root_folder = configuration.get('Publisher', 'publish_root')
archive_project = configuration.get('Archive', 'archive_project')
archive_id = configuration.get('Archive', 'archive_proj_id')
archive_path = configuration.get('Archive', 'archive_path')
archive_dest = configuration.get('Archive', 'archive_destination')
archive_orig = configuration.get('Archive', 'archive_origin')
archive_path_to_watch = '%s%s/\w+/\w+' % (archive_path, archive_orig)
server_root = configuration.get('IAP', 'server_root')
auth_code = configuration.get('Slack', 'auth_code')
slack_url = configuration.get('Slack', 'slack_url')
global_ref_entity = configuration.get('Referencer', 'global_ref_entity')
ref_docs_folder = configuration.get('Referencer', 'ref_docs_folder')
ref_imgs_folder = configuration.get('Referencer', 'ref_imgs_folder')
ref_vids_folder = configuration.get('Referencer', 'ref_vids_folder')
api_user_id = configuration.get('IAP', 'api_user_id')

# Output window startup messages
print(('-' * 100))
print('INTERNAL AUTO PUBLISH UTILITY')
print(('+' * 100))


'''
TIME LORD UPDATE
The latest changes are going to be a test of utilizing some existing Time Lord tech and integrating it into the IAP just
a little bit.
There are a few things that I do need to figure out.
1. How to start and/or retroactively start a timesheet based on the drag and drop
2. How to test against the timesheets that are currently in line, and thus update the Time Lord UI.
'''


# Create Log file
debug = configuration.get('Logging', 'debug_logging')

if debug == 'True':
    log_level = logging.DEBUG
else:
    log_level = logging.INFO


def _setFilePathOnLogger(logger, path):
    # Remove any previous handler.
    _removeHandlersFromLogger(logger, None)

    # Add the file handler
    handler = logging.handlers.TimedRotatingFileHandler(path, 'D', interval=30, backupCount=10)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s:%(lineno)d - %(message)s"))
    logger.addHandler(handler)


def _removeHandlersFromLogger(logger, handlerTypes=None):
    """
    Remove all handlers or handlers of a specified type from a logger.

    @param logger: The logger who's handlers should be processed.
    @type logger: A logging.Logger object
    @param handlerTypes: A type of handler or list/tuple of types of handlers
        that should be removed from the logger. If I{None}, all handlers are
        removed.
    @type handlerTypes: L{None}, a logging.Handler subclass or
        I{list}/I{tuple} of logging.Handler subclasses.
    """
    for handler in logger.handlers:
        if handlerTypes is None or isinstance(handler, handlerTypes):
            logger.removeHandler(handler)


logfile = "%s/internalAutoPublish.%s.log" % (configuration.get('Logging', 'log_file_path'),
                                             datetime.date(datetime.now()))

logger = logging.getLogger('internal_auto_publish')
logger.setLevel(log_level)
_setFilePathOnLogger(logger, logfile)

print('Logging system setup.')
logger.info('Starting the Internal Auto Publisher...')
print('Starting the Internal Auto Publisher...')

# --------------------------------------------------------------------------------------------------------------
# Global Variables
# --------------------------------------------------------------------------------------------------------------
# Because of the simplistic nature of this tool, I am currently limiting its use to one task: design.main.
# The reason for this is simple: having task folders as subfolders of assets will make remote use cumbersome for
# designers who struggle with anything more complicated than a doorknob. (The same people who could not set the clock
# on their VCRs and just let them blink endlessly.)  The other reason is that, currently, only designers will be using
# this, and there are no immediate plans to change that.  That being said, there is some minor architecture in place
# to handle a more complex, task-based system if one is ever needed.
# Thus, the one task_name:

# Default task name
task_name = configuration.get('Publisher', 'default_task_name')
# Design task step ID
task_step = int(configuration.get('Publisher', 'task_step_id'))
# Schema path used for getting the base configuration files
relative_config_path = configuration.get('IAP', 'relative_config_path')
task_name_format = configuration.get('Publisher', 'task_name_format')

publish_types = {
    '.psd': 'Photoshop Image',
    '.psb': 'Photoshop Image',
    '.nk': 'Nuke Script',
    '.mb': 'Maya Scene',
    '.ma': 'Maya Scene',
    '.ztl': 'ZBrush',
    '.zzz': 'ZBrush',
    '.zpr': 'ZBrush',
    '.mud': 'Mudbox',
    '.bip': 'Keyshot Package',
    '.ksp': 'Keyshot Package',
    '.kpg': 'Keyshot File',
    '.spp': 'Substance Painter'
}
ignore_types = [
    '.DS_Store',
    '.db',
    '.smbdeleteAAA0dca4.4',
    '.smbdeleteAAA0dca4',
    '.smbdelete'
]

'''
# generate_types will create the values if the keys are certain values.  Thus, if ext == '.psd' then '.jpg' will be made
# Settings are as follows: 
:param: type: Document type
:param: output: file type to export
:param: render: where to put the file. Acceptable answers are 'Renders', 'Textures', and 'Upload'
'''
generate_types = {
    '.psd': {
        'type': 'Photoshop Image',
        'output': 'jpg',
        'render': 'Renders'
    },
    '.psb': {
        'type': 'Photoshop Image',
        'output': 'jpg',
        'render': 'Renders'
    }
}
upload_types = [
    '.jpg',
    '.gif',
    '.jpeg',
    '.tif',
    '.tiff',
    '.png',
    '.mov',
    '.mp4',
    '.tga',
    '.mpg',
    '.pdf'
]
video_types = [
    '.mov',
    '.mp4',
    '.mpeg',
    '.avi',
    '.mpg',
    '.pdf'
]
reference_types = [
    '.jpg',
    '.jpeg',
    '.tif',
    '.tiff',
    '.png',
    '.mov',
    '.mp4',
    '.tga',
    '.mpg',
    '.pdf',
    '.xls',
    '.xlsx',
    '.csv',
    '.doc',
    '.docx',
    '.txt',
    '.rtf',
    '.htm',
    '.html',
    '.psd',
    '.obj',
    '.fbx',
    '.dpx',
    '.exr',
    '.ma',
    '.mb',
    '.nk',
    '.ztl',
    '.zpr',
    '.gif'
]
templates = {
    'Photoshop Image': {
        'work_area': 'asset_work_area_photoshop',
        'work_template': 'photoshop_asset_work',
        'publish_area': 'asset_publish_area_photoshop',
        'publish_template': 'photoshop_asset_publish'
    },
    'Nuke Script': {
        'work_area': 'asset_work_area_nuke',
        'work_template': 'nuke_asset_work',
        'publish_area': 'asset_publish_area_nuke',
        'publish_template': 'nuke_asset_publish'
    },
    'Maya Scene': {
        'work_area': 'asset_work_area_maya',
        'work_template': 'maya_asset_work',
        'publish_area': 'asset_publish_area_maya',
        'publish_template': 'maya_asset_publish'
    },
    'ZBrush': {
        'work_area': 'asset_work_area_zbrush',
        'work_template': 'asset_work_zbrush',
        'publish_area': 'asset_publish_area_zbrush',
        'publish_template': 'asset_publish_zbrush'
    },
    'Mudbox': {
        'work_area': 'asset_work_area_mudbox',
        'work_template': 'asset_work_mudbox',
        'publish_area': 'asset_publish_area_mudbox',
        'publish_template': 'asset_publish_mudbox'
    },
    'Keyshot Package': {
        'work_area': 'asset_work_area_keyshot',
        'work_template': 'asset_work_keyshot_bip',
        'publish_area': 'asset_publish_area_keyshot',
        'publish_template': 'asset_publish_keyshot_bip'
    },
    'Keyshot File': {
        'work_area': 'asset_work_area_keyshot',
        'work_template': 'asset_work_keyshot',
        'publish_area': 'asset_publish_area_keyshot',
        'publish_template': 'asset_publish_keyshot'
    },
    'Renders': {
        'work_area': None,
        'work_template': None,
        'publish_area': 'asset_render_area',
        'publish_template': 'asset_render_output_jpg'
    },
    'Textures': {
        'work_area': None,
        'work_template': None,
        'publish_area': 'asset_texture_publish_area',
        'publish_template': 'asset_texture_publish'
    },
    'Send Today': {
        'work_area': 'send_today',
        'work_template': None,
        'publish_area': None,
        'publish_template': None
    },
    'Root Reference': {
        'work_area': 'root_reference',
        'work_template': None,
        'publish_area': None,
        'publish_template': None
    },
    'Asset Reference': {
        'work_area': 'asset_reference_area',
        'work_template': None,
        'publish_area': None,
        'publish_template': None
    },
    'Asset Renders': {
        'work_area': 'asset_render_area',
        'work_template': None,
        'publish_area': None,
        'publish_template': None
    },
    'Substance Painter': {
        'work_area': 'asset_work_area_substancepainter',
        'work_template': 'substancepainter_asset_work',
        'publish_area': 'asset_publish_area_substancepainter',
        'publish_template': 'substancepainter_asset_publish'
    }
}


# -----------------------------------------------------------------------------------------------------------------
# Processor Queue
# -----------------------------------------------------------------------------------------------------------------
logger.debug('Creating the Queue...')
q = queue.Queue()

logger.debug('Creating the Archival Queue...')
aq = queue.Queue()

logger.debug('Creating the Reference Queue...')
rq = queue.Queue()


# -----------------------------------------------------------------------------------------------------------------
# Start Processing...
# -----------------------------------------------------------------------------------------------------------------
def process_file(filename=None, template=None, roots=None, proj_id=None, proj_name=None, user=None, ip=None):
    """
    This processes the new file and decides if it is a simple image, or a more complex file and then figures out what
     it should do with it from there.
    :param filename:
    :param template:
    :param roots:
    :param proj_id:
    :param proj_name:
    :return:
    """

    # Taking the global task_name, so that it can be set globally and passed to other functions.
    global task_name

    try:
        if user:
            if '.' in task_name:
                base_task = task_name.split('.')[0]
                task_name = '%s.%s' % (base_task, user)
        # Check that data is there and that the file actually exists
        if filename and os.path.exists(filename):
            logger.info('-' * 120)
            logger.info('NEW FILE PROCESSING...')
            logger.info('!' * 100)
            print('New File Processing...')
            print(filename)
            logger.info(filename)
            print(('Published by %s' % user))
            logger.info('Published by %s' % user)
            print(('At: %s' % datetime.now()))
            logger.info('At: %s' % datetime.now())

            # Get the path details from the filename
            path = os.path.dirname(filename)
            logger.debug('PATH: %s' % path)
            # Filename without path
            base_file = os.path.basename(filename)
            # Relative path outside the dropbox structure
            split_pattern = re.findall(publish_path_to_watch, path)
            if split_pattern:
                split_pattern = split_pattern[0]
            else:
                logger.warning('This file is not in a proper asset structure!  Can not process.')
                print('This file is not in the proper asset structure!  Cannot process!')
                print(('=' * 100))

                # Send a pop up message to the user!
                msg = 'DRAG -N- DROP PUBLISHER ALERT!\n\n' \
                      'You can not publish files from the root "Publish" folder. It MUST be put into a pre-existing ' \
                      'ASSET folder. If there is no existing folder, see your supervisor or coordinator.'
                send_user_message(user=user, ip=ip, msg=msg)
                return False
            rel_path = path.split(split_pattern)[1]
            if not rel_path:
                rel_path = path
            logger.debug('Relative Path: %s' % rel_path)

            f = os.path.splitext(base_file)
            # File extension
            ext = str(f[1]).lower()
            # Filename without path or extension.
            file_name = f[0]

            logger.debug('Project Details returns: project: %s ID: %s' % (proj_name, proj_id))

            # If the project is found, continue processing.
            if proj_id:
                # Look for assets based on the project name and the relative path
                find_asset = get_asset_details_from_path(proj_name, proj_id, rel_path)
                asset_name = find_asset['name']
                asset_id = find_asset['id']
                asset_type = find_asset['type']

                # If an asset is found, continue processing.
                if asset_id:
                    logger.info('The Asset is found in the system! %s: %s' % (asset_id, asset_name))
                    logger.debug('Asset type: %s' % asset_type)

                    task = get_set_task(asset=find_asset, proj_id=proj_id, user=user)
                    logger.debug('Task ID returned: %s' % task)

                    # Find the Shotgun configuration root path
                    find_config = get_configuration(proj_id)
                    logger.debug('Configuration found: %s' % find_config)

                    if ext.lower() in publish_types:
                        # Find out from the ext which configuration to get from the template.
                        logger.debug('This is a publish level file...')
                        publish_type = publish_types[ext]
                        template_type = templates[publish_type]

                        # Resolve the templates with known data to get the template path.
                        work_template = resolve_template_path(template_type['work_template'], template)
                        logger.debug('WORK TEMPLATE: %s' % work_template)
                        work_area = resolve_template_path(template_type['work_area'], template)
                        logger.debug('WORK Area: %s' % work_area)
                        publish_template = resolve_template_path(template_type['publish_template'], template)
                        logger.debug('PUBLISH TEMPLATE: %s' % publish_template)
                        publish_area = resolve_template_path(template_type['publish_area'], template)
                        logger.debug('PUBLISH AREA: %s' % publish_area)

                        # Now to get the show roots.  This listener will be on a windows machine.
                        project_root = roots['primary']['windows_path']

                        # Each of the template paths put together in complete files.
                        root_template_path = os.path.join(project_root, proj_name)
                        work_template_path = os.path.join(root_template_path, work_template).replace('\\', '/')
                        work_area_path = os.path.join(root_template_path, work_area).replace('\\', '/')
                        publish_template_path = os.path.join(root_template_path, publish_template).replace('\\', '/')
                        # publish_area_path = os.path.join(root_template_path, publish_area).replace('\\', '/')

                        # Get the resolved working area and find existing files in it.
                        # No version passed because we're only looking for the folder
                        res_path_work_area = process_template_path(template=work_area_path, asset=find_asset)

                        # Create paths if they're not already there.
                        if not os.path.exists(res_path_work_area):
                            logger.info('Creating paths: %s' % res_path_work_area)
                            os.makedirs(res_path_work_area)

                        # Create the basic taskname template from the data.
                        template_name = task_name_format.format(Asset=asset_name, task_name=task_name, ext=ext)

                        find_files_from_template = '%s/%s' % (res_path_work_area, template_name)
                        logger.debug('find_files_from_template RETURNS: %s' % find_files_from_template)
                        get_files = [f for f in glob(find_files_from_template)]
                        logger.debug('get_files RAW RETURN: %s' % get_files)
                        if get_files:
                            # Look for an existing version number based on the template
                            logger.debug('GET FILES: %s ' % get_files)
                            last_file = sorted(get_files)[-1]
                            logger.debug('last_file: %s' % last_file)
                            get_filename = os.path.basename(last_file)
                            find_version = re.findall(r'_v\d*|_V\d*', get_filename)[0]
                        else:
                            find_version = None

                        # Set the version number for the new file.
                        if find_version:
                            version = int(find_version.lower().strip('_v'))
                            # Increase to the next available version number
                            version += 1
                        else:
                            version = 1
                        logger.debug('VERSION: %s' % version)

                        # resolve the working template into an actual file path that can be written out.
                        if ext == '.mb' or '.ma':
                            res_path_work_template = process_template_path(template=work_template_path, asset=find_asset,
                                                                           version=version, ext=ext)
                        else:
                            res_path_work_template = process_template_path(template=work_template_path, asset=find_asset,
                                                                           version=version)
                        res_path_work_template = res_path_work_template.replace('\\', '/')
                        logger.debug('res_path_work_template: %s' % res_path_work_template)

                        # Copy the file to the correct place on the server.  There are some wait time handlers in here.
                        logger.info('Copying the file to the server...')
                        copy_file = filename.replace('\\', '/')
                        try:
                            shutil.move(copy_file, res_path_work_template)
                            message = 'The file is moved!  Prepping for publish!'
                        except IOError as e:
                            message = ''
                            # Waiting tries...
                            attempts = 1
                            while attempts < 10:
                                time.sleep(2 * attempts)
                                try:
                                    shutil.move(copy_file, res_path_work_template)
                                    message = 'The File is copied after %i tries!  Prepping for publish' % attempts
                                    break
                                except Exception:
                                    message = ''
                                    attempts += 1
                                    logger.warning('Copy attempt failed.  Tyring again...')
                            logger.error('Copying attempts failed! %s' % e)
                        if message:
                            logger.info(message)
                        else:
                            logger.error('The file could not be copied! %s' % copy_file)

                        new_file = res_path_work_template

                        # Now check to see if the file type needs to generate other file types
                        if ext in list(generate_types.keys()):
                            logger.debug('Generator type detected!')
                            export_type = generate_types[ext]['type']
                            output_type = generate_types[ext]['output']
                            render_area = generate_types[ext]['render']
                            logger.debug('export_type: %s' % export_type)
                            logger.debug('output_type: %s' % output_type)
                            logger.debug('render_area: %s' % render_area)

                            # ------------------------------------------------------------------------------------
                            # Sub Processing Routines
                            # ------------------------------------------------------------------------------------
                            # Here I can add different job types as the come up.  For now, it's only Photoshop
                            if export_type == 'Photoshop Image':
                                logger.debug('export type detected: PHOTOSHOP')
                                get_template_name = templates[render_area]
                                render_publish_area = get_template_name['publish_area']
                                logger.debug('get_template_name: %s' % get_template_name)
                                try:
                                    image = process_Photoshop_image(template=template, filename=new_file,
                                                                    pub_area=render_publish_area,
                                                                    task=task, f_type=output_type, proj_id=proj_id,
                                                                    asset=find_asset, root=root_template_path,
                                                                    user=user)
                                    if image:
                                        # getting template settings
                                        send_today_template = template['paths']['send_today']
                                        project_root = roots['primary']['windows_path']
                                        root_template_path = os.path.join(project_root, proj_name)
                                        logger.debug('send_today_template: %s' % send_today_template)
                                        resolved_send_today_template = resolve_template_path('send_today', template)
                                        logger.debug('RESOLVED send_today_template: %s' % resolved_send_today_template)
                                        send_today_path = os.path.join(root_template_path, resolved_send_today_template)
                                        logger.debug('SEND TODAY PATH: %s' % send_today_path)
                                        is_sent = send_today(filename=image, path=send_today_path, proj_id=proj_id,
                                                             asset=find_asset)
                                        logger.debug('is_sent RETURNS: %s' % is_sent)
                                    else:
                                        is_sent = False

                                    logger.info('Image file has been created from PSD.')
                                except IOError as e:
                                    logger.error('Unable to process the %s for the following reasons: %s' % (ext, e))
                                    pass

                        # Publish the file
                        if ext == '.ma' or '.mb':
                            res_publish_path = process_template_path(template=publish_template_path, asset=find_asset,
                                                                     version=version, ext=ext)
                        else:
                            res_publish_path = process_template_path(template=publish_template_path, asset=find_asset,
                                                                     version=version)
                        logger.debug('Publish Path: %s' % res_publish_path)
                        next_version = version + 1
                        try:
                            logger.info('Attempting to publish...')
                            publish_path = publish_to_shotgun(publish_file=new_file, publish_path=res_publish_path,
                                                              asset_id=asset_id, proj_id=proj_id, task_id=task,
                                                              next_version=next_version)
                            logger.debug('PUBLISH_PATH: %s' % publish_path)
                            if is_sent and publish_path:
                                # Call to set the related version
                                logger.debug('Setting related version...')
                                set_related_version(proj_id=proj_id, origin_path=publish_path, path=is_sent)
                        except Exception as e:
                            logger.error('Publish failed for the following! %s' % e)
                            pass

                    elif ext.lower() in upload_types:
                        # getting template settings
                        send_today_template = template['paths']['send_today']
                        project_root = roots['primary']['windows_path']
                        root_template_path = os.path.join(project_root, proj_name)
                        logger.debug('send_today_template: %s' % send_today_template)
                        resolved_send_today_template = resolve_template_path('send_today', template)
                        logger.debug('RESOLVED send_today_template: %s' % resolved_send_today_template)
                        send_today_path = os.path.join(root_template_path, resolved_send_today_template)
                        logger.debug('SEND TODAY PATH: %s' % send_today_path)
                        logger.info('Uploading for review %s' % file_name)

                        # Setup render paths
                        asset_render_template_name = templates['Asset Renders']
                        asset_render_template = resolve_template_path(asset_render_template_name['work_area'], template)
                        logger.debug('Template Asset Render Path: %s' % asset_render_template)
                        asset_render_path = os.path.join(root_template_path, asset_render_template)
                        resolved_asset_render_path = process_template_path(template=asset_render_path, asset=find_asset)
                        logger.debug('RESOLVED Asset Render Path: %s' % resolved_asset_render_path)
                        asset_render_file = os.path.join(resolved_asset_render_path, base_file)

                        # Try to copy the file to the render path
                        try:
                            shutil.copy2(filename, asset_render_file)
                        except Exception as e:
                            logger.error('Could not copy the file to render path: %s' % e)

                        # Upload the file to shotgun
                        send = upload_to_shotgun(filename=filename, asset_id=asset_id, task_id=task, proj_id=proj_id,
                                                 user=user)
                        logger.debug('SEND: %s' % send)
                        if send:
                            is_sent = send_today(filename=filename, path=send_today_path, proj_id=proj_id,
                                                 asset=find_asset)
                            logger.debug('is_sent RETURNS: %s' % is_sent)
                        else:
                            is_sent = False

                        if is_sent:
                            logger.debug('Setting related version...')
                            set_related_version(proj_id=proj_id, origin_path=filename, path=is_sent)

            logger.info('Finished processing the file')
            logger.info('=' * 100)
            q.task_done()
            print('Finished processing file.')

            # Start Time Lord integration.
            logger.info('Processing Timesheet....')
            # Build the context for the timesheet.
            context = {
                'Project': {
                    'id': proj_id,
                    'name': proj_name
                },
                'Task': {
                    'id': task,
                    'name': task_name
                }
            }

            logger.info('Sending to Time Lord...')
            try:
                tlc.time_lord(user=user, context=context, log=logger)
            except Exception as err:
                print(('Time Lord fucked up: %s' % err))
                logger.error('Time Lord failed to process the file: %s' % err)
            logger.info('Time Lord processed.')
            print(('=' * 100))
            return True
        else:
            q.task_done()
            return True
    except Exception as e:
        print(('Skipping!  The following error occurred: %s' % e))
        logger.error('Skipping!  The following error occurred: %s' % e)
        logger.info('%s' % e)
        q.task_done()
        return False


def process_Photoshop_image(template=None, filename=None, task=None, pub_area=None, f_type=None, proj_id=None,
                            asset=None, root=None, user=None):
    """
    This tool processes photoshop files in order to export out an image for uploading.
    :param template:
    :param filename:
    :param task:
    :param pub_area:
    :param f_type:
    :param proj_id:
    :param asset:
    :param root:
    :return:
    """
    logger.info(('-' * 35) + 'PROCESS PHOTOSHOP IMAGE' + ('-' * 35))
    if filename:
        # Find where to save the file from the template
        res_template_path = resolve_template_path(pub_area, template)
        logger.debug('PHOTOSHOP TEMPLATE: %s' % res_template_path)
        resolved_path = process_template_path(template=res_template_path, asset=asset)
        logger.debug('RESOLVED PHOTOSHOP PATH: %s' % resolved_path)
        full_path = os.path.join(root, resolved_path).replace('\\', '/')
        logger.debug('FULL SHOTGUN PATH: %s' % full_path)

        # Get the photoshop file basename
        base_filename = os.path.basename(filename)
        root_filename = os.path.splitext(base_filename)[0]
        logger.debug('Render filename: %s' % root_filename)

        # Create the export path:
        render = '%s.%s' % (root_filename, f_type)
        render_path = os.path.join(full_path, render)

        # Process the image.
        logger.info('Processing Photoshop file...')
        try:
            file_to_publish = psd.PSDImage.open(filename)
            file_to_PIL = file_to_publish.composite()
            converted_file = file_to_PIL.convert(mode="RGB")
            converted_file.save(render_path)
        except Exception as e:
            logger.error('Photoshop File could not generate an image! %s' % e)
            pass

        # Upload a version
        upload_to_shotgun(filename=render_path, asset_id=asset['id'], task_id=task, proj_id=proj_id, user=user)

        logger.debug(('.' * 35) + 'END PROCESS PHOTOSHOP IMAGE' + ('.' * 35))
        return render_path
    return None


def upload_to_shotgun(filename=None, asset_id=None, task_id=None, proj_id=None, user=None, archive=False, tries=1):
    """
    A simple tool to create Shotgun versions and upload them
    :param filename:
    :param asset_id:
    :param task_id:
    :param proj_id:
    :return:
    """
    logger.info(('-' * 35) + 'UPLOAD TO SHOTGUN' + ('-' * 35))
    file_name = os.path.basename(filename)
    file_path = filename
    if user:
        description = '%s published this file using the Internal Auto Publish utility' % user
    else:
        description = 'Someone published this file using the Internal Auto Publish utility'
    if archive:
        status = 'sent'
    else:
        status = 'rev'
    version_data = {
        'description': description,
        'project': {'type': 'Project', 'id': proj_id},
        'sg_status_list': status,
        'code': file_name,
        'entity': {'type': 'Asset', 'id': asset_id},
        'sg_path_to_frames': filename
    }
    if task_id:
        version_data['sg_task'] = {'type': 'Task', 'id': task_id}
    if user:
        filters = [
            ['login', 'is', user]
        ]
        fields = [
            'id'
        ]
        get_user = sg.find_one('HumanUser', filters, fields)
        if get_user:
            user_id = get_user['id']
            version_data['user'] = {'type': 'HumanUser', 'id': user_id}
        else:
            version_data['user'] = {'type': 'ApiUser', 'id': int(api_user_id)}
    try:
        new_version = sg.create('Version', version_data)
        logger.debug('new_version RETURNS: %s' % new_version)
        version_id = new_version['id']
        ext = os.path.splitext(file_path)[1]
        ext = ext.lower()
        if ext not in video_types:
            sg.upload_thumbnail('Version', version_id, file_path)
        sg.upload('Version', version_id, file_path, field_name='sg_uploaded_movie', display_name=file_name)
        logger.info('New Version Created!')
        logger.debug(('.' * 35) + 'END UPLOAD TO SHOTGUN' + ('.' * 35))
        return True
    except Exception as e:
        logger.error('The new version could not be created: %s' % e)
        if tries <= 5:
            tries += 1
            upload_to_shotgun(filename=filename, asset_id=asset_id, task_id=task_id, proj_id=proj_id, user=user,
                              tries=tries)
        else:
            return False
    return False


def send_today(filename=None, path=None, proj_id=None, asset={}):
    """

    :param filename: (str) Name of the file being sent
    :param path: (str) relative path for getting send details
    :param proj_id: (int) Project ID number
    :param asset: (dict) Asset details, name, id num...
    :return: (Bool) True or false.
    """
    logger.info(('-' * 35) + 'SEND TODAY' + ('-' * 35))
    logger.info('Getting the Send Today folder from the template...')
    filename = filename.replace('\\', '/')
    logger.debug('INCOMING FILENAME: %s' % filename)
    logger.debug('INCOMING PATH: %s' % path)

    # Get the file extension
    ext = os.path.splitext(filename)[-1]

    # Find Send Today code in Shotgun; Else use the default.
    logger.debug('Collecting the Client Naming Convention...')
    filters = [
        ['id', 'is', proj_id]
    ]
    fields = [
        'sg_project_naming_convention'
    ]
    get_fields = sg.find_one('Project', filters, fields)
    naming_convention = get_fields['sg_project_naming_convention']
    logger.debug('NAMING CONVENTION: %s' % naming_convention)

    # set dats
    date_test = str(datetime.date(datetime.now()))
    today_path = os.path.join(path, date_test)
    logger.debug('TODAY PATH: %s' % today_path)
    # today_path = os.path.join(today_path, 'REMOTE')
    if not os.path.exists(today_path):
        os.makedirs(today_path)

    # Compile the naming convention.
    # Run Create Client Name here
    client_name = create_client_name(path=path, filename=filename, proj_id=proj_id, asset=asset)
    logger.debug('CLIENT NAME: %s' % client_name)
    if client_name:
        client_name += ext
        send_today_path = os.path.join(today_path, client_name)
        if os.path.exists(send_today_path):
            while os.path.exists(send_today_path):
                logger.debug('Version already exists!!!  Going to attempt versioning up from current.')
                # Create new version number
                current_version = version_tool(send_today_path)
                logger.debug('Current version number found: %s' % current_version)
                new_version = version_tool(send_today_path, version_up=True)
                logger.debug('New version created: %s' % new_version)
                send_today_path = send_today_path.replace(current_version, new_version)
                # send_today_path = send_today_path.replace('\\', '/')

        send_today_path = send_today_path.replace('\\', '/')
        filename = filename.replace('\\', '/')
        logger.debug('send_today_path: %s' % send_today_path)
        try:
            shutil.move(filename, send_today_path)
            logger.debug(('.' * 35) + 'END SEND TODAY' + ('.' * 35))
            return send_today_path
        except Exception as e:
            logger.error('Can not copy the file! %s' % e)
            return False
    else:
        logger.error('The client naming convention could not be rectified!')
        return False


def get_sg_translator(sg_task=None, fields=[]):
    """
    The T-Sheets Translator requires a special Shotgun page to be created.
    The fields in the database are as follows:
    Database Name:  code:                (str) A casual name of the database.
    sgtask:         sg_sgtask:          (str-unique) The shotgun task. Specifically, '.main' namespaces are removed.
    tstask:         sg_tstask:          (str) The T-Sheets name for a task
    ts_short_code:  sg_ts_short_code:   (str) The ironically long name for a 3 letter code.
    task_depts:     sg_task_grp:        (multi-entity) Returns the groups that are associated with tasks
    people_override:sg_people_override: (multi-entity) Returns individuals assigned to specific tasks

     :param:        sg_task:            (str) Shotgun task name from context
    :return:        translation:        (dict) {
                                                task: sg_tstask
                                                short: sg_ts_short_code
                                                dept: sg_task_depts
                                                people: sg_people_override
                                                }
    """

    logger.debug(('^' * 35) + 'get_sg_translator' + ('^' * 35))
    translation = {}
    if sg_task:
        task_name = sg_task.split('.')[0]

        task_name = task_name.lower()

        filters = [
            ['sg_sgtask', 'is', task_name]
        ]
        translation_data = sg.find_one('CustomNonProjectEntity07', filters, fields=fields)

        if translation_data:
            task = translation_data['sg_tstask']
            short = translation_data['sg_ts_short_code']
            group = translation_data['sg_task_grp']
            people = translation_data['sg_people_override']
            delivery_code = translation_data['sg_delivery_code']
            translation = {'task': task, 'short': short, 'group': group, 'people': people,
                           'delivery_code': delivery_code}
        else:
            translation = {'task': 'General', 'short': 'gnrl', 'group': None, 'people': None, 'delivery_code': None}

    logger.debug(('.' * 35) + 'end get_sg_translator' + ('.' * 35))
    return translation


def version_tool(path=None, version_up=False, padding=3):
    """
    This tool finds and creates padded version numbers
    :param path: (str) relative path to file
    :param version_up: (bool) Setting for running a version up
    :param padding: (int) Number padding
    :return: new_num (str) a padded string version number.
    """
    logger.debug(('+' * 35) + 'version_tool' + ('+' * 35))
    logger.debug('Version Tool Activated!!')
    new_num = '001'
    if path:
        logger.debug('Path is discovered: %s' % path)
        try:
            find_file_version = re.findall(r'(v\d+|V\d+)', path)[-1]
        except:
            find_file_version = re.findall(r'(v\d+|V\d+)', path)
            logger.debug('BAD INDEX for re.findall.  Using default instead.')
        logger.debug('find_file_version: %s' % find_file_version)
        if find_file_version:
            new_num = int(find_file_version.lower().strip('v'))
            if version_up:
                new_num += 1
                logger.debug('version up: %s' % new_num)
            logger.debug('new_version: %s' % new_num)
            new_num = str(new_num).zfill(padding)
            logger.debug('NEW_NUM: %s' % new_num)
        else:
            new_num = '001'
    logger.debug('Returning from Version Tools: %s' % new_num)

    logger.debug(('.' * 35) + 'END version_tool' + ('.' * 35))
    return new_num


def create_client_name(path=None, filename=None, proj_id=None, asset={}, version=None):
    """
    Parses our tagged client file formats and creates proper names from the available data.
    :param path: (str) path to the file
    :param filename: (str) The coded filename pattern
    :param proj_id: (int) project ID number
    :param asset: (dict) Asset Details
    :param version: The version number
    :return: (str) Proper file name
    """

    logger.debug(('#' * 35) + 'create_client_name' + ('#' * 35))
    logger.debug('create_client_name PATH: %s' % path)
    logger.debug('create_client_name FILENAME: %s' % filename)
    new_name = None
    document = filename
    try:
        # Start Send Today capture
        custom_tags = {
            "{Task}": {
                "type": "translator",
                "fields": [
                    "sg_sgtask",
                    "sg_tstask",
                    "sg_ts_short_code",
                    "sg_task_grp",
                    "sg_people_override",
                    "sg_delivery_code"
                ],
                "correlation": "{task_name}"
            },
            "{Stage}": {
                "type": "property",
                "fields": [
                    "stage"
                ],
                "correlation": None
            },
            "{code}": {
                "type": "project_info",
                "fields": [],
                "correlation": None
            },
            "{YYYYMMDD}": {
                "type": "date",
                "fields": [],
                "correlation": "{timestamp}"
            },
            "{YYMMDD}": {
                "type": "date",
                "fields": [],
                "correlation": "{timestamp}"
            },
            "{YYYYDDMM}": {
                "type": "date",
                "fields": [],
                "correlation": "{timestamp}"
            },
            "{YYDDMM}": {
                "type": "date",
                "fields": [],
                "correlation": "{timestamp}"
            },
            "{MMDDYY}": {
                "type": "date",
                "fields": [],
                "correlation": "{timestamp}"
            },
            "{MMDDYYYY}": {
                "type": "date",
                "fields": [],
                "correlation": "{timestamp}"
            },
            "{DDMMYY}": {
                "type": "date",
                "fields": [],
                "correlation": "{timestamp}"
            },
            "{DDMMYYYY}": {
                "type": "date",
                "fields": [],
                "correlation": "{timestamp}"
            },
        }
        # Find Send Today code in Shotgun; Else use the default.
        filters = [
            ['id', 'is', proj_id]
        ]
        fields = [
            'sg_project_naming_convention'
        ]
        get_fields = sg.find_one('Project', filters, fields)
        logger.info('PROJEcT DETAILS: %s' % get_fields)
        naming_convention = get_fields['sg_project_naming_convention']
        logger.info('NAMING CONVENTION: %s' % naming_convention)
        # Get the fields from the system.
        work_fields = {'version': version, 'Asset': asset['name'], 'sg_asset_type': asset['type']}
        # I might need to find the work path and search for existing version.  Can probably steal that routine from
        # above!

        translations = {}
        # Read the naming convention:
        if naming_convention:
            existing_tags = re.findall(r'{\w*}', naming_convention)

            if ':' not in naming_convention:
                # if a frame padding number isn't found, this will add one to the end
                naming_convention += ':3'

            if ':' in naming_convention:
                nc = naming_convention.split(':')
                naming_convention = nc[0]
                padding = nc[1]
                logger.info('PADDING: %s' % padding)
                if 'version' in list(work_fields.keys()):
                    # Convert numeric version to padded string
                    current_version = work_fields['version']
                    del work_fields['version']
                    new_num = '%s' % current_version
                    new_num = new_num.zfill(int(padding))
                    logger.info('NEW NUM: %s' % new_num)
                    work_fields['version'] = new_num
                if work_fields['version'] == 'None':
                    logger.warning('None detected for the version!  Attempting to correct...')
                    del work_fields['version']
                    # Attempt to get the version from the file.  Else: 001
                    new_num = version_tool(path=path, padding=padding)
                    logger.info('Corrected Version Number: %s' % new_num)
                    logger.debug('Replacing version in work fields...')
                    work_fields['version'] = new_num
            logger.info('FOUND TAGS: %s' % existing_tags)
            if existing_tags:
                for tag in existing_tags:
                    if tag in custom_tags:
                        tag_data = custom_tags[tag]
                        tag_type = tag_data['type']
                        tag_fields = tag_data['fields']
                        correlation = tag_data['correlation']
                        logger.info('Tag Type: %s' % tag_type)
                        logger.info('Tag Fields: %s' % tag_fields)
                        logger.info('Correlation: %s' % correlation)
                        # date, project_info, property, translator
                        if tag_type == 'translator':
                            translation = get_sg_translator(sg_task=task_name, fields=tag_fields)
                            logger.info('TRANSLATION: %s' % translation)
                            base_tag = tag.strip('{')
                            base_tag = base_tag.strip('}')
                            if task_name.endswith('.main') or task_name.endswith('.auto'):
                                short_task = translation['delivery_code']
                            else:
                                try:
                                    find_suffix = task_name.split('.')[1]
                                except Exception as e:
                                    find_suffix = ''
                                short_task = '%s%s' % (translation['delivery_code'], find_suffix)
                            translations[base_tag] = short_task
                        elif tag_type == 'project_info':
                            base_tag = tag.strip('{')
                            base_tag = base_tag.strip('}')
                            filters = [
                                ['id', 'is', proj_id]
                            ]
                            fields = [
                                base_tag
                            ]
                            get_fields = sg.find_one('Project', filters, fields)
                            val = get_fields[base_tag]
                            logger.info('Project Info Tag: %s' % val)
                            translations[base_tag] = val
                        elif tag_type == 'date':
                            base_tag = tag.strip('{')
                            base_tag = base_tag.strip('}')
                            get_year = re.findall('Y*', base_tag)
                            year = [x for x in get_year if x][0]
                            year_count = len(year)
                            if year_count == 4:
                                year_tag = '%Y'
                            else:
                                year_tag = '%y'
                            logger.debug('YEAR: %s' % year)
                            logger.debug('YEAR_TAG: %s' % str(year_tag))
                            date_tag = base_tag.replace(str(year), str(year_tag))
                            date_tag = date_tag.replace('MM', '%m')
                            date_tag = date_tag.replace('DD', '%d')
                            date = datetime.now().strftime(date_tag)
                            logger.info('DATE: %s' % date)
                            translations[base_tag] = date
                        elif tag_type == 'property':
                            pass
            logger.info('TRANSCODES: %s' % translations)
        if translations:
            work_fields.update(translations)
            logger.debug('work_fields: %s' % work_fields)
        new_name = naming_convention.format(**work_fields)
        logger.info('NEW_NAME: %s' % new_name)
        # item.display_name = new_name
    except Exception as e:
        logger.error('It looks like the Project Naming Convention is incorrectly set. See the Admins. %s' % e)
        return False

    logger.debug(('.' * 35) + 'END create_client_name' + ('.' * 35))
    return new_name


# ---------------------------------------------------------------------------------------------------------------------
# Archive File Processing
# ---------------------------------------------------------------------------------------------------------------------
def archive_file(full_filename=None, user=None, ip=None):
    if full_filename:
        try:
            logger.info('Processing archive file...')
            print('Processing archive file...')
            print(('Submitted by: %s' % user))
            origin_path = os.path.dirname(full_filename)
            filename = os.path.basename(full_filename)

            # Move the file into its final resting place
            destination_path = origin_path.replace(archive_orig, archive_dest)
            logger.debug('DESTINATION PATH: %s' % destination_path)
            # print 'Destination path: %s' % destination_path
            destination_file = os.path.join(destination_path, filename)
            # print 'Destination file: %s' % destination_file
            logger.debug('DESTINATION FILE: %s' % destination_file)
            print(('Moving the file to %s...' % destination_path))
            logger.info('Moving the file to %s...' % destination_path)
            shutil.move(full_filename, destination_file)
            print('File moved!')
            logger.info('File Moved!')

            # get the asset name from the path
            asset_name = destination_path.rsplit('/', 1)[-1]
            # print 'Asset Name: %s' % asset_name
            logger.debug('Asset Name: %s' % asset_name)

            logger.info('Getting the Asset ID from the path...')
            filters = [
                ['project', 'is', {'type': 'Project', 'id': int(archive_id)}],
                ['code', 'is', asset_name]
            ]
            fields = [
                'id'
            ]
            asset = sg.find_one('Asset', filters, fields)
            logger.debug('Asset returns: %s' % asset)
            if asset:
                logger.debug('Asset found!')
                id = asset['id']
                logger.debug('Asset ID: %s' % id)

                # Upload it to Shotgun
                logger.info('Uploading %s to Shotgun' % filename)
                print(('Uploading %s...' % filename))
                upload_to_shotgun(filename=destination_file, asset_id=id, proj_id=int(archive_id), user=user,
                                  archive=True)
                logger.info('Archive published to Shotgun!')
                logger.info('=' * 100)
                print('Archive uploaded to Shotgun!')
                print(('=' * 100))
            aq.task_done()
            return True
        except Exception as e:
            print(('Skipping!  The following error occurred: %s' % e))
            logger.error('Skipping!  The following error occurred: %s' % e)
            aq.task_done()
            return False
    aq.task_done()
    return False


def get_slack_user(email=None, auth_code=None, url=None, tries=0):
    logger.info('Getting slack user ID...')
    user_id = None
    if email:
        headers = {
            'Authorization': 'Bearer %s' % auth_code,
            'Content-type': 'application/json'
        }
        try:
            slack_users = requests.get('%susers.list' % url, headers=headers)
            logger.debug('Checking slack request... %s' % slack_users.json())
            if slack_users.json()['ok'] == True:
                all_users = slack_users.json()['members']
                user_id = None
                for user in all_users:
                    profile = user['profile']
                    if 'email' in list(profile.keys()):
                        user_email = profile['email']
                        if user_email == email:
                            user_id = user['id']
                            logger.debug('Slack user ID found! %s' % user_id)
                            break
            else:
                logger.info('Waiting 10 seconds to allow for Slack rate limits...')
                time.sleep(10)
                logger.info('Trying again...')
                user_id = get_slack_user(email=email, auth_code=auth_code, url=url)

        except KeyError as e:
            logger.error('Key not found! %s  Trying again...' % e)
            try:
                t = tries + 1
                time.sleep(30)
                if t > 5:
                    raise Exception("Too many tries!  Skipping...")
                user_id = get_slack_user(email=email, auth_code=auth_code, url=url, tries=t)
            except Exception as e:
                logger.error('There is no saving this thing: %s' % e)
                return None
        except Exception as e:
            try:
                t = tries + 1
                if t > 10:
                    logger.error("Too many tries!  Skipping...")
                user_id = get_slack_user(email=email, auth_code=auth_code, url=url, tries=t)
            except Exception as e:
                logger.error('There is no saving this thing!: %s' % e)
                return None
    return user_id


def get_project_users(proj_id=None):
    emails = {}
    if proj_id:
        logger.info('Looking up global project users...')
        filters = [
            ['id', 'is', proj_id]
        ]
        fields = [
            'users'
        ]
        find_people = sg.find_one('Project', filters, fields)

        if find_people:
            users = find_people['users']
            logger.info('People found!')
            for user in users:
                filters = [
                    ['id', 'is', user['id']]
                ]
                fields = [
                    'email',
                    'name'
                ]
                get_email = sg.find_one('HumanUser', filters, fields)
                if get_email['email']:
                    emails[get_email['name']] = get_email['email']
    return emails


def get_asset_users(asset_id=None):
    users = {}
    if asset_id:
        # Get all the tasks
        filters = [
            ['entity', 'is', {'type': 'Asset', 'id': asset_id}]
        ]
        fields = [
            'task_assignees'
        ]
        search_tasks = sg.find('Task', filters, fields)
        for task in search_tasks:
            if task['task_assignees']:
                assignees = task['task_assignees']
                for assignee in assignees:
                    if assignee['name'] not in list(users.keys()):
                        filters = [
                            ['id', 'is', assignee['id']]
                        ]
                        fields = [
                            'email'
                        ]
                        find_email = sg.find_one('HumanUser', filters, fields)
                        if find_email:
                            users[assignee['name']] = {'email': find_email['email'], 'id': assignee['id']}
    return users


def send_slack_message(user_id=None, asset_name=None, user=None, username=None, filename=None, project=None):
    data = {
        'type': 'message',
        'channel': user_id,
        'text': '*%s* has created a new reference for *%s*' % (user, asset_name),
        'attachments': [
            {
                'fallback': 'New References',
                'title': 'New %s Reference' % asset_name,
                'text': 'file:%s' % filename,
                'color': '#00aa00',
                'fields': [
                    {
                        'title': 'Project',
                        'value': '_%s_' % project
                    }
                ]
            }
        ],
        'as_user': True,
        'username': 'Robo-Coordinator'
    }

    if data:
        headers = {
            'Authorization': 'Bearer %s' % auth_code,
            'Content-type': 'application/json'
        }
        data = json.dumps(data)
        try:
            person = requests.post('%schat.postMessage' % slack_url, headers=headers, data=data)
            logger.debug('Message Sent: %s' % person.json())
            print(('Message sent to %s' % username))
            logger.info('Message sent to %s' % username)
        except Exception as error:
            logger.error('Something went wrong sending the message!  %s' % error)


def upload_asset_reference(asset_id=None, path=None, name=None, user=None):
    if asset_id and path and user and name:
        logger.info('Uploading the reference...')
        print('Uploading the reference...')
        new_ref = sg.upload('Asset', asset_id, path, field_name='sg_references', display_name=name)
        data = {
            'description': 'Reference created by %s using the IAP' % user,
            'sg_status_list': 'na',
            'attachment_reference_links': [{'type': 'Asset', 'id': asset_id}]
        }
        sg.update('Attachment', new_ref, data,
                  multi_entity_update_modes={'attachment_reference_links': 'add'})
        print('Done!')
        logger.info('Done!')
        return True
    return False


def upload_global_reference(path=None, proj_id=None, user=None):
    if path and proj_id:
        logger.info('Uploading a global reference...')
        print('Uploading a global reference...')
        filename = os.path.basename(path)
        fn = os.path.splitext(filename)
        name = fn[0]
        ext = fn[1]
        data = {
            'project': {'type': 'Project', 'id': proj_id},
            'code': name,
            'description': '%s has created a global reference using the IAP' % user
        }
        reference = sg.create(global_ref_entity, data)
        sg.upload(global_ref_entity, reference['id'], path, field_name='sg_link', display_name=filename)
        logger.info('Global reference uploaded')
        logger.debug('Checking for image file types')
        if ext in upload_types and ext not in video_types:
            logger.info('Uploading thumbnail...')
            sg.upload_thumbnail(global_ref_entity, reference['id'], path)
        logger.info('Global reference upload complete!')
        print('Global reference upload complete!')
        return True
    return False


# ---------------------------------------------------------------------------------------------------------------------
# Process References
# ---------------------------------------------------------------------------------------------------------------------
def process_reference(filename=None, template=None, roots=None, proj_id=None, proj_name=None, user=None, ip=None):

    try:
        if filename and os.path.exists(filename):
            logger.info('^' * 120)
            logger.info('NEW REFERENCE BEING MADE...')
            logger.info('#' * 120)
            print('New Reference Processing...')
            print(filename)
            logger.info(filename)
            print(('Published by %s' % user))
            logger.info('Published by %s' % user)
            print(('At: %s' % datetime.now()))
            logger.info('At: %s' % datetime.now())

            # Get the path details from the filename
            path = os.path.dirname(filename)
            logger.debug('PATH: %s' % path)
            # Filename without path
            base_file = os.path.basename(filename)
            base_dir = os.path.dirname(filename)

            f = os.path.splitext(base_file)
            # File extension
            ext = str(f[1]).lower()
            # Filename without path or extension.
            file_name = f[0]

            if proj_id:
                # ensure the slashes are pointing forward
                base_dir = base_dir.replace('\\', '/')
                split_pattern = re.findall(ref_path_to_watch, path)
                if split_pattern:
                    split_pattern = split_pattern[0]

                    print(('SPLIT PATTERN: %s' % split_pattern))
                    rel_path = path.split(split_pattern)[1]
                    print(('REL PATH: %s' % rel_path))
                    if not rel_path:
                        rel_path = path
                    logger.debug('Relative path: %s' % rel_path)

                    find_asset = get_asset_details_from_path(proj_name, proj_id, rel_path)

                    asset_name = find_asset['name']
                    asset_id = find_asset['id']
                    asset_type = find_asset['type']

                    # If an asset is found, continue processing.
                    if asset_id:
                        logger.info('The Asset is found in the system! %s: %s' % (asset_id, asset_name))
                        logger.debug('Asset type: %s' % asset_type)

                        # Find the Shotgun configuration root path
                        find_config = get_configuration(proj_id)
                        logger.debug('Configuration found: %s' % find_config)

                        if ext in reference_types:
                            logger.info('Known reference type discovered!')
                            print('Known reference type discovered!')

                            asset_template_type = templates['Asset Reference']
                            asset_template = resolve_template_path(asset_template_type['work_area'], template)
                            logger.debug('Asset Template: %s' % asset_template)

                            project_root = roots['primary']['windows_path']

                            root_template_path = os.path.join(project_root, proj_name)
                            reference_template_path = os.path.join(root_template_path, asset_template)
                            reference_template_path = reference_template_path.replace('\\', '/')

                            reference_asset_path = process_template_path(template=reference_template_path,
                                                                         asset=find_asset)
                            logger.debug('Reference asset path: %s' % reference_asset_path)

                            if not os.path.exists(reference_asset_path):
                                logger.info('Creating asset path: %s' % reference_asset_path)
                                os.makedirs(reference_asset_path)

                            # Set destination path name
                            asset_reference_path = os.path.join(reference_asset_path, base_file)
                            print(('Moving asset to: %s' % asset_reference_path))

                            # move the reference into place.
                            try:
                                shutil.move(filename, asset_reference_path)
                            except Exception as e:
                                logger.error('Can\'t move the file %s' % filename)

                            # Upload the reference to shotgun.
                            new_ref = upload_asset_reference(asset_id=asset_id, path=asset_reference_path,
                                                             name=file_name, user=user)
                            if new_ref:
                                get_users = get_asset_users(asset_id=asset_id)
                                if get_users:
                                    for artist, details in get_users.items():
                                        slack_user = get_slack_user(email=details['email'], auth_code=auth_code,
                                                                    url=slack_url)
                                        if slack_user:
                                            send_slack_message(user_id=slack_user, asset_name=asset_name,
                                                               username=artist, user=user,
                                                               filename=asset_reference_path, project=proj_name)
                            print('New reference created!')
                            logger.info('New reference created!')
                            print(('=' * 120))
                else:
                    print(('GLOBAL REFERENCe: %s' % file_name))
                    # Find the Shotgun configuration root path
                    find_config = get_configuration(proj_id)
                    logger.debug('Configuration found: %s' % find_config)

                    if ext in reference_types:
                        logger.info('Known reference type discovered!')

                        root_template = templates['Root Reference']
                        res_root_template = resolve_template_path(root_template['work_area'], template)
                        logger.debug('Global reference template: %s' % res_root_template)

                        project_root = roots['primary']['windows_path']

                        root_template_path = os.path.join(project_root, proj_name)
                        reference_root_path = os.path.join(root_template_path, res_root_template)
                        reference_root_path = reference_root_path.replace('\\', '/')
                        logger.debug('Reference Root Path: %s' % reference_root_path)

                        if ext in upload_types and ext not in video_types:
                            # Put the reference in the "artwork" folder
                            reference_path = os.path.join(reference_root_path, ref_imgs_folder)
                            reference_path = os.path.join(reference_path, base_file)
                            logger.info('Updated file path: %s' % reference_path)
                        elif ext in video_types:
                            # put the reference in the "footage" folder
                            reference_path = os.path.join(reference_root_path, ref_vids_folder)
                            reference_path = os.path.join(reference_path, base_file)
                            logger.info('Updated file path: %s' % reference_path)
                        else:
                            # Put the reference in thd "docs" folder
                            reference_path = os.path.join(reference_root_path, ref_docs_folder)
                            reference_path = os.path.join(reference_path, base_file)
                            logger.info('Updated file path: %s' % reference_path)
                        logger.info('Moving the file...')
                        try:
                            shutil.move(filename, reference_path)
                        except Exception as e:
                            logger.error('Can\'t move the file %s' % filename)
                        new_ref = upload_global_reference(path=reference_path, proj_id=proj_id, user=user)
                        if new_ref:
                            logger.info('Global reference uploaded successfully!')
                            print('Global reference uploaded successfully')
                            project_emails = get_project_users(proj_id)
                            if project_emails:
                                for name, email in project_emails.items():
                                    slack_user = get_slack_user(email=email, auth_code=auth_code, url=slack_url)

                                    if slack_user:
                                        send_slack_message(user_id=slack_user, asset_name=proj_name, username=name,
                                                           filename=reference_path, project=proj_name, user=user)
                            print('Done!')
                            print(('=' * 120))

        rq.task_done()
    except Exception as e:
        print(('Skipping!  The following error occurred: %s' % e))
        logger.error('Skipping!  The following error occurred: %s' % e)
        logger.info('%s' % e)
        rq.task_done()
        return False


def publish_to_shotgun(publish_file=None, publish_path=None, asset_id=None, proj_id=None, task_id=None, next_version=1):
    """

    :param publish_file: (str) The file being published
    :param publish_path: (str) the publish path
    :param asset_id: (int) Asset ID number
    :param proj_id: (int) Project ID number
    :param task_id: (int) Task ID number
    :param next_version: (int) version number
    :return:
    """

    logger.info(('~' * 35) + 'PUBLISH TO SHOTGUN' + ('~' * 35))
    global task_name
    uploaded = None
    if publish_file:
        # Copy the file to the publish area.  This will be the file published.
        try:
            logger.info('Copying file to the publish area...')
            check_path = os.path.dirname(publish_path)
            if not os.path.exists(check_path):
                os.makedirs(check_path)
            shutil.copy2(publish_file, publish_path)
        except Exception as e:
            logger.error('Copy failed for the following: %s' % e)
            pass

        # Parse the copied data
        base_name = os.path.basename(publish_file)
        find_version = re.findall(r'_v\d*|_V\d*', base_name)[0]
        digits_only = find_version.lower().strip('_v')
        count_digits = len(digits_only)
        version = int(digits_only)
        ext = os.path.splitext(base_name)[1]
        ext = ext.lower()

        # Get the publish type.
        get_publish_type = publish_types[ext]
        filters = [
            ['code', 'is', get_publish_type]
        ]
        fields = ['id']

        find_type = sg.find_one('PublishedFileType', filters, fields)

        if find_type:
            # Register the publish
            data = {
                'description': 'A remote file was detected in Dropbox and has been published into the pipeline.',
                'project': {'type': 'Project', 'id': proj_id},
                'code': base_name,
                'entity': {'type': 'Asset', 'id': asset_id},
                'name': task_name,
                'task': {'type': 'Task', 'id': task_id},
                'path_cache': publish_path,
                'version_number': version,
                'published_file_type': find_type
            }
            new_publish = sg.create('PublishedFile', data)
            logger.debug('NEW PUBLISH: %s' % new_publish)
            publish_id = new_publish['id']
            publish_update = {
                'path': {'local_path': publish_path.replace('/', '\\')}
            }
            sg.update('PublishedFile', publish_id, publish_update)
            logger.info('%s has been published successfully!' % base_name)

            uploaded = publish_path.replace('/', '\\')

            logger.debug(('.' * 35) + 'END PUBLISH TO SHOTGUN' + ('.' * 35))
        else:
            logger.error('FAIL!!!  No PublishedFileType could be found for %s' % base_name)
    return uploaded


def set_related_version(proj_id=None, origin_path=None, path=None):
    logger.debug(('=' * 35) + 'set_related_version' + ('=' * 35))
    logger.debug('project ID: %s' % proj_id)
    logger.debug('origin_path: %s' % origin_path)
    logger.debug('path: %s' % path)
    # path is the final destination path: publish/maya/maya_file.mb
    if path:
        file_name = os.path.basename(origin_path)
        logger.debug('Associated Version: %s' % file_name)

        if file_name.endswith('.psd'):
            file_name = file_name.replace('.psd', '.jpg')

        main_file_name = os.path.basename(path)
        logger.debug('Main Version: %s' % main_file_name)

        filters = [
            ['project', 'is', {'type': 'Project', 'id': proj_id}],
            ['code', 'is', file_name]
        ]
        fields = [
            'created_at'
        ]
        version = sg.find_one('Version', filters, fields, order=[{'field_name': 'created_at', 'direction': 'desc'}])
        logger.debug('Versions returns: %s' % version)
        if version:
            sg.update('Version', version['id'], data={'sg_name_option': main_file_name})
            logger.info('Version updated with Send Today Submission')
        else:
            logger.debug('SHIT')
            logger.debug(file_name)
        logger.debug(('.' * 35) + 'END set_related_version' + ('.' * 35))


def send_user_message(user=None, ip=None, msg=None):
    if user and ip:
        subprocess.call("msg /time:90 /server:%s %s %s" % (ip, user, msg))


def get_set_task(asset=None, proj_id=None, user=None):
    """
    This will look for an existing task in Shotgun and return the info. If no task if found, it creates one and returns
    the info
    :param asset: (dict) Asset details
    :param proj_id: (int) Project ID number
    :return: (int) task: Task ID number
    """
    logger.debug(('=' * 35) + 'get_set_task' + ('=' * 35))
    global task_step
    task = None
    if asset:
        asset_id = asset['id']

        filters = [
            ['entity', 'is', {'type': 'Asset', 'id': asset_id}]
        ]
        fields = [
            'content',
            'step',
            'id'
        ]
        tasks = sg.find('Task', filters, fields)
        logger.debug('TASKS RETURNS: %s' % tasks)
        if tasks:
            logger.info('Searching for remote task...')
            for tsk in tasks:
                if tsk['content'] == task_name:
                    logger.info('Task found!')
                    task_id = tsk['id']
                    task_step = tsk['step']['id']
                    task = task_id

                    # Add task assignments
                    assign_user_to_task(user=user, task_id=task_id)
                    break
        if not task:
            logger.info('No task found.  Creating a new task...')
            task_data = {
                'project': {'type': 'Project', 'id': proj_id},
                'content': task_name,
                'entity': {'type': 'Asset', 'id': asset_id},
                'step': {'type': 'Step', 'id': task_step},
                'sg_status_list': 'ip'
            }
            new_task = sg.create('Task', task_data)
            logger.info('New Task Created!')
            task = new_task['id']

            # Add task assignments
            assign_user_to_task(user=user, task_id=task)

    logger.debug(('.' * 35) + 'END get_set_task' + ('.' * 35))
    return task


def assign_user_to_task(user=None, task_id=None):
    """
    The following is how I did this in the task_historian.
    data = {
        'sg_assignment_history': [{'type': 'HumanUser', 'id': uid}]
    }
    sg.update('Task', task_id, data, multi_entity_update_modes={'sg_assignment_history': 'add'})
    :param user:
    :param task_id:
    :return:
    """
    logger.info('Checking user assignments')
    if user and task_id:
        filters = [
            ['login', 'is', user]
        ]
        fields = [
            'id'
        ]
        get_user = sg.find_one('HumanUser', filters, fields)
        logger.info('get_user: %s' % get_user)
        if get_user:
            user_id = get_user['id']
            logger.info('user_id: %s' % user_id)
            if user_id:
                data = {
                    'task_assignees': [{'type': 'HumanUser', 'id': user_id}],
                    'sg_status_list': 'ip'
                }
                sg.update('Task', task_id, data, multi_entity_update_modes={'task_assignees': 'add'})
                logger.info('Task assignment complete.')


def process_template_path(template=None, asset=None, ext=None, version=0):
    """
    This converts the publish template into an actual path
    :param template: (str) The template being converted
    :param asset: (dict) the details of the Asset
    :param version: (int) the version number
    :return: (str) res_path: the resolved path name
    """
    logger.debug(('*' * 35) + 'process_template_path' + ('*' * 35))
    logger.debug('TEMPLATE HAS: %s' % template)
    logger.debug('ASSET HAS: %s' % asset)
    global task_name
    res_path = None
    if template:
        if asset:
            asset_name = asset['name']
            asset_type = asset['type']
        else:
            asset_name = None
            asset_type = None
        if ext:
            res_path = template.format(Asset=asset_name, task_name=task_name, sg_asset_type=asset_type,
                                       version='%03d' % version, maya_extension=ext.strip('.'))
        else:
            res_path = template.format(Asset=asset_name, task_name=task_name, sg_asset_type=asset_type,
                                       version='%03d' % version)
        logger.debug('RESOLVED PATH: %s' % res_path)
    logger.debug(('.' * 35) + 'END process_template_path' + ('.' * 35))
    return res_path


def resolve_template_path(template_key, template):
    """
    This loop cycles in on itself until all the references in a YAML file have been resolved.
    For instance:
    @work_area/Publish/{Asset}  -- Becomes:
    @root/{Asset}/Publish/{Asset} -- Becomes:
    c:/{Project}/{Asset}/Publish/{Asset} and soforth until all '@' signs have been resolved
    :param template_key:
    :param template:
    :return:
    """
    logger.debug(('&' * 35) + 'resolve_template_path' + ('&' * 35))
    if template_key and template:
        try:
            read = template['paths'][template_key]['definition']
            logger.debug('Main read template succeded')
        except Exception:
            read = template['paths'][template_key]
            logger.warning('Unable to open main template. Alternate read template used.')
        read = read.replace('\\', '/')
        split_read = read.split('/')
        for x in split_read:
            if '@' in x:
                d = x.strip('@')
                g = resolve_template_path(d, template)
                template_path = read.replace(x, g)
                logger.debug('resolving iteration: %s' % template_path)
                return template_path
        template_path = read
        logger.debug('resolved path: %s' % template_path)
        logger.debug(('.' * 35) + 'END resolve_template_path' + ('.' * 35))
        return template_path


def get_asset_details_from_path(project=None, proj_id=None, path=None):
    """
    Convert a path to a series of details about an asset.
    :param project:
    :param proj_id:
    :param path:
    :return: ass - The asset details
    """
    logger.debug(('~' * 35) + 'get_asset_details_from_path' + ('~' * 35))
    logger.info('Searching for Assets in %s...' % path)
    ass = {}
    if project and path:
        filters = [
            ['project', 'is', {'type': 'Project', 'id': proj_id}]
        ]
        fields = [
            'code',
            'id',
            'sg_asset_type'
        ]
        try:
            find_assets = sg.find('Asset', filters, fields)
        except AttributeError as e:
            find_assets = None
            logger.error('This shit went bad. Probably from a mac "computer". Returned the following: %s' % e)
        logger.debug('Shotgun Returns: %s' % find_assets)
        if find_assets:
            logger.debug('Assets exist!  Finding our guy...')
            for asset in find_assets:
                logger.debug('Testing %s IN %s...' % (asset['code'], path))

                probable_asset_in_path = path.split('/')[-1]

                if asset['code'] == probable_asset_in_path:
                    ass['name'] = asset['code']
                    ass['id'] = asset['id']
                    ass['type'] = asset['sg_asset_type']
                    logger.info('%s found in %s' % (ass['name'], path))
                    return ass
    logger.debug(('.' * 35) + 'END get_asset_details_from_path' + ('.' * 35))
    return ass


def get_details_from_path(path):
    """
    Get the basic project details from the path
    :param path:
    :return: prj - Project details
    """
    logger.debug(('$' * 35) + 'get_details_from_path' + ('$' * 35))
    prj = {}
    if path:
        logger.info('Attempting to get project details from the path...')
        projects = get_active_shotgun_projects()
        if projects:
            for proj in projects:
                project = proj['tank_name']
                if project:
                    if project in path:
                        prj['name'] = project
                        prj['id'] = proj['id']
                        logger.debug('Project %s found.' % project)
                        break
    logger.debug(('.' * 35) + 'END get_details_from_path' + ('.' * 35))
    return prj


def get_configuration(proj_id):
    """
    Get the Pipeline configuration from the Project ID.  This gets the windows_path to where the pipeline config files
    exist on the server
    :param proj_id:
    :return: config_path
    """
    logger.debug(('%' * 35) + 'get_configuration' + ('%' * 35))
    try:
        if proj_id:
            filters = [
                ['project', 'is', {'type': 'Project', 'id': proj_id}],
                ['code', 'is', 'Primary']
            ]
            fields = [
                'windows_path'
            ]
            get_config = sg.find_one('PipelineConfiguration', filters, fields)
            if get_config:
                config_path = get_config['windows_path']
                config_path = config_path.replace('\\', '/')

                logger.debug(('.' * 35) + 'END get_configuration' + ('.' * 35))
                return config_path
        return
    except Exception as e:
        logger.error('Some shit when down! %s' % e)
        return False


def get_active_shotgun_projects():
    """
    Creates a list of all active Shotgun Projects to search through
    :return:
    """
    logger.debug(('+' * 35) + 'get_active_shotgun_projects' + ('+' * 35))
    filters = [
        {
            'filter_operator': 'or',
            'filters': [
                ['sg_status', 'is', 'active'],
                ['sg_status', 'is', 'bidding']
            ]
        }
    ]

    fields = [
        'id',
        'tank_name'
    ]
    try:
        projects_list = sg.find('Project', filters, fields)
        logger.debug('Active Projects Found: %s' % projects_list)
    except Exception as e:
        logger.error('The following error occurred: %s' % e)
        projects_list = []
    logger.debug(('.' * 35) + 'END get_active_shotgun_projects' + ('.' * 35))
    return projects_list


# ---------------------------------------------------------------------------------------------------------------------
# Run Queues
# ---------------------------------------------------------------------------------------------------------------------
def file_queue():
    """
    The Queue.  This handles each of the multiple files dropped, so the tool doesn't overload.
    :return:
    """
    logger.debug('Queue Running...')
    print('Queue Running...')
    while True:
        # Get the package from the Queue and parse it out.
        package = q.get(block=True)
        full_filename = package['filename']
        template = package['template']
        roots = package['roots']
        proj_id = package['proj_id']
        proj_name = package['proj_name']
        ip = package['ip']
        user = package['user']
        logger.debug('Queued file: %s' % full_filename)

        # Set the copying status to true, so it begins waiting for a copy to finish
        copying = True
        size2 = -1
        # Start Copying...
        while copying:
            # Check the file size and compare it with the previous file size.  If the same, copying is done.
            try:
                size = os.stat(full_filename).st_size
                if size == size2:
                    time.sleep(2)

                    copying = False
                    process_file(filename=full_filename, template=template, roots=roots, proj_id=proj_id,
                                 proj_name=proj_name, user=user, ip=ip)
                    logger.debug('~' * 45)
                    break
                else:
                    # Copying not finished, wait to seconds and try again...
                    size2 = os.stat(full_filename).st_size
                    time.sleep(2)
            except WindowsError as e:
                logger.debug(e)
                break


def archive_queue():
    """
    This queue is specifially for running archival processes and should run apart from the main queue.
    :return:
    """
    logger.info('Archive queue running...')
    print('Archive Queue running...')
    while True:
        package = aq.get(block=True)
        full_filename = package['filename']
        user = package['user']
        ip = package['ip']
        logger.debug('Archive Queued file: %s' % full_filename)

        copying = True
        size2 = -1
        # Start copying...
        while copying:
            try:
                size = os.stat(full_filename).st_size
                if size == size2:
                    time.sleep(2)
                    copying = False
                    archive_file(full_filename=full_filename, user=user, ip=ip)
                    logger.debug('~' * 45)
                    break
                else:
                    size2 = os.stat(full_filename).st_size
                    time.sleep(2)
            except WindowsError as e:
                logger.debug(e)
                break


def reference_queue():
    """
    This queue is specifically for running the reference system.
    :return:
    """
    logger.info('Reference queue running...')
    print('Reference Queue Running...')
    while True:
        package = rq.get(block=True)
        full_filename = package['filename']
        template = package['template']
        roots = package['roots']
        proj_id = package['proj_id']
        proj_name = package['proj_name']
        ip = package['ip']
        user = package['user']
        logger.debug('Queued reference: %s' % full_filename)

        # Set the copying status to true, so it begins waiting for a copy to finish
        copying = True
        size2 = -1
        # Start Copying...
        while copying:
            # Check the file size and compare it with the previous file size.  If the same, copying is done.
            try:
                size = os.stat(full_filename).st_size
                if size == size2:
                    time.sleep(2)

                    copying = False
                    process_reference(filename=full_filename, template=template, roots=roots, proj_id=proj_id,
                                      proj_name=proj_name, user=user, ip=ip)
                    logger.debug('~' * 45)
                    break
                else:
                    # Copying not finished, wait to seconds and try again...
                    size2 = os.stat(full_filename).st_size
                    time.sleep(2)
            except WindowsError as e:
                logger.debug(e)
                break


def datetime_to_float(d):
    # Change the date-time to a decimal floating point number
    epoch = datetime.utcfromtimestamp(0)
    total_seconds = (d - epoch).total_seconds()
    return total_seconds


# Start the threads
'''
This starts the thread that runs the main publish queue
'''
logger.debug('Starting the main publish thread...')
t = threading.Thread(target=file_queue, name='FileQueue')
t.setDaemon(True)
t.start()

'''
This starts the thread that runs the archival system
'''
logger.debug('Starting the secondary archival thread...')
at = threading.Thread(target=archive_queue, name='ArchiveQueue')
at.setDaemon(True)
at.start()

'''
This starts the thread that runs the reference system
'''
logger.debug('Starting the reference thread...')
rt = threading.Thread(target=reference_queue, name='ReferenceQueue')
rt.setDaemon(True)
rt.start()
print('Queue Threading initialized...')


# ---------------------------------------------------------------------------------------------------------------------
# Socket Server Log Listener
# ---------------------------------------------------------------------------------------------------------------------
class SyslogUDPHandler(socketserver.BaseRequestHandler):
    logger.info('Enter the Sandman')

    def handle(self):
        try:
            data = bytes.decode(self.request[0].strip())
        except UnicodeDecodeError as e:
            logger.error('Handle attempt failed: %s' % e)
            print(('Handle attempt failed: %s' % e))
            logger.error('Probably a bad handler message.  Skipping...')
            print('Probably a bad handler message.  Skipping...')
            return False

        socket = self.request[1]
        data_list = data.split(',')

        # Raw Data List
        try:
            event = data_list[0]
            event = str(event.split(': ')[1])
        except IndexError:
            event = None
        try:
            path = data_list[1]
            path = path.split(': ')[1]
        except IndexError:
            path = None
        try:
            event_type = data_list[2]
            event_type = event_type.split(': ')[1]
        except IndexError:
            event_type = None
        try:
            file_size = data_list[3]
            file_size = file_size.split(': ')[1]
        except IndexError:
            file_size = None
        try:
            user = data_list[4]
            user = user.split(': ')[1]
            user = user.strip('ASC\\')
        except IndexError:
            user = None
        try:
            ip = data_list[5]
            ip = ip.split(': ')[1]
        except IndexError:
            ip = None

        if event == 'write' or 'move':
            # logger.debug('Event Triggered: %s' % event)
            if event_type == 'File':
                # Adjust path if a move type is detected.
                if event == 'move':
                    crop_path = path.split(' -> ')
                    path = crop_path[1]

                # logger.debug('Event Type is FILE')
                if path.startswith(publish_root_folder) and not re.findall(archive_path_to_watch, path):
                    # logger.debug('JOBS is in the path')

                    # Publish path plugin condition starts here.
                    if re.findall(publish_path_to_watch, path):
                        ignore_this = False
                        for ignore in ignore_types:
                            if ignore in path:
                                ignore_this = True
                                break
                        if not ignore_this:
                            logger.info('Publish path detected!  Testing...')
                            logger.info('%s | %s | %s | %s' % (user, path, file_size, ip))

                            # Start double check that the file is valid and begin packing it up for processing.
                            project_details = get_details_from_path(path)
                            if project_details:
                                proj_name = project_details['name']
                                proj_id = project_details['id']

                                # Assuming a project id was returned, process the results
                                if proj_id:
                                    # Get the configuration from the project ID
                                    find_config = get_configuration(proj_id)
                                    logger.debug('find_config RETURNS: %s' % find_config)

                                    # If a configuration is found, build paths to the appropriate files
                                    if find_config:
                                        templates_path = find_config + relative_config_path
                                        template_file = os.path.join(templates_path, 'templates.yml')
                                        root_file = os.path.join(templates_path, 'roots.yml')
                                        template_file = template_file.replace('/', '\\')
                                        root_file = root_file.replace('/', '\\')

                                        # Open the configuration files...
                                        try:
                                            logger.info('Opening config files...')
                                            f = open(template_file, 'r')
                                            r = open(root_file, 'r')
                                        except Exception as err:
                                            # If unable to open the configuration files, try another 10 times.
                                            tries = 1
                                            while tries < 10:
                                                logger.error('Opening files took a shit.  Trying again...')
                                                time.sleep(2)
                                                try:
                                                    logger.warning('Open attempt #%i' % tries)
                                                    f = open(template_file, 'r')
                                                    r = open(root_file, 'r')
                                                    break
                                                except Exception as e:
                                                    tries += 1
                                                    logging.error('File Open failed again. Trying again... ERROR: %s' % e)
                                            raise 'Total failure! %s' % err

                                        # Path the tempate fields into something more usable.
                                        template = yaml.load(f)
                                        roots = yaml.load(r)

                                        get_root_path = roots['primary']['windows_path']
                                        root_drive = str(get_root_path).rsplit('\\', 1)[0]
                                        full_filename = '%s%s' % (root_drive, path)

                                        # Package data into a dict for passing to the queue
                                        package = {'filename': full_filename, 'template': template, 'roots': roots,
                                                   'proj_id': proj_id, 'proj_name': proj_name, 'user': user, 'ip': ip}
                                        # Add the package to the queue for processing.
                                        q.put(package, block=True)
                                        logger.debug('%s added to queue...' % full_filename)

                    elif re.findall(ref_path_to_watch, path):
                        ignore_this = False
                        for ignore in ignore_types:
                            if ignore in path:
                                ignore_this = True
                                break
                        if not ignore_this:
                            logger.info('Reference path detected!')
                            logger.info('%s | %s | %s | %s' % (user, path, file_size, ip))
                            project_details = get_details_from_path(path)
                            if project_details:
                                proj_name = project_details['name']
                                proj_id = project_details['id']
                                '''
                                Ok.  The main reference page does not show thumbnails by default, but references linked to 
                                assets do seem to show the thumbnail... just not on the main reference page; only on the actual
                                asset page.  Actually... the asset references do not show up in the overall reference page.
                                Main reference page will need thumbnails added separately.
                                
                                There will need to be 2 processes:
                                Asset Reference
                                Project Reference
                                
                                Asset type = File(Attachment)
                                Proj. type = Reference(CustomEntity03)
                                '''
                                # Assuming a project id was returned, process the results
                                if proj_id:
                                    # Get the configuration from the project ID
                                    find_config = get_configuration(proj_id)
                                    logger.debug('find_config RETURNS: %s' % find_config)

                                    # If a configuration is found, build paths to the appropriate files
                                    if find_config:
                                        templates_path = find_config + relative_config_path
                                        template_file = os.path.join(templates_path, 'templates.yml')
                                        root_file = os.path.join(templates_path, 'roots.yml')
                                        template_file = template_file.replace('/', '\\')
                                        root_file = root_file.replace('/', '\\')

                                        # Open the configuration files...
                                        try:
                                            logger.info('Opening config files...')
                                            f = open(template_file, 'r')
                                            r = open(root_file, 'r')
                                        except Exception as err:
                                            # If unable to open the configuration files, try another 10 times.
                                            tries = 1
                                            while tries < 10:
                                                logger.error('Opening files took a shit.  Trying again...')
                                                time.sleep(2)
                                                try:
                                                    logger.warning('Open attempt #%i' % tries)
                                                    f = open(template_file, 'r')
                                                    r = open(root_file, 'r')
                                                    break
                                                except Exception as e:
                                                    tries += 1
                                                    logging.error('File Open failed again. Trying again... ERROR: %s' % e)
                                            raise 'Total failure! %s' % err

                                        # Path the tempate fields into something more usable.
                                        template = yaml.load(f)
                                        roots = yaml.load(r)

                                        get_root_path = roots['primary']['windows_path']
                                        root_drive = str(get_root_path).rsplit('\\', 1)[0]
                                        full_filename = '%s%s' % (root_drive, path)

                                        # Package data into a dict for passing to the queue
                                        package = {'filename': full_filename, 'template': template, 'roots': roots,
                                                   'proj_id': proj_id, 'proj_name': proj_name, 'user': user, 'ip': ip}
                                        rq.put(package, block=True)
                                        logger.debug('%s added to the Reference queue...' % full_filename)
                elif re.findall(archive_path_to_watch, path):
                    print('Archive found!')
                    print(path)
                    full_archive_path = '%s%s' % (server_root, path)
                    package = {
                        'filename': full_archive_path,
                        'user': user,
                        'ip': ip
                    }
                    aq.put(package, block=True)
                    logger.debug('%s added to the archive queue...' % full_archive_path)


# ---------------------------------------------------------------------------------------------------------------------
# Watch Folder
# ---------------------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        server = socketserver.UDPServer((HOST, PORT), SyslogUDPHandler)
        print('Internal Auto Publisher is now listening!')
        print('Press Ctrl + C to terminate!')
        print(('=' * 100))
        server.serve_forever(poll_interval=0.5)
    except (IOError, SystemExit):
        raise
    except KeyboardInterrupt:
        print("Crtl+C Pressed. Shutting down.")
