#!/usr/bin/env python3

"""
=> Simple Storage Service Static Site Uploader <=

License: GNU General Public License,
         see http://www.gnu.org/licenses/gpl-3.0.en.html
Author:  Ondrej Slamecka <ondrej@slamecka.cz>
Website: https://github.com/OndrejSlamecka/s5upload
"""

import boto3
import os
import datetime
import argparse
import yaml
import re
import mimetypes
import hashlib
from sys import stderr
from dateutil.tz import tzlocal
from operator import attrgetter


""" Data types """


class FileInfo():
    def __init__(self, path, mtime):
        self.path = path
        self.mtime = mtime

    def __repr__(self):
        return str((self.path, self.mtime))


class LocalFileInfo(FileInfo):
    def __init__(self, path, mtime, dir):
        # The path attribute is relative to the given directory
        super(LocalFileInfo, self).__init__(path, mtime)
        self.dir = dir

    def full_path(self):
        return os.path.join(self.dir, self.path)

    def should_replace(self, objectinfo):
        if self.mtime > objectinfo.mtime:
            if os.path.getsize(self.full_path()) != objectinfo.size:
                return True

            # Amazon's ETag is md5
            return file_hash(self.full_path()) != objectinfo.etag

        return False


class ObjectInfo(FileInfo):
    """
    S3 object information.
    """
    def __init__(self, path, mtime, etag, size, obj):
        super(ObjectInfo, self).__init__(path, mtime)
        self.etag = etag
        self.size = size
        self.bucket_object = obj


""" Manipulating files """


def get_remote(bucket):
    """
    Yields ObjectInfo of objects in given S3 bucket.
    """
    for o in bucket.objects.all():
        mtime = o.last_modified.astimezone(tzlocal())
        etag = o.e_tag[1:-1]  # unwrap from " quotes
        yield ObjectInfo(o.key, mtime, etag, o.size, o)


def get_local(directory):
    """
    Yields LocalFileInfo of files in given directory.
    """
    for root, _, files in os.walk(directory):
        for filename in files:
            filepath = os.path.join(root, filename)
            t = datetime.datetime.fromtimestamp(os.path.getmtime(filepath),
                                                tzlocal())
            yield LocalFileInfo(filepath[len(directory) + 1:], t,
                                directory)


def upload_file(cache_config, bucket, fileinfo):
    """
    Uploads file given file to given bucket with cache control attribute
    set according to given cache configuration.
    """
    params = {
        'Key': fileinfo.path,
        'CacheControl': cache_control(cache_config,
                                      fileinfo.full_path())
    }

    ct = mimetypes.guess_type(fileinfo.full_path())[0]
    if ct is not None:
        params['ContentType'] = ct

    with open(fileinfo.full_path(), 'rb') as data:
        params['Body'] = data
        bucket.put_object(**params)


def file_hash(path):
    """
    Returns md5 hash of file on a given path.
    """
    m = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            m.update(chunk)
    return m.hexdigest()


""" CloudFront tools """


def invalidation_batch(items):
    """
    Given a list of FileInfo objects, creates a tuple with:
    * a list of files suitable for CloudFront,
    * invalidation identifier.
    """
    # CloudFront needs / at the beginning of paths
    cfitems = ['/' + fi.path for fi in items]

    # Identify uniquely this diff
    m = hashlib.md5()
    for fi in items:
        s = fi.path + '~' + str(fi.mtime.timestamp())
        m.update(s.encode('utf-8'))
    diff_hash = m.hexdigest()

    return (cfitems, diff_hash)


def create_cloudfront_invalidation(client, dist_id, items, hash):
    """
    Creates the invalidation in AWS.
    """
    return client.create_invalidation(
        DistributionId=dist_id,
        InvalidationBatch={
            'Paths': {
                'Quantity': len(items),
                'Items': items
            },
            'CallerReference': hash
        }
    )


""" Algorithm for computing the difference of two FileInfo lists """


def differences(local, remote):
    """
    Input:  Lists of local and remote files' FileInfo-s.
    Output: List of FileInfo-s which are in the local system but missing
            at remote and list of FileInfo-s which are in the bucket but
            not in the local system.
    """
    local = sorted(local, key=attrgetter('path'))
    remote = sorted(remote, key=attrgetter('path'))

    # lmore -- the list of files to be uploaded/overwritten
    # rmore -- the list of files to be deleted from the bucket
    lmore, rmore = [], []
    while local and remote:
        l, r = local[-1], remote[-1]
        if l.path > r.path:
            lmore.append(l)
            del local[-1]
        elif r.path > l.path:
            rmore.append(r)
            del remote[-1]
        else:  # l.path == r.path
            if l.should_replace(r):
                lmore.append(l)

            del local[-1]
            del remote[-1]

    if local:
        lmore.extend(local)

    if remote:
        rmore.extend(remote)

    return (lmore, rmore)


""" Cache-Control tools """


def cache_control(config, path):
    """
    Returns CacheControl attribute for file at given path.
    """
    def t(age):
        return 'public,max-age=' + str(age)

    for rule, age in config['rules'].items():
        if re.search(rule, path, re.I):
            return t(age)

    return t(config['default'])


""" Configuration """


def default_configuration():
    """
    Returns the default configuration string.
    """
    return """
cache_control: # set max-age
    default: 86400 # a day
    rules:
        '\.(ico|jpg|jpeg|png|gif)$': 31536000 # 365 days
        '\.(css|js)$': 604800 # a week"""


def parse_config_source(s):
    return yaml.load(s)


def choose_config_source(filename):
    """
    If file exists then returns its content.
    Otherwise returns the default configuration string.
    """
    if not os.path.exists(filename):
        src = default_configuration()
    else:
        with open(filename, 'r') as f:
            src = f.read()

    return src


def create_configuration(args):
    """
    Creates the object with configuration given the arguments to this
    program.
    """
    # s5upload.yml shouldn't be hardcoded,... create a pull request at
    # https://github.com/OndrejSlamecka/s5upload if this is causing you
    # problems
    source = choose_config_source('s5upload.yml')
    config = parse_config_source(source)

    config['dry_run'] = args.dry_run

    # Overwrite dir, bucket, distribution settings if provided in CLI args
    if args.dir:
        config['dir'] = args.dir

    if args.bucket:
        config['bucket'] = args.bucket

    if args.distribution:
        config['distribution'] = args.distribution

    # Use the default cache_control settings if they weren't specified
    if not config['cache_control']:
        default = parse_config_source(default_configuration)
        config['cache_control'] = default['cache_control']

    return config


def check_configuration(config):
    """
    Checks (and warns) if the configuration defines all required
    information.
    """
    doexit = False

    if 'dir' not in config:
        print("Directory to upload was not specified. Use either the -d "
              "flag or 'dir:' in the configuration file.", file=stderr)
        doexit = True

    if 'bucket' not in config:
        print("Bucket to upload to was not specified. Use either the -b "
              "flag or 'bucket:' in the configuration file.", file=stderr)
        doexit = True

    if doexit:  # Report the two errors together
        exit(1)

    if 'distribution' not in config:
        print("WARNING: You did not specify distribution ID",
              file=stderr)

    if 'default' not in config['cache_control']:
        print("You have overwritten the default cache_control config "
              "but did not set the default max-age. Run this program "
              "again with the -pc flag to print the default "
              "configuration")
        exit(1)

    if not os.path.exists(config['dir']):
        print("Given directory (" + config['dir'] + ") is not a "
              "directory.", file=stderr)
        exit(1)


""" Main """


def argument_parser():
    parser = argparse.ArgumentParser(
        description="Simple Storage Service Static Site Uploader.\n"
        "Output: '-\tfilepath' for each file deleted from the bucket "
        "and '+\tfilepath' for each file uploaded to the bucket. "
        "Reads configuration from s5upload.yml (see -p flag).")

    parser.add_argument('-d', '--dir', help="The path the directory "
                        "with the site. Required unless you set 'dir' "
                        "in the config file.")
    parser.add_argument('-b', '--bucket', help="The name of the bucket. "
                        "Required unless you set 'bucket' in the "
                        "config file.")
    parser.add_argument('-cf', '--distribution', help="CloudFront "
                        "distribution ID for the website.")

    parser.add_argument('-n', '--dry-run', action='store_const',
                        const=True, default=False,
                        help='Do not sync, just output diff.')

    parser.add_argument('-p', '--default-config', action='store_const',
                        const=True, default=False,
                        help='Print the default configuration and halt.')

    return parser


if __name__ == "__main__":
    # Process arguments
    parser = argument_parser()
    args = parser.parse_args()

    # The -p flag to print default configuration
    if args.default_config:
        if args.dir:
            print("dir: '" + args.dir + "'")

        if args.bucket:
            print("bucket: '" + args.bucket + "'")

        if args.distribution:
            print("distribution: '" + args.distribution + "'")

        print(default_configuration())
        exit(0)

    # Load and check configuration
    config = create_configuration(args)
    check_configuration(config)

    # Get the diff of local and remote
    bucket = boto3.resource('s3').Bucket(config['bucket'])
    remote = get_remote(bucket)
    local = get_local(config['dir'])

    to_upload, to_delete = differences(local, remote)

    # Delete files
    for fileinfo in to_delete:
        print('-\t/' + fileinfo.path)
        if not config['dry_run']:
            fileinfo.bucket_object.delete()

    # Upload files
    for fileinfo in to_upload:
        print('+\t/' + fileinfo.path)
        if not config['dry_run']:
            upload_file(config['cache_control'], bucket, fileinfo)

    # Invalidate CloudFront distribution cache
    diff = to_delete + to_upload
    if not config['dry_run'] and 'distribution' in config and diff:
        client = boto3.client('cloudfront')
        items, hash = invalidation_batch(diff)
        create_cloudfront_invalidation(client, config['distribution'],
                                       items, hash)
