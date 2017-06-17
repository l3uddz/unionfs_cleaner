import logging

import git

logger = logging.getLogger("GIT")
logger.setLevel(logging.DEBUG)

############################################################
# UPDATER STUFF
############################################################

repo = git.Repo.init()


def active_branch():
    global repo

    try:
        branch = repo.active_branch.name
        return branch

    except Exception as ex:
        logger.exception("Exception retrieving current branch")

    return 'Unknown'


def latest_version():
    global repo

    try:
        fetch_info = repo.remotes.origin.fetch()
        return fetch_info[0].commit

    except Exception as ex:
        logger.exception("Exception while checking for the latest version commit id")

    return 'Unknown'


def current_version():
    global repo

    try:
        result = repo.active_branch.commit
        return result

    except Exception as ex:
        logger.exception("Exception while retrieving current version commit id")

    return 'Unknown'


def update():
    global repo

    current = current_version()
    latest = latest_version()

    if current == 'Unknown' or latest == 'Unknown':
        logger.debug("Aborting update because could not determine current / latest version")
        return False

    if current != latest:
        logger.info("Updating to the latest version")

        try:
            pull_info = repo.remotes.origin.pull()

            if pull_info[0].commit == latest:
                logger.info("Successfully updated to version: %s", latest)
                return True

        except Exception as ex:
            logger.exception("Exception while pulling the latest version from git, branch: %s - commit: %s",
                             active_branch(), latest)

    else:
        logger.info("Already using the latest version!")

    return False
