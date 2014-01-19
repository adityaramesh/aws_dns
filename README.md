<!--
  ** File Name:	README.md
  ** Author:	Aditya Ramesh
  ** Date:	01/09/2014
  ** Contact:	_@adityaramesh.com
-->

# Introduction

If you use AWS, `aws_dns` essentially gives you DynDNS for free.

`aws_dns` is a daemon that periodically checks the public IP address of the host
machine, and pushes the address to an A record for a hosted zone. This allows
you to tie an SSH server behind a dynamic IP to a domain name like
`bob.example.com`.

This rest of this document describes how to set up your machine to run the
daemon.

# TODO

  - Dependency checking.
  - Installation script.

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
- Install awscli using pip.
- After installation, type `aws configure`, and enter the credentials that you
obtained previously.

# Getting Started

- You may want to read the [AWS CLI guide][aws_cli] if you would like to use it
  yourself.
- The default configuration is file located in `~/.aws`, so it will persist even
if you change Python versions and download a different version of pip.

# Python Packages

The following packages are used by the script to run. If you do not have them
installed, you will need to do so using `pip install`.

# Installation

- git clone
- rake install

[security_credentials]:
https://console.aws.amazon.com/iam/home?#security_credential
"IAM Management Console"

[aws_cli]:
http://docs.aws.amazon.com/cli/latest/userguide/cli-chap-welcome.html
"AWS CLI"
