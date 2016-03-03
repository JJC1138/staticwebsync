__all__ = ('log', 'progress_callback', 'progress_callback_divisions',
    'BadUserError', 'setup')

import binascii
import mimetypes
import os
import posixpath
import re
import sys # FIXME remove
import time

import boto3
import botocore

log = None
progress_callback_factory = lambda: None
progress_callback_divisions = 10

MARKER_KEY_NAME = '.staticwebsync'

class BadUserError(Exception):
    def __init__(self, message):
        self.message = message

def split_all(s, splitter):
    out = []
    while len(s) != 0:
        s, tail = splitter(s)
        out.insert(0, tail)
    return out

def setup(args):
    prefix = 'http://'
    if args.host_name.startswith(prefix):
        args.host_name = args.host_name[len(prefix):]

    suffix = '/'
    if args.host_name.endswith(suffix):
        args.host_name = args.host_name[:-len(suffix)]

    standard_bucket_name = args.host_name

    is_index_key = re.compile('(?P<path>^|.*?/)%s$' % re.escape(args.index))

    s3 = boto3.resource('s3',
        aws_access_key_id=args.access_key_id,
        aws_secret_access_key=args.secret_access_key)

    bucket = None
    region = None
    all_buckets = None
    try:
        log('looking for existing S3 bucket')
        all_buckets = list(s3.buckets.all())
    except botocore.exceptions.ClientError as e:
        if e.response['ResponseMetadata']['HTTPStatusCode'] == 403:
            raise BadUserError('Access denied: %s' % e.response['Error']['Message'])
        else:
            raise e

    use_cloudfront = not args.no_cloudfront

    def install_marker_key(bucket):
        s3.Object(bucket.name, MARKER_KEY_NAME).put(Body=b'', ACL='private')

    def object_or_none(bucket, key):
        try:
            o = s3.Object(bucket.name, key)
            o.load()
            return o
        except botocore.exceptions.ClientError as e:
            if e.response['ResponseMetadata']['HTTPStatusCode'] == 404:
                return None
            else:
                raise e

    for b in all_buckets:
        if b.name == standard_bucket_name or \
            b.name.startswith(standard_bucket_name + '-'):

            log('found existing bucket %s' % b.name)

            # The bucket location must be set in boto so that it can use the
            # path addressing style:
            # http://boto3.readthedocs.org/en/latest/guide/s3.html?highlight=botocore.client.Config#changing-the-addressing-style
            # That's required because otherwise requests on buckets with dots
            # in their names fail HTTPS validation:
            # https://github.com/boto/boto/issues/2836
            region = s3.meta.client.get_bucket_location(
                Bucket=b.name)['LocationConstraint']

            # That API returns None when the region is us-east-1:
            # http://docs.aws.amazon.com/AmazonS3/latest/API/RESTBucketGETlocation.html
            if region is None: region = 'us-east-1'

            s3 = boto3.resource('s3', region_name=region,
                aws_access_key_id=args.access_key_id,
                aws_secret_access_key=args.secret_access_key)
            bucket = s3.Bucket(b.name)

            if not object_or_none(b, MARKER_KEY_NAME):
                if not args.take_over_existing_bucket:
                    raise BadUserError("The S3 bucket %s already exists, but was not created by staticwebsync. If you wish to use it anyway and are happy for any existing files in it to be deleted if they don't have a corresponding local file then use the --take-over-existing-bucket option." % bucket.name)

                install_marker_key(bucket)

            break
    else:
        bucket_name = standard_bucket_name
        first_fail = True
        while True:
            try:
                log('creating bucket %s' % bucket_name)

                configuration = None

                region = args.bucket_location
                if not region or region == 'US': region = 'us-east-1'

                if region != 'us-east-1':
                    configuration = { 'LocationConstraint': region }

                s3 = boto3.resource('s3', region_name=region,
                    aws_access_key_id=args.access_key_id,
                    aws_secret_access_key=args.secret_access_key)
                if configuration:
                    bucket = s3.create_bucket(
                        Bucket=bucket_name, CreateBucketConfiguration=configuration)
                else:
                    bucket = s3.create_bucket(
                        Bucket=bucket_name)

                install_marker_key(bucket)
                break
            except botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'BucketAlreadyExists':
                    log('bucket %s was already used by another user' %
                        bucket_name)
                    if first_fail:
                        log('We can use an alternative bucket name, but this will only work with CloudFront and not with standard S3 web site hosting (because it requires the bucket name to match the host name).')
                        first_fail = False
                    if not use_cloudfront:
                        raise BadUserError("Using CloudFront is disabled, so we can't continue.")
                    bucket_name = \
                        standard_bucket_name + \
                        '-' + binascii.b2a_hex(os.urandom(8)).decode('ascii')
                    continue
                else:
                    raise e

    log('configuring bucket ACL policy')
    bucket.Acl().put(ACL='private')

    log('configuring bucket for website access')
    website_configuration = { 'IndexDocument': { 'Suffix': args.index } }
    if args.error_page is not None:
        website_configuration['ErrorDocument'] = { 'Key': args.error_page }
    bucket.Website().put(WebsiteConfiguration=website_configuration)

    if use_cloudfront:
        cf = boto3.client('cloudfront',
            aws_access_key_id=args.access_key_id,
            aws_secret_access_key=args.secret_access_key)

        distribution = None
        all_distributions = []
        try:
            log('looking for existing CloudFront distribution')
            distribution_lists = \
                list(cf.get_paginator('list_distributions').paginate())
            for distribution_list in distribution_lists:
                all_distributions.extend(distribution_list['DistributionList'].get('Items', []))
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'OptInRequired':
                raise BadUserError('Your AWS account is not signed up for CloudFront, please sign up at http://aws.amazon.com/cloudfront/')
            else:
                raise e

        # http://docs.aws.amazon.com/AmazonS3/latest/dev/WebsiteEndpoints.html
        website_endpoint = '%s.s3-website-%s.amazonaws.com' % (bucket.name, region)

        def set_required_config(config):
            any_changed = False

            def get_or_set_default(d, k, default):
                nonlocal any_changed

                value = d.get(k)
                if value is None:
                    any_changed = True
                    d[k] = default
                    return default
                return value

            def set_if_not_equal(d, k, value):
                nonlocal any_changed

                old_value = d.get(k)
                if old_value != value:
                    any_changed = True
                    d[k] = value

            aliases = get_or_set_default(config, 'Aliases', {})
            aliases_items = get_or_set_default(aliases, 'Items', [])
            if args.host_name not in aliases_items:
                any_changed = True
                aliases_items.append(args.host_name)
                aliases['Quantity'] = len(aliases_items)

            origins = get_or_set_default(config, 'Origins', {})
            origins_items = get_or_set_default(origins, 'Items', [])
            if len(origins_items) == 0:
                any_changed = True
                origin = {}
                origins_items[:] = [origin]
            elif len(origins_items) == 1:
                origin = origins_items[0]
            else:
                raise BadUserError("The existing distribution has multiple origins, and we can't configure distributions with more than one. Please delete all but the default origin or delete the distribution.")

            set_if_not_equal(origins, 'Quantity', len(origins_items))

            set_if_not_equal(origin, 'DomainName', website_endpoint)
            set_if_not_equal(origin, 'Id', 'S3 Website')

            custom_origin_config = get_or_set_default(origin, 'CustomOriginConfig', {})
            set_if_not_equal(custom_origin_config, 'OriginProtocolPolicy', 'http-only')
            set_if_not_equal(custom_origin_config, 'HTTPPort', 80)
            set_if_not_equal(custom_origin_config, 'HTTPSPort', 443)

            default_cache_behavior = get_or_set_default(config, 'DefaultCacheBehavior', {})
            set_if_not_equal(default_cache_behavior, 'Compress', True)
            set_if_not_equal(default_cache_behavior, 'TargetOriginId', origin['Id'])
            forwarded_values = get_or_set_default(default_cache_behavior, 'ForwardedValues', {})
            set_if_not_equal(forwarded_values, 'QueryString', False)
            cookies = get_or_set_default(forwarded_values, 'Cookies', {})
            if cookies.get('Forward') != 'none':
                any_changed = True
                cookies.clear()
                cookies['Forward'] = 'none'

            set_if_not_equal(config, 'Enabled', True)

            return any_changed

        def set_caller_reference(options):
            options['CallerReference'] = binascii.b2a_hex(os.urandom(8)).decode('ascii')

        created_new_distribution = False
        for d in all_distributions:
            origins = d['Origins'].get('Items', [])
            if len(origins) == 1:
                origin = origins[0]

                if origin['DomainName'] == website_endpoint:
                    distribution = d
                    log('found distribution: %s' % d['Id'])
                    break

            if args.host_name in d['Aliases'].get('Items', []):
                # TODO Remove the alias if a force option is given.
                raise BadUserError("Existing distribution %s has this hostname set as an alternate domain name (CNAME), but it isn't associated with the correct origin bucket. Please remove the alternate domain name from the distribution or delete the distribution." % d['Id'])
        else:
            log('creating CloudFront distribution')

            creation_config = {}
            set_required_config(creation_config)

            # Set defaults for options that are required to create a distribution:
            creation_config.setdefault('Comment', '')
            default_cache_behavior = creation_config.setdefault('DefaultCacheBehavior', {})
            trusted_signers = default_cache_behavior.setdefault('TrustedSigners', {})
            trusted_signers.setdefault('Enabled', False)
            trusted_signers.setdefault('Quantity', 0)
            default_cache_behavior.setdefault('ViewerProtocolPolicy', 'allow-all')
            default_cache_behavior.setdefault('MinTTL', 0)

            set_caller_reference(creation_config)

            distribution_creation_response = cf.create_distribution(
                DistributionConfig=creation_config)
            distribution = distribution_creation_response['Distribution']['DistributionConfig']
            distribution['Id'] = distribution_creation_response['Distribution']['Id']
            log('created distribution %s' % distribution['Id'])
            created_new_distribution = True

        if not created_new_distribution:
            log('checking distribution configuration')

            get_distribution_config_response = cf.get_distribution_config(Id=distribution['Id'])
            update_config = get_distribution_config_response['DistributionConfig']

            if set_required_config(update_config):
                log('configuring distribution')

                distribution = cf.update_distribution(
                    Id=distribution['Id'],
                    IfMatch=get_distribution_config_response['ETag'],
                    DistributionConfig=update_config)['Distribution']['DistributionConfig']
            else:
                log('distribution configuration already fine')

    sys.exit(0) # FIXME remove

    # TODO Set up custom MIME types.
    mimetypes.init()
    # On my Windows system these get set to silly other values by some registry
    # key, which is, for the avoidance of doubt, super lame.
    mimetypes.types_map['.png'] = 'image/png'
    mimetypes.types_map['.jpg'] = 'image/jpeg'
    mimetypes.types_map['.js'] = 'application/javascript'

    # TODO Serialize these in case of failure, and resume when restarting:
    invalidations = []

    dir = os.path.normpath(args.folder)

    if not os.path.exists(dir):
        raise BadUserError('Folder %s does not exist.' % args.folder)

    if not os.path.isdir(dir):
        raise BadUserError('%s is a file not a folder.' % args.folder)

    os.chdir(dir)

    for (dirpath, dirnames, filenames) in os.walk('.'):
        if not args.allow_dot_files:
            blacklisted = False
            for p in split_all(dirpath, os.path.split):
                if p.startswith('.') and p != '.':
                    log('skipping folder %s' % os.path.normpath(dirpath))
                    blacklisted = True
                    break
            if blacklisted:
                continue

        for filename in filenames:
            if not args.allow_dot_files and filename.startswith('.'):
                log('skipping file %s' % filename)
                continue

            inf = os.path.normpath(os.path.join(dirpath, filename))

            d = os.path.normpath(dirpath)
            if d == '.':
                d = ''

            local_file = open(inf, 'rb')

            type = mimetypes.guess_type(filename, strict=False)
            headers = {}
            if type[0] is not None:
                headers['Content-Type'] = type[0]
            if type[1] is not None:
                headers['Content-Encoding'] = type[1]

            def upload(f):
                # We could re-use this when uploading the same file twice, but
                # the code would be a bit messy.
                md5 = None

                parts = list(split_all(d, os.path.split))
                parts.append(f)
                outf = posixpath.join(*parts)
                if outf == '':
                    outf = args.index

                log('processing "%s" -> "%s"' % (inf, outf))

                key = bucket.get_key(outf)

                existed = key is not None
                if existed:
                    log('%s exists in bucket' % outf)
                    md5 = key.compute_md5(local_file)
                    if key.etag == '"%s"' % md5[0] and \
                        key.content_type == headers.get(
                            'Content-Type', key.content_type) and \
                        key.content_encoding == headers.get('Content-Encoding'):

                        # TODO Check for other headers?
                        log('%s matches local file' % outf)
                        if not args.repair:
                            return

                        policy = key.get_acl()
                        user_grant_okay = False
                        public_grant_okay = False
                        for grant in policy.acl.grants:
                            if grant.id == policy.owner.id:
                                user_grant_okay = grant.permission == 'FULL_CONTROL'
                                if not user_grant_okay:
                                    break
                            elif grant.type == 'Group':
                                public_grant_okay = \
                                    grant.uri == 'http://acs.amazonaws.com/groups/global/AllUsers' and \
                                    grant.permission == 'READ'
                                if not public_grant_okay:
                                    break
                            else:
                                break
                        else:
                            if user_grant_okay and public_grant_okay:
                                log('%s ACL is fine' % outf)
                                return
                        log('%s ACL is wrong' % outf)
                else:
                    key = bucket.new_key(outf)

                log('uploading %s' % outf)
                key.set_contents_from_file(local_file,
                    headers, policy='public-read', md5=md5,
                    cb=progress_callback_factory(),
                    num_cb=progress_callback_divisions)
                if existed:
                    key_name = key.name
                    invalidations.append(key_name)

                    # Index pages are likely to be cached in CloudFront without the trailing filename instead (or as well).
                    m = is_index_key.match(key_name)
                    if m:
                        invalidations.append(m.group('path'))

            upload(filename)

            local_file.close()

    log('checking for changed or deleted files')

    for key in bucket.list():
        name = key.name
        if name == MARKER_KEY_NAME:
            continue
        if name.endswith('/'):
            name = posixpath.join(name, args.index)
        parts = split_all(name, posixpath.split)
        blacklisted = False
        if not args.allow_dot_files:
            for p in parts:
                if p.startswith('.'):
                    blacklisted = True
                    break
        if not blacklisted and os.path.isfile(os.path.join(*parts)):
            log('%s has corresponding local file' % key.name)
            continue
        log('deleting %s' % key.name)
        key.delete()
        invalidations.append(key.name)

    sync_complete_message = '\nsync complete\na DNS entry needs to be set for\n%s\npointing to\n%s'

    if not use_cloudfront:
        log(sync_complete_message % (
            args.host_name, bucket.get_website_endpoint()))
        return

    def cf_complete():
        log(sync_complete_message % (args.host_name, distribution.domain_name))

        if (args.dont_wait_for_cloudfront_propagation):
            log('\nCloudFront may take up to 15 minutes to reflect any changes')
            return

        log('')

        d = distribution
        while True:
            log('checking if CloudFront propagation is complete')
            d = cf.get_distribution_info(d.id)

            if d.status != 'InProgress' and \
                d.in_progress_invalidation_batches == 0:

                log('CloudFront propagation is complete')
                return

            interval = 15
            log('propagation still in progress; checking again in %d seconds' %
                interval)
            time.sleep(interval)

    if len(invalidations) == 0:
        cf_complete()
        return

    log('invalidating cached copies of changed or deleted files')
    def invalidate_all(paths):
        # TODO Handle the error when exceeding the limit, and serialize the
        # remaining paths so that we can restart later.
        cf.create_invalidation_request(distribution.id, paths)
        del paths[:]
    paths = []
    def invalidate(path):
        paths.append(path)
        if len(paths) == 1000:
            invalidate_all(paths)
    for i in invalidations:
        invalidate('/' + i)
        if (i == args.index):
            invalidate('/')

    if len(paths) > 0:
        invalidate_all(paths)

    cf_complete()
