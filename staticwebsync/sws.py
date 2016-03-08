#!/usr/bin/env python3

import argparse
import colorama
import sys
import time

import staticwebsync

def print_log(message):
    print(message)

class progress_reporter:

    def __init__(self):
        self.start_time = time.time()

    def __call__(self, done, doing):
        progress = float(done) / doing if doing != 0 else 1
        kbytesps = (done / (time.time() - self.start_time)) / 1024

        bar_width = 50
        bars = int(progress * bar_width)
        spaces = bar_width - bars

        print('\r' + \
            '[' + ('#' * bars) + (' ' * spaces) + ']' + \
            (' %d kB/s' % kbytesps), end='')

        if done == doing:
            print('\r' + (' ' * 80), end='\r')

def main():
    colorama.init()

    staticwebsync.log = print_log
    if sys.stdout.isatty():
        staticwebsync.progress_callback_factory = progress_reporter

    DEFAULT_LOCATION = 'us-east-1'

    if len(sys.argv) == 1:
        sys.argv.append('-h')

    arg_parser = argparse.ArgumentParser(
        description="%(prog)s is a command-line tool for automating the fiddly aspects of hosting your static web site on Amazon S3 or CloudFront. It automates the process of configuring the services for hosting web sites, and synchronizes the contents of a local folder to the site.")

    def help_text_with_default(text, default=None):
        return '%s [default: %s]' % (text, default if default is not None else '%(default)s')

    arg_parser.add_argument('--access-key-id', default=None,
        help=help_text_with_default("Your Amazon Web Services access key ID", "read from your ~/.aws/credentials file or the AWS_ACCESS_KEY_ID environment variable if they exist"))

    arg_parser.add_argument('--secret-access-key', default=None,
        help=help_text_with_default("Your Amazon Web Services secret access key", "read from your ~/.aws/credentials file or the AWS_SECRET_ACCESS_KEY environment variable if they exist"))

    arg_parser.add_argument('--index', default='index.html',
        help=help_text_with_default("The name of the default file that should be used for the root of the web-site and for requests that correspond to folder names without a filename"))

    arg_parser.add_argument('--error-page', default='4xx.html',
        help=help_text_with_default("The name of a file that should be sent for missing files (404 errors) or any other HTTP errors with 4xx codes"))

    arg_parser.add_argument('--repair', action='store_true',
        help="Do extra checks that take additional time and that shouldn't be needed under normal circumstances. This option might be helpful if things aren't working right or if you have used another tool to manage the bucket in the past. Currently it checks that the security policy (ACL) for every existing file is correct.")

    arg_parser.add_argument('--allow-dot-files', action='store_true',
        help="Normally %(prog)s skips files and folders that start with a '.' because those are often used by tools like version control systems for internal data. Use this option to force such files to be uploaded to the web site.")

    arg_parser.add_argument('--bucket-location', choices = (
        'US',
        DEFAULT_LOCATION,
        'us-west-1',
        'us-west-2',
        'eu-west-1',
        'eu-central-1',
        'ap-southeast-1'
        'ap-southeast-2',
        'ap-northeast-1',
        'ap-northeast-2',
        'sa-east-1'),
        default=DEFAULT_LOCATION,
        help=help_text_with_default("The location that will be used for any new S3 buckets created. This doesn't have any effect if the bucket for the web site already exists, but in a future version this might give an error if it doesn't match the location of the existing bucket."))

    arg_parser.add_argument('--no-cloudfront', action='store_true',
        help="Use this option if you just want your site hosted on S3 and do not want to use CloudFront as well. See the %(prog)s web site for advice about why you might want to do that.")

    arg_parser.add_argument('--dont-wait-for-cloudfront-propagation', action='store_true',
        help="When you change or delete files hosted on CloudFront it takes up to 15 minutes to propagate that change across all CloudFront servers. Normally %(prog)s waits for that to finish before completing so that you know that when it is complete your site is up-to-date, but if you use this option then the program will not wait and just return immediately after it has finished syncing your files.")

    arg_parser.add_argument('--take-over-existing-bucket', action='store_true',
        help="%(prog)s uses an S3 bucket with the same name as the host name for the site. If it finds such a bucket that it didn't create itself then it will normally refuse to sync. This is a safety precaution: %(prog)s does one-way syncing of files, so it deletes anything in the bucket that doesn't have a corresponding local file. If the bucket existed already then there might be files in it that you care about, so %(prog)s plays it safe and refuses to use such a bucket. If you use this option then %(prog)s will treat the bucket as if it created it, and will put a marker key in the bucket to signify that so this option only needs to be used on the first sync.")

    arg_parser.add_argument('host_name',
        help="The host name for the site")

    arg_parser.add_argument('folder',
        help="The folder containing the files to be uploaded to the web site")

    args = arg_parser.parse_args()

    if args.bucket_location == DEFAULT_LOCATION:
        args.bucket_location = ''

    try:
        staticwebsync.setup(args)
    except staticwebsync.BadUserError as e:
        print(e.message, file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
