#!/usr/bin/env python3
'''Describe any given AWS resource by name or ARN'''

import re
import pprint
import argparse
import sys
import boto3
import botocore


def determine_resource_type(args):
    '''
    Determine what type of AWS resource this is and what its name is.
    This will help us determine what methd to use to describe this resource.
    '''
    resource = {
        'type': 'unknown',
        'sub-type': None,
        'name': 'unknown',
    }
    identifier = args.identifier
    # sample arns
    # arn:aws:ec2:us-east-2:643927032162:subnet/subnet-b93f81d0
    # arn:aws:s3:::mk-flacs
    arn_matcher = re.compile(r"""
      ^arn:aws
      :(?P<service>[^:]+)
      :(?P<region>[^:]*)
      :(?P<account>\d*)
      :(?P<resource>\S+)$
      """, re.VERBOSE)
    arn_match = arn_matcher.search(identifier)
    if arn_match:
        arn_dict = arn_match.groupdict()
        resource['type'] = arn_dict['service']
        if arn_dict['service'] == 'ec2':
            (resource['sub_type'], resource['name']) = arn_dict['resource'].split('/')
        elif arn_dict['service'] == 'rds':
            (resource['sub_type'], resource['name']) = arn_dict['resource'].split(':')
        else:
            resource['name'] = arn_dict['resource']
            resource['sub_type'] = None
    else:
        resource['name'] = identifier
        if re.match('i-', identifier):
            resource['type'] = 'ec2'
            resource['sub_type'] = 'instance'
        elif re.match('subnet-', identifier):
            resource['type'] = 'ec2'
            resource['sub_type'] = 'subnet'
        elif re.match('snap-', identifier):
            resource['type'] = 'ec2'
            resource['sub_type'] = 'snapshot'
        elif re.match('vol-', identifier):
            resource['type'] = 'ec2'
            resource['sub_type'] = 'volume'
        else:
            print(f"Cannot determine what type of resource '{identifier}' is.")
            sys.exit(2)

    return resource


def describe_resource(resource, args):
    '''Describe the resource that we were given'''
    if resource['type'] == 'ec2':
        filtered_attributes = [
            'InstanceType',
            'PrivateIpAddress',
            'SecurityGroups',
            'SubnetId',
            'VpcId'
        ]
        client = boto3.client('ec2')
        if resource['sub_type'] == 'instance':
            response = client.describe_instances(
                InstanceIds=[resource['name']]
            )
        if args.full:
            pprint.pprint(response)
        else:
            filtered_response = {n: response['Reservations'][0]['Instances'][0][n] for n in response['Reservations'][0]['Instances'][0] if n in filtered_attributes}
            pprint.pprint(filtered_response)
    if resource['type'] == 's3':
        bucket = {
            'name': resource['name']
        }
        client = boto3.client('s3')
        location = client.get_bucket_location(Bucket=bucket['name'])['LocationConstraint'] or 'us-east-1'
        bucket['location'] = location
        bucket['versioning'] = {'status': client.get_bucket_versioning(Bucket=bucket['name']).get('Status', 'Disabled')}
        try:
            bucket['tags'] = client.get_bucket_tagging(Bucket=bucket['name'])['TagSet']
        except botocore.exceptions.ClientError:
            bucket['tags'] = {}
        pprint.pprint(bucket)


def main():
    '''The main ting'''
    my_parser = argparse.ArgumentParser(description='Describe a given AWS resource.')
    my_parser.set_defaults(
        dry_run=False,
        full=False,
        verbose=False
    )
    my_parser.add_argument('--dry-run',
                           dest='dry_run',
                           action='store_true')
    my_parser.add_argument('--verbose',
                           action='store_true')
    my_parser.add_argument('--full',
                           action='store_true',
                           help='return all info about the resource')
    my_parser.add_argument('--identifier',
                           action='store',
                           type=str,
                           required=True,
                           help='identifier for the resource, a name or ARN')

    args = my_parser.parse_args()

    try:
        iam = boto3.client('iam')
        iam.get_account_summary()
    except botocore.exceptions.ClientError:
        print("Set up AWS credentials or profile in your environment.")
        sys.exit(1)

    resource = determine_resource_type(args)
    if args.verbose or args.dry_run:
        print(f"Resource : type = {resource['type']}, sub type = {resource['sub_type']}, name = {resource['name']}")
    if not args.dry_run:
        describe_resource(resource, args)


if __name__ == '__main__':
    main()
