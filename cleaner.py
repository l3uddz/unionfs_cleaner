#!/usr/bin/env python3.5
import json
import logging
import os
import time
import timeit
from logging.handlers import RotatingFileHandler
from multiprocessing import Process

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

import utils

############################################################
# INIT
############################################################

# Setup logging
logFormatter = logging.Formatter('%(asctime)24s - %(name)-8s - %(funcName)12s() :: %(message)s')
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

observer = None

# Config
config = None
if os.path.exists('config.json'):
    config = utils.config_load()
else:
    config = utils.build_config()
    exit(0)

logger.debug("Using config:\n%s", json.dumps(config, sort_keys=True, indent=4))


# file monitor events
class FileEventHandler(PatternMatchingEventHandler):
    def on_created(self, event):
        super(FileEventHandler, self).on_created(event)
        if event.src_path.endswith('_HIDDEN~'):
            logger.info("File %r was created" % event.src_path)
            cloud_path = event.src_path.replace(config['unionfs_folder'], config['cloud_folder']).rstrip('_HIDDEN~')
            remote_path = event.src_path.replace(config['unionfs_folder'], config['remote_folder']).rstrip('_HIDDEN~')
            if os.path.exists(cloud_path):
                logger.debug("Removing %r" % remote_path)
                if utils.rclone_delete(remote_path, config['dry_run']):
                    logger.debug("Deleted %r", remote_path)
                else:
                    logger.debug("Failed to delete %r", remote_path)
            else:
                logger.debug("File was ignored, does not exist at %r", cloud_path)


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

                    # send start notification
                    if config['pushover_app_token'] and config['pushover_user_token']:
                        utils.send_pushover(config['pushover_app_token'], config['pushover_user_token'],
                                            "Upload process started. %d gigabytes to upload" % size)

                    # rclone move local_folder to local_remote
                    logger.debug("Moving data from %r to %r...", config['local_folder'], config['local_remote'])
                    upload_cmd = utils.rclone_move_command(config['local_folder'], config['local_remote'],
                                                           config['rclone_transfers'], config['rclone_checkers'],
                                                           config['rclone_excludes'], config['dry_run'])
                    logger.debug("Using: %r", upload_cmd)

                    start_time = timeit.default_timer()
                    utils.run_command(upload_cmd)
                    time_taken = timeit.default_timer() - start_time
                    logger.debug("Moving finished in %d seconds", time_taken)

                    # rclone rmdirs specified directories
                    if len(config['rclone_rmdirs']):
                        clearing = False
                        for dir in config['rclone_rmdirs']:
                            if os.path.exists(dir):
                                clearing = True
                                logger.debug("Removing empty directories from %r", dir)
                                cmd = 'rclone rmdirs "%s"' % dir
                                if config['dry_run']:
                                    cmd += ' --dry-run'
                                utils.run_command(cmd)
                        if clearing:
                            logger.debug("Finished clearing empty directories")

                    new_size = utils.folder_size(config['local_folder'], config['du_excludes'])
                    logger.debug("Local folder is now left with %d gigabytes", new_size)

                    # send finish notification
                    if config['pushover_app_token'] and config['pushover_user_token']:
                        utils.send_pushover(config['pushover_app_token'], config['pushover_user_token'],
                                            "Upload process finished in %d seconds. %d gigabytes left over." %
                                            (time_taken, new_size))

                else:
                    logger.debug("Local folder is still under the max size by %d gigabytes",
                                 config['local_folder_size'] - size)

    except Exception as ex:
        logger.exception("Exception occurred: ")


def start(path):
    global observer
    # start folder monitor for file changes
    if observer is None and os.path.exists(path):
        # start hidden file monitor
        event_handler = FileEventHandler()
        observer = Observer()
        observer.schedule(event_handler, path=path, recursive=True)
        observer.start()
        logger.info("Started file monitor for %r", path)

        # start upload manager
        if config['use_upload_manager']:
            upload_process = Process(target=upload_manager)
            upload_process.start()

        # join and wait finish
        observer.join()
        if config['use_upload_manager']:
            upload_process.join()
        logger.debug("Finished monitoring and uploading")

    else:
        logger.debug("File monitor already started, or %r is not a valid path.", path)


def stop():
    global observer

    if observer is not None:
        observer.stop()
        logger.info("Stopped file monitor")
        observer = None
    else:
        logger.debug("File monitor is not running...")


if __name__ == "__main__":
    start(config['unionfs_folder'])
