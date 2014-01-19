#! /usr/bin/env python3

import os
import sys
import time
import logging
import logging.handlers
import traceback
import json
import urllib3
from subprocess import Popen, PIPE

#sys.path.append("###/python_service")
#service_path = "/etc/init.d/aws_dns"
#base_dir     = os.path.abspath(".")
#pidfile      = os.path.join(base_dir, "dat/aws_dns.pid")
#logfile      = os.path.join(base_dir, "dat/aws_dns.log")
#conf_file    = os.path.join(base_dir, "dat/aws_dns.conf")

sys.path.append("/usr/lib/python_service")
pidfile   = "/var/run/aws_dns.pid"
logfile   = "/var/log/aws_dns.log"
conf_file = "/etc/aws_dns.conf"

from system_v import service

def get_json(cmd):
	logger = logging.getLogger("aws_dns")
	out, err = Popen(cmd, stdout=PIPE, stderr=PIPE).communicate()
	if len(err) != 0:
		logger.warning("Command {0} reported error: {1}".
			format(cmd, err.decode("utf-8")))
	return json.loads(out.decode("utf-8"))

def get_set_ip(domain, zone_id):
	logger = logging.getLogger("aws_dns")
	res = get_json(['aws', 'route53', 'list-resource-record-sets',
		'--hosted-zone-id', zone_id, '--output', 'json'])
	sets = res["ResourceRecordSets"]
	try:
		l = list(filter(lambda r: r["Type"] == "A" and r["Name"] == domain, sets))
	except KeyError as e:
		raise Exception("No key {0} in record sets: {1}".format(e.args[0], sets))

	if len(l) == 0:
		raise Exception("No matching A record in response: {0}".format(sets))
	elif len(l) > 1:
		logger.warning("Multiple A records match domain: using first match.")

	addresses = list(filter(lambda r: "Value" in r, l[0]["ResourceRecords"]))
	if len(addresses) == 0:
		logger.warning("Matching A record has no address value.")
	elif len(addresses) > 1:
		logger.warning("Matching A record has multiple address values.")
		logger.warning("Only the first one will be considered.")
	return addresses[0]["Value"]

def get_public_ip():
	http = urllib3.PoolManager()
	r = http.request("GET", "http://ip.42.pl/raw")
	if r.status != 200:
		raise Exception("Bad response code: {0}".format(r.status))
	return r.data.decode("utf-8")

def update_record(domain, zone_id, old_ip, new_ip):
	change_query = json.dumps({
		"Changes": [
			{
				"Action": "DELETE",
				"ResourceRecordSet": {
					"Name": domain,
					"Type": "A",
					"ResourceRecords": [{"Value": old_ip}],
					"TTL": 300
				}
			},
			{
				"Action": "CREATE",
				"ResourceRecordSet": {
					"Name": domain,
					"Type": "A",
					"ResourceRecords": [{"Value": new_ip}],
					"TTL": 300
				}
			}
		]
	})
	info = get_json(
		['aws', 'route53', 'change-resource-record-sets',
		'--hosted-zone-id', zone_id, '--change-batch', change_query,
		'--output', 'json']
	)
	
	if not "ChangeInfo" in info:
		raise Exception("No key {0} in response: {1}".format("ChangeInfo", info))
	for key in ["Status", "Id"]:
		if not key in info["ChangeInfo"]:
			raise Exception("No key {0} in change info: {1}".
				format(key, info["ChangeInfo"]))
	return (info["ChangeInfo"]["Status"] == "INSYNC", info["ChangeInfo"]["Id"])

def change_committed(change_id):
	info = get_json(['aws', 'route53', 'get-change', '--id', change_id,
		'--output', 'json'])

	if not "ChangeInfo" in info:
		raise Exception("No key {0} in response: {1}".format("ChangeInfo", info))
	for key in ["Status", "Id"]:
		if not key in info["ChangeInfo"]:
			raise Exception("No key {0} in change info: {1}".
				format(key, info["ChangeInfo"]))
	return info["ChangeInfo"]["Status"] == "PENDING" 

def get_status(domain, zone_id):
	logger = logging.getLogger("aws_dns")
	set_ip = get_set_ip(domain, zone_id)
	cur_ip = get_public_ip()
	logger.info("Current address associated with domain: " + set_ip)
	logger.info("Current public IP address: " + cur_ip)

	if set_ip != cur_ip:
		change_id = update_record(domain, zone_id, set_ip, cur_ip)[1]
		change_pending = True
		logger.info("Successfully updated record.")
	else:
		change_id = ""
		change_pending = False
	return (set_ip, cur_ip, change_pending, change_id)

def start(domain, zone_id, recheck):
	logger = logging.getLogger("aws_dns")

	while True:
		try:
			status = get_status(domain, zone_id)
			break
		except Exception as e:
			logger.warning("Failed to get initial status: {0}".format(e))
			logger.warning(traceback.format_exc())
			logger.warning("Next attempt in 10 seconds.")
			time.sleep(10)

	(set_ip, cur_ip, change_pending, change_id) = status
	logger.info("Initialization successful.")

	while True:
		time.sleep(recheck)

		# If we already have a pending change, wait for it to commit
		# before making another request.
		if change_pending:
			try:
				if not change_committed(change_id):
					logger.info("Previous change not yet committed.")
					logger.info("Next check in 5 minutes.")
					continue
				else:
					logger.info("Previous change committed.")
					change_pending = False
					set_ip = cur_ip
			except Exception as e:
				logger.warning("Failed to get change status: {0}".format(e))
				logger.warning(traceback.format_exc())
				logger.warning("Next attempt in 5 minutes.")
				continue

		# Try to get the public IP.
		try:
			cur_ip = get_public_ip()
		except Exception as e:
			logger.warning("Failed to get public IP: {0}".format(e))
			logger.warning(traceback.format_exc())
			logger.warning("Next attempt in 5 minutes.")
			continue

		# Try to update the public IP.
		if set_ip != cur_ip:
			try:
				change_id = update_record(domain, zone_id, set_ip, cur_ip)
				change_pending = True
				logger.info("Successfully updated record.")
				logger.info("Next check in 5 minutes.")
			except Exception as e:
				logger.warning("Failed to update record: {0}".format(e))
				logger.warning(traceback.format_exc())
				logger.warning("Next attempt in 5 minutes.")
				continue
		else:
			logger.info("Public IP has not changed.")
			logger.info("Next check in 5 minutes.")

class aws_dns_service(service):
	def __init__(self):
		super(aws_dns_service, self).__init__(service_path, pidfile)
		self.terminating = False
		
	def run(self):
		# Set up the logging.
		fmt = "%(asctime)s :: %(levelname)s :: %(funcName)s, line %(lineno)s :: %(message)s"
		logger = logging.getLogger("aws_dns")
		logger.setLevel(logging.INFO)
		h = logging.handlers.RotatingFileHandler(logfile, maxBytes=2**30, backupCount=5)
		f = logging.Formatter(fmt)
		h.setFormatter(f)
		logger.addHandler(h)

		# Parse the configuration.
		try:
			config = json.load(open(conf_file))
		except Exception as e:
			logger.critical("Error parsing configuration file: {0}".format(e))
			self.log_status(False)
			sys.exit(1)

		for key in ["domain-name", "hosted-zone-id"]:
			if not key in config:
				logger.critical("Configuration missing key \"{0}\"".format(key))
				self.log_status(False)
				sys.exit(1)

		(domain, zone_id) = (config["domain-name"], config["hosted-zone-id"])

		if type(domain) != str or type(zone_id) != str:
			logging.critical("Domain and hosted zone ID must be strings.")
			self.log_status(False)
			sys.exit(1)

		if not domain.endswith("."):
			domain += "."

		if "recheck-time" in config:
			recheck = config["recheck-time"]
			if type(recheck) != float:
				logging.critical("Recheck time must be a number.")
				self.log_status(False)
				sys.exit(1)
			if recheck <= 0:
				logging.critical("Recheck time must be positive.")
				self.log_status(False)
				sys.exit(1)
		else:
			recheck = 300

		self.log_status(True)
		start(domain, zone_id, recheck)

	def terminate(self):
		self.log.close()
		sys.exit(0)
	
s = aws_dns_service()
r = {
	"start"        : s.start,
	"stop"         : s.stop,
	"restart"      : s.restart,
	"try-restart"  : s.try_restart,
	"reload"       : s.reload,
	"force-reload" : s.force_reload,
	"status"       : s.status
}.get(sys.argv[1] if len(sys.argv) > 1 else "usage", s.usage)()
sys.exit(r)
