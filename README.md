<!--
  ** File Name:	README.md
  ** Author:	Aditya Ramesh
  ** Date:	01/09/2014
  ** Contact:	_@adityaramesh.com
-->

# Introduction

If you use AWS, `ip_sync` essentially gives you DynDNS for free.

`ip_sync` is a daemon that periodically checks the public IP address of the host
machine, and pushes the address to an A record for a hosted zone. This allows
you to tie an SSH server behind a dynamic IP to a domain name like
`bob.example.com`.
