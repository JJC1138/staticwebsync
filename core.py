import boto
import boto.s3.connection

def setup(args):
    bucket_name = 'syncfront-' + args.host_name

    s3 = boto.connect_s3(args.access_key_id, args.secret_access_key)

    bucket = None
    try:
        bucket = s3.get_bucket(bucket_name).get_all_keys(max_keys=0)
        if not args.delete_existing_bucket:
            print >>sys.stderr, 'You already have a bucket with that name. Use the %s option to set it up for SyncFront, which will DELETE ANY EXISTING content in the bucket.' % FORCE_EXISTING_OPTION
            sys.exit(BAD_USER_EXIT)
        print 'deleting existing bucket contents'
        bucket = s3.get_bucket(bucket_name)
        for k in bucket.list():
            k.delete()
    except boto.exception.S3ResponseError, e:
        try:
            bucket = s3.create_bucket(bucket_name, location=args.bucket_location)
        except boto.exception.S3CreateError, e:
            if e.error_code == 'BucketAlreadyExists':
                print >>sys.stderr, 'That bucket name is already in use by someone else. Please select another.'
                sys.exit(BAD_USER_EXIT)
            else:
                raise e
        except boto.exception.S3ResponseError, e:
            if e.status == 403:
                print >>sys.stderr, 'Access denied. Please check your AWS Access Key ID and Secret Access Key.'
                sys.exit(BAD_USER_EXIT)
            else:
                raise e

    bucket.set_canned_acl('private')

    cf = boto.connect_cloudfront(args.access_key_id, args.secret_access_key)

    distribution = None
    try:
        print 'creating CloudFront distribution'
        distribution = cf.create_distribution(
            origin=bucket.name + '.s3.amazonaws.com',
            enabled=True)
    except boto.cloudfront.exception.CloudFrontServerError, e:
        if e.error_code == 'OptInRequired':
            print >>sys.stderr, 'Your AWS account is not signed up for CloudFront, please sign up at http://aws.amazon.com/cloudfront/'
            sys.exit(BAD_USER_EXIT)
        else:
            raise e

    try:
        print 'setting CloudFront distribution properties'
        distribution.update(
            cnames=[args.host_name],
            comment='Created by SyncFront',
            default_root_object=args.index)
    except boto.cloudfront.exception.CloudFrontServerError, e:
        if e.error_code == 'CNAMEAlreadyExists':
            print >>sys.stderr, 'You already have a CloudFront distribution set up for this host name. Please remove it.'
            # TODO Find and remove it if a force option is given.
            sys.exit(BAD_USER_EXIT)
        else:
            raise e

    print '\nDistribution is ready. Please set a DNS CNAME entry for\n%s\npointing to\n%s' % (
        args.host_name, distribution.domain_name)
