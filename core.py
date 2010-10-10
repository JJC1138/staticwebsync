__all__ = ('log', 'BadUserError', 'setup')

import boto
import boto.s3.connection

log = None

class BadUserError(Exception):
    def __init__(self, message):
        self.message = message

def setup(args):
    bucket_name = 'syncfront-' + args.host_name

    s3 = boto.connect_s3(args.access_key_id, args.secret_access_key)

    bucket = None
    try:
        bucket = s3.get_bucket(bucket_name).get_all_keys(max_keys=0)
        if not args.delete_existing_bucket:
            raise BadUserError('You already have a bucket with that name. Use the force option to set the existing bucket up for SyncFront, which will DELETE ALL CONTENT in the bucket.')
        log('deleting existing bucket contents')
        bucket = s3.get_bucket(bucket_name)
        for k in bucket.list():
            k.delete()
    except boto.exception.S3ResponseError, e:
        try:
            bucket = s3.create_bucket(bucket_name, location=args.bucket_location)
        except boto.exception.S3CreateError, e:
            if e.error_code == 'BucketAlreadyExists':
                raise BadUserError('That bucket name is already in use by someone else. Please select another.')
            else:
                raise e
        except boto.exception.S3ResponseError, e:
            if e.status == 403:
                raise BadUserError('Access denied. Please check your AWS Access Key ID and Secret Access Key.')
            else:
                raise e

    bucket.set_canned_acl('private')

    cf = boto.connect_cloudfront(args.access_key_id, args.secret_access_key)

    distribution = None
    try:
        log('creating CloudFront distribution')
        distribution = cf.create_distribution(
            origin=bucket.name + '.s3.amazonaws.com',
            enabled=True)
    except boto.cloudfront.exception.CloudFrontServerError, e:
        if e.error_code == 'OptInRequired':
            raise BadUserError('Your AWS account is not signed up for CloudFront, please sign up at http://aws.amazon.com/cloudfront/')
        else:
            raise e

    try:
        log('setting CloudFront distribution properties')
        distribution.update(
            cnames=[args.host_name],
            comment='Created by SyncFront',
            default_root_object=args.index)
    except boto.cloudfront.exception.CloudFrontServerError, e:
        if e.error_code == 'CNAMEAlreadyExists':
            # TODO Find and remove it if a force option is given.
            raise BadUserError('You already have a CloudFront distribution set up for this host name. Please remove it.')
        else:
            raise e

    log('\nDistribution is ready. Please set a DNS CNAME entry for\n%s\npointing to\n%s' % (
        args.host_name, distribution.domain_name))
