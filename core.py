__all__ = ('log', 'BadUserError', 'setup')

import mimetypes
import os
import posixpath

import boto
import boto.s3.connection

log = None

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
    standard_bucket_name = 'staticwebsync-' + args.host_name

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
        if b.name == standard_bucket_name or \
            b.name.startswith(standard_bucket_name + '-'):

            bucket = b
            log('found existing bucket %s' % bucket.name)
            break
    else:
        bucket_name = standard_bucket_name
        while True:
            try:
                log('creating bucket %s' % bucket_name)
                bucket = s3.create_bucket(bucket_name, location=args.bucket_location)
                break
            except boto.exception.S3CreateError, e:
                if e.error_code == 'BucketAlreadyExists':
                    log('bucket %s was already used by another user')
                    bucket_name = \
                        standard_bucket_name + '-' + os.urandom(8).encode('hex')
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
        comment='Created by staticwebsync',
        default_root_object=args.index)

    log('\nDistribution is ready. A DNS CNAME entry needs to be set for\n%s\npointing to\n%s' % (
        args.host_name, distribution.domain_name))

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
                    headers, policy='public-read', md5=md5)
                if existed:
                    invalidations.append(key.name)

            if filename == args.index and d != '':
                upload('')
            upload(filename)

            local_file.close()

    log('checking for changed or deleted files')

    for key in bucket.list():
        name = key.name
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

    if len(invalidations) == 0:
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
