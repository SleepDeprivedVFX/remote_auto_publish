

# -----------------------------------------------------------------------------------------------------------------
# Start Processing...
# -----------------------------------------------------------------------------------------------------------------
def process_file(filename=None, template=None, roots=None, proj_id=None, proj_name=None):
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
    # Check that data is there and that the file actually exists
    if filename and os.path.exists(filename):
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
                                                        task=task, f_type=output_type, proj_id=proj_id,
                                                        asset=find_asset, root=root_template_path)
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
                        publish_to_shotgun(publish_file=new_file, publish_path=res_publish_path, asset_id=asset_id,
                                           proj_id=proj_id, task_id=task, next_version=next_version)
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
                    send = upload_to_shotgun(filename=filename, asset_id=asset_id, task_id=task, proj_id=proj_id)
                    logger.debug('SEND: %s' % send)
                    if send:
                        # Run the Send Today portion of our show.
                        # This will need to get the send folder from the template, and make sure there is a date
                        # folder.
                        is_sent = send_today(filename=filename, path=send_today_path, proj_id=proj_id,
                                             asset=find_asset)
                        logger.debug('is_sent RETURNS: %s' % is_sent)

        logger.info('Finished processing the file')
        logger.info('=' * 100)
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
            file_to_publish.compose().save(render_path)
        except Exception, e:
            logger.error('Photoshop File could not generate an image! %s' % e)
            pass

        # Upload a version
        upload_to_shotgun(filename=render_path, asset_id=asset['id'], task_id=task, proj_id=proj_id)


def upload_to_shotgun(filename=None, asset_id=None, task_id=None, proj_id=None):
    """
    A simple tool to create Shotgun versions and upload them
    :param filename:
    :param asset_id:
    :param task_id:
    :param proj_id:
    :return:
    """
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
    try:
        new_version = sg.create('Version', version_data)
        logger.debug('new_version RETURNS: %s' % new_version)
        version_id = new_version['id']
        sg.upload_thumbnail('Version', version_id, file_path)
        sg.upload('Version', version_id, file_path, field_name='sg_uploaded_movie', display_name=file_name)
        logger.info('New Version Created!')
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
    logger.info('Getting the Send Today folder from the template...')
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
    today_path = os.path.join(today_path, 'REMOTE')
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
        try:
            shutil.move(filename, send_today_path)
            return True
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
    return translation


def version_tool(path=None, version_up=False, padding=3):
    """
    This tool finds and creates padded version numbers
    :param path: (str) relative path to file
    :param version_up: (bool) Setting for running a version up
    :param padding: (int) Number padding
    :return: new_num (str) a padded string version number.
    """
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
            logger.info('NEW_NUM: %s' % new_num)
        else:
            new_num = '001'
    logger.debug('Returning from Version Tools: %s' % new_num)
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
            if ':' in naming_convention:
                # TODO: I probably need to write an ELSE for this IF
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
                            translation = get_sg_translator(sg_task='design.remote', fields=tag_fields)
                            logger.info('TRANSLATION: %s' % translation)
                            base_tag = tag.strip('{')
                            base_tag = base_tag.strip('}')
                            translations[base_tag] = translation['delivery_code']
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
            pass


def get_set_task(asset=None, proj_id=None):
    """
    This will look for an existing task in Shotgun and return the info. If no task if found, it creates one and returns
    the info
    :param asset: (dict) Asset details
    :param proj_id: (int) Project ID number
    :return: (int) task: Task ID number
    """
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
    """
    This converts the publish template into an actual path
    :param template: (str) The template being converted
    :param asset: (dict) the details of the Asset
    :param version: (int) the version number
    :return: (str) res_path: the resolved path name
    """
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
        return template_path


def get_asset_details_from_path(project=None, proj_id=None, path=None):
    """
    Convert a path to a series of details about an asset.
    :param project:
    :param proj_id:
    :param path:
    :return: ass - The asset details
    """
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
    """
    Get the basic project details from the path
    :param path:
    :return: prj - Project details
    """
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
    """
    Get the Pipeline configuration from the Project ID.  This gets the windows_path to where the pipeline config files
    exist on the server
    :param proj_id:
    :return: config_path
    """
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
    """
    Creates a list of all active Shotgun Projects to search through
    :return:
    """
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
