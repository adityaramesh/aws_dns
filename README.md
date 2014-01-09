<!--
  ** File Name:	README.md
  ** Author:	Aditya Ramesh
  ** Date:	01/09/2014
  ** Contact:	_@adityaramesh.com
-->

# Introduction

If you use EC2, `ip_sync` essentially gives you DynDNS for free.

`ip_sync` is a daemon for users of Amazon EC2 that periodically checks the
public IP address of a machine and synchronizes it with an A record for a hosted
zone. This allows you to tie an SSH server behind a dynamic IP to a domain name
like `bob.example.com`.
