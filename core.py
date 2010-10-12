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

def setup(args):
    standard_bucket_name = 'syncfront-' + args.host_name

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
        comment='Created by SyncFront',
        default_root_object=args.index)

    log('\nDistribution is ready. A DNS CNAME entry needs to be set for\n%s\npointing to\n%s' % (
        args.host_name, distribution.domain_name))

    # TODO Set up custom MIME types.
    mimetypes.init()
    # On my Windows system these get set to silly other values by some registry
    # key, which is, for the avoidance of doubt, super lame.
    mimetypes.types_map['.png'] = 'image/png'
    mimetypes.types_map['.jpg'] = 'image/jpeg'

    dir = os.path.normpath(args.folder)

    if not os.path.exists(dir):
        raise BadUserError('Folder %s does not exist.' % args.folder)

    if not os.path.isdir(dir):
        raise BadUserError('%s is a file not a folder.' % args.folder)

    os.chdir(dir)

    for (dirpath, dirnames, filenames) in os.walk('.'):
        for filename in filenames:
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

                parts = list(os.path.split(d))
                parts.append(f)
                outf = posixpath.join(*parts)
                if outf == '':
                    outf = args.index

                log('processing "%s" -> "%s"' % (inf, outf))

                key = bucket.get_key(outf)

                if key is not None:
                    log('%s exists in bucket' % outf)
                    md5 = key.compute_md5(local_file)
                    if key.etag == '"%s"' % md5[0] and \
                        key.content_type == headers.get('Content-Type') and \
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

            if filename == args.index and d != '':
                upload('')
            upload(filename)

            local_file.close()
