#!/usr/bin/env python3
"""
Describe any given AWS resource by name or ARN.
Someday rewrite this as a package thing.
"""

import argparse
import datetime
import json
import re
import sys

import boto3
import botocore
from botocore.config import Config


def print_err(m):
    print(m, file=sys.stderr)


def json_value_converter(o):
    """
    Use this function in the 'default' argument for json.dumps to convert values that
    are not strings.
    """
    if isinstance(o, datetime.datetime):
        return o.__str__()


def print_json(o):
    """
    print out the object as json
    """
    print(
        json.dumps(
            o,
            default=json_value_converter,
            sort_keys=True,
            indent=2,
        )
    )


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
    else:
        raise ValueError(f"Invalid ARN: {arn}")
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


def possible_route53_resource(args):
    """
    Check if this is a route53 zone or resource name
    """
    name = args.identifier
    dotted_name = name if name.endswith(".") else name + "."
    client = boto3.client("route53")
    all_zones = client.list_hosted_zones(MaxItems="100")["HostedZones"]
    matched_zones = {
        zone["Name"]: zone["Id"]
        for zone in all_zones
        if dotted_name.endswith(zone["Name"])
    }
    if dotted_name in matched_zones.keys():
        """Do a zone lookup"""
        print(f"Doing a zone lookup on {dotted_name}") if args.verbose else None
        return {
            "name": matched_zones[dotted_name],
            "type": "route53",
            "sub_type": "hosted_zone",
        }
    elif len(matched_zones) > 0:
        """Lookup the name against the zones here."""
        for zone_name, zone_id in matched_zones.items():
            print(
                f"Checking zone {zone_name} for record {name}"
            ) if args.verbose else None
            paginator = client.get_paginator("list_resource_record_sets")
            page_iterator = paginator.paginate(HostedZoneId=zone_id)
            filtered_iterator = page_iterator.search(
                "ResourceRecordSets[?Name==`" + dotted_name + "`]"
            )

            # for page in page_iterator:
            for data in filtered_iterator:
                return {
                    "name": name,
                    "type": "route53",
                    "sub_type": "record",
                    "data": data,
                }
    else:
        return None


def describe_route53_resource(r, client, cli_args):
    """
    Describe a route53 zone or record
    """
    response = client.get_hosted_zone(Id=r["name"])
    return response["HostedZone"]


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
    print(f"Parsing {identifier}") if args.verbose else None
    if identifier.startswith("arn:"):
        print("It's an ARN.") if args.verbose else None
        resource = parse_arn(identifier)
    elif identifier.startswith("s3://"):
        print("It's an s3 URL.") if args.verbose else None
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
        elif re.match("vpc-", identifier):
            resource["type"] = "ec2"
            resource["sub_type"] = "vpc"
        elif re.match(r"[-\w]+\.[-\w]+[\.]*", identifier):
            resource = possible_route53_resource(args)
        else:
            print_err(f"Cannot determine what type of resource '{identifier}' is.")
            sys.exit(2)

    if resource:
        return resource
    else:
        print_err(f"Cannot determine what type of resource '{identifier}' is.")
        sys.exit(2)


def describe_ec2_resource(r, client, cli_args):
    """
    Describe an ec2 type resource
    """
    data = {}
    if r["sub_type"] == "instance":
        filtered_attributes = [
            "InstanceType",
            "PrivateIpAddress",
            "SecurityGroups",
            "SubnetId",
            "VpcId",
        ]
        print(f"Querying EC2 instance {r['name']}") if cli_args.verbose else None
        response = client.describe_instances(InstanceIds=[r["name"]])
        if cli_args.full:
            data = response["Reservations"][0]["Instances"][0]
        else:
            data = {
                n: response["Reservations"][0]["Instances"][0][n]
                for n in response["Reservations"][0]["Instances"][0]
                if n in filtered_attributes
            }
    elif r["sub_type"] == "subnet":
        print(f"Querying subnet {r['name']}") if cli_args.verbose else None
        response = client.describe_subnets(
            SubnetIds=[
                r["name"],
            ]
        )
        data = response["Subnets"][0]
    elif r["sub_type"] == "vpc":
        print(f"Querying vpc {r['name']}") if cli_args.verbose else None

        response = client.describe_vpcs(
            VpcIds=[
                r["name"],
            ]
        )
        data = response["Vpcs"][0]
    elif r["sub_type"] == "volume":
        print(f"Querying EBS volume {r['name']}") if cli_args.verbose else None
        response = client.describe_volumes(
            VolumeIds=[
                r["name"],
            ]
        )
        data = response["Volumes"][0]
    elif r["sub_type"] == "snapshot":
        print(f"Querying EBS snapshot {r['name']}") if cli_args.verbose else None
        response = client.describe_snapshots(
            SnapshotIds=[
                r["name"],
            ]
        )
        data = response["Snapshots"][0]
    return data


def describe_resource(resource, args):
    """Describe the resource that we were given"""
    aws_config = Config()
    if args.region is not None:
        aws_config = Config(region_name=args.region)
    if resource["type"] == "ec2":
        client = boto3.client("ec2", config=aws_config)
        ec2_data = describe_ec2_resource(client=client, r=resource, cli_args=args)
        print_json(ec2_data)
    elif resource["type"] == "s3":
        client = boto3.client("s3", config=aws_config)
        bucket_name = (
            resource["name"]
            if resource["sub_type"] == "bucket"
            else resource["name"][0]
        )
        region = (
            client.get_bucket_location(Bucket=bucket_name)["LocationConstraint"]
            or "us-east-1"
        )
        if resource["sub_type"] == "bucket":
            bucket = {"name": resource["name"]}
            bucket["region"] = region
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
            print_json(bucket)
        elif resource["sub_type"] == "object":
            bucket = resource["name"][0]
            object_key = resource["name"][1]
            bucket_object = {"bucket": bucket, "key": object_key, "region": region}
            bucket_object.update(client.head_object(Bucket=bucket, Key=object_key))
            print_json(bucket_object)
        else:
            print_err("Unknown S3 thing")
            sys.exit(2)
    elif resource["type"] == "route53":
        if resource["sub_type"] == "record":
            print_json(resource["data"])
        else:
            client = boto3.client("route53")
            route53_data = describe_route53_resource(
                client=client, r=resource, cli_args=args
            )
            print_json(route53_data)


def main():
    """The main ting"""
    my_parser = argparse.ArgumentParser(description="Describe a given AWS resource.")
    my_parser.set_defaults(dry_run=False, full=False, verbose=False)
    my_parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    my_parser.add_argument("--verbose", action="store_true")
    # This only affects the ec2 instance data. Take it out? Change it?
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
        "--profile",
        action="store",
        type=str,
        help="Specify an awscli profile to use for this query.",
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

    if args.profile is not None:
        boto3.setup_default_session(profile_name=args.profile)
    try:
        iam = boto3.client("iam")
        iam.get_account_summary()
    except botocore.exceptions.ClientError:
        print_err("Set up AWS credentials or profile in your environment.")
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
