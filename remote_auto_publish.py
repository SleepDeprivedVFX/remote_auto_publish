"""
This is a rebuild of the Dropbox event listener.
I am starting with a basic folder listener copied from the the web.  I am using this folder event listener as the
driver for everything else that will happen.
"""

import os
from glob import glob
import re
import win32file
import win32con
import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import platform
import time
import logging
import logging.handlers
import shutil
import yaml
import psd_tools as psd
import shotgun_api3
import queue
import threading

# Build Shotgun Connection
sg_url = 'https://asc.shotgunstudio.com'
sg_name = 'remoteAutoPublisher'
sg_key = '&pmudbcro6esChtccfurpnxwp'
sg = shotgun_api3.Shotgun(sg_url, sg_name, sg_key)

# Windows Triggers
ACTIONS = {
    1: "Created",
    2: "Deleted",
    3: "Updated",
    4: "Renamed from something",
    5: "Renamed to something"
}
# Thanks to Claudio Grondi for the correct set of numbers
FILE_LIST_DIRECTORY = 0x0001

# Dropbox Folder
path_to_watch = "C:/Users/sleep/OneDrive/Documents/Scripts/Area51"
hDir = win32file.CreateFile(
    path_to_watch,
    FILE_LIST_DIRECTORY,
    win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
    None,
    win32con.OPEN_EXISTING,
    win32con.FILE_FLAG_BACKUP_SEMANTICS,
    None
)


# Create Log file
log_level = logging.INFO


def _setFilePathOnLogger(logger, path):
    # Remove any previous handler.
    _removeHandlersFromLogger(logger, logging.handlers.TimedRotatingFileHandler)

    # Add the file handler
    handler = logging.handlers.TimedRotatingFileHandler(path, 'midnight', backupCount=10)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
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


logDate = str(time.strftime('%m%d%y%H%M%S'))
logfile = "c:/users/sleep/onedrive/documents/scripts/logs/remote_auto_publish.log"
logging.basicConfig(level=log_level, filename=logfile)
logger = logging.getLogger('remoteAutoPublish')
_setFilePathOnLogger(logger, logfile)

logger.info('Starting the Remote Auto Publisher...')

# --------------------------------------------------------------------------------------------------------------
# Global Variables
# --------------------------------------------------------------------------------------------------------------
publish_types = {
    '.psd': 'Photoshop Image',
    '.nk': 'Nuke Script',
    '.mb': 'Maya Scene',
    '.ma': 'Maya Scene',
    '.ztl': 'ZBrush',
    '.mud': 'Mudbox'
}
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
        'output': 'png',
        'render': 'Renders'
    },
    '.psb': {
        'type': 'Photoshop Image',
        'output': 'png',
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
    '.tga'
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
    }
}
task_name_format = '{Asset}_{task_name}_*{ext}'

# Because of the simplistic nature of this tool, I am currently limiting its use to one task.
# The reason for this is simple: having task folders as subfolders of assets will make remote use cumbersome for
# designers who struggle with anything more complicated than a doorknob. (The same people who could not set the clock
# on their VCRs and just let them blink endlessly.)  The other reason is that, currently, only designers will be using
# this, and there are no immediate plans to change that.  That being said, there is some minor architecture in place
# to handle a more complex, task-based system if one is ever needed.
# Thus, the one task_name:
task_name = 'design.remote'
task_step = 23
relative_config_path = '/config/core'


# -----------------------------------------------------------------------------------------------------------------
# Processor Queue
# -----------------------------------------------------------------------------------------------------------------
q = queue.Queue()


# -----------------------------------------------------------------------------------------------------------------
# Start Processing...
# -----------------------------------------------------------------------------------------------------------------
def process_file(filename):
    if filename:
        logger.info('-' * 120)
        logger.info('NEW FILE PROCESSING...')
        print 'New File Processing...'

        # Get the path details from the filename
        path = os.path.dirname(filename)
        logger.debug('PATH: %s' % path)
        # Filename without path
        base_file = os.path.basename(filename)
        # Relative path outside the dropbox structure
        rel_path = path.split(path_to_watch)[1]
        logger.debug('Relative Path: %s' % rel_path)

        f = os.path.splitext(base_file)
        # File extension
        ext = str(f[1]).lower()
        # Filename without path or extension.
        file_name = f[0]

        # Look for project details based on names in the relative path
        project_details = get_details_from_path(rel_path)
        proj_name = project_details['name']
        proj_id = project_details['id']
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

                task = get_set_task(asset=find_asset, proj_id=proj_id)
                logger.debug('Task ID returned: %s' % task)

                # Find the Shotgun configuration root path
                find_config = get_configuration(proj_id)
                logger.debug('Configuration found: %s' % find_config)

                # If a Shotgun configuration is found, continue processing.
                if find_config:
                    logger.debug('find_config passes.')
                    # The the template.yml file and load it into a yaml object
                    templates_path = find_config + relative_config_path
                    logger.debug('templates_path: %s' % templates_path)
                    template_file = os.path.join(templates_path, 'templates.yml')
                    logger.debug('template file returns: %s' % template_file)
                    root_file = os.path.join(templates_path, 'roots.yml')
                    logger.debug('root_file returns: %s' % root_file)
                    template_file = template_file.replace('/', '\\')
                    root_file = root_file.replace('/', '\\')
                    f = open(template_file, 'r')
                    logger.debug('template file opened.')
                    r = open(root_file, 'r')
                    logger.debug('root file opened.')
                    template = yaml.load(f)
                    logger.debug('template yaml created.')
                    roots = yaml.load(r)
                    logger.debug('root yaml created.')
                    # Look for publish types from the extension
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
                        publish_area_path = os.path.join(root_template_path, publish_area).replace('\\', '/')

                        # Get the resolved working area and find existing files in it.
                        res_path_work_area = process_template_path(template=work_area_path, asset=find_asset)

                        # Create paths if they're not already there.
                        if not os.path.exists(res_path_work_area):
                            logger.info('Creating paths: %s' % res_path_work_area)
                            os.makedirs(res_path_work_area)

                        # Create the basic taskname template from the data.
                        template_name = task_name_format.format(Asset=asset_name, task_name=task_name, ext=ext)

                        find_files_from_template = '%s/%s' % (res_path_work_area, template_name)
                        get_files = [f for f in glob(find_files_from_template)]
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

                        # Copy the file to the correct place on the server.  There are some wait time handlers in here.
                        logger.info('Copying the file to the server...')
                        copy_file = filename.replace('\\', '/')
                        try:
                            shutil.copy2(copy_file, res_path_work_template)
                            message = 'The file is copied!  Prepping for publish!'
                        except IOError, e:
                            message = ''
                            # Waiting tries...
                            attempts = 1
                            while attempts < 10:
                                time.sleep(2 * attempts)
                                try:
                                    shutil.copy2(copy_file, res_path_work_template)
                                    message = 'The File is copied after %i tries!  Prepping for publish' % attempts
                                    break
                                except:
                                    message = ''
                                    attempts += 1
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

                            # ------------------------------------------------------------------------------------
                            # Sub Processing Routines
                            # ------------------------------------------------------------------------------------
                            # Here I can add different job types as the come up.  For now, it's only Photoshop
                            if export_type == 'Photoshop':
                                logger.debug('export type detected: PHOTOSHOP')
                                get_template_name = templates[render_area]
                                render_publish_area = get_template_name['publish_area']
                                logger.debug('get_template_name: %s' % get_template_name)
                                try:
                                    process_Photoshop_image(template=template, filename=new_file,
                                                            pub_area=render_publish_area,
                                                            task=task, type=output_type, proj_id=proj_id,
                                                            asset=find_asset, root=root_template_path)
                                except IOError, e:
                                    logger.error('Unable to process the %s for the following reasons: %s' % (ext, e))

                        # Publish the file
                        res_publish_path = process_template_path(template=publish_template_path, asset=find_asset,
                                                                 version=version)
                        logger.debug('Publish Path: %s' % res_publish_path)
                        next_version = version + 1
                        # try:
                        logger.info('Attempting to publish...')
                        publish_to_shotgun(publish_file=new_file, publish_path=res_publish_path, asset_id=asset_id,
                                           proj_id=proj_id, task_id=task, next_version=next_version)
                        # except Exception, e:
                        #     logger.error('Publish failed for the following! %s' % e)

                    elif ext.lower() in upload_types:
                        logger.info('Uploading for review %s' % file_name)
                        upload_to_shotgun(filename=filename, asset_id=asset_id, task_id=task, proj_id=proj_id)
        logger.info('Finished processing the file')
        logger.info('=' * 100)
        q.task_done()
        print 'Finished processing the file'


def process_Photoshop_image(template=None, filename=None, task=None, pub_area=None, type=None, proj_id=None, asset=None,
                            root=None):
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
        render = '%s.%s' % (root_filename, type)
        render_path = os.path.join(full_path, render)

        # Process the image.
        logger.info('Processing Photoshop file...')
        file_to_publish = psd.PSDImage.open(filename)
        file_to_publish.compose().save(render_path)

        # Upload a version
        upload_to_shotgun(filename=render_path, asset_id=asset['id'], task_id=task, proj_id=proj_id)


def upload_to_shotgun(filename=None, asset_id=None, task_id=None, proj_id=None):
    file_name = os.path.basename(filename)
    file_path = filename
    description = 'A remote file was detected in Dropbox and this version was created from it.'
    version_data = {
        'description': description,
        'project': {'type': 'Project', 'id': proj_id},
        'sg_status_list': 'rev',
        'code': file_name,
        'entity': {'type': 'Asset', 'id': asset_id},
        'sg_task': {'type': 'Task', 'id': task_id}
    }

    new_version = sg.create('Version', version_data)
    logger.debug('new_version RETURNS: %s' % new_version)
    version_id = new_version['id']
    sg.upload_thumbnail('Version', version_id, file_path)
    sg.upload('Version', version_id, file_path, field_name='sg_uploaded_movie', display_name=file_name)
    logger.info('New Version Created!')


def publish_to_shotgun(publish_file=None, publish_path=None, asset_id=None, proj_id=None, task_id=None, next_version=1):
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

        # Parse the copied data
        base_name = os.path.basename(publish_file)
        find_version = re.findall(r'_v\d*|_V\d*', base_name)[0]
        digits_only = find_version.lower().strip('_v')
        count_digits = len(digits_only)
        version = int(digits_only)
        ext = os.path.splitext(base_name)[1]

        # Get the publish type.
        get_publish_type = publish_types[ext]
        filters = [
            ['code', 'is', get_publish_type]
        ]
        fields = ['id']

        find_type = sg.find_one('PublishedFileType', filters, fields)

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

        # Create a new version and save up.
        new_version = '_v' + str(next_version).zfill(count_digits)
        version_up = publish_file.replace(find_version, new_version)
        logger.info('Versioning up the file...')
        try:
            shutil.copy2(publish_file, version_up)
            logger.info('Version up completed!')
        except Exception, e:
            logger.error('The version up failed!: %s ' % e)


def get_set_task(asset=None, proj_id=None):
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
    return task


def process_template_path(template=None, asset=None, version=0):
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
    return res_path


def resolve_template_path(template_key, template):
    if template_key and template:
        try:
            read = template['paths'][template_key]['definition']
        except:
            read = template['paths'][template_key]
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
        return template_path


def get_asset_details_from_path(project=None, proj_id=None, path=None):
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
                if asset['code'] in path:
                    ass['name'] = asset['code']
                    ass['id'] = asset['id']
                    ass['type'] = asset['sg_asset_type']
                    logger.info('%s found in %s' % (ass['name'], path))
                    return ass
    return


def get_details_from_path(path):
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
    return prj


def get_configuration(proj_id):
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
            return config_path
    return


def get_active_shotgun_projects():
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
    projects_list = sg.find('Project', filters, fields)
    logger.debug('Active Projects Found: %s' % projects_list)
    return projects_list


# The following print lines (and all print lines) are temporary output for the command line window that will
# be running until I get the service working properly.
print 'Starting the Dropbox listener...'


# ---------------------------------------------------------------------------------------------------------------------
# Run Queue
# ---------------------------------------------------------------------------------------------------------------------
def file_queue():
    logger.debug('Queue Running...')
    print 'Queue running...'
    while True:
        full_filename = q.get()
        logger.debug('Queued file: %s' % full_filename)
        copying = True
        size2 = -1
        while copying:
            size = os.stat(full_filename).st_size
            if size == size2:
                time.sleep(2)
                process_file(full_filename)
                copying = False
            else:
                size2 = os.stat(full_filename).st_size
                time.sleep(2)


# Start the thread
print 'Start Threading...'
t = threading.Thread(target=file_queue, name='FileQueue')
t.setDaemon(True)
t.start()


# ---------------------------------------------------------------------------------------------------------------------
# Watch Folder
# ---------------------------------------------------------------------------------------------------------------------
# class remoteAutoPublisher(win32serviceutil.ServiceFramework):
#     _svc_name_ = "RemoteAutoPublisher"
#     _svc_display_name_ = "Remote Auto Publisher"
#
#     def __init__(self, args):
#         win32serviceutil.ServiceFramework.__init__(self, args)
#         self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
#         socket.setdefaulttimeout(60)
#
#     def SvcStop(self):
#         self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
#         win32event.SetEvent(self.hWaitStop)
#
#     def SvcDoRun(self):
#         servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
#                               servicemanager.PYS_SERVICE_STARTED,
#                               (self._svc_name_, ''))
#         self.main()
#
#     def main(self):
#         while 1:
#             results = win32file.ReadDirectoryChangesW(
#                 hDir,
#                 1024,
#                 True,
#                 win32con.FILE_NOTIFY_CHANGE_FILE_NAME |
#                 win32con.FILE_NOTIFY_CHANGE_DIR_NAME |
#                 win32con.FILE_NOTIFY_CHANGE_ATTRIBUTES |
#                 win32con.FILE_NOTIFY_CHANGE_SIZE |
#                 win32con.FILE_NOTIFY_CHANGE_LAST_WRITE |
#                 win32con.FILE_NOTIFY_CHANGE_SECURITY,
#                 None,
#                 None
#             )
#             for action, file in results:
#                 full_filename = os.path.join(path_to_watch, file)
#                 print full_filename, ACTIONS.get(action, "Unknown")
#                 logger.info(full_filename, ACTIONS.get(action, "Unknown"))
#                 # This is where my internal processes get triggered.
#                 # Needs a logger at the very least, although a window would be nice too.
#                 if action == 1:
#                     if os.path.isfile(full_filename):
#                         logger.info('New file detected. %s' % full_filename)
#                         # From here down, I should move this into a Queue.  Then the Queue can handle multiple files.
#                         q.put(full_filename)
#
#
# if __name__ == '__main__':
#     win32serviceutil.HandleCommandLine(remoteAutoPublisher)

# -------------------------------------------------------------------------------------------------------------
# TESTING SETUP
# -------------------------------------------------------------------------------------------------------------
print 'Folder watching has begun.'
while 1:
    results = win32file.ReadDirectoryChangesW(
        hDir,
        1024,
        True,
        win32con.FILE_NOTIFY_CHANGE_FILE_NAME |
        win32con.FILE_NOTIFY_CHANGE_DIR_NAME |
        win32con.FILE_NOTIFY_CHANGE_ATTRIBUTES |
        win32con.FILE_NOTIFY_CHANGE_SIZE |
        win32con.FILE_NOTIFY_CHANGE_LAST_WRITE |
        win32con.FILE_NOTIFY_CHANGE_SECURITY,
        None,
        None
    )
    for action, file in results:
        full_filename = os.path.join(path_to_watch, file)
        print full_filename, ACTIONS.get(action, "Unknown")
        # This is where my internal processes get triggered.
        # Needs a logger at the very least, although a window would be nice too.
        if action == 1:
            if os.path.isfile(full_filename):
                logger.info('New file detected. %s' % full_filename)
                # From here, add to the queue and let it handle multiple files.
                q.put(full_filename)

