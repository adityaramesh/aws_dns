#! /usr/bin/env python3

import os
import sys
import shutil
from glob import glob
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
if not "Debian" in dist and not "Ubuntu" in dist:
	log_failure("This installation script was designed for Debian-based "
		"GNU/Linux distributions.")
	log_info("You will need to proceed with the uninstallation manually.")
	log_info("Please consult README.md for more details.")
	log_info("If you have time, please submit a ticket or patch. Thanks!")
	sys.exit(1)

out, err = Popen("service aws_dns stop", shell=True, stdout=PIPE,
	stderr=PIPE).communicate()
if len(err) != 0 and "unrecognized service" not in err.decode("utf-8"):
	log_failure("Failed to stop \"aws_dns\" service.")
	log_info("You will need to stop the service manually.")
	sys.exit(1)

try:
	if os.path.exists("/usr/lib/python_service"):
		shutil.rmtree("/usr/lib/python_service")
	for file in [
		"/etc/init.d/aws_dns",
		"/etc/aws_dns.conf",
		"/var/run/aws_dns.pid",
	]:
		if os.path.exists(file):
			os.remove(file)
	for file in glob("/var/log/aws_dns.log*"):
		os.remove(file)
except Exception as e:
	log_warning("Error during uninstallation: {0}".format(e))
	
for cmd in ["update-rc.d aws_dns remove"]:
	out, err = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE).communicate()
	if len(err) != 0:
		log_failure("Command \"{0}\" failed: \"{1}\"".format(cmd,
			err.decode("utf-8").strip()))
		sys.exit(1)
log_success("Uninstallation complete.")
