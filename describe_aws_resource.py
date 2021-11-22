#!/usr/bin/env python3
"""
Describe any given AWS resource by name or ARN.
Someday rewrite this as a package thing.
"""

import re
import pprint
import argparse
import sys
import boto3
import botocore
from botocore.config import Config


def parse_arn(arn):
    """
    Parse the arn to figure out what type of resource this is.
    """
    resource = {}
    # sample arns
    # arn:aws:ec2:us-east-2:643927032162:subnet/subnet-b93f81d0
    # arn:aws:s3:::mk-flacs
    arn_matcher = re.compile(
        r"""
      ^arn:aws
      :(?P<service>[^:]+)
      :(?P<region>[^:]*)
      :(?P<account>\d*)
      :(?P<resource>\S+)$
      """,
        re.VERBOSE,
    )
    if arn_match := arn_matcher.search(arn):
        arn_dict = arn_match.groupdict()
        resource["type"] = arn_dict["service"]
        if arn_dict["service"] == "ec2":
            (resource["sub_type"], resource["name"]) = arn_dict["resource"].split("/")
        elif arn_dict["service"] == "rds":
            (resource["sub_type"], resource["name"]) = arn_dict["resource"].split(":")
        elif arn_dict["service"] == "s3":
            resource["sub_type"] = "bucket"
            resource["name"] = arn_dict["resource"]
        else:
            resource["name"] = arn_dict["resource"]
            resource["sub_type"] = None
    return resource


def parse_s3_url(url):
    """
    Parse an s3 URL to figure out if it is just the bucket or an object key is
    included.
    """
    resource = {}
    s3_match = re.match(r"s3://(?P<bucket>[^/]+)/?(?P<key>\S+)?$", url)
    bucket_dict = s3_match.groupdict()
    resource["type"] = "s3"
    if bucket_dict["key"] is None:
        resource["sub_type"] = "bucket"
        resource["name"] = bucket_dict["bucket"]
    else:
        resource["sub_type"] = "object"
        resource["name"] = [bucket_dict["bucket"], bucket_dict["key"]]
    return resource


def determine_resource_type(args):
    """
    Determine what type of AWS resource this is and what its name is.
    This will help us determine what methd to use to describe this resource.
    """
    resource = {
        "type": "unknown",
        "sub-type": None,
        "name": "unknown",
    }
    identifier = args.identifier
    if identifier.startswith("arn:"):
        resource = parse_arn(identifier)
    if identifier.startswith("s3://"):
        resource = parse_s3_url(identifier)
    else:
        resource["name"] = identifier
        if re.match("i-", identifier):
            resource["type"] = "ec2"
            resource["sub_type"] = "instance"
        elif re.match("subnet-", identifier):
            resource["type"] = "ec2"
            resource["sub_type"] = "subnet"
        elif re.match("snap-", identifier):
            resource["type"] = "ec2"
            resource["sub_type"] = "snapshot"
        elif re.match("vol-", identifier):
            resource["type"] = "ec2"
            resource["sub_type"] = "volume"
        else:
            print(f"Cannot determine what type of resource '{identifier}' is.")
            sys.exit(2)

    return resource


def describe_resource(resource, args):
    """Describe the resource that we were given"""
    aws_config = Config()
    if args.region is not None:
        aws_config = Config(region_name=args.region)
    if resource["type"] == "ec2":
        filtered_attributes = [
            "InstanceType",
            "PrivateIpAddress",
            "SecurityGroups",
            "SubnetId",
            "VpcId",
        ]
        client = boto3.client("ec2", config=aws_config)
        if resource["sub_type"] == "instance":
            response = client.describe_instances(InstanceIds=[resource["name"]])
        if args.full:
            pprint.pprint(response)
        else:
            filtered_response = {
                n: response["Reservations"][0]["Instances"][0][n]
                for n in response["Reservations"][0]["Instances"][0]
                if n in filtered_attributes
            }
            pprint.pprint(filtered_response)
    if resource["type"] == "s3":
        client = boto3.client("s3", config=aws_config)
        if resource["sub_type"] == "bucket":
            bucket = {"name": resource["name"]}
            location = (
                client.get_bucket_location(Bucket=bucket["name"])["LocationConstraint"]
                or "us-east-1"
            )
            bucket["location"] = location
            bucket["versioning"] = {
                "status": client.get_bucket_versioning(Bucket=bucket["name"]).get(
                    "Status", "Disabled"
                )
            }
            try:
                bucket["tags"] = client.get_bucket_tagging(Bucket=bucket["name"])[
                    "TagSet"
                ]
            except botocore.exceptions.ClientError:
                bucket["tags"] = {}
            pprint.pprint(bucket)
        elif resource["sub_type"] == "object":
            bucket = resource["name"][0]
            object_key = resource["name"][1]
            bucket_object = {"bucket": bucket, "key": object_key}
            bucket_object.update(client.head_object(Bucket=bucket, Key=object_key))
            pprint.pprint(bucket_object)
        else:
            print("Unknown S3 thing")


def main():
    """The main ting"""
    my_parser = argparse.ArgumentParser(description="Describe a given AWS resource.")
    my_parser.set_defaults(dry_run=False, full=False, verbose=False)
    my_parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    my_parser.add_argument("--verbose", action="store_true")
    my_parser.add_argument(
        "--full", action="store_true", help="return all info about the resource"
    )
    my_parser.add_argument(
        "--identifier",
        action="store",
        type=str,
        required=True,
        help="identifier for the resource, a name or ARN",
    )
    my_parser.add_argument(
        "--region",
        action="store",
        type=str,
        help="""Specify the region that this resource is in.
                           Otherwise the region in your environment, awscli
                           profile, or default region will be used.""",
    )

    args = my_parser.parse_args()

    try:
        iam = boto3.client("iam")
        iam.get_account_summary()
    except botocore.exceptions.ClientError:
        print("Set up AWS credentials or profile in your environment.")
        sys.exit(1)

    resource = determine_resource_type(args)
    if args.verbose or args.dry_run:
        print(
            f"Resource : type = {resource['type']}, sub type = {resource['sub_type']}, name = {resource['name']}"
        )
    if not args.dry_run:
        describe_resource(resource, args)


if __name__ == "__main__":
    main()
