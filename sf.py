import argparse
import sys

import boto

from core import setup

BAD_USER_EXIT = 1
FORCE_EXISTING_OPTION = '--delete-existing-bucket'
DEFAULT_LOCATION = 'US'

arg_parser = argparse.ArgumentParser(
    description='Set up S3 and CloudFront for SyncFront.')

arg_parser.add_argument('--access-key-id', required=True)
arg_parser.add_argument('--secret-access-key', required=True)
arg_parser.add_argument('--index', default='index.html')
arg_parser.add_argument('--bucket-location', choices = (
    DEFAULT_LOCATION,
    boto.s3.connection.Location.USWest,
    boto.s3.connection.Location.EU,
    'ap-southeast-1'),
    default='US')
arg_parser.add_argument('host_name')
arg_parser.add_argument(FORCE_EXISTING_OPTION, action='store_true')

args = arg_parser.parse_args()

if args.bucket_location == DEFAULT_LOCATION:
    args.bucket_location = ''

setup(args)
