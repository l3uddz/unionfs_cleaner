import http.client
import json
import logging
import os
import shlex
import subprocess
from urllib import parse

logger = logging.getLogger("UTILS")
logger.setLevel(logging.DEBUG)


############################################################
# SCRIPT STUFF
############################################################

def get_num(x):
    return int(''.join(ele for ele in x if ele.isdigit() or ele == '.'))


def run_command(command):
    process = subprocess.Popen(shlex.split(command), shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    while True:
        output = str(process.stdout.readline())
        if process.poll() is not None:
            break
        if output and len(output) > 6:
            logger.info(str(output).lstrip('b').replace('\\n', ''))

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
        cmd = 'rclone delete "%s"' % path
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
        process = os.popen('lsof -Fn +D "%s" | tail -n +2 | cut -c2-' % path)
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


def rclone_move_command(local, remote, transfers, checkers, excludes, dry_run):
    upload_cmd = 'rclone move "%s" "%s"' \
                 ' --delete-after' \
                 ' --no-traverse' \
                 ' --stats=60s' \
                 ' -v' \
                 ' --transfers=%d' \
                 ' --checkers=%d' % \
                 (local, remote, transfers, checkers)
    for item in excludes:
        upload_cmd += ' --exclude="%s"' % item
    if dry_run:
        upload_cmd += ' --dry-run'
    return upload_cmd


def du_size_command(path, excludes):
    size_cmd = "du -s --block-size=1G"
    for item in excludes:
        size_cmd += ' --exclude="%s"' % item
    size_cmd += ' "%s" | cut -f1' % path
    return size_cmd


############################################################
# CONFIG STUFF
############################################################

base_config = {
    'unionfs_folder': '/home/seed/media/local/.unionfs',  # .unionfs location inside unionfs read/write folder
    'remote_folder': 'google:',  # rclone remote
    'cloud_folder': '/home/seed/media/gcd',  # mount location of read/write folder
    'local_folder': '/home/seed/media/local/Media',  # local folder to upload
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
    'rclone_rmdirs': [
        # folders to clear with rclone rmdirs after upload
        # remember this folder can be removed too, so always go one step deeper than local_folder
        '/home/seed/media/local/Media/Movies',
        '/home/seed/media/local/Media/TV'
    ],
    'rclone_excludes': [
        # exclusions for the rclone move "local_folder" "local_remote"
        '**partial~',
        '**_HIDDEN',
        '.unionfs/**',
        '.unionfs-fuse/**',
    ],
    'pushover_user_token': '',  # your pushover user token - upload notifications are sent here
    'pushover_app_token': '',  # your pushover user token - upload notifications are sent here
    'use_upload_manager': False,  # whether or not to start the upload manager upon script start
    'use_git_autoupdater': False,  # whether to automatically update (git pull) when theres a new commit on script start
    'dry_run': True,  # whether or not to use dry-run with rclone so no files are deleted/moved. use to verify working.
}


def config_load():
    config = None

    with open('config.json', 'r') as fp:
        config = upgrade_config(json.load(fp))
        fp.close()
    logger.debug("Loaded config.json")
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

    with open('config.json', 'w') as fp:
        json.dump(new_config, fp, indent=4, sort_keys=True)
        fp.close()

    if added_fields and len(fields):
        logger.debug("Upgraded config.json, added %d new field(s): %r", added_fields, fields)
    return new_config


def build_config():
    with open('config.json', 'w') as fp:
        json.dump(base_config, fp, indent=4, sort_keys=True)
        fp.close()
        logger.debug("Created default config.json, please configure it before running me again.")
        exit(0)
