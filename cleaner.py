#!/usr/bin/env python3.5
import logging
import os
from logging.handlers import RotatingFileHandler

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

############################################################
# INIT
############################################################

# Config
unionfs_folder = "/home/seed/media/local/.unionfs"
remote_folder = "google:"
cloud_folder = "/home/seed/media/gcd"

# Setup logging
logFormatter = logging.Formatter('%(asctime)24s - %(name)-12s - %(funcName)20s() :: %(message)s')
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
                if rclone_delete(remote_path):
                    logger.debug("Deleted %r", remote_path)
                else:
                    logger.debug("Failed to delete %r", remote_path)
            else:
                logger.debug("File was ignored, it was not found at %r", cloud_path)


def rclone_delete(path):
    try:
        process = os.popen('rclone delete "%s"' % path)
        data = process.read()
        process.close()
        if 'Failed to delete' in data:
            return False
        else:
            return True
    except Exception as ex:
        logger.error("Exception deleting %r:\n%s", path, ex)
        return False


def start(local_folder):
    global observer
    # start folder monitor for file changes
    if observer is None and os.path.exists(local_folder):
        event_handler = FileEventHandler()
        observer = Observer()
        observer.schedule(event_handler, path=local_folder, recursive=True)
        observer.start()
        logger.info("Started file monitor for: %s", local_folder)
        observer.join()
    else:
        logger.debug("File monitor already started, or %s is not a valid path.", local_folder)


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
