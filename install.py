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
	log_warning("This installation script was designed for Debian-based "
		"GNU/Linux distributions.")
	log_info("Please pay attention to the output; you will need to do "
		"some things manually.")
	log_info("Please consult README.md after installation to make sure "
		"everything works.")
	log_info("If you have time, please submit a ticket or patch. Thanks!")
	debian = False

for dir in ["/etc", "/usr/lib", "/var/log", "/var/run"]:
	if not os.path.exists(dir):
		log_failure("The directory \"{0}\" does not exist.".format(dir))
		sys.exit(1)

for file in ["/etc/aws_dns", "/etc/aws_dns.conf", "/usr/lib/python_service",
	"/var/run/aws_dns.pid", "/var/log/aws_dns.log"]:
	if os.path.exists(file):
		log_failure("The file \"{0}\" already exists.".format(file))
		log_info("To uninstall a previous installation, run "
			"uninstall.py as root.")
		sys.exit(1)

try:
	os.mkdirs("/usr/lib/python_service")
	shutil.copy("system_v.py", "/usr/lib/python_service")
	shutil.copy("dat/aws_dns.conf", "/etc")
except OSError as e:
	print("{0}Error:{1} installation failed: {0}.".
		format(Fore.RED, Fore.RESET, e))
	sys.exit(1)

if debian:
	for cmd in ["update-rc.d aws_dns defaults",
		"update-rc.d aws_dns enable"]:
		out, err = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE).communicate()
		if len(err) != 0:
			log_failure("Command \"{0}\" failed: \"{1}\"".
				format(cmd, err.decode("utf-8")))
			log_info("You will need to enable the \"aws_dns\" "
				"service yourself.")
			sys.exit(1)
else:
	log_success("Installation complete.")
	log_info("However, you need to enable the \"aws_dns\" service yourself.")

log_success("Installation complete.")
