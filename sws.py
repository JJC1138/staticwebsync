import argparse
import os
import sys

import boto

import core

def print_log(message):
    print message

core.log = print_log

DEFAULT_LOCATION = 'US'

arg_parser = argparse.ArgumentParser(
    description='Sync static web sites to Amazon S3 or CloudFront')

arg_parser.add_argument('--access-key-id',
    required=not 'AWS_ACCESS_KEY_ID' in os.environ)
arg_parser.add_argument('--secret-access-key',
    required=not 'AWS_SECRET_ACCESS_KEY' in os.environ)
arg_parser.add_argument('--index', default='index.html')
arg_parser.add_argument('--error-page', default='4xx.html')
arg_parser.add_argument('--repair', action='store_true')
arg_parser.add_argument('--allow-dot-files', action='store_true')
arg_parser.add_argument('--bucket-location', choices = (
    DEFAULT_LOCATION,
    boto.s3.connection.Location.USWest,
    boto.s3.connection.Location.EU,
    'ap-southeast-1'),
    default='US')
arg_parser.add_argument('--no-cloudfront', action='store_true')
arg_parser.add_argument('host_name')
arg_parser.add_argument('folder')

args = arg_parser.parse_args()

if args.bucket_location == DEFAULT_LOCATION:
    args.bucket_location = ''

try:
    core.setup(args)
except core.BadUserError, e:
    print >>sys.stderr, e.message
    sys.exit(1)
