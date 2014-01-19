#! /usr/bin/env python

import os
import sys
import time
import logging
import traceback
import json
import urllib3
from subprocess import Popen, PIPE

sys.path.append("/Users/aditya/projects/utility/python_service")
from system_v import service

service_path = "/etc/init.d/aws_dns"
base_dir     = os.path.abspath(".")
pidfile      = os.path.join(base_dir, "dat/aws_dns.pid")
logfile      = os.path.join(base_dir, "dat/aws_dns.log")
conf_file    = os.path.join(base_dir, "dat/aws_dns.json")

def get_json(cmd):
	out, err = Popen(cmd, stdout=PIPE, stderr=PIPE).communicate()
	if len(err) != 0:
		logging.warning("Command {0} reported error: {1}".
			format(cmd, err.decode("utf-8")))
	return json.loads(out.decode("utf-8"))

def get_set_ip(domain, zone_id):
	res = get_json(['aws', 'route53', 'list-resource-record-sets', '--hosted-zone-id', zone_id])
	sets = res["ResourceRecordSets"]
	try:
		l = list(filter(lambda r: r["Type"] == "A" and r["Name"] == domain, sets))
	except KeyError as e:
		raise Exception("No key {0} in record sets: {1}".format(e.args[0], sets))

	if len(l) == 0:
		raise Exception("No matching A record in response: {0}".format(sets))
	elif len(l) > 1:
		logging.warning("Multiple A records match domain: using first match.")

	addresses = list(filter(lambda r: "Value" in r, l[0]["ResourceRecords"]))
	if len(addresses) == 0:
		logging.warning("Matching A record has no address value.")
	elif len(addresses) > 1:
		logging.warning("Matching A record has multiple address values.")
		logging.warning("Only the first one will be considered.")
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
		'--hosted-zone-id', zone_id, '--change-batch', change_query]
	)
	
	if not "ChangeInfo" in info:
		raise Exception("No key {0} in response: {1}".format("ChangeInfo", info))
	for key in ["Status", "Id"]:
		if not key in info["ChangeInfo"]:
			raise Exception("No key {0} in change info: {1}".
				format(key, info["ChangeInfo"]))
	return (info["ChangeInfo"]["Status"] == "INSYNC", info["ChangeInfo"]["Id"])

def change_committed(change_id):
	info = get_json(['aws', 'route53', 'get-change', '--id', change_id])

	if not "ChangeInfo" in info:
		raise Exception("No key {0} in response: {1}".format("ChangeInfo", info))
	for key in ["Status", "Id"]:
		if not key in info["ChangeInfo"]:
			raise Exception("No key {0} in change info: {1}".
				format(key, info["ChangeInfo"]))
	return info["ChangeInfo"]["Status"] == "PENDING" 

def get_status(domain, zone_id):
	set_ip = get_set_ip(domain, zone_id)
	cur_ip = get_public_ip()
	logging.info("Current address associated with domain: " + set_ip)
	logging.info("Current public IP address: " + cur_ip)

	if set_ip != cur_ip:
		change_id = update_record(domain, zone_id, set_ip, cur_ip)[1]
		change_pending = True
		logging.info("Successfully updated record.")
	else:
		change_id = ""
		change_pending = False
	return (set_ip, cur_ip, change_pending, change_id)

def start(domain, zone_id):
	while True:
		try:
			status = get_status(domain, zone_id)
			break
		except Exception as e:
			logging.warning("Failed to get initial status: {0}".format(e))
			logging.warning(traceback.format_exc())
			logging.warning("Next attempt in 10 seconds.")
			time.sleep(10)

	(set_ip, cur_ip, change_pending, change_id) = status
	logging.info("Initialization successful.")

	while True:
		time.sleep(10)

		# If we already have a pending change, wait for it to commit
		# before making another request.
		if change_pending:
			try:
				if not change_committed(change_id):
					logging.info("Previous change not yet committed.")
					logging.info("Next check in 5 minutes.")
					continue
				else:
					logging.info("Previous change committed.")
					change_pending = False
					set_ip = cur_ip
			except Exception as e:
				logging.warning("Failed to get change status: {0}".format(e))
				logging.warning(traceback.format_exc())
				logging.warning("Next attempt in 5 minutes.")
				continue

		# Try to get the public IP.
		try:
			cur_ip = get_public_ip()
		except Exception as e:
			logging.warning("Failed to get public IP: {0}".format(e))
			logging.warning(traceback.format_exc())
			logging.warning("Next attempt in 5 minutes.")
			continue

		# Try to update the public IP.
		if set_ip != cur_ip:
			try:
				change_id = update_record(domain, zone_id, set_ip, cur_ip)
				change_pending = True
				logging.info("Successfully updated record.")
				logging.info("Next check in 5 minutes.")
			except Exception as e:
				logging.warning("Failed to update record: {0}".format(e))
				logging.warning(traceback.format_exc())
				logging.warning("Next attempt in 5 minutes.")
				continue
		else:
			logging.info("Public IP has not changed.")
			logging.info("Next check in 5 minutes.")

class aws_dns_service(service):
	def __init__(self):
		super(aws_dns_service, self).__init__(service_path, pidfile, logfile)
		self.terminating = False
		
	def run(self):
		logging.basicConfig(stream=self.log, level=logging.INFO)

		try:
			config = json.load(open(conf_file))
		except Exception as e:
			logging.critical("Error parsing configuration file: {0}".format(e))
			self.log_status(False)
			sys.exit(1)

		for key in ["domain-name", "hosted-zone-id"]:
			if not key in config:
				logging.critical("Configuration missing key \"{0}\"".format(key))
				self.log_status(False)
				sys.exit(1)

		(domain, zone_id) = (config["domain-name"], config["hosted-zone-id"])
		if not domain.endswith("."):
			logging.critical("Value for \"domain-name\" does not end with \".\"")
			self.log_status(False)
			sys.exit(1)

		self.log_status(True)
		start(domain, zone_id)

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
