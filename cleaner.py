#!/usr/bin/env python3.5
import json
import logging
import os
import signal
import sys
import time
import timeit
from logging.handlers import RotatingFileHandler
from multiprocessing import Process

import updater
import utils

############################################################
# INIT
############################################################

# Setup logging
logFormatter = logging.Formatter('%(asctime)24s - %(name)-8s - %(funcName)25s() :: %(message)s')
rootLogger = logging.getLogger()

consoleHandler = logging.StreamHandler()
consoleHandler.setLevel(logging.DEBUG)
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)

fileHandler = RotatingFileHandler('activity.log', maxBytes=1024 * 1024 * 5, backupCount=5)
fileHandler.setLevel(logging.DEBUG)
fileHandler.setFormatter(logFormatter)
rootLogger.addHandler(fileHandler)

logger = rootLogger.getChild("CLEANER")
logger.setLevel(logging.DEBUG)

# Config
config_path = os.path.join(os.path.dirname(sys.argv[0]), 'config.json')
config = None
if os.path.exists(config_path):
    config = utils.config_load()
else:
    config = utils.build_config()
    exit(0)

logger.debug("Using config:\n%s", json.dumps(config, sort_keys=True, indent=4))


############################################################
# HIDDEN REMOVER
############################################################

def remove_hidden():
    hidden = 0
    deleted = 0
    logger.debug("Checking %r", config['unionfs_folder'])
    for path, subdirs, files in os.walk(config['unionfs_folder']):
        for name in files:
            file = os.path.join(path, name)
            if file and file.endswith('_HIDDEN~'):
                hidden += 1
                logger.debug("Hidden file found: %r", file)
                cloud_path = file.replace(config['unionfs_folder'], config['cloud_folder']).rstrip('_HIDDEN~')
                remote_path = file.replace(config['unionfs_folder'], config['remote_folder']).rstrip('_HIDDEN~')
                if os.path.exists(cloud_path):
                    logger.debug("Removing %r", remote_path)
                    if utils.rclone_delete(remote_path, config['dry_run']):
                        deleted += 1
                        logger.debug("Deleted %r", remote_path)
                        if not config['dry_run']:
                            try:
                                os.remove(file)
                            except Exception as ex:
                                logger.exception("Exception removing _HIDDEN~ file %s: ", file)
                    else:
                        logger.debug("Failed to delete %r", remote_path)
                else:
                    logger.debug("File does not exist on remote, removing %r", file)
                    if not config['dry_run']:
                        os.remove(file)

    logger.debug("Found %d hidden file(s), deleted %d file(s) off remote", hidden, deleted)


############################################################
# UPLOAD MANAGER
############################################################

def upload_manager():
    try:
        logger.debug("Started upload manager for %r", config['local_folder'])
        while True:
            time.sleep(60 * config['local_folder_check_interval'])
            logger.debug("Checking size of %r", config['local_folder'])
            size = utils.folder_size(config['local_folder'], config['du_excludes'])
            if size is not None and size > 0:
                if size >= config['local_folder_size']:
                    logger.debug("Local folder has %d gigabytes, %d too many!",
                                 size, size - config['local_folder_size'])

                    # check if files are opened, skip this upload if so
                    opened_files = utils.opened_files(config['local_folder'], config['lsof_excludes'])
                    if opened_files:
                        for item in opened_files:
                            logger.debug("File is being accessed: %r", item)
                        logger.debug("Local folder has %d file(s) open, skipping upload until next check...",
                                     len(opened_files))
                        # send skip notification
                        if config['pushover_app_token'] and config['pushover_user_token']:
                            utils.send_pushover(config['pushover_app_token'], config['pushover_user_token'],
                                                "Upload process of %d gigabytes temporarily skipped.\n"
                                                "%d file(s) are currently being accessed." %
                                                (size, len(opened_files)))
                        continue

                    # remove hidden before upload
                    # (we don't want to delete a hidden from remote, after already replacing it)
                    logger.debug("Purging _HIDDEN~ before upload commences")
                    remove_hidden()

                    # send start notification
                    if config['pushover_app_token'] and config['pushover_user_token']:
                        utils.send_pushover(config['pushover_app_token'], config['pushover_user_token'],
                                            "Upload process started. %d gigabytes to upload." % size)

                    # rclone move local_folder to local_remote
                    logger.debug("Moving data from %r to %r...", config['local_folder'], config['local_remote'])
                    upload_cmd = utils.rclone_move_command(config['local_folder'], config['local_remote'],
                                                           config['rclone_transfers'], config['rclone_checkers'],
                                                           config['rclone_bwlimit'], config['rclone_excludes'],
                                                           config['dry_run'])
                    logger.debug("Using: %r", upload_cmd)

                    start_time = timeit.default_timer()
                    utils.run_command(upload_cmd)
                    time_taken = timeit.default_timer() - start_time
                    logger.debug("Moving finished in %s", utils.seconds_to_string(time_taken))

                    # remove empty directories
                    if len(config['rclone_remove_empty_on_upload']):
                        time.sleep(5)
                        utils.remove_empty_directories(config)

                    new_size = utils.folder_size(config['local_folder'], config['du_excludes'])
                    logger.debug("Local folder is now left with %d gigabytes", new_size)

                    # send finish notification
                    if config['pushover_app_token'] and config['pushover_user_token']:
                        utils.send_pushover(config['pushover_app_token'], config['pushover_user_token'],
                                            "Upload process finished in %s. %d gigabytes left over." %
                                            (utils.seconds_to_string(time_taken), new_size))

                else:
                    logger.debug("Local folder is still under the max size by %d gigabytes",
                                 config['local_folder_size'] - size)

    except Exception as ex:
        logger.exception("Exception occurred: ")

############################################################
# CONFIG MONITOR
############################################################

def config_monitor():
    old_config = utils.read_file_text('config.json')
    if not len(old_config):
        logger.error("Could not read config.json file... not starting config monitor")
        return

    try:
        mod_time = os.path.getmtime('config.json')
        logger.debug("Started config monitor for config.json")
        while True:
            time.sleep(60)
            if os.path.getmtime('config.json') != mod_time:
                logger.debug("config.json was modified, restarting in 3 seconds...")
                time.sleep(3)
                os.kill(os.getppid(), signal.SIGHUP)

    except Exception as ex:
        logger.exception("Exception occurred: ")


############################################################
# PROCESS STUFF
############################################################
processes = []


def start(path):
    # start folder monitor for file changes
    if os.path.exists(path):
        # start upload manager
        upload_process = None
        if config['use_upload_manager']:
            upload_process = Process(target=upload_manager)
            upload_process.start()
            processes.append(upload_process.pid)

        # start config manager
        config_process = None
        if config['use_config_manager']:
            config_process = Process(target=config_monitor)
            config_process.start()
            processes.append(config_process.pid)

        # join and wait finish
        if config['use_upload_manager'] and upload_process is not None:
            upload_process.join()
        if config['use_config_manager'] and config_process is not None:
            config_process.join()

        logger.debug("Finished!")

    else:
        logger.debug("Cannot start file monitor, %r is not a valid path.", path)


def exit_gracefully(signum, frame):
    logger.debug("Shutting down process %r", os.getpid())
    sys.exit(0)


def exit_restart(signum, frame):
    for pid in processes:
        if pid == os.getpid():
            continue
        os.kill(pid, signal.SIGTERM)
    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv):
        for item in sys.argv:
            if item == 'test':
                utils.config_test(config)
                exit(0)
            if item == 'rmdirs':
                utils.remove_empty_directories(config)
                exit(0)
            if item == 'rmhidden':
                remove_hidden()
                exit(0)

    logger.debug("Current branch: %s", updater.active_branch())
    logger.debug("Current version: %s", updater.current_version())
    logger.debug("Latest version: %s", updater.latest_version())
    if config['use_git_autoupdater'] and updater.update():
        logger.debug("Restarting...")
        sys.exit(1)

    signal.signal(signal.SIGINT, exit_gracefully)
    signal.signal(signal.SIGTERM, exit_gracefully)
    signal.signal(signal.SIGHUP, exit_restart)
    start(config['unionfs_folder'])
