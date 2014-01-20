<!--
  ** File Name:	README.md
  ** Author:	Aditya Ramesh
  ** Date:	01/09/2014
  ** Contact:	_@adityaramesh.com
-->

# Introduction

If you use AWS, `aws_dns` essentially gives you DynDNS for free.

`aws_dns` is a service that periodically checks the public IP address of the
host machine, and pushes the address to an A record for a hosted zone. This
allows you to tie an SSH server behind a dynamic IP to a domain name like
`bob.example.com`.

This rest of this document describes how to set up your machine to run the
service.

# TODO

  - Installation script.
  - Dependency checking. (If you know how to write `setup.py` to check for the
  necessary libraries, please let me know. I have not had time to go through the
  documentation to figure out which fields to fill out with what.)

# Python Dependencies

This service requires a Python 3 interpreter, along with the Python package
manager `pip`. The following packages are not included in the default Python 3
distribution, so if you do not have them installed, you should do so using `pip
install`:

  - `colorama`
  - `urllib3`

# Obtaining Your Credentials

To use the Route 53 API, you will need access to your AWS Account ID. You will
also need to create a secret access key, if you do not have one already. To do
either of these things, navigate to [this webpage][security_credentials]. To
obtain your AWS Account ID, open the "Account Identifiers" tab at the bottom of
the page. Create an access key using the "Access Keys" tab. You may want to
consoliate all of this information in a single file, perhaps called
`ec2_credentials`.

# Using the Route 53 API

The easiest way to use the Route 53 API is by means of Amazon's command-line
tool called `aws`.

- Install pip for Python 3.
- Install `awscli` using pip.
- After installation, **log in as root**, type `aws configure`, and enter the
  credentials that you obtained previously. Since the service will be started by
  root, the AWS configuration needs to be associated with root. You can also
  type `aws configure` using your account if you wish to use the `aws` utility
  locally.

# Getting Started with AWS CLI

- You may want to read the [AWS CLI guide][aws_cli] if you would like to use it
  yourself.
- The default configuration is file located in `~/.aws`, so it will persist even
if you change Python versions and download a different version of pip.

# Installation

Before installation, edit the file `aws_dns.conf`, and replace the "domain-name"
and "hosted-zone-id" fields with the desired values. For example, if you wish to
associate your machine with the domain name `bob.example.com`, then you would
need to do the following:

  - Log into the Route 53 service using the AWS Management Console.
  - Obtain the hosted zone ID corresponding to the domain `example.com`.
  - Replace the `domain-name` field with `bob.example.com`.
  - Replace the `hosted-zone-id` field with the hosted zone ID corresponding to
  `example.com`.
  - Optionally change the `recheck-time` field to another value (in seconds).
  This indicate the frequently with which the service checks for public IP
  changes.

If you are not using a Debian- or Ubuntu-based Linux distribution, please see
the section titled "Manual Installation". Otherwise, you can now run
`install.py` as root. To uninstall the service, run `uninstall.py` as root. Bug
reports, patches, and requests for new features are welcome.

# Manual Installation

The script `install.py` and `uninstall.py` are designed for Ubuntu-based
distributions using System V init systems. If you are using a different Linux
distribution, you wil need to copy the following files to the proper locations:

  - `aws_dns.py` (This should probably be renamed to `aws_dns` after it is
  moved and given execute permissions.)
  - `aws_dns.conf`
  - `system_v.py`
 
You will also need to edit the first few lines of the `aws_dns.py` script before
moving it, so that it looks for the `system_v.py` file in the correct directory,
looks for the configuration file in the right place, and creates the log and PID
files in the correct directory.

If you have some time, I would appreciate it if you would submit a ticket or a
patch with these changes, so that the installation process works automatically
for your distribution in the future. Thanks!

[security_credentials]:
https://console.aws.amazon.com/iam/home?#security_credential
"IAM Management Console"

[aws_cli]:
http://docs.aws.amazon.com/cli/latest/userguide/cli-chap-welcome.html
"AWS CLI"
