__all__ = ('log', 'progress_callback_factory', 'progress_callback_divisions', 'BadUserError', 'setup')

import binascii
import hashlib
import mimetypes
import mmap
import os
import posixpath
import re
import time

import boto3
import botocore
import termcolor

log = lambda msg: None
progress_callback_factory = lambda: None
progress_callback_divisions = 10 # this is no longer used, but is retained so as not to break the module API

class BadUserError(Exception):
    def __init__(self, message):
        self.message = message

def setup(args):
    def split_all(s, splitter):
        out = []
        while len(s) != 0:
            s, tail = splitter(s)
            out.insert(0, tail)
        return out

    def md5_hex_digest_string(filename):
        digestor = hashlib.md5()
        with open(filename, 'rb') as opened_file:
            fd = opened_file.fileno()
            if os.fstat(fd).st_size > 0: # can't mmap empty files
                with mmap.mmap(fd, 0, access=mmap.ACCESS_READ) as mm:
                    digestor.update(mm)
        return digestor.hexdigest()

    def log_check(msg):
        """Use this when reporting that we are about to check something."""
        log(msg)

    def log_noop(msg):
        """Use this when reporting that we checked something and it was fine as-is so it didn't need to be changed."""
        log(termcolor.colored(msg, 'cyan', attrs=['bold']))

    def log_op(msg):
        """Use this when reporting that we changed something (uploaded a file, changed a setting etc.)"""
        log(termcolor.colored(msg, 'green', attrs=['bold']))

    def log_warn(msg):
        """Use this when warning the user about something."""
        log(termcolor.colored(msg, 'red', attrs=['bold']))

    prefix = 'http://'
    if args.host_name.startswith(prefix):
        args.host_name = args.host_name[len(prefix):]

    suffix = '/'
    if args.host_name.endswith(suffix):
        args.host_name = args.host_name[:-len(suffix)]

    standard_bucket_name = args.host_name

    is_index_key = re.compile('(?P<path>^|.*?/)%s$' % re.escape(args.index))

    session = boto3.session.Session(
        aws_access_key_id=args.access_key_id,
        aws_secret_access_key=args.secret_access_key)

    s3 = session.resource('s3')

    bucket = None
    region = None
    all_buckets = None
    try:
        log_check('looking for existing S3 bucket')
        all_buckets = list(s3.buckets.all())
    except botocore.exceptions.ClientError as e:
        if e.response['ResponseMetadata']['HTTPStatusCode'] == 403:
            raise BadUserError('Access denied: %s' % e.response['Error']['Message'])
        else:
            raise e
    except botocore.exceptions.NoCredentialsError:
        raise BadUserError('No AWS credentials found. Please set up your ~/.aws/credentials file or specify them on the command line.')

    use_cloudfront = not args.no_cloudfront

    MARKER_KEY_NAME = '.staticwebsync'

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
        if b.name == standard_bucket_name or b.name.startswith(standard_bucket_name + '-'):
            log_noop('found existing bucket %s' % b.name)

            # The bucket location must be set in boto so that it can use the
            # path addressing style:
            # http://boto3.readthedocs.org/en/latest/guide/s3.html?highlight=botocore.client.Config#changing-the-addressing-style
            # That's required because otherwise requests on buckets with dots
            # in their names fail HTTPS validation:
            # https://github.com/boto/boto/issues/2836
            region = s3.meta.client.get_bucket_location(Bucket=b.name)['LocationConstraint']

            # That API returns None when the region is us-east-1:
            # http://docs.aws.amazon.com/AmazonS3/latest/API/RESTBucketGETlocation.html
            if region is None: region = 'us-east-1'

            s3 = session.resource('s3', region_name=region)
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
                log_op('creating bucket %s' % bucket_name)

                configuration = None

                region = args.bucket_location
                if not region or region == 'US': region = 'us-east-1'

                if region != 'us-east-1':
                    configuration = { 'LocationConstraint': region }

                s3 = session.resource('s3', region_name=region)
                if configuration:
                    bucket = s3.create_bucket(Bucket=bucket_name, CreateBucketConfiguration=configuration)
                else:
                    bucket = s3.create_bucket(Bucket=bucket_name)

                install_marker_key(bucket)
                break
            except botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'BucketAlreadyExists':
                    log_warn('bucket %s was already used by another user' % bucket_name)
                    if first_fail:
                        log_warn('We can use an alternative bucket name, but this will only work with CloudFront and not with standard S3 web site hosting (because it requires the bucket name to match the host name).')
                        first_fail = False
                    if not use_cloudfront:
                        raise BadUserError("Using CloudFront is disabled, so we can't continue.")
                    bucket_name = standard_bucket_name + '-' + binascii.b2a_hex(os.urandom(8)).decode('ascii')
                    continue
                else:
                    raise e

    log_op('configuring bucket ACL policy')
    bucket.Acl().put(ACL='private')

    log_op('configuring bucket for website access')
    website_configuration = { 'IndexDocument': { 'Suffix': args.index } }
    if args.error_page is not None:
        website_configuration['ErrorDocument'] = { 'Key': args.error_page }
    bucket.Website().put(WebsiteConfiguration=website_configuration)

    # http://docs.aws.amazon.com/AmazonS3/latest/dev/WebsiteEndpoints.html
    website_endpoint = '%s.s3-website-%s.amazonaws.com' % (bucket.name, region)

    def set_caller_reference(options):
        options['CallerReference'] = binascii.b2a_hex(os.urandom(8)).decode('ascii')

    if use_cloudfront:
        cf = session.client('cloudfront')

        distribution = None
        all_distributions = []
        try:
            log_check('looking for existing CloudFront distribution')
            distribution_lists = list(cf.get_paginator('list_distributions').paginate())
            for distribution_list in distribution_lists:
                all_distributions.extend(distribution_list['DistributionList'].get('Items', []))
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'OptInRequired':
                raise BadUserError('Your AWS account is not signed up for CloudFront, please sign up at http://aws.amazon.com/cloudfront/')
            else:
                raise e

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

        created_new_distribution = False
        for d in all_distributions:
            origins = d['Origins'].get('Items', [])
            if len(origins) == 1:
                origin = origins[0]

                if origin['DomainName'] == website_endpoint:
                    distribution = d
                    log_noop('found distribution: %s' % d['Id'])
                    break

            if args.host_name in d['Aliases'].get('Items', []):
                # TODO Remove the alias if a force option is given.
                raise BadUserError("Existing distribution %s has this hostname set as an alternate domain name (CNAME), but it isn't associated with the correct origin bucket. Please remove the alternate domain name from the distribution or delete the distribution." % d['Id'])
        else:
            log_op('creating CloudFront distribution')

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
            log_op('created distribution %s' % distribution['Id'])
            created_new_distribution = True

        if not created_new_distribution:
            log_check('checking distribution configuration')

            get_distribution_config_response = cf.get_distribution_config(Id=distribution['Id'])
            update_config = get_distribution_config_response['DistributionConfig']

            if set_required_config(update_config):
                log_op('configuring distribution')

                distribution = cf.update_distribution(
                    Id=distribution['Id'],
                    IfMatch=get_distribution_config_response['ETag'],
                    DistributionConfig=update_config)['Distribution']['DistributionConfig']
            else:
                log_noop('distribution configuration already fine')

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
                    log_noop('skipping folder %s' % os.path.normpath(dirpath))
                    blacklisted = True
                    break
            if blacklisted:
                continue

        for filename in filenames:
            if not args.allow_dot_files and filename.startswith('.'):
                log_noop('skipping file %s' % filename)
                continue

            inf = os.path.normpath(os.path.join(dirpath, filename))

            d = os.path.normpath(dirpath)
            if d == '.':
                d = ''

            type = mimetypes.guess_type(filename, strict=False)
            upload_extra_args = {}
            if type[0] is not None:
                # the lack of hyphens in the keys is correct, because these are method arguments rather than HTTP headers:
                upload_extra_args['ContentType'] = type[0]
            if type[1] is not None:
                upload_extra_args['ContentEncoding'] = type[1]

            def upload(f):
                # We could re-use this when uploading the same file twice, but
                # the code would be a bit messy.
                md5 = None

                parts = list(split_all(d, os.path.split))
                parts.append(f)
                outf = posixpath.join(*parts)
                if outf == '':
                    outf = args.index

                log_check('processing "%s" -> "%s"' % (inf, outf))

                obj = s3.Object(bucket.name, outf)

                try:
                    obj.load()
                    existed = True

                    log_noop('%s exists in bucket' % outf)
                    md5 = md5_hex_digest_string(inf)
                    if obj.e_tag == '"%s"' % md5 and \
                        obj.content_type == upload_extra_args.get('ContentType', obj.content_type) and \
                        obj.content_encoding == upload_extra_args.get('ContentEncoding'):

                        # TODO Check for other headers?
                        log_noop('%s matches local file' % outf)
                        if not args.repair:
                            return

                        acl = obj.Acl()
                        user_grant_okay = False
                        public_grant_okay = False
                        for grant in acl.grants:
                            grantee = grant['Grantee']
                            if grantee.get('ID') == acl.owner['ID']:
                                user_grant_okay = grant['Permission'] == 'FULL_CONTROL'
                                if not user_grant_okay:
                                    break
                            elif grantee['Type'] == 'Group':
                                public_grant_okay = \
                                    grantee['URI'] == 'http://acs.amazonaws.com/groups/global/AllUsers' and \
                                    grant['Permission'] == 'READ'
                                if not public_grant_okay:
                                    break
                            else:
                                break
                        else:
                            if user_grant_okay and public_grant_okay:
                                log_noop('%s ACL is fine' % outf)
                                return
                        log_op('%s ACL is wrong' % outf)

                except botocore.exceptions.ClientError as ce:
                    if ce.response['Error']['Code'] != '404':
                        raise ce
                    existed = False

                log_op('uploading %s' % outf)
                upload_extra_args['ACL'] = 'public-read'

                # Convert our callbacks to be compatible with the boto3 upload callback API:
                class CallbackWrapper:
                    def __init__(self, old_callback_factory, file_size):
                        self.old_callback = old_callback_factory()
                        self.file_size = file_size
                        self.total_transferred = 0
                    def __call__(self, newly_transferred_bytes_count):
                        self.total_transferred += newly_transferred_bytes_count
                        self.old_callback(self.total_transferred, self.file_size)

                obj.upload_file(inf, ExtraArgs=upload_extra_args,
                    Callback=CallbackWrapper(progress_callback_factory, os.path.getsize(inf)))

                if existed:
                    key_name = obj.key
                    invalidations.append(key_name)

                    # Index pages are likely to be cached in CloudFront without the trailing filename instead (or as well).
                    m = is_index_key.match(key_name)
                    if m:
                        invalidations.append(m.group('path'))

            upload(filename)

    log_check('checking for deleted files')

    for obj in list(bucket.objects.all()):
        name = obj.key
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
            log_noop('%s has corresponding local file' % obj.key)
            continue
        log_op('deleting %s' % obj.key)
        obj.delete()
        invalidations.append(obj.key)

    def log_sync_complete(dns_entry_name, dns_entry_target):
        log_op('sync complete')
        log_check('a DNS entry needs to be set for\n%s\npointing to\n%s' % (dns_entry_name, dns_entry_target))

    if not use_cloudfront:
        log_sync_complete(args.host_name, website_endpoint)
        return

    def cf_complete():
        log_sync_complete(args.host_name, distribution['DomainName'])

        if (args.dont_wait_for_cloudfront_propagation):
            log_noop('CloudFront may take up to 15 minutes to reflect any changes')
            return

        d = distribution
        while True:
            log_check('checking if CloudFront propagation is complete')
            d = cf.get_distribution(Id=d['Id'])['Distribution']

            if d['Status'] != 'InProgress' and d['InProgressInvalidationBatches'] == 0:
                log_op('CloudFront propagation is complete')
                return

            interval = 15
            log_check('propagation still in progress; checking again in %d seconds' % interval)
            time.sleep(interval)

    if len(invalidations) == 0:
        cf_complete()
        return

    log_op('invalidating cached copies of changed or deleted files')

    def invalidate_all(paths):
        batch = {
            'Paths': {
                'Quantity': len(paths),
                'Items': paths,
            },
        }

        while True:
            try:
                set_caller_reference(batch)
                cf.create_invalidation(DistributionId=distribution['Id'], InvalidationBatch=batch)
                break
            except botocore.exceptions.ClientError as ce:
                if ce.response['Error']['Code'] != 'TooManyInvalidationsInProgress':
                    raise ce

                interval = 60
                log_check('too many invalidations in progress; trying again in %d seconds' % interval)
                time.sleep(interval)

        paths.clear()

    paths = []

    def invalidate(path):
        paths.append(path)
        if len(paths) == 3000:
            invalidate_all(paths)

    for i in invalidations:
        invalidate('/' + i)
        if (i == args.index):
            invalidate('/')

    if len(paths) > 0:
        invalidate_all(paths)

    cf_complete()
