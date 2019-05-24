"""
The Internal Auto Publisher (IAP) is a server listener that gets data from the server logs in order to better port
"""

import os
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
import SocketServer
import subprocess

# Build Shotgun Connection
sg_url = 'https://radiowaves.shotgunstudio.com'
sg_name = 'InternalAutoPublisher'
sg_key = 'urNiaiobqzxpwxtpfpq~nie7l'
sg = shotgun_api3.Shotgun(sg_url, sg_name, sg_key)

# Server Logs Connections
HOST, PORT = '0.0.0.0', 514

# Watch Folder Filters
publish_path_to_watch = "/Jobs/\w+/publish/\w+"
ref_path_to_watch = '/Jobs/\w+/reference/auto/\w+'
publish_root_folder = '/Jobs/'

# Output window startup messages
print '-' * 100
print 'INTERNAL AUTO PUBLISH UTILITY'
print '+' * 100

'''
TODO:
1. Setup reference system
2. Need to add auto task assignments for artists who drag and drop into an asset publisher.
'''

# Create Log file
log_level = logging.INFO
# log_level = logging.DEBUG


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


logfile = "C:/shotgun/remote_auto_publish/logs/internalAutoPublish.%s.log" % datetime.date(datetime.now())

logger = logging.getLogger('remote_auto_publish')
logger.setLevel(log_level)
_setFilePathOnLogger(logger, logfile)

logger.info('Starting the Internal Auto Publisher...')
print 'Starting the Internal Auto Publisher...'
print 'Logging system setup.'

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
task_name = 'design.auto'
task_step = 23
relative_config_path = '/config/core'
task_name_format = '{Asset}_{task_name}_*{ext}'

publish_types = {
    '.psd': 'Photoshop Image',
    '.nk': 'Nuke Script',
    '.mb': 'Maya Scene',
    '.ma': 'Maya Scene',
    '.ztl': 'ZBrush',
    '.mud': 'Mudbox',
    '.bip': 'Keyshot Package',
    '.kip': 'Keyshot File'
}
ignore_types = [
    '.DS_Store',
    '.db'
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
    '.jpeg',
    '.tif',
    '.tiff',
    '.png',
    '.mov',
    '.mp4',
    '.tga',
    '.mpg'
]
video_types = [
    '.mov',
    '.mp4',
    '.mpeg',
    '.avi',
    '.mpg'
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
    }
}


# -----------------------------------------------------------------------------------------------------------------
# Processor Queue
# -----------------------------------------------------------------------------------------------------------------
logger.debug('Creating the Queue...')
q = queue.Queue()


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
            print 'New File Processing...'
            print filename
            logger.info(filename)
            print 'Published by %s' % user
            logger.info('Published by %s' % user)
            print 'At: %s' % datetime.now()
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
                print 'This file is not in the proper asset structure!  Cannot process!'
                print '=' * 100

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

                    if ext in publish_types:
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
                        except IOError, e:
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
                        if ext in generate_types.keys():
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
                                                                    asset=find_asset, root=root_template_path)
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
                                except IOError, e:
                                    logger.error('Unable to process the %s for the following reasons: %s' % (ext, e))
                                    pass

                        # Publish the file
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
                        except Exception, e:
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
            print 'Finished processing file.'
            print '=' * 100
    except Exception, e:
        print 'Skipping!  The following error occurred: %s' % e
        logger.error('Skipping!  The following error occurred: %s' % e)
        logger.info('%s' % e)
        q.task_done()


def process_Photoshop_image(template=None, filename=None, task=None, pub_area=None, f_type=None, proj_id=None,
                            asset=None, root=None):
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
            file_to_PIL = file_to_publish.compose()
            converted_file = file_to_PIL.convert(mode="RGB")
            converted_file.save(render_path)
        except Exception, e:
            logger.error('Photoshop File could not generate an image! %s' % e)
            pass

        # Upload a version
        upload_to_shotgun(filename=render_path, asset_id=asset['id'], task_id=task, proj_id=proj_id)

        logger.debug(('.' * 35) + 'END PROCESS PHOTOSHOP IMAGE' + ('.' * 35))
        return render_path
    return None


def upload_to_shotgun(filename=None, asset_id=None, task_id=None, proj_id=None, user=None):
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
    version_data = {
        'description': description,
        'project': {'type': 'Project', 'id': proj_id},
        'sg_status_list': 'rev',
        'code': file_name,
        'entity': {'type': 'Asset', 'id': asset_id},
        'sg_task': {'type': 'Task', 'id': task_id}
    }
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
    except Exception, e:
        logger.error('The new version could not be created: %s' % e)
        pass
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
        except Exception, e:
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
                if 'version' in work_fields.keys():
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
                                except Exception, e:
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
                            logger.info('YEAR: %s' % year)
                            logger.info('YEAR_TAG: %s' % str(year_tag))
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
    except Exception, e:
        logger.error('It looks like the Project Naming Convention is incorrectly set. See the Admins. %s' % e)
        return False

    logger.debug(('.' * 35) + 'END create_client_name' + ('.' * 35))
    return new_name


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
        except Exception, e:
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
                    # TODO: Add task assignment here
                    assign_user_to_task(user=user, task_id=task_id)
                    break
        if not task:
            logger.info('No task found.  Creating a new task...')
            task_data = {
                'project': {'type': 'Project', 'id': proj_id},
                'content': task_name,
                'entity': {'type': 'Asset', 'id': asset_id},
                'step': {'type': 'Step', 'id': task_step}
            }
            new_task = sg.create('Task', task_data)
            logger.info('New Task Created!')
            task = new_task['id']
            # TODO: Add task assignments here.
            assign_user_to_task(user=user, task_id=task_id)

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


def process_template_path(template=None, asset=None, version=0):
    """
    This converts the publish template into an actual path
    :param template: (str) The template being converted
    :param asset: (dict) the details of the Asset
    :param version: (int) the version number
    :return: (str) res_path: the resolved path name
    """
    logger.debug(('*' * 35) + 'process_template_path' + ('*' * 35))
    global task_name
    res_path = None
    if template:
        if asset:
            asset_name = asset['name']
            asset_type = asset['type']
        else:
            asset_name = None
            asset_type = None
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
        find_assets = sg.find('Asset', filters, fields)
        logger.debug('Shotgun Returns: %s' % find_assets)
        if find_assets:
            logger.debug('Assets exist!  Finding our guy...')
            for asset in find_assets:
                logger.debug('Testing %s IN %s...' % (asset['code'], path))
                # TODO: The following 'if asset['code'] in path:' suffers from the following scenario:
                #       'Jack' and 'Village_where_Jack_Lives' both have the word 'Jack' in them.  Thus, the system finds
                #       the correct word, but in the wrong Asset.  I think what I'll have to do is split this further
                #       if asset['code'] in path:
                #           split_path = path.split('/')  # Splitting it at the slashes.
                #           for this in split_path:
                #               if this == 'Jack':
                #                   Do some shit.
                #       The problem with this is that 'Jack' could also be the name of the project, so the pattern will
                #       have to be respected as well.
                if asset['code'] in path:
                    ass['name'] = asset['code']
                    ass['id'] = asset['id']
                    ass['type'] = asset['sg_asset_type']
                    logger.info('%s found in %s' % (ass['name'], path))
                    return ass
    logger.debug(('.' * 35) + 'END get_asset_details_from_path' + ('.' * 35))
    return


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
    except Exception, e:
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
    except Exception, e:
        logger.error('The following error occurred: %s' % e)
        projects_list = []
    logger.debug(('.' * 35) + 'END get_active_shotgun_projects' + ('.' * 35))
    return projects_list


# ---------------------------------------------------------------------------------------------------------------------
# Run Queue
# ---------------------------------------------------------------------------------------------------------------------
def file_queue():
    """
    The Queue.  This handles each of the multiple files dropped, so the tool doesn't overload.
    :return:
    """
    logger.debug('Queue Running...')
    print 'Queue Running...'
    # print 'Queue running...'
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
                    """
                    Here is where we have to start ingecting some "file STILL exists" logic... at least I think.
                    """
                    copying = False
                    process_file(filename=full_filename, template=template, roots=roots, proj_id=proj_id,
                                 proj_name=proj_name, user=user, ip=ip)
                    logger.debug('~' * 45)
                    break
                else:
                    # Copying not finished, wait to seconds and try again...
                    size2 = os.stat(full_filename).st_size
                    time.sleep(2)
            except WindowsError, e:
                logger.debug(e)
                break


def datetime_to_float(d):
    # Change the date-time to a decimal floating point number
    epoch = datetime.utcfromtimestamp(0)
    total_seconds = (d - epoch).total_seconds()
    return total_seconds


# Start the thread
'''
This starts the thread that runs the queue
'''
logger.debug('Starting the thread...')
t = threading.Thread(target=file_queue, name='FileQueue')
t.setDaemon(True)
t.start()
print 'Queue Threading initialized...'


# ---------------------------------------------------------------------------------------------------------------------
# Socket Server Log Listener
# ---------------------------------------------------------------------------------------------------------------------
class SyslogUDPHandler(SocketServer.BaseRequestHandler):
    logger.info('Enter the Sandman')

    def handle(self):
        try:
            data = bytes.decode(self.request[0].strip())
        except UnicodeDecodeError, e:
            logger.error('Handle attempt failed: %s' % e)
            print 'Handle attempt failed: %s' % e
            logger.error('Probably a bad handler message.  Skipping...')
            print 'Probably a bad handler message.  Skipping...'
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
                # logger.debug('Event Type is FILE')
                if path.startswith(publish_root_folder):
                    # logger.debug('JOBS is in the path')

                    if event == 'move':
                        crop_path = path.split(' -> ')
                        path = crop_path[1]
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
                                        except Exception, err:
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
                                                except Exception, e:
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
                                        q.put(package)
                                        logger.debug('%s added to queue...' % full_filename)
                    elif re.findall(ref_path_to_watch, path):
                        logger.info('Reference path detected!')
                        logger.debug('%s | %s | %s | %s' % (user, path, file_size, ip))
                        project_details = get_details_from_path(path)
                        proj_name = project_details['name']
                        proj_id = project_details['id']


# ---------------------------------------------------------------------------------------------------------------------
# Watch Folder
# ---------------------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        server = SocketServer.UDPServer((HOST, PORT), SyslogUDPHandler)
        print 'Internal Auto Publisher is now listening!'
        print 'Press Ctrl + C to terminate!'
        print '=' * 100
        server.serve_forever(poll_interval=0.5)
    except (IOError, SystemExit):
        raise
    except KeyboardInterrupt:
        print ("Crtl+C Pressed. Shutting down.")
