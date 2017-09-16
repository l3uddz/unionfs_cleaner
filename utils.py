import http.client
import json
import logging
import os
import shlex
import subprocess
import sys
from urllib import parse

try:
    from shlex import quote as cmd_quote
except ImportError:
    from pipes import quote as cmd_quote

logger = logging.getLogger("UTILS")
logger.setLevel(logging.DEBUG)

rate_limits_seen = 0


############################################################
# SCRIPT STUFF
############################################################

def seconds_to_string(seconds):
    """ reference: https://codereview.stackexchange.com/a/120595 """
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    resp = ''
    if days:
        resp += '%d days' % days
    if hours:
        if len(resp):
            resp += ', '
        resp += '%d hours' % hours
    if minutes:
        if len(resp):
            resp += ', '
        resp += '%d minutes' % minutes
    if seconds:
        if len(resp):
            resp += ' and '
        resp += '%d seconds' % seconds
    return resp


def get_num(x):
    return int(''.join(ele for ele in x if ele.isdigit() or ele == '.'))


def run_command(command, cfg=None):
    global rate_limits_seen

    process = subprocess.Popen(shlex.split(command), shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    while True:
        output = str(process.stdout.readline()).lstrip('b').replace('\\n', '')
        if process.poll() is not None:
            break
        if output and len(output) > 6:
            logger.info(output)
            if cfg and 'Error 403: User rate limit exceeded' in output:
                if rate_limits_seen <= 4:
                    rate_limits_seen += 1
                else:
                    logger.error("Error 403 detected 5 times, cancelling upload...")
                    process.kill()
                    rate_limits_seen = 0
                    cfg['local_folder_check_interval'] = 1500
                    logger.info("Set local_folder_check_interval to %d mins because of rate limits",
                                cfg['local_folder_check_interval'])
                    # send cancelled notification
                    if cfg['pushover_app_token'] and cfg['pushover_user_token']:
                        send_pushover(cfg['pushover_app_token'], cfg['pushover_user_token'],
                                      "Upload was cancelled due to Error 403 rate limits. local_folder_"
                                      "check_interval has been set to %d minutes." %
                                      cfg['local_folder_check_interval'])

    rc = process.poll()
    return rc


def folder_size(path, excludes):
    try:
        process = os.popen(du_size_command(path, excludes))
        data = process.read()
        process.close()
        if data is not None and int(data) > 0:
            return int(data)

    except Exception as ex:
        logger.exception("Exception calculating size of %r: ", path)
        return None


def rclone_delete(path, dry_run):
    try:
        cmd = 'rclone delete %s --drive-use-trash' % cmd_quote(path)
        if dry_run:
            cmd += ' --dry-run'
        process = os.popen(cmd)
        data = process.read()
        process.close()
        if 'Failed to delete' in data:
            return False
        else:
            return True
    except Exception as ex:
        logger.exception("Exception deleting %r: ", path)
        return False


def file_excluded(path, excludes):
    excluded = False
    for exclude in excludes:
        if exclude.lower() in path.lower():
            return True
    return excluded


def opened_files(path, excludes):
    files = []

    try:
        process = os.popen('lsof -wFn +D %s | tail -n +2 | cut -c2-' % cmd_quote(path))
        data = process.read()
        process.close()
        for item in data.split('\n'):
            if not item or len(item) <= 2 or os.path.isdir(item) or item.isdigit() or file_excluded(item, excludes):
                continue
            files.append(item)

        return files

    except Exception as ex:
        logger.exception("Exception checking %r: ", path)
        return None


def send_pushover(app_token, user_token, message):
    try:
        conn = http.client.HTTPSConnection("api.pushover.net:443")
        conn.request("POST", "/1/messages.json", parse.urlencode({
            'token': app_token,
            'user': user_token,
            'message': message
        }), {"Content-Type": "application/x-www-form-urlencoded"})
        resp = conn.getresponse()
        conn.close()
        return True if resp.status == 200 else False

    except Exception as ex:
        logger.exception("Error sending notification to %r", user_token)
    return False


def rclone_move_command(local, remote, transfers, checkers, bwlimit, excludes, chunk_size, dry_run):
    upload_cmd = 'rclone move %s %s' \
                 ' --delete-after' \
                 ' --no-traverse' \
                 ' --stats=60s' \
                 ' -v' \
                 ' --transfers=%d' \
                 ' --checkers=%d' \
                 ' --drive-chunk-size=%s' % \
                 (cmd_quote(local), cmd_quote(remote), transfers, checkers, chunk_size)
    if bwlimit and len(bwlimit):
        upload_cmd += ' --bwlimit="%s"' % bwlimit
    for item in excludes:
        upload_cmd += ' --exclude="%s"' % item
    if dry_run:
        upload_cmd += ' --dry-run'
    return upload_cmd


def du_size_command(path, excludes):
    size_cmd = "du -s --block-size=1G"
    for item in excludes:
        size_cmd += ' --exclude="%s"' % item
    size_cmd += ' %s | cut -f1' % cmd_quote(path)
    return size_cmd


def read_file_text(file):
    data = ""
    try:
        with open(file, 'r') as fp:
            data = fp.read()
            fp.close()
        return data
    except Exception as ex:
        logger.exception("Exception occurred reading %r:", file)
        return ""


def remove_empty_directories(config, force_dry_run=False):
    open_files = opened_files(config['local_folder'], config['lsof_excludes'])
    if not len(open_files):
        clearing = False
        for dir, depth in config['rclone_remove_empty_on_upload'].items():
            if os.path.exists(dir):
                clearing = True
                logger.debug("Removing empty directories from %r with mindepth %r", dir, depth)
                cmd = 'find %s -mindepth %d -type d -empty' % (cmd_quote(dir), depth)
                if not config['dry_run'] and not force_dry_run:
                    cmd += ' -delete'
                run_command(cmd)
        if clearing:
            logger.debug("Finished clearing empty directories")
    else:
        logger.debug("Skipped removing empty directories because %d files are currently open: %r", len(open_files),
                     open_files)


############################################################
# CONFIG STUFF
############################################################

config_path = os.path.join(os.path.dirname(sys.argv[0]), 'config.json')

base_config = {
    'unionfs_folder': '/mnt/local/.unionfs-fuse',  # .unionfs location inside unionfs read/write folder
    'remote_folder': 'google:',  # rclone remote
    'cloud_folder': '/mnt/plexdrive',  # mount location of read/write folder
    'local_folder': '/mnt/local/Media',  # local folder to upload when size reaches local_folder_size
    'local_remote': 'google:/Media',  # remote folder location of local_folder
    'local_folder_size': 250,  # max size of local_folder in gigabytes before moving content
    'local_folder_check_interval': 60,  # minutes to check size of local_folder
    'du_excludes': [
        # folders to be excluded for the du -s --block-side=1G "local_folder" e.g "downloads"
    ],
    'lsof_excludes': [
        # folders to be excluded from the lsof +D command, if path contains it, ignore it, e.g. "/downloads/"
        ".partial~"
    ],
    'rclone_transfers': 8,  # number of transfers to use with rclone move (--transfers=8)
    'rclone_checkers': 16,  # number of checkers to use with rclone move (--checkers=16)
    'rclone_remove_empty_on_upload': {
        # folders to be emptied of empty dirs with customizable mindepth,
        # e.g. find "/mnt/local/Media/Movies" -mindepth 1 -type d -empty -delete
        '/mnt/local/Media/Movies': 1,
        '/mnt/local/Media/TV': 1
    },
    'rclone_excludes': [
        # exclusions for the rclone move "local_folder" "local_remote"
        '**partial~',
        '**_HIDDEN',
        '.unionfs/**',
        '.unionfs-fuse/**',
    ],
    'rclone_chunk_size': '8M',  # rclone chunk size, must be a multiple of 2
    'rclone_bwlimit': '',  # rclone bandwidth limit
    'pushover_user_token': '',  # your pushover user token - upload notifications are sent here
    'pushover_app_token': '',  # your pushover user token - upload notifications are sent here
    'use_config_manager': False,  # whether or not to start the config manager, restart script on config change
    'use_upload_manager': False,  # whether or not to start the upload manager upon script start
    'use_git_autoupdater': False,  # whether to automatically update (git pull) when theres a new commit on script start
    'dry_run': True,  # whether or not to use dry-run with rclone so no files are deleted/moved. use to verify working.
}


def config_load():
    config = None

    with open(config_path, 'r') as fp:
        config = upgrade_config(json.load(fp))
        fp.close()
    logger.debug("Loaded config.json: %r", config_path)
    return config


def upgrade_config(config):
    new_config = {}
    added_fields = 0
    fields = []

    for name, data in base_config.items():
        if name not in config:
            new_config[name] = data
            fields.append(name)
            added_fields += 1
        else:
            new_config[name] = config[name]

    with open(config_path, 'w') as fp:
        json.dump(new_config, fp, indent=4, sort_keys=True)
        fp.close()

    if added_fields and len(fields):
        logger.debug("Upgraded config.json, added %d new field(s): %r", added_fields, fields)
    return new_config


def build_config():
    with open(config_path, 'w') as fp:
        json.dump(base_config, fp, indent=4, sort_keys=True)
        fp.close()
        logger.debug(
            'Created default config.json, please configure it and run "./cleaner.py test" to check your config')
        exit(0)


def config_test(config):
    # test parse .unionfs folder
    logger.debug("Testing unionfs_folder, cloud_folder and remote_folder")
    tested_hidden = False
    for path, subdirs, files in os.walk(config['unionfs_folder']):
        for name in files:
            file = os.path.join(path, name)
            if file and file.endswith('_HIDDEN~'):
                logger.debug("Hidden file detected: %r", file)
                cloud_path = file.replace(config['unionfs_folder'], config['cloud_folder']).rstrip('_HIDDEN~')
                remote_path = file.replace(config['unionfs_folder'], config['remote_folder']).rstrip('_HIDDEN~')
                logger.debug('Check exists on cloud_folder: %r', cloud_path)
                if os.path.exists(cloud_path):
                    tested_hidden = True
                    logger.debug('Exists! I would have ran when this file was created:\nrclone delete %r', remote_path)
    if not tested_hidden:
        logger.debug("Did not find a _HIDDEN~ file on your cloud_folder, please upgrade a file then check me again!")

    # show example rclone move that would have been used
    size = folder_size(config['local_folder'], config['du_excludes'])
    logger.debug("Local folder size is %d gigabytes", size)
    logger.debug("Testing local_folder, local_remote, rclone_transfers, rclone_checkers, rclone_excludes and dry_run")
    upload_cmd = rclone_move_command(config['local_folder'], config['local_remote'], config['rclone_transfers'],
                                     config['rclone_checkers'], config['rclone_bwlimit'], config['rclone_excludes'],
                                     config['rclone_chunk_size'], config['dry_run'])
    logger.debug("Rclone move command, I would have ran:\n%r", upload_cmd)

    # show example of folders that would have been removed after upload
    logger.debug("I would have removed the following folders after the rclone move:")
    remove_empty_directories(config, True)

    exit(0)
