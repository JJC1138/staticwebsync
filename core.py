__all__ = ('log', 'BadUserError', 'setup')

import os

import boto
import boto.s3.connection

log = None

class BadUserError(Exception):
    def __init__(self, message):
        self.message = message

def setup(args):
    bucket_prefix = 'syncfront-' + args.host_name + '-'

    s3 = boto.connect_s3(args.access_key_id, args.secret_access_key)

    bucket = None
    all_buckets = None
    try:
        log('looking for existing S3 bucket')
        all_buckets = s3.get_all_buckets()
    except boto.exception.S3ResponseError, e:
        if e.status == 403:
            raise BadUserError('Access denied. Please check your AWS Access Key ID and Secret Access Key.')
        else:
            raise e

    for b in all_buckets:
        if b.name.startswith(bucket_prefix):
            bucket = b
            log('found existing bucket %s' % bucket.name)
            break
    else:
        while True:
            bucket_name = bucket_prefix + os.urandom(8).encode('hex')
            try:
                log('creating bucket %s' % bucket_name)
                bucket = s3.create_bucket(bucket_name, location=args.bucket_location)
                break
            except boto.exception.S3CreateError, e:
                if e.error_code == 'BucketAlreadyExists':
                    log('bucket %s was already used (which is astonishingly unlikely)')
                    continue
                else:
                    raise e

    log('configuring bucket ACL policy')
    bucket.set_canned_acl('private')

    cf = boto.connect_cloudfront(args.access_key_id, args.secret_access_key)

    distribution = None
    all_distributions = None
    try:
        log('looking for existing CloudFront distribution')
        all_distributions = cf.get_all_distributions()
    except boto.cloudfront.exception.CloudFrontServerError, e:
        if e.error_code == 'OptInRequired':
            raise BadUserError('Your AWS account is not signed up for CloudFront, please sign up at http://aws.amazon.com/cloudfront/')
        else:
            raise e

    origin = bucket.name + '.s3.amazonaws.com'

    for d in all_distributions:
        if d.origin == origin:
            distribution = d.get_distribution()
            log('found distribution: %s' % distribution.id)
            break
        elif args.host_name in d.cnames:
            # TODO Remove the CNAME if a force option is given.
            raise BadUserError("Existing distribution %s has this hostname set as a CNAME, but it isn't associated with the correct origin bucket. Please remove the CNAME from the distribution or delete the distribution." % d.id)
    else:
        log('creating CloudFront distribution')
        distribution = cf.create_distribution(
            origin=origin, enabled=True)
        log('created distribution: %s' % distribution.id)

    log('configuring distribution')
    distribution.config.origin_access_identity = None
    distribution.config.trusted_signers = None
    distribution.update(
        enabled=True,
        cnames=[args.host_name],
        comment='Created by SyncFront',
        default_root_object=args.index)

    log('\nDistribution is ready. A DNS CNAME entry needs to be set for\n%s\npointing to\n%s' % (
        args.host_name, distribution.domain_name))
