#!/usr/bin/env python3.5
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

# Config
unionfs_folder = "/home/seed/media/local/.unionfs"  # .unionfs location inside unionfs read/write folder
remote_folder = "google:"  # rclone remote
cloud_folder = "/home/seed/media/gcd"  # mount location of read/write folder
local_folder = "/home/seed/media/local/Media"  # local folder to upload
local_remote = "google:/Media"  # remote folder location of local_folder
local_folder_size = 250  # max size of local_folder in gigabytes before moving content
local_folder_check_interval = 60  # minutes to check size of local_folder
du_excludes = [
    # folders to be excluded for the du -s --block-side=1G "local_folder" e.g "downloads"
]
lsof_excludes = [
    # folders to be excluded from the lsof command, if path contains it, ignore it, e.g. "/downloads/"
]
rclone_transfers = 8  # number of transfers to use with rclone move (--transfers=8)
rclone_checkers = 16  # number of checkers to use with rclone move (--checkers=16)
rclone_rmdirs = [
    # folders to clear with rclone rmdirs after upload
    # remember this folder can be removed too, so always go one step deeper than local_folder
    '/home/seed/media/local/Media/Movies',
    '/home/seed/media/local/Media/TV'
]
rclone_excludes = [
    # exclusions for the rclone move "local_folder" "local_remote"
    '**partial~',
    '**_HIDDEN',
    '.unionfs/**',
    '.unionfs-fuse/**',
]
pushover_user_token = None  # your pushover user token - upload notifications are sent here
pushover_app_token = None  # your pushover app token - required to send notifications

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


# file monitor events
class FileEventHandler(PatternMatchingEventHandler):
    def on_created(self, event):
        super(FileEventHandler, self).on_created(event)
        if event.src_path.endswith('_HIDDEN~'):
            logger.info("File %r was created" % event.src_path)
            cloud_path = event.src_path.replace(unionfs_folder, cloud_folder).rstrip('_HIDDEN~')
            remote_path = event.src_path.replace(unionfs_folder, remote_folder).rstrip('_HIDDEN~')
            if os.path.exists(cloud_path):
                logger.debug("Removing %r" % remote_path)
                if utils.rclone_delete(remote_path):
                    logger.debug("Deleted %r", remote_path)
                else:
                    logger.debug("Failed to delete %r", remote_path)
            else:
                logger.debug("File was ignored, does not exist at %r", cloud_path)


def upload_manager():
    try:
        logger.debug("Started upload manager for %r", local_folder)
        while True:
            time.sleep(60 * local_folder_check_interval)
            logger.debug("Checking size of %r", local_folder)
            size = utils.folder_size(local_folder, du_excludes)
            if size is not None and size > 0:
                if size >= local_folder_size:
                    logger.debug("Local folder has %d gigabytes, %d too many!",
                                 size, size - local_folder_size)

                    # check if files are opened, skip this upload if so
                    opened_files = utils.opened_files(local_folder, lsof_excludes)
                    if opened_files:
                        for item in opened_files:
                            logger.debug("File is being accessed: %r", item)
                        logger.debug("Local folder has %d file(s) open, skipping upload until next check...",
                                     len(opened_files))
                        # send skip notification
                        if pushover_app_token and pushover_user_token:
                            utils.send_pushover(pushover_app_token, pushover_user_token,
                                                "Upload process of %d gigabytes temporarily skipped.\n"
                                                "%d file(s) are currently being accessed." %
                                                (size, len(opened_files)))
                        continue

                    # send start notification
                    if pushover_app_token and pushover_user_token:
                        utils.send_pushover(pushover_app_token, pushover_user_token,
                                            "Upload process started. %d gigabytes to upload" % size)

                    # rclone move local_folder to local_remote
                    logger.debug("Moving data from %r to %r...", local_folder, local_remote)
                    upload_cmd = utils.rclone_move_command(local_folder, local_remote, rclone_transfers,
                                                           rclone_checkers, rclone_excludes)
                    logger.debug("Using: %r", upload_cmd)

                    start_time = timeit.default_timer()
                    utils.run_command(upload_cmd)
                    time_taken = timeit.default_timer() - start_time
                    logger.debug("Moving finished in %d seconds", time_taken)

                    # rclone rmdirs specified directories
                    if len(rclone_rmdirs):
                        clearing = False
                        for dir in rclone_rmdirs:
                            if os.path.exists(dir):
                                clearing = True
                                logger.debug("Removing empty directories from %r", dir)
                                utils.run_command('rclone rmdirs "%s"' % dir)
                        if clearing:
                            logger.debug("Finished clearing empty directories")

                    new_size = utils.folder_size(local_folder, du_excludes)
                    logger.debug("Local folder is now left with %d gigabytes", new_size)

                    # send finish notification
                    if pushover_app_token and pushover_user_token:
                        utils.send_pushover(pushover_app_token, pushover_user_token,
                                            "Upload process finished in %d seconds. %d gigabytes left over." %
                                            (time_taken, new_size))

                else:
                    logger.debug("Local folder is still under the max size by %d gigabytes",
                                 local_folder_size - size)

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
        upload_process = Process(target=upload_manager)
        upload_process.start()

        # join and wait finish
        observer.join()
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
    start(unionfs_folder)
