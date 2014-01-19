#! /usr/bin/env python3

import os
import sys
import shutil
from colorama import Fore
from subprocess import Popen, PIPE

def log_info(msg):
	print(" * {0}".format(msg))

def log_warning(msg):
	print("{0}Warning:{1} {2}".format(Fore.YELLOW, Fore.RESET, msg))

def log_failure(msg):
	print("{0}Failure:{1} {2}".format(Fore.RED, Fore.RESET, msg))

def log_success(msg):
	print("{0}Success:{1} {2}".format(Fore.GREEN, Fore.RESET, msg))

if os.geteuid() != 0:
	print("Only root should run this installation script.")
	sys.exit(1)

dist, _ = Popen(["uname", "-a"], stdout=PIPE, stderr=PIPE).communicate()
dist = dist.decode("utf-8")
debian = True
if not "Debian" in dist and not "Ubuntu" in dist:
	log_warning("This uninstallation script was designed for Debian-based "
		"GNU/Linux distributions.")
	log_info("If you did a manual installation, you may need to check "
		"for additional files.")
	log_info("Please pay attention to the output; you will need to do "
		"some things manually.")
	log_info("Please consult README.md after installation to make sure "
		"everything works.")
	log_info("If you have time, please submit a ticket or patch. Thanks!")
	debian = False

try:
	if os.path.exists("/usr/lib/python_service"):
		shutil.rmtree("/usr/lib/python_service")
	for file in ["/var/run/aws_dns.pid", "/var/log/aws_dns.log",
		"/etc/aws_dns.conf"]:
		if os.path.exists(file):
			os.remove(file)
except Exception as e:
	log_warning("Error during installation: {0}".format(e))
	
if debian:
	for cmd in ["update-rc.d aws_dns disable",
		"update-rc.d aws_dns remove"]:
		out, err = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE).communicate()
		if len(err) != 0:
			log_failure("Command \"{0}\" failed: \"{1}\"".
				format(cmd, err.decode("utf-8")))
			log_info("You will need to disable the \"aws_dns\" "
				"service yourself.")
			sys.exit(1)
else:
	log_success("Uninstallation complete.")
	log_info("However, you need to disable the \"aws_dns\" service yourself.")

log_success("Uninstallation complete.")
