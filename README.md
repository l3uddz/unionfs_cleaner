# unionfs_cleaner
Perform scan of .unionfs folder for _HIDDEN~ files, if file exists on remote, delete it and the _HIDDEN~ file.
Perform automated rclone moves on your local media when X gigabytes has been reached and no files are currently being accessed.
Perform automated rsync backups on specified folders after X hours.

## Requirements
1. Python 3.5.2 or higher
2. requirements.txt modules

# Installation on Ubuntu/Debian
## Python 3.5.2

1. `wget https://www.python.org/ftp/python/3.5.2/Python-3.5.2.tar.xz`
2. `tar xvf Python-3.5.2.tar.xz`
3. `cd Python-3.5.2`
4. `sudo apt-get install make git build-essential libssl-dev zlib1g-dev libbz2-dev libsqlite3-dev`
5. `sudo ./configure --enable-loadable-sqlite-extensions && sudo make && sudo make install`

## unionfs_cleaner

1. `cd /opt`
2. `sudo apt-get install lsof`
3. `sudo git clone https://github.com/l3uddz/unionfs_cleaner`
4. `sudo chown -R user:user unionfs_cleaner`
5. `cd unionfs_cleaner`
6. `sudo pip3.5 install -r requirements.txt`
7. `python3.5 cleaner.py`

You should now have unionfs_cleaner installed, and by running it for the first time, it will generate a default config.json configuration and exit for you to adjust your config.

# Setup

Example configuration:
```json
{
    "cloud_folder": "/mnt/plexdrive",
    "dry_run": false,
    "du_excludes": [],
    "local_folder": "/mnt/local/Media",
    "local_folder_check_interval": 2,
    "local_folder_size": 4,
    "local_remote": "google:/Media",
    "lsof_excludes": [
        ".partial~"
    ],
    "pushover_app_token": "",
    "pushover_user_token": "",
    "rclone_checkers": 16,
    "rclone_excludes": [
        "**partial~",
        "**_HIDDEN",
        ".unionfs/**",
        ".unionfs-fuse/**"
    ],
    "rclone_remove_empty_on_upload": {
        "/mnt/local/Media/Movies": 1,
        "/mnt/local/Media/TV": 1
    },
    "rclone_transfers": 8,
    "remote_folder": "google:",
    "rsync_backup_interval": 1,
    "rsync_backups": {
        "/home/seed": [
            "backup*"
        ]
    },
    "rsync_remote": "/home/seed/backup",
    "unionfs_folder": "/mnt/local/.unionfs-fuse",
    "use_backup_manager": false,
    "use_config_manager": true,
    "use_git_autoupdater": true,
    "use_upload_manager": true
}

```
## _HIDDEN~ cleaner

This feature is the core functionality of unionfs_cleaner, it cannot be disabled as it was designed for this purpose initially. When unionfs wants to delete a file that is on the read-only mount, it obviously cannot do this because it has no access. So what it does is it will create a _HIDDEN~ file inside your read-write mount in either .unionfs or .unionfs-fuse, this tells unionfs to hide that file from the merged folder. This typically happens when sonarr/radarr upgrades a file. We want these to be removed from the cloud so we dont have duplicates when we next perform an upload. Below are the key variables to be interested in when setting this up.

1. unionfs_folder (example: `/mnt/local/.unionfs-fuse`)
2. remote_folder (example: `google:`)
3. cloud_folder (example: `/mnt/plexdrive`)

unionfs_folder is the .unionfs/.unionfs-fuse folder that is created inside your read/write folder.

cloud_folder is your read only folder used in your unionfs mount.

remote_folder is your rclone remote.

Keeping this in mind, lets look at the example below:

1. cleaner.py[8040]: File '/mnt/local/.unionfs-fuse/Media/Software/Ubuntu/Ubuntu 16.iso_HIDDEN~' was created
2. cleaner.py[8040]: Removing 'google:/Media/Software/Ubuntu/Ubuntu 16.iso'
3. cleaner.py[8040]: Deleted 'google:/Media/Software/Ubuntu/Ubuntu 16.iso'

What's happened here, is cleaner.py has seen that a new _HIDDEN~ file was created in your unionfs_folder. So it will strip the _HIDDEN~ from the path, and replace unionfs_folder with remote_folder. The output is used as the rclone delete path as seen above.
The cloud_folder does exactly the same, with the exception that instead of performing a delete, it will check if the file exists, before performing the rclone delete. This is used to ensure that the file exists before doing the rclone delete.

**Note: Now using a directory scan method instead of detecting file creations, this seems more reliable. Left above text for illustration purposes of how the settings correlate to paths.**

## Uploader

This feature allows for you to specify a max size limit in GB of your local_folder. It will perform an rclone move, deleting the files as they have been uploaded. Below are the key variables to be interested with when setting this up.

1. local_folder (example: `/mnt/local/Media`)
2. local_remote (example: `google:/Media`)
3. local_folder_size (example: `150`)
4. local_folder_check_interval (example: `30`)
5. rclone_checkers (example: `16`)
6. rclone_transfers (example: `8`)
7. rclone_excludes
8. rclone_remove_empty_on_upload
9. du_excludes
10. lsof_excludes
11. use_upload_manager

local_folder is the source to be used for the rclone move command.

local_remote is the destination to be used for the rclone move command.

local_folder_size is the max size in gigabytes before the move process is initiated.

local_folder_check_interval is how often in minutes to check the size of local_folder.

rclone_checkers is the amount of checkers to use with the rclone move command.

rclone_transfers is the amount of transfers to use with the rlcone move command.

rclone_excludes are the excludes to be used with the rclone move command.

rclone_remove_empty_on_upload are the directories and mindepths to be cleaned after rclone move has completed. This will remove empty directories thus improving the next rclone move. Please remember, to always use directories within your local_folder. If you set this to local_folder then that folder could be removed if you set an incorrect mindepth. To check your mindepth, pls do `find 'FOLDER PATH' -mindepth 1 -type d -empty`. This will show you the folders that would have been deleted after the upload.

du_excludes are the excludes to be used with the du command that is used to determine the size of the local_folder. You may want to ignore a specific directory within local_folder when determing the size of local_folder.

lsof_excludes are the excludes to be used with the lsof command. For example we may want to ignore .partials being accessed and begin uploading anyway. This is always used so we dont begin an upload when a local file is being accessed/streamed.

use_upload_manager is used on script start to determine whether or not to start the upload manager.


Now keeping this in mind, you can look at the example configuration above then look at the rclone move command that would be used for that specific config:

`rclone move "/mnt/local/Media" "google:/Media" --delete-after --no-traverse --stats=60s -v --transfers=8 --checkers=16 --exclude="**partial~" --exclude="**_HIDDEN" --exclude=".unionfs/**" --exclude=".unionfs-fuse/**"`

So using the configuration above, below is what happens.
The script will check the size every 30 minutes of /mnt/local/Media. If the size is bigger or equal to 150 gigabytes, it would then check to see if any files are being accessed, if they are, it checks if each entry to lsof_excludes is contained within the path of the file being accessed. If it is, it will skip the upload until the next check, otherwise the rclone move would be executed.

## Backup

This feature allows for you to perform automated rsync backups on folders of your choosing. Below are the key variables to be interested with when setting this up.

rsync_backup_interval is how often in hours for the rsync backup to be performed.

rsync_backups is the list of locations and excludes for each location to be backed up.

rsync_remote is the destination for these backups.

use_backup_manager is used on script start to determine whether or not to start the backup manager.

Now keeping this in mind, you can look at the example configuration above then look at the rsync command that would have been executed:

`rsync -aAXvP --exclude="Downloads*" --exclude="torrents*" --exclude="plex*" --exclude="chunks*" --exclude="tmp*" --exclude="backup*" "/home/seed" "/home/seed/backup"`

It would perform this for each entry inside the rsync_backups list, adjusting the source location and excludes for each folder.

## General

The other config options are below:

pushover_app_token is used to send notifications on start/stop of the uploader & backup manager

pushover_user_token same as above. Both of these entries must be filled for push notifications, leave empty to disable notifications.

use_git_autoupdater is used on script start. if enabled, and there is a new git commit, it will update itself then restart.

use_config_manager is used to determine whehter or not to start the config manager. all this does is monitor your config file for changes, if they are detected, the script will restart itself. this check happens once per minute (file modified time).

dry_run is used to enable dry-run on the rclone move and rsync commands. I highly recommend keeping this flag true the first time you setup your config, this way you are at no risk of loosing data while still being able to verify your config is correct.



You can run cleaner.py passing the test flag which will perform some very basic checks / tests on your config and show output. e.g. python3.5 cleaner.py test
