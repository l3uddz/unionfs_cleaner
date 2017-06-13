# unionfs_cleaner
Monitor for .HIDDEN file creations, upon detection, check if the hidden file exists on your mount, if it does, run an rclone delete "path" to remove from your cloud drive

## Requirements
1. Python 3.5.2 or higher
2. requirements.txt modules

## Setup
Look at the example output below:
1. cleaner.py[8040]: File '/home/seed/media/local/.unionfs/Media/Software/Ubuntu/Ubuntu 16.iso_HIDDEN~' was created
2. cleaner.py[8040]: Removing 'google:/Media/Software/Ubuntu/Ubuntu 16.iso'
3. cleaner.py[8040]: Deleted 'google:/Media/Software/Ubuntu/Ubuntu 16.iso'

Inside cleaner.py is 3 variables: 
1. unionfs_folder (example: `/home/seed/media/local/.unionfs`)
2. remote_folder (example: `google:`)
3. cloud_folder (example: `/home/seed/media/gcd`)

unionfs_folder is the .unionfs folder that is created inside your read/write folder. This is where unionfs creates the .HIDDEN files when a file is deleted.

cloud_folder is your read only folder used in your unionfs mount.

remote_folder is your rclone remote.

Change these to your setup. 

