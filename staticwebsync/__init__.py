__all__ = ('log', 'progress_callback', 'progress_callback_divisions',
    'BadUserError', 'setup')

import mimetypes
import os
import posixpath
import re
import time

import boto
import boto.s3.connection

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

    # The calling format is needed to address a problem with certificate
    # validation on bucket names with dots:
    # https://github.com/boto/boto/issues/2836
    s3 = boto.connect_s3(args.access_key_id, args.secret_access_key,
        calling_format=boto.s3.connection.OrdinaryCallingFormat())

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

    use_cloudfront = not args.no_cloudfront
    def install_marker_key(bucket):
        bucket.new_key(MARKER_KEY_NAME).set_contents_from_string(
            '', policy='private')

    for b in all_buckets:
        if b.name == standard_bucket_name or \
            b.name.startswith(standard_bucket_name + '-'):

            bucket = b
            log('found existing bucket %s' % bucket.name)

            if not MARKER_KEY_NAME in b:
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
                bucket = s3.create_bucket(
                    bucket_name, location=args.bucket_location)
                install_marker_key(bucket)
                break
            except boto.exception.S3CreateError, e:
                if e.error_code == 'BucketAlreadyExists':
                    log('bucket %s was already used by another user' %
                        bucket_name)
                    if first_fail:
                        log('We can use an alternative bucket name, but this will only work with CloudFront and not with standard S3 web site hosting (because it requires the bucket name to match the host name).')
                        first_fail = False
                    if not use_cloudfront:
                        raise BadUserError("Using CloudFront is disabled, so we can't continue.")
                    bucket_name = \
                        standard_bucket_name + '-' + os.urandom(8).encode('hex')
                    continue
                else:
                    raise e

    log('configuring bucket ACL policy')
    bucket.set_canned_acl('private')

    log('configuring bucket for website access')
    if args.error_page is not None:
        bucket.configure_website(args.index, args.error_page)
    else:
        bucket.configure_website(args.index)

    if use_cloudfront:
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

        origin = boto.cloudfront.origin.CustomOrigin(
            bucket.get_website_endpoint(), origin_protocol_policy='http-only')

        created_new_distribution = False
        for d in all_distributions:
            if d.origin.to_xml() == origin.to_xml():
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
            created_new_distribution = True

        if not created_new_distribution:
            log('checking distribution configuration')
            distribution = cf.get_distribution_info(distribution.id)

        if created_new_distribution or \
            getattr(distribution.config, 'origin_access_identity', None) \
                is not None or \
            distribution.config.trusted_signers is not None or \
            (not distribution.config.enabled) or \
            args.host_name not in distribution.config.cnames:

            log('configuring distribution')

            distribution.config.origin_access_identity = None
            distribution.config.trusted_signers = None
            distribution.update(
                enabled=True,
                cnames=[args.host_name])
        else:
            log('distribution configuration already fine')

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
                    log('Skipping folder %s' % os.path.normpath(dirpath))
                    blacklisted = True
                    break
            if blacklisted:
                continue

        for filename in filenames:
            if not args.allow_dot_files and filename.startswith('.'):
                log('Skipping file %s' % filename)
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

    sync_complete_message = '\nSync complete. A DNS CNAME entry needs to be set for\n%s\npointing to\n%s'

    if not use_cloudfront:
        log(sync_complete_message % (
            args.host_name, bucket.get_website_endpoint()))
        return

    def cf_complete():
        log(sync_complete_message % (args.host_name, distribution.domain_name))

        if (args.dont_wait_for_cloudfront_propagation):
            log('\nCloudFront may take up to 15 minutes to reflect any changes.')
            return

        log('')

        d = distribution
        while True:
            log('Checking if CloudFront propagation is complete.')
            d = cf.get_distribution_info(d.id)

            if d.status != 'InProgress' and \
                d.in_progress_invalidation_batches == 0:

                log('CloudFront propagation is complete.')
                return

            interval = 15
            log('Propagation still in progress; checking again in %d seconds.' %
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
