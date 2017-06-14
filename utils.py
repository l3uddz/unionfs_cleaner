import logging
import os
import shlex
import subprocess

logger = logging.getLogger("UTILS")
logger.setLevel(logging.DEBUG)


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


def folder_size(path):
    try:
        process = os.popen('du -s --block-size=1G %s | cut -f1' % path)
        data = process.read()
        process.close()
        if data is not None and int(data) > 0:
            return int(data)

    except Exception as ex:
        logger.error("Exception calculating size of %r:\n%s", path, ex)
        return None


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
