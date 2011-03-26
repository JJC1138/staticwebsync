import argparse
import os
import sys

import boto

import core

def print_log(message):
    print message

core.log = print_log

DEFAULT_LOCATION = 'US'

if len(sys.argv) == 1:
    sys.argv.append('-h')

arg_parser = argparse.ArgumentParser(
    description="%(prog)s is a command-line tool for automating the fiddly aspects of hosting your static web site on Amazon S3 or CloudFront. It automates the process of configuring the services for hosting web sites, and synchronizes the contents of a local folder to the site. WARNING: The sync is a one-way sync so if you have an S3 bucket with the host name of the site already then any files it contains that do not have a corresponding local file will be DELETED from the bucket (if that doesn't mean anything to you and you've not used S3 before then you don't need to worry about it).")

def help_text_with_default(text, default=None):
    return '%s [default: %s]' % (text, default if default is not None else '%(default)s')

AWS_ACCESS_KEY_ENV = 'AWS_ACCESS_KEY_ID'
arg_parser.add_argument('--access-key-id',
    required=not AWS_ACCESS_KEY_ENV in os.environ,
    help=help_text_with_default("Your Amazon Web Services access key ID", "the contents of the %s environment variable if it exists" % AWS_ACCESS_KEY_ENV))

AWS_SECRET_ACCESS_KEY_ENV = 'AWS_SECRET_ACCESS_KEY'
arg_parser.add_argument('--secret-access-key',
    required=not AWS_SECRET_ACCESS_KEY_ENV in os.environ,
    help=help_text_with_default("Your Amazon Web Services secret access key", "the contents of the %s environment variable if it exists" % AWS_SECRET_ACCESS_KEY_ENV))

arg_parser.add_argument('--index', default='index.html',
    help=help_text_with_default("The name of the default file that should be used for the root of the web-site and for requests that correspond to folder names without a filename"))

arg_parser.add_argument('--error-page', default='4xx.html',
    help=help_text_with_default("The name of a file that should be sent for missing files (404 errors) or any other HTTP errors with 4xx codes"))

arg_parser.add_argument('--repair', action='store_true',
    help="Do extra checks that take additional time and that shouldn't be needed under normal circumstances. This option might be helpful if things aren't working right or if you have used another tool to manage the bucket in the past. Currently it checks that the security policy (ACL) for every existing file is correct.")

arg_parser.add_argument('--allow-dot-files', action='store_true',
    help="Normally %(prog)s skips files and folders that start with a '.' because those are often used by tools like version control systems for internal data. Use this option to force such files to be uploaded to the web site.")

arg_parser.add_argument('--bucket-location', choices = (
    DEFAULT_LOCATION,
    boto.s3.connection.Location.USWest,
    boto.s3.connection.Location.EU,
    'ap-southeast-1'),
    default='US',
    help=help_text_with_default("The location that will be used for any new S3 buckets created. This doesn't have any effect if the bucket for the web site already exists, but in a future version this might give an error if it doesn't match the location of the existing bucket."))

arg_parser.add_argument('--no-cloudfront', action='store_true',
    help="Use this option if you just want your site hosted on S3 and do not want to use CloudFront as well. See the %(prog)s web site for advice about why you might want to do that.")

arg_parser.add_argument('--dont-wait-for-cloudfront-propagation', action='store_true',
    help="When you change or delete files hosted on CloudFront it takes up to 15 minutes to propagate that change across all CloudFront servers. Normally %(prog)s waits for that to finish before completing so that you know that when it is complete your site is up-to-date, but if you use this option then the program will not wait and just return immediately after it has finished syncing your files.")

arg_parser.add_argument('host_name',
    help="The host name for the site")

arg_parser.add_argument('folder',
    help="The folder containing the files to be uploaded to the web site")

args = arg_parser.parse_args()

if args.bucket_location == DEFAULT_LOCATION:
    args.bucket_location = ''

try:
    core.setup(args)
except core.BadUserError, e:
    print >>sys.stderr, e.message
    sys.exit(1)
